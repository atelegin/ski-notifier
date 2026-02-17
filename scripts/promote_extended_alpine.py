#!/usr/bin/env python3
"""Promote high-quality extended Alpine candidates to resorts.yaml."""

from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
RESORTS_PATH = ROOT / "ski_notifier" / "resorts.yaml"
REGISTRY_PATH = ROOT / "ski_notifier" / "alpine_registry.yaml"

TARGET_ADDITIONS = 20
MIN_DISTANCE_KM_FROM_EXISTING = 3.0
MIN_DISTANCE_KM_BETWEEN_NEW = 4.0

UA = {"User-Agent": "ski-notifier-promote-alpine/1.0"}
BERGFEX_ALPINE_SOURCES = [
    ("DE", "https://www.bergfex.de/deutschland/"),
    ("CH", "https://www.bergfex.ch/schweiz/"),
    ("AT", "https://www.bergfex.at/oesterreich/"),
]

BAD_SUBSTRINGS = (
    "talstation",
    "bergstation",
    "piste",
    "abfahrt",
    "route",
    "zubringer",
    "sektion",
    "lift",
    "bahn",
)



def haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    import math

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



def quality_name(name: str) -> bool:
    s = name.strip().lower()
    if len(s) < 6:
        return False
    if any(x in s for x in BAD_SUBSTRINGS):
        return False
    return True



def is_hard_blocked_name(name: str) -> bool:
    """Names that should never be promoted as standalone alpine resorts."""
    s = name.strip().lower()
    if "skiweg" in s:
        return True
    return False


def norm_name(name: str) -> str:
    s = name.lower()
    for token in ["skigebiet", "ski area", "ski resort", "winter sports", "mountain", "berg"]:
        s = s.replace(token, " ")
    s = re.sub(r"\d+", " ", s)
    return " ".join(s.split())


def norm_match(s: str) -> str:
    s = s.lower().strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    for t in ["skigebiet", "ski area", "ski resort", "winter sports", "ski", "bergbahn", "lift"]:
        s = s.replace(t, " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def fetch_bergfex_alpine_allowlist() -> List[dict]:
    """Fetch alpine place titles from Bergfex country pages."""
    rows = []
    seen = set()
    # Alpine entries are mostly linked via /<country>/skiurlaub/<slug>/.
    pattern = re.compile(
        r'href="(/[^"]*/skiurlaub/[^"/]+/)"[^>]*title="([^"]+)"',
        re.IGNORECASE,
    )
    for country, src in BERGFEX_ALPINE_SOURCES:
        try:
            r = requests.get(src, timeout=25, headers=UA)
            r.raise_for_status()
            html = r.text
        except Exception:
            continue

        for href, title in pattern.findall(html):
            key = (href.lower(), title.strip().lower(), country)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "title": title.strip(),
                    "name_norm": norm_match(title),
                    "url": f"https://www.bergfex.de{href}",
                    "country": country,
                }
            )
    return rows


def is_bergfex_alpine_match(candidate_name: str, allowlist: List[dict]) -> Tuple[bool, str | None]:
    """Match candidate against Bergfex alpine allowlist."""
    cn = norm_match(candidate_name)
    if not cn:
        return False, None
    c_tokens = set(cn.split())
    for row in allowlist:
        bn = row["name_norm"]
        if not bn:
            continue
        if cn == bn or cn in bn or bn in cn:
            return True, row["url"]
        b_tokens = set(bn.split())
        if c_tokens and b_tokens and len(c_tokens & b_tokens) >= 2:
            return True, row["url"]
    return False, None



def slugify(text: str) -> str:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s.lower()).strip("_")
    s = re.sub(r"_+", "_", s)
    return s[:48] if len(s) > 48 else s



def infer_country(lat: float, lon: float) -> str:
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 8, "addressdetails": 1},
            headers=UA,
            timeout=20,
        )
        if r.status_code == 200:
            cc = (r.json().get("address", {}).get("country_code") or "").upper()
            if cc in {"DE", "CH", "AT", "FL"}:
                return cc
    except Exception:
        pass
    if 47.04 <= lat <= 47.27 and 9.47 <= lon <= 9.65:
        return "FL"
    if 46.80 <= lat <= 47.60 and 9.45 <= lon <= 10.35:
        return "AT"
    if 46.70 <= lat <= 47.90 and 8.20 <= lon <= 10.30:
        return "CH"
    return "DE"



