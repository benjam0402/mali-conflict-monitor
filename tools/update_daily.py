from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import os
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
EVENTS_GEOJSON = DATA_DIR / "events.geojson"
EVENTS_CSV = DATA_DIR / "events.csv"
MANUAL_EVENTS_GEOJSON = DATA_DIR / "manual_events.geojson"
REVIEW_CANDIDATES_CSV = DATA_DIR / "review_candidates.csv"
SOURCE_LOG = DATA_DIR / "source_log.json"
SAHEL_PLACES_CSV = ROOT / "tools" / "sahel_places.csv"
PUBLIC_SOURCES_JSON = ROOT / "tools" / "public_sources.json"
SOCIAL_TARGETS_JSON = ROOT / "tools" / "social_targets.json"
SOCIAL_WATCH_JSON = DATA_DIR / "social_watch.json"

GDELT_QUERY = (
    '(Mali OR Niger OR "Burkina Faso" OR Mauritania OR Mauritanie OR Chad OR Tchad) '
    '(JNIM OR GSIM OR FAMa OR FDS OR VDP OR insurgent OR attack OR attaque OR clash '
    'OR affrontement OR violence OR blockade OR blocus)'
)

EVENT_FIELDS = [
    "id",
    "date",
    "title",
    "location",
    "region",
    "country",
    "latitude",
    "longitude",
    "layer",
    "layer_label",
    "category",
    "actor",
    "status",
    "confidence",
    "precision",
    "summary",
    "source",
    "source_url",
    "source_system",
    "language",
]

CANDIDATE_FIELDS = [
    "date",
    "title",
    "source_system",
    "source",
    "domain",
    "language",
    "matched_place",
    "country",
    "latitude",
    "longitude",
    "category",
    "relevance_score",
    "summary",
    "url",
    "status",
]

TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}

COUNTRY_TERMS = {
    "Mali": {"mali", "malien", "malienne", "bamako", "azawad", "fama"},
    "Niger": {"niger", "nigerien", "nigerienne", "niamey"},
    "Burkina Faso": {"burkina", "burkina faso", "burkinabe", "ouagadougou", "fds", "vdp"},
    "Mauritanie": {"mauritanie", "mauritania", "mauritanien", "mauritanienne", "nouakchott"},
    "Tchad": {"tchad", "chad", "tchadien", "tchadienne", "n djamena", "ndjamena"},
}
SAHEL_TERMS = set().union(*COUNTRY_TERMS.values())

CONFLICT_TERMS = {
    "attaque",
    "attaques",
    "attack",
    "attacks",
    "affrontement",
    "affrontements",
    "clash",
    "clashes",
    "combat",
    "combats",
    "conflit",
    "conflict",
    "coup d etat",
    "couvre feu",
    "drone",
    "explosion",
    "frappe",
    "insurgent",
    "jihadist",
    "jihadiste",
    "jihadistes",
    "militaire",
    "military",
    "armee",
    "armed",
    "rebelle",
    "rebel",
    "soldat",
    "soldats",
    "securite",
    "security",
    "terrorisme",
    "terrorist",
    "violence",
    "blocus",
    "blockade",
}

HARD_CONFLICT_TERMS = {
    "attaque",
    "attaques",
    "attack",
    "attacks",
    "affrontement",
    "affrontements",
    "ambush",
    "blocus",
    "blockade",
    "combat",
    "combattant",
    "combattants",
    "combats",
    "conflit",
    "conflict",
    "coup d etat",
    "couvre feu",
    "drone",
    "embuscade",
    "enlevement",
    "explosion",
    "explosif",
    "explosifs",
    "frappe",
    "frappes",
    "hostage",
    "insurgent",
    "ied",
    "jihadist",
    "jihadiste",
    "jihadistes",
    "kidnap",
    "otage",
    "otages",
    "raid",
    "rebelle",
    "rebel",
    "terrorisme",
    "terrorist",
    "violence",
    "groupe arme",
    "groupes armes",
}

