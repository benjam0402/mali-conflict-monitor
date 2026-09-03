#!/usr/bin/env python3
"""Reconstruit data/events.geojson depuis le CSV normalisé du monitor."""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "events.csv"
OUT_PATH = ROOT / "data" / "events.geojson"

REQUIRED_COLUMNS = {
    "id",
    "date",
    "title",
    "layer",
    "layer_label",
    "actor",
    "status",
    "confidence",
    "summary",
    "source",
    "source_url",
}


def optional_float(value: str, row_id: str, field: str) -> float | None:
    if not str(value or "").strip():
        return None
    try:
        number = float(str(value).replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"Coordonnée invalide pour {row_id or 'ligne inconnue'} : {field}={value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"Coordonnée non finie pour {row_id or 'ligne inconnue'} : {field}")
    return number


def main() -> None:
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"Fichier introuvable : {CSV_PATH}")

    features = []
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Colonnes manquantes dans events.csv : {', '.join(sorted(missing))}")

        for row in reader:
            row_id = row.get("id", "")
            latitude = optional_float(row.get("latitude", ""), row_id, "latitude")
            longitude = optional_float(row.get("longitude", ""), row_id, "longitude")
            if (latitude is None) != (longitude is None):
                raise ValueError(f"Latitude et longitude doivent être renseignées ensemble pour {row_id}")
            if latitude is not None and not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                raise ValueError(f"Coordonnées hors limites pour {row_id}")

            source_url = str(row.get("source_url") or "").strip()
            parsed_url = urlparse(source_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                raise ValueError(f"URL source invalide pour {row_id}")

            properties = {
                key: (value or "").strip()
                for key, value in row.items()
                if key not in {"latitude", "longitude"}
            }
            properties["as_of"] = properties.get("date", "")
            geometry = None
            if latitude is not None and longitude is not None:
                geometry = {"type": "Point", "coordinates": [longitude, latitude]}
            features.append({"type": "Feature", "geometry": geometry, "properties": properties})

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {
        "type": "FeatureCollection",
        "metadata": {
            "title": "Mali Conflict Monitor — signaux médiatiques publics",
            "last_updated": generated_at,
            "generated_at": generated_at,
            "event_count": len(features),
            "mapped_event_count": sum(1 for feature in features if feature["geometry"] is not None),
            "warning": "Signaux médiatiques à vérifier ; les coordonnées sont approximatives.",
        },
        "features": features,
    }
    temporary = OUT_PATH.with_suffix(OUT_PATH.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(OUT_PATH)
    print(f"OK — {len(features)} signaux écrits dans {OUT_PATH}")


if __name__ == "__main__":
    main()
