"""Scoring engine for ski conditions."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from .fetch import PointWeather


@dataclass
class PointScore:
    """Score for a single point."""
    score: float  # 0-100
    has_snow_data: bool  # True if snow_depth or snowfall available


@dataclass
class ResortScore:
    """Combined score for a resort on a specific day."""
    date: date
    score: float  # 0-100, weighted combination of low/high
    confidence: float  # 0-1
    score_low: PointScore
    score_high: PointScore
    weather_low: PointWeather
    weather_high: PointWeather


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp value to [min_val, max_val]."""
    return max(min_val, min(max_val, value))


def calculate_point_score(weather: PointWeather) -> PointScore:
    """Calculate score for a single point based on weather.
    
    Scoring formula (0-100):
    - base = 50
    - + clamp(snow_depth_cm, 0..60) * 0.6
    - + clamp(snow24_to_9_cm, 0..30) * 0.4   (fresh snow: 24h ending at 09:00)
    - - max(0, wind_gust_kmh_max - 35) * 0.8
    - - max(0, precip_mm_sum - 8) * 1.0   (heavy rain/wet snow penalty)
    - - max(0, temp_C_avg - 4) * 3.0      (warm = worse snow)
    - - max(0, -temp_C_avg - 18) * 1.0    (extreme cold discomfort)
    
    Note: Wind threshold (35 km/h) is for GUSTS, not average wind.
    Note: snow24_to_9_cm used for scoring, fallback to snowfall_cm if unavailable.
    """
    score = 50.0
    has_snow_data = False
    
    # Snow depth bonus
    if weather.snow_depth_cm is not None:
        has_snow_data = True
        score += clamp(weather.snow_depth_cm, 0, 60) * 0.6
    
    # Fresh snow bonus: use snow24_to_9_cm (24h ending at 09:00)
    # Fallback to deprecated snowfall_cm for backward compatibility
    snowfall_for_scoring = weather.snow24_to_9_cm if weather.snow24_to_9_cm is not None else weather.snowfall_cm
    if snowfall_for_scoring is not None:
        has_snow_data = True
        score += clamp(snowfall_for_scoring, 0, 30) * 0.4
    
    # Wind gust penalty (threshold for GUSTS specifically)
    if weather.wind_gust_kmh_max_9_16 is not None:
        penalty = max(0, weather.wind_gust_kmh_max_9_16 - 35) * 0.8
        score -= penalty
    
    # Heavy precipitation penalty (wet/rain)
    if weather.precip_mm_sum_9_16 is not None:
        penalty = max(0, weather.precip_mm_sum_9_16 - 8) * 1.0
        score -= penalty
    
    # Temperature penalties
    if weather.temp_c_avg_9_16 is not None:
        # Too warm = worse snow conditions
        warm_penalty = max(0, weather.temp_c_avg_9_16 - 4) * 3.0
        # Extreme cold = discomfort
        cold_penalty = max(0, -weather.temp_c_avg_9_16 - 18) * 1.0
        score -= warm_penalty + cold_penalty
    
    # Clamp final score to 0-100
    score = clamp(score, 0, 100)
    
    return PointScore(score=round(score, 1), has_snow_data=has_snow_data)


def calculate_point_score_xc(weather: PointWeather) -> PointScore:
    """Calculate XC-specific score for a single point based on weather.

    Scoring formula (0-100):
    - base = 55
    - + 0.8 * clamp(snow_depth_cm, 0..30)
    - + 0.3 * clamp(snow_depth_cm - 30, 0..40)
    - + 0.35 * clamp(snow24_to_9_cm, 0..20)  (fallback to snowfall_cm)
    - - max(0, wind_gust_kmh_max_9_16 - 40) * 0.6
    - - max(0, precip_mm_sum_9_16 - 5) * 1.5
    - - [max(0, temp_C_avg - 2) * 2.0 + max(0, temp_C_avg - 6) * 4.0]
    - - max(0, -temp_C_avg - 20) * 0.5
    - - max(0, 12 - snow_depth_cm) * 1.2   (only if snow_depth is available)
    """
    score = 55.0
    has_snow_data = False

    snow_depth = weather.snow_depth_cm
    if snow_depth is not None:
        has_snow_data = True
        score += clamp(snow_depth, 0, 30) * 0.8
        score += clamp(snow_depth - 30, 0, 40) * 0.3
        score -= max(0, 12 - snow_depth) * 1.2

    snowfall_for_scoring = weather.snow24_to_9_cm if weather.snow24_to_9_cm is not None else weather.snowfall_cm
    if snowfall_for_scoring is not None:
        has_snow_data = True
        score += clamp(snowfall_for_scoring, 0, 20) * 0.35

    if weather.wind_gust_kmh_max_9_16 is not None:
        score -= max(0, weather.wind_gust_kmh_max_9_16 - 40) * 0.6

    if weather.precip_mm_sum_9_16 is not None:
        score -= max(0, weather.precip_mm_sum_9_16 - 5) * 1.5

    if weather.temp_c_avg_9_16 is not None:
        warm_penalty = max(0, weather.temp_c_avg_9_16 - 2) * 2.0
        warm_penalty += max(0, weather.temp_c_avg_9_16 - 6) * 4.0
        cold_penalty = max(0, -weather.temp_c_avg_9_16 - 20) * 0.5
        score -= warm_penalty + cold_penalty

    score = clamp(score, 0, 100)
    return PointScore(score=round(score, 1), has_snow_data=has_snow_data)


def calculate_resort_score(
    weather_low: PointWeather,
    weather_high: PointWeather,
    discipline: Literal["alpine", "xc"] = "alpine",
) -> ResortScore:
    """Calculate combined resort score for a day.
    
    Resort score:
    - alpine: 0.45 * score_low + 0.55 * score_high
    - xc: 0.60 * score_low + 0.40 * score_high
    
    Confidence:
    - 1.0 if snow data available for both points
    - 0.7 if snow data missing for one point
    - 0.4 if snow data missing for both points
    """
    if discipline == "xc":
        score_low = calculate_point_score_xc(weather_low)
        score_high = calculate_point_score_xc(weather_high)
        combined_score = 0.6 * score_low.score + 0.4 * score_high.score
    else:
        score_low = calculate_point_score(weather_low)
        score_high = calculate_point_score(weather_high)
        # Weighted combination (higher weight for summit)
        combined_score = 0.45 * score_low.score + 0.55 * score_high.score
    
    # Confidence based on snow data availability
    if score_low.has_snow_data and score_high.has_snow_data:
        confidence = 1.0
    elif score_low.has_snow_data or score_high.has_snow_data:
        confidence = 0.7
    else:
        confidence = 0.4
    
    return ResortScore(
        date=weather_low.date,
        score=round(combined_score, 1),
        confidence=confidence,
        score_low=score_low,
        score_high=score_high,
        weather_low=weather_low,
        weather_high=weather_high,
    )
