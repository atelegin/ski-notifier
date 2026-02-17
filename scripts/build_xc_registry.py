#!/usr/bin/env python3
"""Build extended XC registry around Konstanz.

Output file contains:
- core: XC resorts already curated in resorts.yaml
- extended: discovered OSM nordic candidates (deduped, rough drive estimate)
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
OUT_PATH = ROOT / "ski_notifier" / "xc_registry.yaml"

KONSTANZ = (47.6779, 9.1758)  # lat, lon
SEARCH_RADIUS_M = 180_000
MAX_APPROX_DRIVE_MIN = 120

UA = {"User-Agent": "ski-notifier-xc-registry/1.0"}
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
]

GOOD_NAME_TOKENS = (
    "loipe",
    "langlauf",
    "nordic",
    "zentrum",
    "center",
    "centre",
    "ski",
    "schanze",
    "arena",
)
BAD_NAME_TOKENS = (
    "zubringer",
    "weg",
    "strasse",
    "straße",
    "parking",
    "parkplatz",
    "trailhead",
)


def haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Distance between 2 lat/lon points in km."""
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
    """Conservative rough ETA from crow-flight distance."""
    # ~65 km/h average road speed with detour factor.
    minutes = distance_km / 65.0 * 60.0 * 1.4
    return int(round(minutes))


def country_from_tags(tags: Dict[str, str]) -> str:
    """Best-effort country extraction from OSM tags."""
    for key in ("addr:country", "country_code", "is_in:country_code"):
        val = tags.get(key)
        if val:
            return val.upper()[:2]
    return "UNK"


def normalize_name(name: str) -> str:
    """Normalize candidate names for dedupe buckets."""
    s = name.lower().strip()
    for token in ["langlauf", "loipe", "nordic", "zentrum", "center", "centre", "ski"]:
        s = s.replace(token, " ")
    return " ".join(s.split())


def is_high_signal_name(name: str) -> bool:
    """Filter out likely connector/micro-segment names."""
    s = name.strip().lower()
    if len(s) < 6:
        return False
    if any(token in s for token in BAD_NAME_TOKENS):
        return False
    return any(token in s for token in GOOD_NAME_TOKENS)


def load_core_xc() -> List[dict]:
    data = yaml.safe_load(RESORTS_PATH.read_text(encoding="utf-8"))
    core = []
    for r in data["resorts"]:
        if r.get("type") != "xc":
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


def fetch_osm_nordic_candidates() -> List[dict]:
    """Discover named nordic features around Konstanz via Overpass."""
    lat, lon = KONSTANZ
    query = f"""
[out:json][timeout:90];
(
  node["piste:type"="nordic"](around:{SEARCH_RADIUS_M},{lat},{lon});
  way["piste:type"="nordic"](around:{SEARCH_RADIUS_M},{lat},{lon});
  relation["piste:type"="nordic"](around:{SEARCH_RADIUS_M},{lat},{lon});
);
out center tags;
"""
    payload = None
    errors: List[str] = []
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            resp = requests.post(
                endpoint,
                data=query.encode("utf-8"),
                headers=UA,
                timeout=120,
            )
            resp.raise_for_status()
            payload = resp.json()
            break
        except Exception as exc:  # pragma: no cover - network-dependent
            errors.append(f"{endpoint}: {exc}")
            continue

    if payload is None:
        joined = " | ".join(errors)
        raise RuntimeError(f"All Overpass endpoints failed: {joined}")

    raw = []
    for el in payload.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue

        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue

        lat = float(lat)
        lon = float(lon)
        dist = haversine_km(KONSTANZ, (lat, lon))
        drive = approx_drive_minutes(dist)

        if not is_high_signal_name(name):
            continue

        raw.append(
            {
                "name": name,
                "country": country_from_tags(tags),
                "lat": lat,
                "lon": lon,
                "distance_km": round(dist, 1),
                "approx_drive_time_min": drive,
                "source": "osm_overpass:piste:type=nordic",
            }
        )

    # Dedupe by normalized name + near-identical coordinates.
    buckets: Dict[str, List[dict]] = defaultdict(list)
    for row in raw:
        buckets[normalize_name(row["name"])].append(row)

    deduped: List[dict] = []
    for rows in buckets.values():
        rows.sort(key=lambda r: (r["approx_drive_time_min"], r["distance_km"], r["name"]))
        picked: List[dict] = []
        for row in rows:
            too_close = False
            for existing in picked:
                if haversine_km((row["lat"], row["lon"]), (existing["lat"], existing["lon"])) < 2.0:
                    too_close = True
                    break
            if not too_close:
                picked.append(row)
        deduped.extend(picked)

    # Keep only reasonably reachable candidates.
    extended = [r for r in deduped if r["approx_drive_time_min"] <= MAX_APPROX_DRIVE_MIN]

    # Sort and cap list for signal/noise balance.
    extended.sort(key=lambda r: (r["approx_drive_time_min"], r["distance_km"], r["name"]))
    return extended[:140]


def main() -> None:
    core = load_core_xc()
    extended = fetch_osm_nordic_candidates()

    # Remove near-duplicates against core by proximity.
    core_points = [(c["low_point"]["lat"], c["low_point"]["lon"]) for c in core]
    filtered_extended = []
    for row in extended:
        pt = (row["lat"], row["lon"])
        if any(haversine_km(pt, cp) < 4.0 for cp in core_points):
            continue
        filtered_extended.append(row)

    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "core": "ski_notifier/resorts.yaml (type=xc)",
            "extended": "OpenStreetMap Overpass (piste:type=nordic)",
            "center": {"name": "Konstanz", "lat": KONSTANZ[0], "lon": KONSTANZ[1]},
            "max_approx_drive_time_min": MAX_APPROX_DRIVE_MIN,
            "note": "Extended list is semi-automatic and needs manual verification before promotion to core.",
        },
        "core": core,
        "extended": filtered_extended,
        "stats": {
            "core_count": len(core),
            "extended_count": len(filtered_extended),
            "total_count": len(core) + len(filtered_extended),
        },
    }

    OUT_PATH.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")
    print(payload["stats"])


if __name__ == "__main__":
    main()