def access_for_country(country: str) -> Tuple[bool, bool, float]:
    if country == "AT":
        return False, True, 9.3
    if country == "CH":
        return True, False, 0.0
    if country == "FL":
        return False, False, 0.0
    return False, False, 0.0



def make_entry(c: dict, country: str, id_set: set[str], website_override: str | None = None) -> dict:
    base = f"{country.lower()}_{slugify(c['name'])}"
    rid = base
    n = 2
    while rid in id_set:
        rid = f"{base}_{n}"
        n += 1

    ch_req, at_req, at_vign = access_for_country(country)

    lat = float(c["lat"])
    lon = float(c["lon"])

    return {
        "id": rid,
        "name": f"{c['name']} ({country})",
        "country": country,
        "type": "alpine",
        "drive_time_min_from_konstanz": int(c["approx_drive_time_min"]),
        "drive_time_note": "Auto-promoted from OSM alpine registry (needs field validation)",
        "website": website_override
        or f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}#map=12/{lat:.6f}/{lon:.6f}",
        "notes": "Auto-promoted alpine candidate from OSM. Verify resort boundaries, parking, and pass pricing manually.",
        "access": {
            "requires_ch_vignette": ch_req,
            "requires_at_vignette": at_req,
        },
        "points": {
            "low": {
                "label": "Base area / parking (OSM)",
                "lat": lat,
                "lon": lon,
            },
            "high": {
                "label": "Upper area (approx)",
                "lat": round(lat + 0.02, 6),
                "lon": round(lon + 0.02, 6),
                "elev_m": None,
            },
        },
        "costs": {
            "assume_ferry_used": True,
            "ferry_roundtrip_eur": 24.2,
            "austria_vignette_1day_eur": at_vign,
            "requires_ch_vignette": ch_req,
        },
    }



def main() -> None:
    resorts_doc = yaml.safe_load(RESORTS_PATH.read_text(encoding="utf-8"))
    registry = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))

    resorts = resorts_doc["resorts"]
    existing_ids = {r["id"] for r in resorts}
    existing_points = [
        (float(r["points"]["low"]["lat"]), float(r["points"]["low"]["lon"]))
        for r in resorts
        if r.get("type") == "alpine"
    ]

    bergfex_allowlist = fetch_bergfex_alpine_allowlist()

    candidates = []
    for c in registry.get("extended", []):
        if int(c.get("approx_drive_time_min", 999)) > 120:
            continue
        if is_hard_blocked_name(c["name"]):
            continue
        is_bf, bf_url = is_bergfex_alpine_match(c["name"], bergfex_allowlist)
        if not is_bf and not quality_name(c["name"]):
            continue
        row = dict(c)
        row["_bergfex_match"] = is_bf
        row["_bergfex_url"] = bf_url
        candidates.append(row)

    by_key: Dict[str, dict] = {}
    for c in sorted(
        candidates,
        key=lambda x: (0 if x.get("_bergfex_match") else 1, x["approx_drive_time_min"], x["name"]),
    ):
        key = norm_name(c["name"])
        if key and key not in by_key:
            by_key[key] = c

    deduped = list(by_key.values())

    selected = []
    new_points: List[Tuple[float, float]] = []
    for c in sorted(
        deduped,
        key=lambda x: (0 if x.get("_bergfex_match") else 1, x["approx_drive_time_min"], x["distance_km"], x["name"]),
    ):
        pt = (float(c["lat"]), float(c["lon"]))
        if any(haversine_km(pt, p) < MIN_DISTANCE_KM_FROM_EXISTING for p in existing_points):
            continue
        if any(haversine_km(pt, p) < MIN_DISTANCE_KM_BETWEEN_NEW for p in new_points):
            continue
        selected.append(c)
        new_points.append(pt)
        if len(selected) >= TARGET_ADDITIONS:
            break

    added = []
    for c in selected:
        country = infer_country(float(c["lat"]), float(c["lon"]))
        entry = make_entry(c, country, existing_ids, website_override=c.get("_bergfex_url"))
        existing_ids.add(entry["id"])
        resorts.append(entry)
        added.append(entry["id"])
        time.sleep(0.15)

    RESORTS_PATH.write_text(yaml.safe_dump(resorts_doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"added={len(added)}")
    print("first_ids=", ",".join(added[:10]))


if __name__ == "__main__":
    main()
