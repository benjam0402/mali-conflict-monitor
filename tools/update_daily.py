#!/usr/bin/env python3
"""
Mise à jour quotidienne du Mali Conflict Monitor.

Sources :
- ACLED : source principale pour les événements géolocalisés de conflit.
- GDELT + ReliefWeb : signaux presse/humanitaire exportés en candidats à relire.

Le script génère :
- data/events.geojson : événements publiés sur la carte.
- data/events.csv : version tableur des événements publiés.
- data/review_candidates.csv : articles/signaux à relire manuellement.
- data/source_log.json : résumé de la dernière exécution.

Variables d'environnement utiles :
- ACLED_USERNAME / ACLED_PASSWORD : compte myACLED pour l'API ACLED.
- ACLED_ACCESS_TOKEN : optionnel, si tu disposes d'un jeton Bearer.
- LOOKBACK_DAYS : nombre de jours à reprendre à chaque exécution, défaut 10.
- MIN_DAYS_DELAY : délai de sécurité avant publication, défaut 1 = pas d'événement du jour même.
- COORD_DECIMALS : arrondi des coordonnées, défaut 3.
- RELIEFWEB_APPNAME : nom d'app ReliefWeb, défaut mali-conflict-monitor.
- FETCH_GDELT : true/false, défaut true.
- FETCH_RELIEFWEB : true/false, défaut true.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
EVENTS_GEOJSON = DATA_DIR / "events.geojson"
EVENTS_CSV = DATA_DIR / "events.csv"
MANUAL_EVENTS_GEOJSON = DATA_DIR / "manual_events.geojson"
REVIEW_CANDIDATES_CSV = DATA_DIR / "review_candidates.csv"
SOURCE_LOG = DATA_DIR / "source_log.json"
MALI_PLACES_CSV = ROOT / "tools" / "mali_places.csv"

ACLED_LOGIN_URL = "https://acleddata.com/user/login?_format=json"
ACLED_READ_URL = "https://acleddata.com/api/acled/read"
RELIEFWEB_REPORTS_URL = "https://api.reliefweb.int/v2/reports"
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

EVENT_FIELDS = [
    "id", "date", "title", "location", "region", "latitude", "longitude", "type", "actors",
    "reliability", "precision", "summary", "source", "url", "source_event_id", "source_system"
]
CANDIDATE_FIELDS = [
    "date", "title", "source_system", "source", "domain", "matched_place", "latitude", "longitude",
    "summary", "url", "status"
]

# Termes larges : l'objectif est de capter des signaux à relire, pas de publier automatiquement ces articles.
GDELT_QUERY = 'Mali (JNIM OR FAMa OR FLA OR CSP OR Azawad OR jihadist OR insurgent OR attaque OR affrontement OR Gao OR Kidal OR Tombouctou OR Mopti OR Menaka)'


def env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def safe_text(value: Any, max_len: int = 500) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def stable_hash(*parts: Any, prefix: str = "evt") -> str:
    raw = "|".join(str(p or "") for p in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def parse_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    # ACLED renvoie généralement YYYY-MM-DD ; GDELT peut renvoyer YYYYMMDDHHMMSS.
    if re.fullmatch(r"\d{8,14}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10]


def round_coord(value: Any, decimals: int) -> Optional[float]:
    try:
        return round(float(value), decimals)
    except (TypeError, ValueError):
        return None


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


@dataclass
class Place:
    name: str
    region: str
    latitude: float
    longitude: float


def load_places() -> List[Place]:
    places: List[Place] = []
    if not MALI_PLACES_CSV.exists():
        return places
    with MALI_PLACES_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                places.append(Place(
                    name=row["name"].strip(),
                    region=row.get("region", "Mali").strip(),
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                ))
            except Exception:
                continue
    # Les noms longs d'abord pour éviter que "Gao" gagne face à un nom composé.
    return sorted(places, key=lambda p: len(p.name), reverse=True)


def match_place(text: str, places: List[Place]) -> Optional[Place]:
    haystack = f" {text.lower()} "
    for place in places:
        # Frontières souples pour noms avec accents/apostrophes.
        pattern = r"(?<![\w])" + re.escape(place.name.lower()) + r"(?![\w])"
        if re.search(pattern, haystack, flags=re.IGNORECASE):
            return place
    return None


def classify_acled_event(row: Dict[str, Any]) -> str:
    event_type = str(row.get("event_type") or "").lower()
    sub_event = str(row.get("sub_event_type") or "").lower()
    notes = str(row.get("notes") or "").lower()

    if "violence against civilians" in event_type or "attack" in sub_event:
        return "attaque"
    if "battles" in event_type or "armed clash" in sub_event:
        return "combat"
    if "explosions" in event_type or "remote violence" in event_type or "shelling" in sub_event or "air/drone" in sub_event:
        return "attaque"
    if "strategic developments" in event_type:
        if "looting" in sub_event or "disrupted" in sub_event or "abduction" in sub_event:
            return "attaque"
        return "politique"
    if "protests" in event_type or "riots" in event_type:
        return "politique"
    if "humanitarian" in notes or "aid" in notes or "displacement" in notes:
        return "humanitaire"
    return "autre"


def reliability_from_acled(row: Dict[str, Any]) -> str:
    geo_precision = str(row.get("geo_precision") or "").strip()
    time_precision = str(row.get("time_precision") or "").strip()
    # Chez ACLED, 1 = précision meilleure que 2/3 ; on reste prudent.
    if geo_precision == "1" and time_precision in {"1", ""}:
        return "probable"
    if geo_precision in {"2", "3"}:
        return "a-verifier"
    return "probable"


def precision_from_acled(row: Dict[str, Any]) -> str:
    geo_precision = str(row.get("geo_precision") or "").strip()
    if geo_precision == "1":
        return "approximation"
    if geo_precision == "2":
        return "regional"
    if geo_precision == "3":
        return "regional"
    return "approximation"


def actor_text(row: Dict[str, Any]) -> str:
    actors = []
    for key in ("actor1", "assoc_actor_1", "actor2", "assoc_actor_2"):
        value = safe_text(row.get(key), 180)
        if value and value not in actors:
            actors.append(value)
    return " / ".join(actors)


def acled_to_event(row: Dict[str, Any], coord_decimals: int) -> Optional[Dict[str, Any]]:
    lat = round_coord(row.get("latitude"), coord_decimals)
    lon = round_coord(row.get("longitude"), coord_decimals)
    if lat is None or lon is None:
        return None

    event_id = safe_text(row.get("event_id_cnty") or row.get("event_id_no_cnty") or "", 80)
    event_date = parse_date(row.get("event_date"))
    location = safe_text(row.get("location"), 120)
    admin1 = safe_text(row.get("admin1"), 120)
    event_type = safe_text(row.get("event_type"), 120)
    sub_event_type = safe_text(row.get("sub_event_type"), 120)
    fatalities = safe_text(row.get("fatalities"), 20)
    notes = safe_text(row.get("notes"), 600)
    actors = actor_text(row)

    title_parts = [part for part in [sub_event_type or event_type, location] if part]
    title = " — ".join(title_parts) if title_parts else "Événement ACLED au Mali"
    source_detail = safe_text(row.get("source"), 200)
    source_label = "ACLED" + (f" — {source_detail}" if source_detail else "")
    summary = notes or f"{event_type} / {sub_event_type}. Acteurs : {actors or 'non précisés'}."
    if fatalities not in {"", "0", "0.0"}:
        summary = f"{summary} Victimes rapportées par la source structurée : {fatalities}."

    return {
        "id": f"acled_{event_id}" if event_id else stable_hash(event_date, location, actors, summary, prefix="acled"),
        "date": event_date,
        "title": title,
        "location": location,
        "region": admin1 or "Mali",
        "latitude": lat,
        "longitude": lon,
        "type": classify_acled_event(row),
        "actors": actors,
        "reliability": reliability_from_acled(row),
        "precision": precision_from_acled(row),
        "summary": summary,
        "source": source_label,
        "url": "https://acleddata.com/",
        "source_event_id": event_id,
        "source_system": "ACLED",
    }


def acled_session() -> requests.Session:
    session = requests.Session()
    token = os.getenv("ACLED_ACCESS_TOKEN")
    if token:
        session.headers.update({"Authorization": f"Bearer {token}"})
        return session

    username = os.getenv("ACLED_USERNAME")
    password = os.getenv("ACLED_PASSWORD")
    if not username or not password:
        raise RuntimeError("ACLED_USERNAME/ACLED_PASSWORD absents : ACLED ignoré.")

    response = session.post(
        ACLED_LOGIN_URL,
        json={"name": username, "pass": password},
        timeout=30,
        headers={"Content-Type": "application/json"},
    )
    response.raise_for_status()
    return session


def fetch_acled(start: date, end: date, coord_decimals: int) -> List[Dict[str, Any]]:
    try:
        session = acled_session()
    except RuntimeError as exc:
        print(f"WARN — {exc}", file=sys.stderr)
        return []

    params = {
        "country": "Mali",
        "event_date": f"{start.isoformat()}|{end.isoformat()}",
        "event_date_where": "BETWEEN",
        "limit": "5000",
        "with_total": "true",
    }
    response = session.get(ACLED_READ_URL, params=params, timeout=60)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data", payload if isinstance(payload, list) else [])
    events = []
    for row in rows:
        if isinstance(row, dict):
            event = acled_to_event(row, coord_decimals)
            if event:
                events.append(event)
    return events


def gdelt_date(value: Any) -> str:
    return parse_date(value)


def fetch_gdelt_candidates(start: date, end: date, places: List[Place], coord_decimals: int) -> List[Dict[str, Any]]:
    if not env_bool("FETCH_GDELT", True):
        return []

    candidates: List[Dict[str, Any]] = []
    # GDELT DOC travaille bien avec timespan ; on limite largement pour rester léger.
    timespan_days = max(1, (end - start).days + 1)
    params = {
        "query": GDELT_QUERY,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": "75",
        "sort": "DateDesc",
        "timespan": f"{timespan_days}d",
    }
    try:
        response = requests.get(GDELT_DOC_URL, params=params, timeout=45)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        print(f"WARN — GDELT ignoré : {exc}", file=sys.stderr)
        return []

    seen_urls = set()
    for article in payload.get("articles", []) or []:
        url = safe_text(article.get("url"), 500)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        title = safe_text(article.get("title"), 300)
        domain = safe_text(article.get("domain") or urlparse(url).netloc, 120)
        text = " ".join([title, safe_text(article.get("seendate")), url])
        place = match_place(text, places)
        candidates.append({
            "date": gdelt_date(article.get("seendate")),
            "title": title,
            "source_system": "GDELT",
            "source": domain,
            "domain": domain,
            "matched_place": place.name if place else "",
            "latitude": round(place.latitude, coord_decimals) if place else "",
            "longitude": round(place.longitude, coord_decimals) if place else "",
            "summary": safe_text(article.get("snippet") or title, 500),
            "url": url,
            "status": "review",
        })
    return candidates


def fetch_reliefweb_candidates(start: date, end: date, places: List[Place], coord_decimals: int) -> List[Dict[str, Any]]:
    if not env_bool("FETCH_RELIEFWEB", True):
        return []

    appname = os.getenv("RELIEFWEB_APPNAME", "mali-conflict-monitor")
    payload = {
        "limit": 50,
        "sort": ["date:desc"],
        "fields": {
            "include": ["title", "date.created", "date.original", "source.name", "country.name", "url", "body"]
        },
        "filter": {
            "operator": "AND",
            "conditions": [
                {"field": "country.name", "value": "Mali"},
                {"field": "date.created", "value": {"from": start.isoformat(), "to": end.isoformat()}},
            ],
        },
        "query": {
            "value": "security conflict violence armed attack access humanitarian Mali",
            "operator": "OR",
        },
    }
    try:
        response = requests.post(f"{RELIEFWEB_REPORTS_URL}?appname={appname}", json=payload, timeout=45)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        print(f"WARN — ReliefWeb ignoré : {exc}", file=sys.stderr)
        return []

    candidates: List[Dict[str, Any]] = []
    for item in data.get("data", []) or []:
        fields = item.get("fields", {}) if isinstance(item, dict) else {}
        title = safe_text(fields.get("title"), 300)
        body = safe_text(fields.get("body"), 700)
        url = safe_text(fields.get("url"), 500)
        source_names = fields.get("source", []) or []
        source = ", ".join(safe_text(s.get("name"), 80) for s in source_names if isinstance(s, dict)) or "ReliefWeb"
        created = fields.get("date", {}).get("created") if isinstance(fields.get("date"), dict) else ""
        place = match_place(" ".join([title, body]), places)
        candidates.append({
            "date": parse_date(created),
            "title": title,
            "source_system": "ReliefWeb",
            "source": source,
            "domain": "reliefweb.int",
            "matched_place": place.name if place else "",
            "latitude": round(place.latitude, coord_decimals) if place else "",
            "longitude": round(place.longitude, coord_decimals) if place else "",
            "summary": body or title,
            "url": url,
            "status": "review",
        })
    return candidates


def read_manual_events() -> List[Dict[str, Any]]:
    data = read_json(MANUAL_EVENTS_GEOJSON, {"features": []})
    events = []
    for feature in data.get("features", []) or []:
        props = dict(feature.get("properties", {}) or {})
        coords = feature.get("geometry", {}).get("coordinates", [])
        if len(coords) >= 2:
            props["longitude"] = coords[0]
            props["latitude"] = coords[1]
            props.setdefault("source_system", "manual")
            props.setdefault("source_event_id", props.get("id", ""))
            events.append(props)
    return events


def dedupe_events(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    for event in events:
        event_id = safe_text(event.get("id"), 120) or stable_hash(
            event.get("date"), event.get("location"), event.get("actors"), event.get("summary"), prefix="evt"
        )
        event["id"] = event_id
        by_id[event_id] = event
    return sorted(by_id.values(), key=lambda e: str(e.get("date", "")), reverse=True)


def write_events_csv(events: List[Dict[str, Any]]) -> None:
    with EVENTS_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EVENT_FIELDS)
        writer.writeheader()
        for event in events:
            writer.writerow({field: event.get(field, "") for field in EVENT_FIELDS})


def event_to_feature(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    lat = round_coord(event.get("latitude"), 6)
    lon = round_coord(event.get("longitude"), 6)
    if lat is None or lon is None:
        return None
    props = {k: event.get(k, "") for k in EVENT_FIELDS if k not in {"latitude", "longitude"}}
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": props,
    }


def write_events_geojson(events: List[Dict[str, Any]], log: Dict[str, Any]) -> None:
    features = [feature for event in events if (feature := event_to_feature(event))]
    payload = {
        "type": "FeatureCollection",
        "metadata": {
            "title": "Mali Conflict Monitor",
            "last_updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event_count": len(features),
            "source_summary": log,
            "warning": "Carte analytique basée sur sources ouvertes. Ne pas publier de positions tactiques en temps réel, de mouvements non publics ou de données personnelles.",
        },
        "features": features,
    }
    EVENTS_GEOJSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_candidates(candidates: List[Dict[str, Any]]) -> None:
    seen = set()
    rows = []
    for c in candidates:
        key = c.get("url") or stable_hash(c.get("date"), c.get("title"), prefix="cand")
        if key in seen:
            continue
        seen.add(key)
        rows.append(c)
    with REVIEW_CANDIDATES_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CANDIDATE_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CANDIDATE_FIELDS})


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lookback_days = env_int("LOOKBACK_DAYS", 10)
    min_days_delay = env_int("MIN_DAYS_DELAY", 1)
    coord_decimals = env_int("COORD_DECIMALS", 3)

    end = today_utc() - timedelta(days=min_days_delay)
    start = end - timedelta(days=max(1, lookback_days) - 1)
    places = load_places()

    started = datetime.now(timezone.utc)
    source_counts: Dict[str, Any] = {
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "min_days_delay": min_days_delay,
        "coord_decimals": coord_decimals,
    }

    acled_events = fetch_acled(start, end, coord_decimals)
    source_counts["acled_events"] = len(acled_events)

    manual_events = read_manual_events()
    source_counts["manual_events"] = len(manual_events)

    gdelt_candidates = fetch_gdelt_candidates(start, end, places, coord_decimals)
    reliefweb_candidates = fetch_reliefweb_candidates(start, end, places, coord_decimals)
    source_counts["gdelt_candidates"] = len(gdelt_candidates)
    source_counts["reliefweb_candidates"] = len(reliefweb_candidates)

    events = dedupe_events([*acled_events, *manual_events])
    write_events_csv(events)
    write_candidates([*gdelt_candidates, *reliefweb_candidates])

    source_counts["published_events"] = len(events)
    source_counts["generated_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    source_counts["duration_seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 2)
    write_events_geojson(events, source_counts)
    SOURCE_LOG.write_text(json.dumps(source_counts, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(source_counts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
