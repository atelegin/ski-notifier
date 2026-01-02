"""Tests for features module."""

from datetime import date

import pytest

from ski_notifier.features import (
    ResortFeatures,
    WeeklyBest,
    compute_resort_features,
    compute_weekly_best,
    format_reason_line,
)
from ski_notifier.fetch import PointWeather


class TestComputeResortFeatures:
    def test_snow24_index(self):
        """snow24 should be daily_snowfall[1] (tomorrow)."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=-5,
            wind_gust_kmh_max_9_16=20,
            precip_mm_sum_9_16=0,
            snow_depth_cm=50,
            snowfall_cm=10,
        )
        # day0=2, day1=5, day2=3
        daily_snowfall = [2.0, 5.0, 3.0]
        
        features = compute_resort_features(weather, weather, daily_snowfall)
        
        assert features.snow24_cm == 5.0
    
    def test_snow48_sum(self):
        """snow48 should be daily_snowfall[1] + daily_snowfall[2]."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=-5,
            wind_gust_kmh_max_9_16=20,
            precip_mm_sum_9_16=0,
            snow_depth_cm=50,
            snowfall_cm=10,
        )
        # day0=2, day1=5, day2=3 -> snow48 = 5+3 = 8
        daily_snowfall = [2.0, 5.0, 3.0]
        
        features = compute_resort_features(weather, weather, daily_snowfall)
        
        assert features.snow48_cm == 8.0
    
    def test_slush_risk_triggered(self):
        """slush_risk when temp in [-0.5, +2] AND rain > 0.5."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=1.0,  # in range
            wind_gust_kmh_max_9_16=10,
            precip_mm_sum_9_16=1.0,  # > 0.5
            snow_depth_cm=30,
            snowfall_cm=0,
        )
        
        features = compute_resort_features(weather, weather, [])
        
        assert features.slush_risk is True
    
    def test_slush_risk_cold(self):
        """No slush_risk when temp < -0.5."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=-5.0,  # too cold
            wind_gust_kmh_max_9_16=10,
            precip_mm_sum_9_16=1.0,
            snow_depth_cm=30,
            snowfall_cm=0,
        )
        
        features = compute_resort_features(weather, weather, [])
        
        assert features.slush_risk is False
    
    def test_slush_risk_dry(self):
        """No slush_risk when rain <= 0.5."""
        weather = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=1.0,
            wind_gust_kmh_max_9_16=10,
            precip_mm_sum_9_16=0.3,  # too dry
            snow_depth_cm=30,
            snowfall_cm=0,
        )
        
        features = compute_resort_features(weather, weather, [])
        
        assert features.slush_risk is False
    
    def test_aggregation_rules(self):
        """temp_min/max from min/max of points, wind/rain from max."""
        weather_low = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=-2.0,
            wind_gust_kmh_max_9_16=15,
            precip_mm_sum_9_16=0.5,
            snow_depth_cm=20,
            snowfall_cm=0,
        )
        weather_high = PointWeather(
            date=date(2025, 1, 15),
            temp_c_avg_9_16=-5.0,
            wind_gust_kmh_max_9_16=25,
            precip_mm_sum_9_16=1.0,
            snow_depth_cm=40,
            snowfall_cm=5,
        )
        
        features = compute_resort_features(weather_low, weather_high, [])
        
        assert features.temp_min == -5.0
        assert features.temp_max == -2.0
        assert features.wind_max == 25
        assert features.rain_mm == 1.0


class TestComputeWeeklyBest:
    def test_tomorrow_best_margin_ok(self):
        """tomorrow_is_best when margin >= 10 and confidence >= 0.7."""
        tomorrow = date(2025, 1, 15)
        scores = {
            date(2025, 1, 15): 78,  # tomorrow
            date(2025, 1, 16): 64,  # second
            date(2025, 1, 17): 55,
        }
        
        result = compute_weekly_best(scores, tomorrow, 0.8)
        
        assert result.tomorrow_is_best is True
        assert result.tomorrow_score == 78
        assert result.second_best_score == 64
    
    def test_tomorrow_best_margin_low(self):
        """Not best when margin < 10."""
        tomorrow = date(2025, 1, 15)
        scores = {
            date(2025, 1, 15): 70,
            date(2025, 1, 16): 65,  # margin = 5 < 10
        }
        
        result = compute_weekly_best(scores, tomorrow, 0.8)
        
        assert result.tomorrow_is_best is False
    
    def test_tomorrow_not_highest(self):
        """Not best when tomorrow not highest score."""
        tomorrow = date(2025, 1, 15)
        scores = {
            date(2025, 1, 15): 60,
            date(2025, 1, 16): 78,  # higher
        }
        
        result = compute_weekly_best(scores, tomorrow, 0.8)
        
        assert result.tomorrow_is_best is False
        assert result.best_day == date(2025, 1, 16)


class TestFormatReasonLine:
    def test_reason_line_prefix(self):
        """Reason line uses 'Условия завтра:' prefix, not 'Причина:'."""
        features = ResortFeatures(
            snow24_cm=10,
            snow48_cm=15,
            overnight_cm=None,
            rain_mm=0,
            temp_min=-5,
            temp_max=-2,
            wind_max=10,
            slush_risk=False,
            rain_risk=False,
        )
        
        result = format_reason_line(features)
        
        assert result.startswith("Условия завтра: ")
        assert "Причина:" not in result
    
    def test_with_snow_and_temp(self):
        """Reason line includes snow and temp."""
        features = ResortFeatures(
            snow24_cm=18,
            snow48_cm=25,
            overnight_cm=None,
            rain_mm=0,
            temp_min=-4,
            temp_max=-1,
            wind_max=6,
            slush_risk=False,
            rain_risk=False,
        )
        
        result = format_reason_line(features)
        
        assert "+18cm/24h" in result
        assert "T" in result
        assert "−4" in result or "-4" in result
    
    def test_slush_label(self):
        """Reason line includes slush label when risk."""
        features = ResortFeatures(
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
        
        result = format_reason_line(features)
        
        assert "(каша)" in result
