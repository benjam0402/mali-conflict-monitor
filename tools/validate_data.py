from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

REQUIRED_EVENT_PROPERTIES = {
    "id",
    "title",
    "layer",
    "layer_label",
    "actor",
    "status",
    "confidence",
    "as_of",
    "summary",
    "source",
    "source_url",
}


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.relative_to(ROOT)} : JSON invalide ({exc})") from exc


def validate_url(value: Any, context: str) -> None:
    parsed = urlparse(str(value or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{context} : URL source invalide")


def walk_coordinates(value: Any, context: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{context} : coordonnées non conformes")
    if value and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value):
        if len(value) < 2 or not all(math.isfinite(float(item)) for item in value[:2]):
            raise ValueError(f"{context} : coordonnées invalides")
        longitude, latitude = float(value[0]), float(value[1])
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError(f"{context} : coordonnées hors limites")
        return
    for child in value:
        walk_coordinates(child, context)


def validate_collection(path: Path, require_features: bool) -> dict[str, Any]:
    payload = load_json(path)
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError(f"{path.relative_to(ROOT)} : FeatureCollection attendue")
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError(f"{path.relative_to(ROOT)} : features doit être une liste")
    if require_features and not features:
        raise ValueError(f"{path.relative_to(ROOT)} : aucun événement publié")
    return payload


def validate_events(payload: dict[str, Any]) -> None:
    seen_ids: set[str] = set()
    for index, feature in enumerate(payload["features"], start=1):
        context = f"data/events.geojson feature {index}"
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(f"{context} : Feature attendue")
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ValueError(f"{context} : propriétés manquantes")
        missing = sorted(key for key in REQUIRED_EVENT_PROPERTIES if not properties.get(key))
        if missing:
            raise ValueError(f"{context} : propriétés absentes ({', '.join(missing)})")
        event_id = str(properties["id"])
        if event_id in seen_ids:
            raise ValueError(f"{context} : identifiant dupliqué {event_id}")
        seen_ids.add(event_id)
        if properties.get("layer") != "event":
            raise ValueError(f"{context} : layer doit valoir event")
        validate_url(properties.get("source_url"), context)
        geometry = feature.get("geometry")
        if geometry is not None:
            if not isinstance(geometry, dict) or geometry.get("type") != "Point":
                raise ValueError(f"{context} : seuls les points ou geometry=null sont acceptés")
            walk_coordinates(geometry.get("coordinates"), context)


def validate_map_context(payload: dict[str, Any]) -> None:
    for index, feature in enumerate(payload["features"], start=1):
        context = f"data/map_context.geojson feature {index}"
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(f"{context} : Feature attendue")
        properties = feature.get("properties")
        if not isinstance(properties, dict) or not properties.get("name"):
            raise ValueError(f"{context} : nom de pays absent")
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"{context} : Polygon ou MultiPolygon attendu")
        walk_coordinates(geometry.get("coordinates"), context)


def validate_source_log() -> dict[str, Any]:
    log = load_json(DATA_DIR / "source_log.json")
    if not isinstance(log, dict) or int(log.get("successful_sources", 0)) < 1:
        raise ValueError("data/source_log.json : aucune source publique réussie")
    if int(log.get("published_events", 0)) < 1:
        raise ValueError("data/source_log.json : aucun signal publié")
    return log


def validate_csv() -> int:
    path = DATA_DIR / "events.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("data/events.csv : aucun événement publié")
    return len(rows)


def validate_social_watch() -> dict[str, Any]:
    payload = load_json(DATA_DIR / "social_watch.json")
    targets = payload.get("targets") if isinstance(payload, dict) else None
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    if not isinstance(targets, list) or not isinstance(metadata, dict):
        raise ValueError("data/social_watch.json : structure invalide")
    seen_handles: set[str] = set()
    for index, target in enumerate(targets, start=1):
        context = f"data/social_watch.json cible {index}"
        if not isinstance(target, dict) or not target.get("name") or not target.get("handle"):
            raise ValueError(f"{context} : nom ou identifiant absent")
        handle = str(target["handle"]).casefold()
        if handle in seen_handles:
            raise ValueError(f"{context} : identifiant dupliqué")
        seen_handles.add(handle)
        validate_url(target.get("profile_url"), context)
        if not isinstance(target.get("feed_active"), bool):
            raise ValueError(f"{context} : feed_active doit être booléen")
    if int(metadata.get("target_count", -1)) != len(targets):
        raise ValueError("data/social_watch.json : compteur de cibles incohérent")
    return payload


def main() -> None:
    validate_collection(DATA_DIR / "situation.geojson", require_features=True)
    map_context = validate_collection(DATA_DIR / "map_context.geojson", require_features=True)
    validate_map_context(map_context)
    events = validate_collection(DATA_DIR / "events.geojson", require_features=True)
    validate_events(events)
    log = validate_source_log()
    social_watch = validate_social_watch()
    csv_count = validate_csv()
    if csv_count != len(events["features"]):
        raise ValueError("events.csv et events.geojson n'ont pas le même nombre d'éléments")
    print(
        "Validation OK — "
        f"{len(events['features'])} signaux, "
        f"{events.get('metadata', {}).get('mapped_event_count', 0)} cartographiés, "
        f"{log.get('successful_sources')} sources accessibles, "
        f"{social_watch['metadata'].get('target_count')} comptes sociaux ciblés."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"VALIDATION ERROR — {exc}", file=sys.stderr)
        sys.exit(1)