ACTOR_PATTERNS = [
    ({"jnim", "gsim", "jama at nusrat"}, "JNIM / GSIM"),
    ({"fama", "armee malienne", "malian army", "forces armees maliennes"}, "FAMa / État malien"),
    ({"fla", "front de liberation de l azawad", "azawad liberation front"}, "FLA / Azawad"),
    ({"etat islamique au sahel", "islamic state sahel", "issp", "eigs"}, "État islamique au Sahel"),
    ({"forces armees nigeriennes", "armee nigerienne", "fan niger"}, "Forces nigériennes"),
    ({"forces de defense et de securite", "volontaires pour la defense de la patrie", "vdp"}, "FDS / VDP — Burkina Faso"),
    ({"armee mauritanienne", "forces armees mauritaniennes"}, "Forces mauritaniennes"),
    ({"armee tchadienne", "forces armees tchadiennes"}, "Forces tchadiennes"),
]

TRUSTED_SOURCE_TERMS = {
    "associated press",
    "bamada",
    "bbc",
    "burkina 24",
    "burkina24",
    "deutsche welle",
    "dw",
    "france 24",
    "journal du mali",
    "maliactu",
    "malijet",
    "maliweb",
    "onu info",
    "reuters",
    "rfi",
    "sahara medias",
    "studio tamani",
    "studio kalangou",
    "tchadinfos",
}

MAX_RESPONSE_BYTES = 6_000_000
SAHEL_BOUNDS = {"min_lon": -18.5, "max_lon": 25.5, "min_lat": 7.0, "max_lat": 28.5}
SOCIAL_HANDLE_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,30}$")


@dataclass(frozen=True)
class Place:
    name: str
    region: str
    latitude: float
    longitude: float
    normalized_name: str
    country: str = "Mali"
    normalized_aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Article:
    title: str
    url: str
    source: str
    source_system: str
    published: str
    summary: str
    language: str
    tier: str
    query_matched: bool = False
    country_hint: str = ""


def env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def normalize_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def safe_text(value: Any, max_len: int = 500) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def stable_hash(*parts: Any, prefix: str = "signal") -> str:
    raw = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def parse_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"\d{8,14}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def parse_iso_date(value: Any) -> Optional[date]:
    parsed = parse_date(value)
    try:
        return date.fromisoformat(parsed)
    except ValueError:
        return None


def round_coord(value: Any, decimals: int) -> Optional[float]:
    try:
        coordinate = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(coordinate):
        return None
    return round(coordinate, decimals)


def is_sahel_coordinate(latitude: float, longitude: float) -> bool:
    return (
        SAHEL_BOUNDS["min_lat"] <= latitude <= SAHEL_BOUNDS["max_lat"]
        and SAHEL_BOUNDS["min_lon"] <= longitude <= SAHEL_BOUNDS["max_lon"]
    )


def canonical_url(value: Any) -> str:
    text = str(value or "").strip()
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    query = urlencode(
        [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() not in TRACKING_QUERY_KEYS]
    )
    cleaned = parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower(), query=query, fragment="")
    return urlunparse(cleaned)


def strip_source_suffix(title: str, source: str) -> str:
    cleaned_title = safe_text(title, 320)
    cleaned_source = safe_text(source, 120)
    if not cleaned_source:
        return cleaned_title
    for separator in (" - ", " – ", " — "):
        suffix = f"{separator}{cleaned_source}"
        if cleaned_title.casefold().endswith(suffix.casefold()):
            return cleaned_title[: -len(suffix)].rstrip()
    return cleaned_title


