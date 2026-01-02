"""Tests for message format."""

from datetime import date
from typing import Dict

import pytest

from ski_notifier.features import ResortFeatures, WeeklyBest
from ski_notifier.fetch import PointWeather
from ski_notifier.message import RankedResort, format_message, format_cost_line
from ski_notifier.resorts import Costs, Point, Resort
from ski_notifier.score import ResortScore, PointScore


def make_resort(id: str, type: str = "alpine") -> Resort:
    """Create a minimal resort for testing."""
    point = Point(lat=47.0, lon=9.0, elevation_m=1500)
    return Resort(
        id=id,
        name=f"Resort {id}",
        country="AT",
        type=type,
        drive_time_min=60,
        point_low=point,
        point_high=point,
        requires_ferry=True,
        requires_at_vignette=True,
        requires_ch_vignette=False,
        ferry_roundtrip_eur=24.0,
        at_vignette_eur=10.0,
        ski_pass_day_adult_eur=62,
        ski_pass_currency="EUR",
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


def make_features() -> ResortFeatures:
    """Create features for testing."""
    return ResortFeatures(
        snow24_cm=10,
        snow48_cm=15,
        overnight_cm=None,
        rain_mm=0,
        temp_min=-5,
        temp_max=-2,
        wind_max=15,
        slush_risk=False,
        rain_risk=False,
    )


def make_weekly_best(is_best: bool = True) -> WeeklyBest:
    """Create WeeklyBest for testing."""
    return WeeklyBest(
        tomorrow_is_best=is_best,
        tomorrow_score=78,
        best_day=date(2025, 1, 15),
        best_day_score=78,
        second_best_score=64,
        message="✅ Завтра — лучший день (78 vs 2nd 64)" if is_best else "ℹ️ Лучший день: чт (82). Завтра: 68",
    )


class TestFormatMessage:
    def test_no_card_blocks(self):
        """Message has no --- separators and proper structure."""
        r1 = make_ranked(make_resort("a", "alpine"), 80)
        r2 = make_ranked(make_resort("b", "xc"), 75)
        
        features: Dict[str, ResortFeatures] = {
            "a": make_features(),
            "b": make_features(),
        }
        costs = Costs(ferry_konstanz_meersburg_rt_eur=24, at_vignette_1day_eur=10)
        
        message = format_message(
            date(2025, 1, 15),
            [r1, r2],
            make_weekly_best(),
            features,
            costs,
        )
        
        # No --- separators
        assert "---" not in message
        
        # Check structure: header, blank, resorts
        lines = message.split("\n")
        assert lines[0].startswith("🟦")
    
    def test_discipline_icons(self):
        """Message contains discipline icons."""
        r1 = make_ranked(make_resort("a", "alpine"), 80)
        r2 = make_ranked(make_resort("b", "xc"), 75)
        
        features: Dict[str, ResortFeatures] = {
            "a": make_features(),
            "b": make_features(),
        }
        costs = Costs(ferry_konstanz_meersburg_rt_eur=24, at_vignette_1day_eur=10)
        
        message = format_message(
            date(2025, 1, 15),
            [r1, r2],
            make_weekly_best(),
            features,
            costs,
        )
        
        assert "🎿" in message  # alpine
        assert "⛷️" in message  # xc
    
    def test_header_format(self):
        """Header starts with correct format."""
        r1 = make_ranked(make_resort("a"), 80)
        
        features: Dict[str, ResortFeatures] = {"a": make_features()}
        costs = Costs(ferry_konstanz_meersburg_rt_eur=24, at_vignette_1day_eur=10)
        
        message = format_message(
            date(2025, 1, 15),
            [r1],
            make_weekly_best(),
            features,
            costs,
        )
        
        assert message.startswith("🟦 Ski forecast")
    
    def test_xc_no_skipass(self):
        """XC resorts don't show skipass in costs."""
        xc_resort = make_resort("xc1", "xc")
        xc_resort.ski_pass_day_adult_eur = 50  # Should be ignored
        
        cost_line = format_cost_line(xc_resort)
        
        assert "Skipass" not in cost_line
    
    def test_slush_label(self):
        """Slush label appears when slush_risk is True."""
        r1 = make_ranked(make_resort("a"), 80)
        
        slush_features = ResortFeatures(
            snow24_cm=0,
            snow48_cm=0,
            overnight_cm=None,
            rain_mm=1.0,
            temp_min=0,
            temp_max=1,
            wind_max=5,
            slush_risk=True,
            rain_risk=False,
        )
        features: Dict[str, ResortFeatures] = {"a": slush_features}
        costs = Costs(ferry_konstanz_meersburg_rt_eur=24, at_vignette_1day_eur=10)
        
        message = format_message(
            date(2025, 1, 15),
            [r1],
            make_weekly_best(),
            features,
            costs,
        )
        
        assert "(каша)" in message
