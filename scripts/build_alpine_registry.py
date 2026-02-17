#!/usr/bin/env python3
"""Build extended Alpine registry around Konstanz.

Output file contains:
- core: Alpine resorts curated in resorts.yaml
- extended: discovered OSM downhill/winter_sports candidates (deduped, rough ETA)
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
RESORTS_PATH = ROOT / "ski_notifier" / "resorts.yaml"
OUT_PATH = ROOT / "ski_notifier" / "alpine_registry.yaml"

KONSTANZ = (47.6779, 9.1758)  # lat, lon
SEARCH_RADIUS_M = 220_000
MAX_APPROX_DRIVE_MIN = 150

UA = {"User-Agent": "ski-notifier-alpine-registry/1.0"}
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
]

GOOD_NAME_TOKENS = (
    "ski",
    "skigebiet",
    "skilift",
    "bergbahn",
    "alp",
    "mountain",
    "berg",
    "resort",
)
BAD_NAME_TOKENS = (
    "piste",
    "abfahrt",
    "route",
    "talstation",
    "bergstation",
    "zubringer",
    "liftstütze",
    "stütze",
)


def haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    x = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def approx_drive_minutes(distance_km: float) -> int:
    minutes = distance_km / 65.0 * 60.0 * 1.45
    return int(round(minutes))


def normalize_name(name: str) -> str:
    s = name.lower().strip()
    for token in [
        "skigebiet",
        "ski area",
        "ski resort",
        "ski",
        "bergbahn",
        "lift",
    ]:
        s = s.replace(token, " ")
    return " ".join(s.split())


def is_high_signal_name(name: str) -> bool:
    s = name.strip().lower()
    if len(s) < 6:
        return False
    if any(t in s for t in BAD_NAME_TOKENS):
        return False
    return any(t in s for t in GOOD_NAME_TOKENS)


def load_core_alpine() -> List[dict]:
    data = yaml.safe_load(RESORTS_PATH.read_text(encoding="utf-8"))
    core = []
    for r in data["resorts"]:
        if r.get("type") != "alpine":
            continue
        low = r["points"]["low"]
        core.append(
            {
                "id": r["id"],
                "name": r["name"],
                "country": r["country"],
                "drive_time_min_from_konstanz": int(r["drive_time_min_from_konstanz"]),
                "website": r.get("website"),
                "low_point": {
                    "label": low.get("label") or low.get("name"),
                    "lat": float(low["lat"]),
                    "lon": float(low["lon"]),
                },
            }
        )
    core.sort(key=lambda x: x["drive_time_min_from_konstanz"])
    return core


def fetch_osm_alpine_candidates() -> List[dict]:
    lat, lon = KONSTANZ
    query = f"""
[out:json][timeout:120];
(
  node["piste:type"="downhill"](around:{SEARCH_RADIUS_M},{lat},{lon});
  way["piste:type"="downhill"](around:{SEARCH_RADIUS_M},{lat},{lon});
  relation["piste:type"="downhill"](around:{SEARCH_RADIUS_M},{lat},{lon});
  node["landuse"="winter_sports"](around:{SEARCH_RADIUS_M},{lat},{lon});
  way["landuse"="winter_sports"](around:{SEARCH_RADIUS_M},{lat},{lon});
  relation["landuse"="winter_sports"](around:{SEARCH_RADIUS_M},{lat},{lon});
);
out center tags;
"""

    payload = None
    errs: List[str] = []
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            resp = requests.post(endpoint, data=query.encode("utf-8"), headers=UA, timeout=130)
            resp.raise_for_status()
            payload = resp.json()
            break
        except Exception as exc:
            errs.append(f"{endpoint}: {exc}")

    if payload is None:
        raise RuntimeError("All Overpass endpoints failed: " + " | ".join(errs))

    raw = []
    for el in payload.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name or not is_high_signal_name(name):
            continue

        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue

        lat = float(lat)
        lon = float(lon)
        dist = haversine_km(KONSTANZ, (lat, lon))
        drive = approx_drive_minutes(dist)
        if drive > MAX_APPROX_DRIVE_MIN:
            continue

        raw.append(
            {
                "name": name,
                "country": "UNK",
                "lat": lat,
                "lon": lon,
                "distance_km": round(dist, 1),
                "approx_drive_time_min": drive,
                "source": "osm_overpass:downhill+winter_sports",
            }
        )

    buckets: Dict[str, List[dict]] = defaultdict(list)
    for row in raw:
        buckets[normalize_name(row["name"])].append(row)

    deduped: List[dict] = []
    for rows in buckets.values():
        rows.sort(key=lambda r: (r["approx_drive_time_min"], r["distance_km"], r["name"]))
        keep: List[dict] = []
        for row in rows:
            if any(haversine_km((row["lat"], row["lon"]), (k["lat"], k["lon"])) < 3.0 for k in keep):
                continue
            keep.append(row)
        deduped.extend(keep)

    deduped.sort(key=lambda r: (r["approx_drive_time_min"], r["distance_km"], r["name"]))
    return deduped[:220]


def main() -> None:
    core = load_core_alpine()
    extended = fetch_osm_alpine_candidates()

    core_points = [(c["low_point"]["lat"], c["low_point"]["lon"]) for c in core]
    filtered = []
    for row in extended:
        pt = (row["lat"], row["lon"])
        if any(haversine_km(pt, cp) < 5.0 for cp in core_points):
            continue
        filtered.append(row)

    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "core": "ski_notifier/resorts.yaml (type=alpine)",
            "extended": "OpenStreetMap Overpass (piste:type=downhill + landuse=winter_sports)",
            "center": {"name": "Konstanz", "lat": KONSTANZ[0], "lon": KONSTANZ[1]},
            "max_approx_drive_time_min": MAX_APPROX_DRIVE_MIN,
            "note": "Extended list is semi-automatic and needs manual verification before promotion to core.",
        },
        "core": core,
        "extended": filtered,
        "stats": {
            "core_count": len(core),
            "extended_count": len(filtered),
            "total_count": len(core) + len(filtered),
        },
    }

    OUT_PATH.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")
    print(payload["stats"])


if __name__ == "__main__":
    main()