def article_priority(article: Article) -> tuple[int, int, int]:
    normalized_source = normalize_text(article.source)
    return (
        1 if article.tier == "editorial" else 0,
        1 if contains_any(normalized_source, TRUSTED_SOURCE_TERMS) else 0,
        1 if article.summary and article.summary != article.title else 0,
    )


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def atomic_write_text(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def load_places() -> list[Place]:
    places: list[Place] = []
    with SAHEL_PLACES_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                latitude = float(row["latitude"])
                longitude = float(row["longitude"])
                name = row["name"].strip()
                country = (row.get("country") or "").strip()
                aliases = tuple(
                    normalized
                    for alias in str(row.get("aliases") or "").split("|")
                    if (normalized := normalize_text(alias)) and len(normalized) >= 4
                )
                if name and country in COUNTRY_TERMS and is_sahel_coordinate(latitude, longitude):
                    places.append(
                        Place(
                            name=name,
                            region=(row.get("region") or country).strip(),
                            latitude=latitude,
                            longitude=longitude,
                            normalized_name=normalize_text(name),
                            country=country,
                            normalized_aliases=aliases,
                        )
                    )
            except (KeyError, TypeError, ValueError):
                continue
    return sorted(places, key=lambda place: len(place.normalized_name), reverse=True)


def load_public_sources() -> list[dict[str, Any]]:
    payload = read_json(PUBLIC_SOURCES_JSON, [])
    if not isinstance(payload, list):
        raise ValueError("tools/public_sources.json doit contenir une liste JSON.")
    sources: list[dict[str, Any]] = []
    for source in payload:
        if not isinstance(source, dict) or source.get("enabled", True) is False:
            continue
        name = safe_text(source.get("name"), 120)
        kind = str(source.get("kind") or "").strip().lower()
        url = canonical_url(source.get("url"))
        if name and kind in {"gdelt", "rss"} and url:
            sources.append({**source, "name": name, "kind": kind, "url": url})
    if not sources:
        raise ValueError("Aucune source publique active et valide.")
    return sources


def normalize_social_targets(
    payload: Any, rss_template: str = ""
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(payload, list):
        raise ValueError("tools/social_targets.json doit contenir une liste JSON.")
    template = str(rss_template or "").strip()
    if template and "{handle}" not in template:
        raise ValueError("X_RSS_TEMPLATE doit contenir le marqueur {handle}.")

    targets: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict) or item.get("enabled", True) is False:
            continue
        platform = str(item.get("platform") or "x").strip().lower()
        handle = str(item.get("handle") or "").strip().lstrip("@")
        name = safe_text(item.get("name"), 120)
        if platform not in {"x", "twitter"} or not name or not SOCIAL_HANDLE_PATTERN.fullmatch(handle):
            continue

        profile_url = canonical_url(item.get("profile_url")) or f"https://x.com/{handle}"
        rss_url = canonical_url(item.get("rss_url"))
        discovery_method = "Flux RSS direct"
        if not rss_url and template:
            try:
                rss_url = canonical_url(template.format(handle=handle))
            except (KeyError, ValueError):
                rss_url = ""
        if not rss_url:
            rss_url = canonical_url(item.get("search_rss_url"))
            discovery_method = "Index public de X"

        target = {
            "name": name,
            "platform": "X",
            "handle": handle,
            "profile_url": profile_url,
            "country": safe_text(item.get("country") or "Sahel", 40),
            "feed_active": bool(rss_url),
            "discovery_method": discovery_method if rss_url else "Veille directe",
        }
        targets.append(target)
        if rss_url:
            sources.append(
                {
                    "name": f"X indexé — @{handle}" if discovery_method == "Index public de X" else f"X public — @{handle}",
                    "kind": "social_rss",
                    "url": rss_url,
                    "tier": "social",
                    "language": safe_text(item.get("language") or "fr", 40),
                    "publisher": name,
                    "handle": handle,
                    "country": target["country"],
                    "query_matched": discovery_method == "Index public de X",
                }
            )
    return targets, sources


def load_social_targets() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = read_json(SOCIAL_TARGETS_JSON, [])
    return normalize_social_targets(payload, os.getenv("X_RSS_TEMPLATE", ""))


def fetch_bytes(url: str, accept: str, attempts: int = 3) -> bytes:
    last_error: Optional[Exception] = None
    for attempt in range(attempts):
        request = Request(
            url,
            headers={
                "Accept": accept,
                "User-Agent": "SahelConflictMonitor/3.0 (+https://github.com/benjam0402/mali-conflict-monitor)",
            },
        )
        try:
            with urlopen(request, timeout=45) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise ValueError(f"Réponse trop volumineuse ({len(payload)} octets)")
                return payload
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(2**attempt)
    raise RuntimeError(f"Échec HTTP après {attempts} essais : {last_error}")


def identify_country(text: str, place: Optional[Place] = None, country_hint: str = "") -> str:
    if place:
        return place.country
    if country_hint in COUNTRY_TERMS:
        return country_hint
    normalized = normalize_text(text)
    for country, terms in COUNTRY_TERMS.items():
        if contains_any(normalized, terms):
            return country
    return ""


def match_place(text: str, places: list[Place], country_hint: str = "") -> Optional[Place]:
    haystack = f" {normalize_text(text)} "
    inferred_country = identify_country(text, country_hint=country_hint)
    candidates = [place for place in places if not inferred_country or place.country == inferred_country]
    for place in candidates:
        names = (place.normalized_name, *place.normalized_aliases)
        for name in names:
            pattern = r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])"
            if re.search(pattern, haystack):
                return place
    return None


