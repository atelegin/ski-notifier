"""Resort data loader from YAML (schema_version: 1)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, List

import yaml


@dataclass
class Point:
    """Geographic point with coordinates."""
    lat: float
    lon: float
    elevation_m: Optional[int] = None
    label: Optional[str] = None


@dataclass
class Resort:
    """Ski resort with metadata and coordinates."""
    id: str
    name: str
    country: str
    type: Literal["alpine", "xc"]
    drive_time_min: int
    point_low: Point
    point_high: Point
    # Cost info
    requires_ferry: bool
    requires_at_vignette: bool
    requires_ch_vignette: bool
    ferry_roundtrip_eur: float
    at_vignette_eur: float
    ski_pass_day_adult_eur: Optional[float] = None
    ski_pass_currency: str = "EUR"


@dataclass
class Costs:
    """Default cost constants."""
    ferry_konstanz_meersburg_rt_eur: float
    at_vignette_1day_eur: float


def _parse_point(data: dict) -> Point:
    """Parse a point from YAML data."""
    return Point(
        lat=data["lat"],
        lon=data["lon"],
        elevation_m=data.get("elev_m"),
        label=data.get("label") or data.get("name"),
    )


def load_resorts(yaml_path: Optional[Path] = None) -> tuple[List[Resort], Costs]:
    """Load resorts and costs from YAML file (schema_version: 1).
    
    Args:
        yaml_path: Path to YAML file. Defaults to resorts.yaml in same directory.
        
    Returns:
        Tuple of (list of Resort, Costs).
    """
    if yaml_path is None:
        yaml_path = Path(__file__).parent / "resorts.yaml"
    
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    # Get defaults
    defaults = data.get("defaults", {})
    default_costs = defaults.get("costs", {})
    
    # Build default Costs object
    costs = Costs(
        ferry_konstanz_meersburg_rt_eur=default_costs.get("ferry_roundtrip_eur", 24.2),
        at_vignette_1day_eur=default_costs.get("austria_vignette_1day_eur", 9.6),
    )
    
    resorts = []
    for r in data.get("resorts", []):
        # Get resort-level costs (fallback to defaults)
        r_costs = r.get("costs", {})
        r_access = r.get("access", {})
        
        # Determine access requirements from costs or access block
        requires_ferry = r_costs.get("assume_ferry_used", default_costs.get("assume_ferry_used", True))
        requires_at_vignette = r_access.get("requires_at_vignette", False) or r_costs.get("austria_vignette_1day_eur", 0) > 0
        requires_ch_vignette = r_access.get("requires_ch_vignette", False) or r_costs.get("requires_ch_vignette", False)
        
        # Get ski pass price
        ski_pass = r_costs.get("ski_pass_day_adult_eur")
        ski_pass_currency = r_costs.get("ski_pass_currency", "EUR")
        
        # Parse points
        points = r.get("points", {})
        point_low = _parse_point(points.get("low", {}))
        point_high = _parse_point(points.get("high", {}))
        
        resort = Resort(
            id=r.get("id", r["name"]),
            name=r["name"],
            country=r["country"],
            type=r["type"],
            drive_time_min=r.get("drive_time_min_from_konstanz", r.get("drive_time_min", 60)),
            point_low=point_low,
            point_high=point_high,
            requires_ferry=requires_ferry,
            requires_at_vignette=requires_at_vignette,
            requires_ch_vignette=requires_ch_vignette,
            ferry_roundtrip_eur=r_costs.get("ferry_roundtrip_eur", costs.ferry_konstanz_meersburg_rt_eur),
            at_vignette_eur=r_costs.get("austria_vignette_1day_eur", 0),
            ski_pass_day_adult_eur=ski_pass if ski_pass is not None else None,
            ski_pass_currency=ski_pass_currency,
        )
        resorts.append(resort)
    
    return resorts, costs
