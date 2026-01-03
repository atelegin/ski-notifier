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
    tomorrow_score: float
    best_day: date
    best_day_score: float
    message: str


@dataclass
class DisciplineWeekly:
    """Weekly analysis for a single discipline (alpine or xc)."""
    discipline: str  # "alpine" or "xc"
    tomorrow_score: int
    best_day: date
    best_day_score: int
    
    @property
    def tomorrow_is_best(self) -> bool:
        """Check if tomorrow is the best day (or tied for best)."""
        # Use == because best_day_score is the max, tomorrow can only equal it (not exceed)
        return self.tomorrow_score == self.best_day_score


def compute_discipline_weekly(
    scores_by_day_by_discipline: Dict[str, Dict[date, int]],
    tomorrow: date,
) -> Dict[str, "DisciplineWeekly"]:
    """Compute weekly best analysis per discipline.
    
    Args:
        scores_by_day_by_discipline: {"alpine": {date: max_score}, "xc": {date: max_score}}
        tomorrow: tomorrow's date
        
    Returns:
        Dict mapping discipline to DisciplineWeekly.
        Only includes disciplines that have data for tomorrow.
        If a discipline has no tomorrow_score, it is omitted from the result.
    """
    result: Dict[str, DisciplineWeekly] = {}
    
    for disc, scores_by_day in scores_by_day_by_discipline.items():
        if not scores_by_day:
            continue
        
        # Skip discipline if no data for tomorrow
        if tomorrow not in scores_by_day:
            continue
        
        tomorrow_score = scores_by_day[tomorrow]
        
        # Find best day (earliest wins on tie)
        sorted_days = sorted(scores_by_day.items(), key=lambda x: (-x[1], x[0]))
        best_day, best_day_score = sorted_days[0]
        
        result[disc] = DisciplineWeekly(
            discipline=disc,
            tomorrow_score=tomorrow_score,
            best_day=best_day,
            best_day_score=best_day_score,
        )
    
    return result


def compute_weekly_best(
    best_scores_by_day: Dict[date, float],
    tomorrow: date,
) -> WeeklyBest:
    """Compute weekly best day analysis.
    
    Message logic:
    - tomorrow_score == best_score AND best_day == tomorrow:
      "✅ Завтра — лучший день недели (<score>)"
    - tomorrow_score == best_score AND best_day != tomorrow (tie):
      "✅ Завтра — один из лучших дней недели (<score>)"
    - tomorrow_score < best_score:
      "ℹ️ Лучший день: <day> (<best_score>). Завтра: <tomorrow_score> (−<diff>)"
    """
    if not best_scores_by_day:
        return WeeklyBest(
            tomorrow_score=0,
            best_day=tomorrow,
            best_day_score=0,
            message="ℹ️ Нет данных о прогнозе",
        )
    
    tomorrow_score = best_scores_by_day.get(tomorrow, 0)
    
    # Find best day (earliest wins on tie)
    sorted_days = sorted(best_scores_by_day.items(), key=lambda x: (-x[1], x[0]))
    best_day, best_day_score = sorted_days[0]
    
    # Generate message
    if tomorrow_score == best_day_score:
        if best_day == tomorrow:
            message = f"✅ Завтра — лучший день недели ({tomorrow_score:.0f})"
        else:
            message = f"✅ Завтра — один из лучших дней недели ({tomorrow_score:.0f})"
    else:
        weekday_names = {0: "пн", 1: "вт", 2: "ср", 3: "чт", 4: "пт", 5: "сб", 6: "вс"}
        best_weekday = weekday_names.get(best_day.weekday(), "")
        diff = best_day_score - tomorrow_score
        message = f"ℹ️ Лучший день: {best_weekday} ({best_day_score:.0f}). Завтра: {tomorrow_score:.0f} (−{diff:.0f})"
    
    return WeeklyBest(
        tomorrow_score=tomorrow_score,
        best_day=best_day,
        best_day_score=best_day_score,
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