def contains_any(text: str, terms: Iterable[str]) -> bool:
    padded = f" {text} "
    return any(f" {normalize_text(term)} " in padded for term in terms)


def classify_article(text: str) -> str:
    normalized = normalize_text(text)
    if contains_any(normalized, {"humanitaire", "humanitarian", "deplace", "displaced", "refugie", "refugee", "famine"}):
        return "humanitaire"
    if contains_any(normalized, {"election", "transition", "diplomatie", "diplomacy", "sanction", "negociation", "talks"}):
        return "politique"
    if contains_any(normalized, CONFLICT_TERMS):
        return "sécurité"
    return "autre"


def identify_actor(text: str) -> str:
    normalized = normalize_text(text)
    actors = [label for terms, label in ACTOR_PATTERNS if contains_any(normalized, terms)]
    if len(actors) == 1:
        return actors[0]
    if len(actors) > 1:
        return "Plusieurs acteurs"
    return "À vérifier"


def relevance_score(article: Article, place: Optional[Place]) -> int:
    normalized = normalize_text(f"{article.title} {article.summary}")
    score = 0
    if contains_any(normalized, SAHEL_TERMS) or place or article.country_hint in COUNTRY_TERMS:
        score += 2
    if contains_any(normalized, CONFLICT_TERMS):
        score += 2
    if any(contains_any(normalized, terms) for terms, _ in ACTOR_PATTERNS):
        score += 1
    if place:
        score += 1
    if article.tier == "editorial":
        score += 1
    if article.query_matched:
        score += 1
    return score


def is_publishable(article: Article, place: Optional[Place], score: int, threshold: int) -> bool:
    normalized = normalize_text(f"{article.title} {article.summary}")
    mentions_sahel_country = (
        contains_any(normalized, SAHEL_TERMS)
        or place is not None
        or article.country_hint in COUNTRY_TERMS
    )
    mentions_conflict = contains_any(normalized, HARD_CONFLICT_TERMS)
    if article.tier == "social":
        return score >= max(threshold, 5) and mentions_sahel_country and mentions_conflict
    return score >= threshold and (article.query_matched or (mentions_sahel_country and mentions_conflict))


