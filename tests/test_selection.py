"""Tests for selection logic."""

from datetime import date

import pytest

from ski_notifier.fetch import PointWeather
from ski_notifier.main import select_top_with_coverage
from ski_notifier.message import RankedResort
from ski_notifier.resorts import Point, Resort
from ski_notifier.score import ResortScore, PointScore


def make_resort(id: str, type: str = "alpine") -> Resort:
    """Create a minimal resort for testing."""
    point = Point(lat=47.0, lon=9.0)
    return Resort(
        id=id,
        name=f"Resort {id}",
        country="AT",
        type=type,
        drive_time_min=60,
        point_low=point,
        point_high=point,
        requires_ferry=False,
        requires_at_vignette=False,
        requires_ch_vignette=False,
        ferry_roundtrip_eur=0,
        at_vignette_eur=0,
    )


def make_ranked(resort: Resort, score: float) -> RankedResort:
    """Create a RankedResort for testing."""
    weather = PointWeather(
        date=date(2025, 1, 15),
        temp_c_avg_9_16=-5,
        wind_gust_kmh_max_9_16=20,
        precip_mm_sum_9_16=0,
        snow_depth_cm=50,
        snowfall_cm=10,
    )
    point_score = PointScore(score=score, has_snow_data=True)
    resort_score = ResortScore(
        date=date(2025, 1, 15),
        score=score,
        confidence=1.0,
        score_low=point_score,
        score_high=point_score,
        weather_low=weather,
        weather_high=weather,
    )
    return RankedResort(resort=resort, score=resort_score)


class TestSelectTopWithCoverage:
    def test_empty_input(self):
        """Empty list returns empty."""
        result = select_top_with_coverage([])
        assert result == []
    
    def test_fewer_than_3(self):
        """Less than 3 resorts returns all."""
        r1 = make_ranked(make_resort("a"), 80)
        r2 = make_ranked(make_resort("b"), 70)
        
        result = select_top_with_coverage([r1, r2])
        
        assert len(result) == 2
    
    def test_top3_mixed_stays_3(self):
        """TOP-3 with both types stays at 3."""
        r1 = make_ranked(make_resort("a", "alpine"), 80)
        r2 = make_ranked(make_resort("b", "xc"), 75)
        r3 = make_ranked(make_resort("c", "alpine"), 70)
        r4 = make_ranked(make_resort("d", "xc"), 65)
        
        result = select_top_with_coverage([r1, r2, r3, r4])
        
        assert len(result) == 3
    
    def test_top3_all_alpine_adds_xc(self):
        """TOP-3 all alpine adds best XC as #4."""
        r1 = make_ranked(make_resort("a", "alpine"), 80)
        r2 = make_ranked(make_resort("b", "alpine"), 75)
        r3 = make_ranked(make_resort("c", "alpine"), 70)
        r4 = make_ranked(make_resort("d", "xc"), 65)
        r5 = make_ranked(make_resort("e", "xc"), 60)
        
        result = select_top_with_coverage([r1, r2, r3, r4, r5])
        
        assert len(result) == 4
        assert result[3].resort.type == "xc"
        assert result[3].resort.id == "d"  # best XC
    
    def test_top3_all_xc_adds_alpine(self):
        """TOP-3 all XC adds best alpine as #4."""
        r1 = make_ranked(make_resort("a", "xc"), 80)
        r2 = make_ranked(make_resort("b", "xc"), 75)
        r3 = make_ranked(make_resort("c", "xc"), 70)
        r4 = make_ranked(make_resort("d", "alpine"), 65)
        
        result = select_top_with_coverage([r1, r2, r3, r4])
        
        assert len(result) == 4
        assert result[3].resort.type == "alpine"
