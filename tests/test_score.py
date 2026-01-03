"""Tests for scoring engine."""

from datetime import date

import pytest

from ski_notifier.fetch import PointWeather
from ski_notifier.score import (
    calculate_point_score,
    calculate_resort_score,
    clamp,
)


class TestClamp:
    def test_within_range(self):
        assert clamp(50, 0, 100) == 50

    def test_below_min(self):
        assert clamp(-10, 0, 100) == 0

    def test_above_max(self):
        assert clamp(150, 0, 100) == 100


class TestPointScore:
    def test_base_score_no_data(self):
        """With no data, base score is 50."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=None,
            wind_gust_kmh_max_9_16=None,
            precip_mm_sum_9_16=None,
            snow_depth_cm=None,
            snowfall_cm=None,
        )
        score = calculate_point_score(weather)
        assert score.score == 50.0
        assert score.has_snow_data is False

    def test_snow_bonus(self):
        """Snow depth and snowfall add bonus."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=None,
            wind_gust_kmh_max_9_16=None,
            precip_mm_sum_9_16=None,
            snow_depth_cm=60,  # +36 (60 * 0.6)
            snowfall_cm=30,   # +12 (30 * 0.4)
        )
        score = calculate_point_score(weather)
        # 50 + 36 + 12 = 98
        assert score.score == 98.0
        assert score.has_snow_data is True

    def test_snow_capped(self):
        """Snow bonuses are capped."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=None,
            wind_gust_kmh_max_9_16=None,
            precip_mm_sum_9_16=None,
            snow_depth_cm=200,  # capped at 60 -> +36
            snowfall_cm=100,    # capped at 30 -> +12
        )
        score = calculate_point_score(weather)
        assert score.score == 98.0

    def test_wind_penalty(self):
        """High wind gusts reduce score."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=None,
            wind_gust_kmh_max_9_16=55,  # 20 over threshold -> -16
            precip_mm_sum_9_16=None,
            snow_depth_cm=None,
            snowfall_cm=None,
        )
        score = calculate_point_score(weather)
        # 50 - 16 = 34
        assert score.score == 34.0

    def test_warm_temperature_penalty(self):
        """Warm temperatures reduce score."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=10,  # 6 over threshold -> -18
            wind_gust_kmh_max_9_16=None,
            precip_mm_sum_9_16=None,
            snow_depth_cm=None,
            snowfall_cm=None,
        )
        score = calculate_point_score(weather)
        # 50 - 18 = 32
        assert score.score == 32.0

    def test_cold_temperature_penalty(self):
        """Extreme cold slightly reduces score."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=-25,  # 7 below -18 -> -7
            wind_gust_kmh_max_9_16=None,
            precip_mm_sum_9_16=None,
            snow_depth_cm=None,
            snowfall_cm=None,
        )
        score = calculate_point_score(weather)
        # 50 - 7 = 43
        assert score.score == 43.0

    def test_precipitation_penalty(self):
        """Heavy precipitation reduces score."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=None,
            wind_gust_kmh_max_9_16=None,
            precip_mm_sum_9_16=18,  # 10 over threshold -> -10
            snow_depth_cm=None,
            snowfall_cm=None,
        )
        score = calculate_point_score(weather)
        # 50 - 10 = 40
        assert score.score == 40.0

    def test_ideal_conditions(self):
        """Test ideal skiing conditions."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=-5,     # Good, no penalty
            wind_gust_kmh_max_9_16=20,  # Below 35, no penalty
            precip_mm_sum_9_16=0,   # No precip
            snow_depth_cm=50,       # +30
            snowfall_cm=15,         # +6
        )
        score = calculate_point_score(weather)
        # 50 + 30 + 6 = 86
        assert score.score == 86.0
        assert score.has_snow_data is True


class TestResortScore:
    def test_weighted_combination(self):
        """Resort score is weighted 45% low + 55% high."""
        weather_low = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=None,
            wind_gust_kmh_max_9_16=None,
            precip_mm_sum_9_16=None,
            snow_depth_cm=None,
            snowfall_cm=None,
        )
        weather_high = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=None,
            wind_gust_kmh_max_9_16=None,
            precip_mm_sum_9_16=None,
            snow_depth_cm=60,     # +36
            snowfall_cm=30,       # +12
        )
        
        result = calculate_resort_score(weather_low, weather_high)
        
        # low = 50, high = 98
        # combined = 0.45 * 50 + 0.55 * 98 = 22.5 + 53.9 = 76.4
        assert result.score == 76.4
        assert result.confidence == 0.7  # Only high has snow data

    def test_confidence_both_snow_data(self):
        """Full confidence when both points have snow data."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=None,
            wind_gust_kmh_max_9_16=None,
            precip_mm_sum_9_16=None,
            snow_depth_cm=50,
            snowfall_cm=10,
        )
        result = calculate_resort_score(weather, weather)
        assert result.confidence == 1.0

    def test_confidence_no_snow_data(self):
        """Low confidence when neither point has snow data."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=-5,
            wind_gust_kmh_max_9_16=20,
            precip_mm_sum_9_16=0,
            snow_depth_cm=None,
            snowfall_cm=None,
        )
        result = calculate_resort_score(weather, weather)
        assert result.confidence == 0.4


class TestSnow24Scoring:
    """Tests for snow24_to_9_cm scoring wiring (P0 - must implement before merge)."""
    
    def test_scorer_uses_snow24_to_9(self):
        """Scorer should use snow24_to_9_cm for fresh snow bonus."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=0,           # No penalty
            wind_gust_kmh_max_9_16=0,    # No penalty
            precip_mm_sum_9_16=0,        # No penalty
            snow_depth_cm=0,             # No bonus
            snowfall_cm=10.0,            # DEPRECATED - should be ignored
            snow24_to_9_cm=20.0,         # This should be used
            snow24_quality="ok",
        )
        score = calculate_point_score(weather)
        # Base=50 + snow24 bonus: 20 * 0.4 = 8
        # If snowfall_cm was used instead: 10 * 0.4 = 4
        assert score.score == 58.0
        assert score.has_snow_data is True
    
    def test_snow24_clamp_at_30(self):
        """snow24_to_9_cm > 30 should be clamped."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=0,
            wind_gust_kmh_max_9_16=0,
            precip_mm_sum_9_16=0,
            snow_depth_cm=0,
            snowfall_cm=None,
            snow24_to_9_cm=40.0,         # Should clamp to 30
            snow24_quality="ok",
        )
        score = calculate_point_score(weather)
        # Base=50 + clamped bonus: 30 * 0.4 = 12 (not 40 * 0.4 = 16)
        assert score.score == 62.0
    
    def test_fallback_to_snowfall_cm(self):
        """When snow24_to_9_cm is None, fallback to snowfall_cm."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=0,
            wind_gust_kmh_max_9_16=0,
            precip_mm_sum_9_16=0,
            snow_depth_cm=0,
            snowfall_cm=15.0,            # Fallback value
            snow24_to_9_cm=None,         # Not available
            snow24_quality="missing",
        )
        score = calculate_point_score(weather)
        # Base=50 + fallback bonus: 15 * 0.4 = 6
        assert score.score == 56.0
        assert score.has_snow_data is True
