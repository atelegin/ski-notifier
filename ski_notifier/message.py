"""Telegram message formatter — compact format."""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

from .features import ResortFeatures, DisciplineWeekly
from .resorts import Costs, Resort
from .score import ResortScore

# Constants for discipline header formatting
WEEKDAY_NAMES = {0: "пн", 1: "вт", 2: "ср", 3: "чт", 4: "пт", 5: "сб", 6: "вс"}
DISCIPLINE_LABELS = {"alpine": "Горные", "xc": "Беговые"}


@dataclass
class RankedResort:
    """Resort with its score for ranking."""
    resort: Resort
    score: ResortScore


def format_discipline_header_line(summary: DisciplineWeekly) -> str:
    """Format one header line for a discipline.
    
    Verdict thresholds by tomorrow_score:
    - >= 70: ✅ <disc>: стоит
    - 60..69: ⚠️ <disc>: сомнительно
    - < 60: ⛔️ <disc>: не стоит
    
    If tomorrow_is_best:
        "<ICON> <Disc>: <verdict>. Завтра — лучший день недели: <score>"
    Else:
        "<ICON> <Disc>: <verdict>. Завтра <score> (<diff>). Лучший день <day>: <best_score>"
    """
    score = summary.tomorrow_score
    disc_label = DISCIPLINE_LABELS.get(summary.discipline, summary.discipline)
    
    # Determine verdict
    if score >= 70:
        icon = "✅"
        verdict = "стоит"
    elif score >= 60:
        icon = "⚠️"
        verdict = "сомнительно"
    else:
        icon = "⛔️"
        verdict = "не стоит"
    
    if summary.tomorrow_is_best:
        return f"{icon} {disc_label}: {verdict}. Завтра — лучший день недели: {score}"
    else:
        diff = summary.tomorrow_score - summary.best_day_score  # negative
        best_weekday = WEEKDAY_NAMES.get(summary.best_day.weekday(), "")
        return f"{icon} {disc_label}: {verdict}. Завтра {score} ({diff:+d}). Лучший день {best_weekday}: {summary.best_day_score}"


def format_costs_line(resort: Resort) -> Optional[str]:
    """Format costs line with ↳ prefix.
    
    Returns: "↳ 💶 <costs...>" or None if no costs to show.
    XC resorts don't show skipass.
    """
    parts = []
    
    # Access costs
    access_parts = []
    if resort.requires_ferry:
        access_parts.append(f"ferry €{resort.ferry_roundtrip_eur:.0f}")
    if resort.requires_at_vignette:
        access_parts.append(f"AT vignette")
    if resort.requires_ch_vignette:
        access_parts.append("CH vignette")
    
    if access_parts:
        parts.append(" + ".join(access_parts))
    
    # Skipass (only for alpine, if known)
    if resort.type == "alpine" and resort.ski_pass_day_adult_eur is not None and resort.ski_pass_day_adult_eur > 0:
        currency = resort.ski_pass_currency
        parts.append(f"Skipass {currency} {resort.ski_pass_day_adult_eur:.0f}")
    
    if not parts:
        return None
    
    return "↳ 💶 " + " | ".join(parts)