def fetch_gdelt(source: dict[str, Any], lookback_days: int) -> list[Article]:
    params = {
        "query": safe_text(source.get("query") or GDELT_QUERY, 600),
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(env_int("GDELT_MAX_RECORDS", 250, 10, 250)),
        "sort": "DateDesc",
        "timespan": f"{lookback_days}d",
    }
    separator = "&" if urlparse(source["url"]).query else "?"
    url = f"{source['url']}{separator}{urlencode(params)}"
    payload: dict[str, Any] = {}
    for attempt in range(3):
        raw_payload = fetch_bytes(url, "application/json", attempts=1).decode("utf-8-sig")
        try:
            decoded = json.loads(raw_payload)
            payload = decoded if isinstance(decoded, dict) else {}
            break
        except json.JSONDecodeError as exc:
            if "limit requests" not in raw_payload.lower() or attempt == 2:
                raise ValueError(f"Réponse GDELT non JSON : {safe_text(raw_payload, 160)}") from exc
            time.sleep(6 * (attempt + 1))
    articles: list[Article] = []
    for item in payload.get("articles", []):
        if not isinstance(item, dict):
            continue
        article_url = canonical_url(item.get("url"))
        title = safe_text(item.get("title"), 320)
        if not article_url or not title:
            continue
        domain = safe_text(item.get("domain") or urlparse(article_url).netloc, 120)
        articles.append(
            Article(
                title=title,
                url=article_url,
                source=domain,
                source_system=source["name"],
                published=parse_date(item.get("seendate")),
                summary=safe_text(item.get("snippet") or title, 600),
                language=safe_text(item.get("language") or source.get("language"), 40),
                tier=str(source.get("tier") or "aggregator"),
                query_matched=True,
                country_hint=safe_text(source.get("country"), 40),
            )
        )
    return articles


def xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def first_xml_text(element: ET.Element, names: set[str]) -> str:
    for child in element.iter():
        if xml_local_name(child.tag) in names and child.text and child.text.strip():
            return child.text.strip()
    return ""


def rss_item_link(item: ET.Element) -> str:
    for child in item.iter():
        if xml_local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href", "").strip()
        relation = child.attrib.get("rel", "alternate").strip().lower()
        if href and relation in {"alternate", ""}:
            return canonical_url(href)
        if child.text and child.text.strip():
            return canonical_url(child.text.strip())
    return ""


def fetch_rss(source: dict[str, Any]) -> list[Article]:
    root = ET.fromstring(fetch_bytes(source["url"], "application/rss+xml, application/atom+xml, application/xml, text/xml"))
    entries = [element for element in root.iter() if xml_local_name(element.tag) in {"item", "entry"}]
    articles: list[Article] = []
    for item in entries:
        title = safe_text(first_xml_text(item, {"title"}), 320)
        article_url = rss_item_link(item)
        if not title or not article_url:
            continue
        description = first_xml_text(item, {"description", "summary", "content", "encoded"})
        published = first_xml_text(item, {"pubdate", "published", "updated", "date"})
        item_source = first_xml_text(item, {"source"})
        publisher = safe_text(source.get("publisher") or item_source, 120) or source["name"]
        if source.get("query_matched", False):
            title = strip_source_suffix(title, publisher)
        articles.append(
            Article(
                title=title,
                url=article_url,
                source=publisher,
                source_system=source["name"],
                published=parse_date(published),
                summary=safe_text(description or title, 350),
                language=safe_text(source.get("language"), 40),
                tier=str(source.get("tier") or "editorial"),
                query_matched=bool(source.get("query_matched", False)),
                country_hint=safe_text(source.get("country"), 40),
            )
        )
    return articles


def candidate_row(article: Article, place: Optional[Place], score: int, status: str, decimals: int) -> dict[str, Any]:
    country = identify_country(f"{article.title} {article.summary}", place, article.country_hint)
    return {
        "date": article.published,
        "title": article.title,
        "source_system": article.source_system,
        "source": article.source,
        "domain": urlparse(article.url).netloc,
        "language": article.language,
        "matched_place": place.name if place else "",
        "country": country,
        "latitude": round(place.latitude, decimals) if place else "",
        "longitude": round(place.longitude, decimals) if place else "",
        "category": classify_article(f"{article.title} {article.summary}"),
        "relevance_score": score,
        "summary": article.summary,
        "url": article.url,
        "status": status,
    }


