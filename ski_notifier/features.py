"""Display features for ski resorts (non-scoring)."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from .fetch import PointWeather

TZ = ZoneInfo("Europe/Berlin")


@dataclass
class ResortFeatures:
    """Display-only features for a resort."""
    snow24_cm: Optional[float]      # = daily_snowfall[1] (tomorrow)
    snow48_cm: Optional[float]      # = daily_snowfall[1] + daily_snowfall[2]
    overnight_cm: Optional[float]   # max(now,17:00) → 09:00 (v2, None for now)
    rain_mm: float                  # max(low, high) precip 9-16
    temp_min: Optional[float]       # min of low/high temp
    temp_max: Optional[float]       # max of low/high temp
    wind_max: Optional[float]       # max of low/high gust
    slush_risk: bool                # temp∈[−0.5,+2] AND rain>0.5
    rain_risk: bool                 # rain>1.0 AND temp_max>1


def compute_resort_features(
    weather_low: PointWeather,
    weather_high: PointWeather,
    daily_snowfall: List[Optional[float]],  # [day0=today, day1=tomorrow, day2, ...]
) -> ResortFeatures:
    """Compute display features from weather data.
    
    Args:
        weather_low: Weather for base station (tomorrow, 09-16 window).
        weather_high: Weather for summit (tomorrow, 09-16 window).
        daily_snowfall: List of daily snowfall values [day0, day1, day2, ...].
        
    Returns:
        ResortFeatures with computed display values.
    """
    # snow24 = tomorrow's snowfall
    snow24_cm: Optional[float] = None
    if len(daily_snowfall) > 1 and daily_snowfall[1] is not None:
        snow24_cm = daily_snowfall[1]
    
    # snow48 = tomorrow + day after
    snow48_cm: Optional[float] = None
    if len(daily_snowfall) > 2:
        day1 = daily_snowfall[1] if daily_snowfall[1] is not None else 0
        day2 = daily_snowfall[2] if daily_snowfall[2] is not None else 0
        if daily_snowfall[1] is not None or daily_snowfall[2] is not None:
            snow48_cm = day1 + day2
    
    # Aggregation: max(low, high) for rain
    rain_low = weather_low.precip_mm_sum_9_16 or 0
    rain_high = weather_high.precip_mm_sum_9_16 or 0
    rain_mm = max(rain_low, rain_high)
    
    # Aggregation: min/max for temp
    temps = [t for t in [weather_low.temp_c_avg_9_16, weather_high.temp_c_avg_9_16] if t is not None]
    temp_min = min(temps) if temps else None
    temp_max = max(temps) if temps else None
    
    # Aggregation: max for wind
    winds = [w for w in [weather_low.wind_gust_kmh_max_9_16, weather_high.wind_gust_kmh_max_9_16] if w is not None]
    wind_max = max(winds) if winds else None
    
    # Slush risk: temp in [-0.5, +2] AND rain > 0.5
    slush_risk = False
    if temp_max is not None and -0.5 <= temp_max <= 2.0 and rain_mm > 0.5:
        slush_risk = True
    
    # Rain risk: rain > 1.0 AND temp_max > 1
    rain_risk = False
    if temp_max is not None and rain_mm > 1.0 and temp_max > 1.0:
        rain_risk = True
    
    return ResortFeatures(
        snow24_cm=snow24_cm,
        snow48_cm=snow48_cm,
        overnight_cm=None,  # v2 feature
        rain_mm=rain_mm,
        temp_min=temp_min,
        temp_max=temp_max,
        wind_max=wind_max,
        slush_risk=slush_risk,
        rain_risk=rain_risk,
    )


@dataclass
class WeeklyBest:
    """Best day of week analysis."""
    tomorrow_is_best: bool
    tomorrow_score: float
    best_day: date
    best_day_score: float
    second_best_score: float
    message: str  # formatted header line


def compute_weekly_best(
    scores_by_day: Dict[date, float],
    tomorrow: date,
    tomorrow_confidence: float,
) -> WeeklyBest:
    """Compute weekly best day analysis.
    
    Args:
        scores_by_day: Dict of date -> best resort score for each day.
        tomorrow: Tomorrow's date.
        tomorrow_confidence: Confidence of top-1 resort for tomorrow.
        
    Returns:
        WeeklyBest with analysis and formatted message.
    """
    if not scores_by_day:
        return WeeklyBest(
            tomorrow_is_best=False,
            tomorrow_score=0,
            best_day=tomorrow,
            best_day_score=0,
            second_best_score=0,
            message="ℹ️ Нет данных о прогнозе",
        )
    
    tomorrow_score = scores_by_day.get(tomorrow, 0)
    
    # Find best day and second best
    sorted_days = sorted(scores_by_day.items(), key=lambda x: x[1], reverse=True)
    best_day, best_day_score = sorted_days[0]
    second_best_score = sorted_days[1][1] if len(sorted_days) > 1 else 0
    
    # Check if tomorrow is best
    # Conditions: tomorrow has highest score, margin >= 10, confidence >= 0.7
    tomorrow_is_best = (
        tomorrow_score >= best_day_score and
        tomorrow_score - second_best_score >= 10 and
        tomorrow_confidence >= 0.7
    )
    
    if tomorrow_is_best:
        message = f"✅ Завтра — лучший день ({tomorrow_score:.0f} vs 2nd {second_best_score:.0f})"
    else:
        weekday_names = {
            0: "пн", 1: "вт", 2: "ср", 3: "чт", 4: "пт", 5: "сб", 6: "вс"
        }
        best_weekday = weekday_names.get(best_day.weekday(), "")
        message = f"ℹ️ Лучший день: {best_weekday} ({best_day_score:.0f}). Завтра: {tomorrow_score:.0f}"
    
    return WeeklyBest(
        tomorrow_is_best=tomorrow_is_best,
        tomorrow_score=tomorrow_score,
        best_day=best_day,
        best_day_score=best_day_score,
        second_best_score=second_best_score,
        message=message,
    )


def format_reason_line(features: ResortFeatures) -> str:
    """Generate 'Условия завтра:' line from top signals.
    
    Priority order (max 3 signals):
    1. snow24 if > 0
    2. temp range (always)
    3. slush/rain risk if flagged
    4. wind if > 30
    """
    signals = []
    
    # 1. Snow24
    if features.snow24_cm is not None and features.snow24_cm > 0:
        signals.append(f"+{features.snow24_cm:.0f}cm/24h")
    
    # 2. Temp range (always show if available)
    if features.temp_min is not None and features.temp_max is not None:
        signals.append(f"T {features.temp_min:+.0f}..{features.temp_max:+.0f}°C")
    
    # 3. Risk labels
    if features.slush_risk:
        signals.append("(каша)")
    elif features.rain_risk:
        signals.append("(дождь)")
    elif features.rain_mm < 0.5:
        signals.append("без осадков")
    
    # 4. Wind if high
    if features.wind_max is not None and features.wind_max > 30 and len(signals) < 3:
        signals.append(f"ветер {features.wind_max:.0f}km/h")
    
    return "Условия завтра: " + ", ".join(signals[:3]) if signals else "Условия завтра: —"