def format_resort_weather_line(
    ranked: RankedResort,
    features: Optional[ResortFeatures],
) -> str:
    """Format single-line weather summary for a resort.
    
    Format: 🎿 Name — score — 🚗 Nmin — snow24 Ncm, T −X..−Y, wind N, rain N
    """
    r = ranked.resort
    s = ranked.score
    
    # Base line
    parts = [
        f"{r.discipline_icon} {r.name}",
        f"{s.score:.0f}",
        f"🚗 {r.drive_time_min} мин",
    ]
    
    # Weather details
    weather_parts = []
    
    if features:
        # Snow
        if features.snow24_cm is not None and features.snow24_cm > 0:
            weather_parts.append(f"snow24 {features.snow24_cm:.0f}cm")
        elif s.weather_high.snow_depth_cm is not None:
            weather_parts.append(f"depth {s.weather_high.snow_depth_cm:.0f}cm")
        
        # Temp range
        if features.temp_min is not None and features.temp_max is not None:
            weather_parts.append(f"T {features.temp_min:+.0f}..{features.temp_max:+.0f}")
        
        # Wind
        if features.wind_max is not None:
            weather_parts.append(f"wind {features.wind_max:.0f}")
        
        # Rain
        if features.rain_mm >= 0.1:
            weather_parts.append(f"rain {features.rain_mm:.0f}")
        
        # Risk labels
        if features.slush_risk:
            weather_parts.append("(каша)")
        elif features.rain_risk:
            weather_parts.append("(дождь)")
    else:
        # Fallback: use raw weather data
        if s.weather_high.snow_depth_cm is not None:
            weather_parts.append(f"depth {s.weather_high.snow_depth_cm:.0f}cm")
        if s.weather_high.temp_c_avg_9_16 is not None:
            weather_parts.append(f"T {s.weather_high.temp_c_avg_9_16:+.0f}")
        if s.weather_high.wind_gust_kmh_max_9_16 is not None:
            weather_parts.append(f"wind {s.weather_high.wind_gust_kmh_max_9_16:.0f}")
    
    weather_str = ", ".join(weather_parts) if weather_parts else "—"
    parts.append(weather_str)
    
    return " — ".join(parts)


def format_missing_block(missing_names: List[str], max_show: int = 5) -> str:
    """Format missing forecast warning."""
    if not missing_names:
        return ""
    
    if len(missing_names) <= max_show:
        names_str = ", ".join(missing_names)
    else:
        shown = missing_names[:max_show]
        remaining = len(missing_names) - max_show
        names_str = ", ".join(shown) + f" (+{remaining} more)"
    
    return f"⚠️ Missing: {names_str}"


def format_message(
    tomorrow: date,
    ranked_resorts: List[RankedResort],
    discipline_weekly: Dict[str, DisciplineWeekly],
    resort_features: Dict[str, ResortFeatures],
    costs: Costs,
    missing_resort_names: Optional[List[str]] = None,
    success_rate: float = 1.0,
) -> str:
    """Format compact Telegram message.
    
    Format:
    - Header with date
    - Discipline lines (1-2, alpine then xc if present)
    - Blank line
    - Resort blocks
    - Missing warning (if any)
    """
    lines = [
        f"🟦 Ski forecast (завтра {tomorrow.strftime('%d.%m')} 09:00–16:00)",
    ]
    
    # Warning if low success rate
    if success_rate < 0.50:
        lines.append("⚠️ Forecast mostly unavailable")
    
    if not ranked_resorts:
        lines.append("❌ Нет данных о курортах")
        if missing_resort_names:
            lines.append(format_missing_block(missing_resort_names))
        return "\n".join(lines)
    
    # Discipline header lines (alpine first, then xc)
    for disc in ["alpine", "xc"]:
        if disc in discipline_weekly:
            lines.append(format_discipline_header_line(discipline_weekly[disc]))
    
    # Check if all resorts have low scores
    all_scores = [r.score.score for r in ranked_resorts]
    if all(score < 35 for score in all_scores):
        lines.append("⚠️ Завтра бессмысленно ехать — все курорты <35")
    
    # Build resort blocks (line1 + optional line2, joined by \n\n)
    blocks: List[str] = []
    for ranked in ranked_resorts:
        features = resort_features.get(ranked.resort.id)
        
        # Line 1: weather
        line1 = format_resort_weather_line(ranked, features)
        
        # Line 2: costs (optional)
        line2 = format_costs_line(ranked.resort)
        
        if line2:
            blocks.append(line1 + "\n" + line2)
        else:
            blocks.append(line1)
    
    # Join header + blank line + resort blocks
    lines.append("")  # Blank line after header
    lines.append("\n\n".join(blocks))
    
    # Missing warning at end
    if missing_resort_names:
        lines.append("")
        lines.append(format_missing_block(missing_resort_names))
    
    return "\n".join(lines)