def article_to_event(article: Article, place: Optional[Place], score: int, decimals: int) -> dict[str, Any]:
    event_date = article.published or today_utc().isoformat()
    country = (
        identify_country(f"{article.title} {article.summary}", place, article.country_hint)
        or "Sahel — pays à confirmer"
    )
    actor = identify_actor(f"{article.title} {article.summary}")
    category = classify_article(f"{article.title} {article.summary}")
    return {
        "id": stable_hash(canonical_url(article.url), prefix="media"),
        "date": event_date,
        "title": article.title,
        "location": place.name if place else f"{country} — lieu à confirmer",
        "region": place.region if place else country,
        "country": country,
        "latitude": round(place.latitude, decimals) if place else "",
        "longitude": round(place.longitude, decimals) if place else "",
        "layer": "event",
        "layer_label": "Signal réseau social" if article.tier == "social" else "Signal médiatique",
        "category": category,
        "actor": actor,
        "status": (
            "Signal réseau social — recoupement requis"
            if article.tier == "social"
            else "Signal médiatique — vérification requise"
        ),
        "confidence": "moyenne" if article.tier == "editorial" and place and score >= 6 else "faible",
        "precision": "centre de localité approximatif" if place else "non géolocalisé",
        "summary": article.summary,
        "source": article.source,
        "source_url": article.url,
        "source_system": article.source_system,
        "language": article.language,
    }


