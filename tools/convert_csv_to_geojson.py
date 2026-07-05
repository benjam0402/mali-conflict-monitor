#!/usr/bin/env python3
"""
Convertit data/events.csv en data/events.geojson.

Colonnes attendues :
id,date,title,location,region,latitude,longitude,type,actors,reliability,precision,summary,source,url

Usage :
python tools/convert_csv_to_geojson.py
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "events.csv"
OUT_PATH = ROOT / "data" / "events.geojson"

REQUIRED_COLUMNS = {
    "id", "date", "title", "location", "region", "latitude", "longitude",
    "type", "actors", "reliability", "precision", "summary", "source", "url"
}


def parse_float(value: str, row_id: str, field: str) -> float:
    try:
        return float(str(value).replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"Coordonnée invalide pour {row_id or 'ligne inconnue'} : {field}={value!r}") from exc


def main() -> None:
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"Fichier introuvable : {CSV_PATH}")

    features = []
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Colonnes manquantes dans events.csv : {', '.join(sorted(missing))}")

        for row in reader:
            if not row.get("latitude") or not row.get("longitude"):
                continue

            row_id = row.get("id", "")
            lat = parse_float(row["latitude"], row_id, "latitude")
            lon = parse_float(row["longitude"], row_id, "longitude")

            properties = {k: (row.get(k) or "").strip() for k in REQUIRED_COLUMNS if k not in {"latitude", "longitude"}}
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": properties,
            })

    geojson = {
        "type": "FeatureCollection",
        "metadata": {
            "title": "Mali Conflict Monitor",
            "last_updated": date.today().isoformat(),
            "warning": "Carte analytique basée sur sources ouvertes. Ne pas publier de positions tactiques en temps réel."
        },
        "features": features,
    }

    OUT_PATH.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK — {len(features)} événements écrits dans {OUT_PATH}")


if __name__ == "__main__":
    main()
