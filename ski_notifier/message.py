"""Telegram message formatter."""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

from .resorts import Costs, Resort
from .score import ResortScore


@dataclass
class RankedResort:
    """Resort with its score for ranking."""
    resort: Resort
    score: ResortScore


def format_point_line(
    label: str,
    elevation_m: int,
    snow_depth: Optional[float],
    snowfall: Optional[float],
    temp: Optional[float],
    gust: Optional[float],
    precip: Optional[float],
) -> str:
    """Format a single point's weather line."""
    parts = []
    
    if snow_depth is not None:
        parts.append(f"snow {snow_depth:.0f}cm")
    else:
        parts.append("snow N/A")
    
    if snowfall is not None and snowfall > 0:
        parts.append(f"fresh +{snowfall:.0f}cm")
    
    if temp is not None:
        parts.append(f"temp {temp:+.0f}°C")
    
    if gust is not None:
        parts.append(f"gust {gust:.0f}km/h")
    
    if precip is not None and precip > 0:
        parts.append(f"precip {precip:.1f}mm")
    
    return f"{label} ({elevation_m}m): {', '.join(parts)}"


def format_cost_line(resort: Resort, costs: Costs) -> str:
    """Format the cost information line."""
    parts = []
    
    # Access costs
    access_parts = []
    if resort.requires_ferry:
        access_parts.append(f"ferry €{resort.ferry_roundtrip_eur:.2f}")
    if resort.requires_at_vignette:
        access_parts.append(f"AT vignette €{resort.at_vignette_eur:.2f}")
    if resort.requires_ch_vignette:
        access_parts.append("CH vignette")
    
    if access_parts:
        parts.append(f"Access: {' + '.join(access_parts)}")
    
    # Skipass (only for alpine, if known)
    if resort.type == "alpine" and resort.ski_pass_day_adult_eur is not None and resort.ski_pass_day_adult_eur > 0:
        currency = resort.ski_pass_currency
        parts.append(f"Skipass: {currency} {resort.ski_pass_day_adult_eur:.0f}")
    
    if not parts:
        return ""
    
    return "💶 " + " | ".join(parts)


def format_resort_block(ranked: RankedResort, costs: Costs, rank: int) -> str:
    """Format a single resort block for the message."""
    r = ranked.resort
    s = ranked.score
    
    # Handle optional elevation
    elev_low = r.point_low.elevation_m if r.point_low.elevation_m else 0
    elev_high = r.point_high.elevation_m if r.point_high.elevation_m else 0
    
    lines = [
        f"{'🥇' if rank == 1 else '🥈' if rank == 2 else '🥉'} **{r.name}** — {r.drive_time_min} min",
        f"Score: {s.score:.0f}/100 (confidence: {s.confidence:.1f})",
        "",
        format_point_line(
            "🏔 Low", elev_low,
            s.weather_low.snow_depth_cm, s.weather_low.snowfall_cm,
            s.weather_low.temp_c_avg_9_16, s.weather_low.wind_gust_kmh_max_9_16,
            s.weather_low.precip_mm_sum_9_16,
        ),
        format_point_line(
            "⛰ High", elev_high,
            s.weather_high.snow_depth_cm, s.weather_high.snowfall_cm,
            s.weather_high.temp_c_avg_9_16, s.weather_high.wind_gust_kmh_max_9_16,
            s.weather_high.precip_mm_sum_9_16,
        ),
    ]
    
    cost_line = format_cost_line(r, costs)
    if cost_line:
        lines.append("")
        lines.append(cost_line)
    
    return "\n".join(lines)


def is_best_day_of_week(
    tomorrow_score: float,
    tomorrow_confidence: float,
    best_scores_by_day: Dict[date, float],
    tomorrow: date,
) -> bool:
    """Check if tomorrow is the best day of the week for skiing.
    
    Conditions (all must be true):
    1. tomorrow_score >= 70 (must be a good day)
    2. tomorrow has the highest score of the week
    3. tomorrow_score - second_best >= 10 (clear margin)
    4. tomorrow_confidence >= 0.7
    """
    if tomorrow_score < 70:
        return False
    
    if tomorrow_confidence < 0.7:
        return False
    
    if tomorrow not in best_scores_by_day:
        return False
    
    scores = list(best_scores_by_day.values())
    if not scores:
        return False
    
    max_score = max(scores)
    if tomorrow_score < max_score:
        return False
    
    # Find second best
    sorted_scores = sorted(scores, reverse=True)
    if len(sorted_scores) < 2:
        return True  # Only one day, tomorrow is best by default
    
    second_best = sorted_scores[1]
    if tomorrow_score - second_best < 10:
        return False
    
    return True


def format_missing_block(missing_names: List[str], max_show: int = 5) -> str:
    """Format the missing forecast warning block.
    
    Args:
        missing_names: List of resort names that failed.
        max_show: Maximum number to show before truncating.
        
    Returns:
        Formatted warning string.
    """
    if not missing_names:
        return ""
    
    if len(missing_names) <= max_show:
        names_str = ", ".join(missing_names)
    else:
        shown = missing_names[:max_show]
        remaining = len(missing_names) - max_show
        names_str = ", ".join(shown) + f" (+{remaining} more)"
    
    return f"⚠️ Missing forecast: {names_str}"


def format_message(
    tomorrow: date,
    ranked_resorts: List[RankedResort],
    best_scores_by_day: Dict[date, float],
    costs: Costs,
    missing_resort_names: Optional[List[str]] = None,
    success_rate: float = 1.0,
) -> str:
    """Format the complete Telegram message.
    
    Args:
        tomorrow: The target date.
        ranked_resorts: List of resorts with scores, sorted by score descending.
        best_scores_by_day: Dict of date -> best resort score for each day (7 days).
        costs: Cost constants.
        missing_resort_names: Optional list of resort names that failed to fetch.
        success_rate: Fraction of resorts with successful weather data.
        
    Returns:
        Formatted message string.
    """
    lines = [
        f"🎿 **Завтра ({tomorrow.strftime('%Y-%m-%d')}): куда ехать**",
        "",
    ]
    
    # Show warning if success rate is low
    if success_rate < 0.50:
        lines.append("⚠️ **Forecast mostly unavailable today**")
        lines.append("")
    
    if not ranked_resorts:
        lines.append("❌ Нет данных о курортах.")
        # Still show missing list
        if missing_resort_names:
            lines.append("")
            lines.append(format_missing_block(missing_resort_names))
        return "\n".join(lines)
    
    top = ranked_resorts[0]
    
    # Check if all resorts have low scores
    all_scores = [r.score.score for r in ranked_resorts]
    if all(score < 35 for score in all_scores):
        lines.append("⚠️ **Завтра бессмысленно ехать** — все курорты имеют низкий рейтинг (<35).")
        lines.append("")
    
    # Check if tomorrow is the best day of the week
    elif is_best_day_of_week(
        top.score.score,
        top.score.confidence,
        best_scores_by_day,
        tomorrow,
    ):
        lines.append("🌟 **Завтра почти наверняка будет лучший день недели!**")
        lines.append("")
    
    # Top 3 recommendations
    lines.append("📍 **Рекомендации:**")
    lines.append("")
    
    for i, ranked in enumerate(ranked_resorts[:3]):
        lines.append(format_resort_block(ranked, costs, i + 1))
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # Remove trailing separator
    if lines[-1] == "":
        lines.pop()
    if lines[-1] == "---":
        lines.pop()
    
    # Add missing resorts warning at the end
    if missing_resort_names:
        lines.append("")
        lines.append("")
        lines.append(format_missing_block(missing_resort_names))
    
    return "\n".join(lines)