def event_to_feature(event: dict[str, Any]) -> dict[str, Any]:
    latitude = round_coord(event.get("latitude"), 6)
    longitude = round_coord(event.get("longitude"), 6)
    geometry: Optional[dict[str, Any]] = None
    if latitude is not None and longitude is not None and is_sahel_coordinate(latitude, longitude):
        geometry = {"type": "Point", "coordinates": [longitude, latitude]}
    properties = {field: event.get(field, "") for field in EVENT_FIELDS if field not in {"latitude", "longitude"}}
    properties["as_of"] = properties.get("date", "")
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def feature_to_event(feature: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not isinstance(feature, dict):
        return None
    properties = dict(feature.get("properties") or {})
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates") if geometry.get("type") == "Point" else None
    if isinstance(coordinates, list) and len(coordinates) >= 2:
        properties["longitude"] = coordinates[0]
        properties["latitude"] = coordinates[1]
    properties.setdefault("date", properties.get("as_of", ""))
    properties.setdefault("layer", "event")
    properties.setdefault("layer_label", "Événement manuel")
    properties.setdefault("category", "autre")
    properties.setdefault("actor", "À vérifier")
    properties.setdefault("status", "Événement manuel — vérification requise")
    properties.setdefault("confidence", "faible")
    properties.setdefault("precision", "approximation")
    properties.setdefault("source_url", properties.get("url", ""))
    properties.setdefault("source_system", "manual")
    properties.setdefault("language", "fr")
    properties.setdefault("country", "Mali")
    properties["id"] = safe_text(properties.get("id"), 120) or stable_hash(
        properties.get("date"), properties.get("title"), properties.get("source_url"), prefix="manual"
    )
    if not properties.get("title"):
        return None
    return {field: properties.get(field, "") for field in EVENT_FIELDS}


def event_matches_current_filter(event: dict[str, Any]) -> bool:
    normalized = normalize_text(f"{event.get('title', '')} {event.get('summary', '')}")
    return contains_any(normalized, HARD_CONFLICT_TERMS)


def read_previous_events(cutoff: date) -> list[dict[str, Any]]:
    payload = read_json(EVENTS_GEOJSON, {"features": []})
    events: list[dict[str, Any]] = []
    for feature in payload.get("features", []) if isinstance(payload, dict) else []:
        event = feature_to_event(feature)
        event_date = parse_iso_date(event.get("date")) if event else None
        if event and event_date and event_date >= cutoff and event_matches_current_filter(event):
            events.append(event)
    return events


def read_manual_events() -> list[dict[str, Any]]:
    payload = read_json(MANUAL_EVENTS_GEOJSON, {"features": []})
    events: list[dict[str, Any]] = []
    for feature in payload.get("features", []) if isinstance(payload, dict) else []:
        event = feature_to_event(feature)
        if event:
            event["source_system"] = "manual"
            events.append(event)
    return events


def dedupe_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for event in events:
        source_url = canonical_url(event.get("source_url"))
        normalized_title = normalize_text(
            strip_source_suffix(str(event.get("title", "")), str(event.get("source", "")))
        )
        key = stable_hash(event.get("date"), normalized_title, prefix="story") if len(normalized_title) >= 24 else source_url
        key = key or safe_text(event.get("id"), 120)
        if not key:
            key = stable_hash(event.get("date"), event.get("title"), event.get("source"))
        event["source_url"] = source_url
        by_key[key] = event
    return sorted(by_key.values(), key=lambda event: (str(event.get("date", "")), str(event.get("title", ""))), reverse=True)


def write_events_csv(events: list[dict[str, Any]]) -> None:
    temporary = EVENTS_CSV.with_suffix(EVENTS_CSV.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS, lineterminator="\n")
        writer.writeheader()
        for event in events:
            writer.writerow({field: event.get(field, "") for field in EVENT_FIELDS})
    os.replace(temporary, EVENTS_CSV)


def write_candidates(candidates: list[dict[str, Any]]) -> None:
    temporary = REVIEW_CANDIDATES_CSV.with_suffix(REVIEW_CANDIDATES_CSV.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDS, lineterminator="\n")
        writer.writeheader()
        for candidate in candidates:
            writer.writerow({field: candidate.get(field, "") for field in CANDIDATE_FIELDS})
    os.replace(temporary, REVIEW_CANDIDATES_CSV)


def write_social_watch(targets: list[dict[str, Any]], generated_at: str) -> None:
    payload = {
        "metadata": {
            "generated_at": generated_at,
            "target_count": len(targets),
            "active_feed_count": sum(1 for target in targets if target.get("feed_active")),
            "warning": (
                "Les profils X sont suivis via leur indexation publique dans des flux RSS ouverts. "
                "Cette méthode sans jeton reste partielle ; chaque signal est filtré, retardé et doit être recoupé."
            ),
        },
        "targets": targets,
    }
    atomic_write_text(SOCIAL_WATCH_JSON, json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def write_events_geojson(events: list[dict[str, Any]], log: dict[str, Any]) -> None:
    features = [event_to_feature(event) for event in events]
    dated_events = [event.get("date", "") for event in events if parse_iso_date(event.get("date"))]
    payload = {
        "type": "FeatureCollection",
        "metadata": {
            "title": "Sahel Conflict Monitor — signaux médiatiques et sociaux publics",
            "last_updated": log["generated_at_utc"],
            "generated_at": log["generated_at_utc"],
            "latest_signal_date": max(dated_events, default=""),
            "event_count": len(features),
            "mapped_event_count": sum(1 for feature in features if feature["geometry"] is not None),
            "source_summary": log,
            "warning": (
                "Ces points sont des signaux issus de médias publics, pas des faits indépendamment confirmés. "
                "Les coordonnées représentent au mieux le centre approximatif d'une localité citée."
            ),
        },
        "features": features,
    }
    atomic_write_text(EVENTS_GEOJSON, json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lookback_days = env_int("LOOKBACK_DAYS", 14, 2, 90)
    min_days_delay = env_int("MIN_DAYS_DELAY", 2, 1, 30)
    coord_decimals = env_int("COORD_DECIMALS", 3, 1, 3)
    retention_days = env_int("RETENTION_DAYS", 45, lookback_days, 180)
    max_published_events = env_int("MAX_PUBLISHED_EVENTS", 250, 10, 1000)
    relevance_threshold = env_int("RELEVANCE_THRESHOLD", 4, 2, 8)

    now = datetime.now(timezone.utc)
    publish_before = today_utc() - timedelta(days=min_days_delay)
    cutoff = today_utc() - timedelta(days=retention_days)
    places = load_places()
    social_targets, social_sources = load_social_targets()
    sources = [*load_public_sources(), *social_sources]

    source_results: list[dict[str, Any]] = []
    articles: list[Article] = []
    for source in sources:
        if source["kind"] == "gdelt" and not env_bool("FETCH_GDELT", True):
            continue
        if source["kind"] == "rss" and not env_bool("FETCH_RSS", True):
            continue
        if source["kind"] == "social_rss" and not env_bool("FETCH_SOCIAL", True):
            continue
        try:
            fetched = fetch_gdelt(source, lookback_days) if source["kind"] == "gdelt" else fetch_rss(source)
            articles.extend(fetched)
            source_results.append({"name": source["name"], "kind": source["kind"], "status": "ok", "articles": len(fetched)})
        except Exception as exc:
            message = safe_text(exc, 240)
            print(f"WARN — {source['name']} ignorée : {message}", file=sys.stderr)
            source_results.append(
                {"name": source["name"], "kind": source["kind"], "status": "error", "articles": 0, "error": message}
            )

    successful_sources = sum(1 for result in source_results if result["status"] == "ok")
    if successful_sources == 0:
        raise RuntimeError("Toutes les sources publiques ont échoué ; les dernières données valides sont conservées.")

    unique_articles: dict[str, Article] = {}
    for article in articles:
        normalized_title = normalize_text(strip_source_suffix(article.title, article.source))
        key = (
            stable_hash(article.published, normalized_title, prefix="story")
            if len(normalized_title) >= 24
            else canonical_url(article.url) or stable_hash(article.source, article.title, article.published)
        )
        previous = unique_articles.get(key)
        if previous is None or article_priority(article) > article_priority(previous):
            unique_articles[key] = article

    candidates: list[dict[str, Any]] = []
    fresh_events: list[dict[str, Any]] = []
    for article in sorted(unique_articles.values(), key=lambda item: item.published, reverse=True):
        place = match_place(f"{article.title} {article.summary}", places, article.country_hint)
        score = relevance_score(article, place)
        article_date = parse_iso_date(article.published)
        if not article_date:
            status = "date-manquante"
        elif article_date > publish_before:
            status = "embargo-delay"
        elif article_date < cutoff:
            status = "hors-fenetre"
        elif is_publishable(article, place, score, relevance_threshold):
            status = "published-signal"
            fresh_events.append(article_to_event(article, place, score, coord_decimals))
        else:
            status = "filtered"
        candidates.append(candidate_row(article, place, score, status, coord_decimals))

    previous_events = read_previous_events(cutoff)
    manual_events = read_manual_events()
    automatic_events = dedupe_events([*previous_events, *fresh_events])[:max_published_events]
    events = dedupe_events([*automatic_events, *manual_events])

    if not events:
        raise RuntimeError(
            "Aucun signal publiable n'a été trouvé et aucune donnée antérieure n'est disponible ; "
            "les fichiers publiés ne sont pas écrasés."
        )

    generated_at = now.isoformat(timespec="seconds")
    log: dict[str, Any] = {
        "window_start": cutoff.isoformat(),
        "publication_cutoff": publish_before.isoformat(),
        "lookback_days": lookback_days,
        "retention_days": retention_days,
        "min_days_delay": min_days_delay,
        "coord_decimals": coord_decimals,
        "sources_configured": len(sources),
        "sources_attempted": len(source_results),
        "successful_sources": successful_sources,
        "failed_sources": len(source_results) - successful_sources,
        "local_media_sources": sum(1 for source in sources if source.get("local")),
        "social_targets": len(social_targets),
        "social_feeds_active": len(social_sources),
        "countries_monitored": list(COUNTRY_TERMS),
        "source_results": source_results,
        "articles_fetched": len(articles),
        "unique_articles": len(unique_articles),
        "fresh_signals": len(fresh_events),
        "retained_signals": len(automatic_events),
        "manual_events": len(manual_events),
        "published_events": len(events),
        "mapped_events": sum(1 for event in events if event.get("latitude") not in {"", None}),
        "generated_at_utc": generated_at,
        "duration_seconds": round((datetime.now(timezone.utc) - now).total_seconds(), 2),
    }

    write_candidates(candidates[:1000])
    write_events_csv(events)
    write_events_geojson(events, log)
    write_social_watch(social_targets, generated_at)
    atomic_write_text(SOURCE_LOG, json.dumps(log, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps(log, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR — mise à jour annulée : {safe_text(exc, 500)}", file=sys.stderr)
        sys.exit(1)
