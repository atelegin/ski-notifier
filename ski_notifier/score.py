"""Scoring engine for ski conditions."""

from dataclasses import dataclass
from datetime import date

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


def calculate_resort_score(
    weather_low: PointWeather,
    weather_high: PointWeather,
) -> ResortScore:
    """Calculate combined resort score for a day.
    
    Resort score = 0.45 * score_low + 0.55 * score_high
    
    Confidence:
    - 1.0 if snow data available for both points
    - 0.7 if snow data missing for one point
    - 0.4 if snow data missing for both points
    """
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
