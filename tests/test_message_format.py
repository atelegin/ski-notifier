"""Tests for message format."""

from datetime import date
from typing import Dict

import pytest

from ski_notifier.features import ResortFeatures, DisciplineWeekly
from ski_notifier.fetch import PointWeather
from ski_notifier.message import (
    RankedResort,
    format_message,
    format_costs_line,
    format_discipline_header_line,
    format_resort_weather_line,
)
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
        daily_snowfall_cm=12,
    )


def make_discipline_weekly(
    alpine_score: int = 80, 
    xc_score: int = 75,
    alpine_is_best: bool = True,
    xc_is_best: bool = True,
) -> Dict[str, DisciplineWeekly]:
    """Create discipline weekly summaries for testing."""
    result: Dict[str, DisciplineWeekly] = {}
    
    tomorrow = date(2025, 1, 15)  # Wednesday
    
    if alpine_score is not None:
        if alpine_is_best:
            result["alpine"] = DisciplineWeekly(
                discipline="alpine",
                tomorrow_score=alpine_score,
                best_day=tomorrow,
                best_day_score=alpine_score,
            )
        else:
            # Best day is Thursday (day after tomorrow)
            result["alpine"] = DisciplineWeekly(
                discipline="alpine",
                tomorrow_score=alpine_score,
                best_day=date(2025, 1, 16),  # Thursday
                best_day_score=alpine_score + 10,
            )
    
    if xc_score is not None:
        if xc_is_best:
            result["xc"] = DisciplineWeekly(
                discipline="xc",
                tomorrow_score=xc_score,
                best_day=tomorrow,
                best_day_score=xc_score,
            )
        else:
            result["xc"] = DisciplineWeekly(
                discipline="xc",
                tomorrow_score=xc_score,
                best_day=date(2025, 1, 16),  # Thursday
                best_day_score=xc_score + 5,
            )
    
    return result


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
            make_discipline_weekly(),
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
            make_discipline_weekly(),
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
            make_discipline_weekly(),
            features,
            costs,
        )
        
        assert message.startswith("🟦 Ski forecast")
    
    def test_xc_no_skipass(self):
        """XC resorts don't show skipass in costs."""
        xc_resort = make_resort("xc1", "xc")
        xc_resort.ski_pass_day_adult_eur = 50  # Should be ignored
        
        cost_line = format_costs_line(xc_resort)
        
        # May return None or string without Skipass
        if cost_line:
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
            make_discipline_weekly(),
            features,
            costs,
        )
        
        assert "(каша)" in message

    def test_weather_line_uses_precip_label(self):
        """Weather line uses 'precip' label (not 'rain')."""
        ranked = make_ranked(make_resort("a"), 80)
        wet_features = ResortFeatures(
            snow24_cm=10,
            snow48_cm=20,
            overnight_cm=None,
            rain_mm=13,
            temp_min=-4,
            temp_max=-3,
            wind_max=36,
            slush_risk=False,
            rain_risk=False,
            daily_snowfall_cm=20,
        )

        line = format_resort_weather_line(ranked, wet_features)

        assert "precip 13" in line
        assert "rain 13" not in line

    def test_weather_line_shows_zero_snow24_and_daily_separately(self):
        """snow24=0 should still be displayed, alongside calendar-day snowfall."""
        ranked = make_ranked(make_resort("a"), 80)
        mixed_snow_features = ResortFeatures(
            snow24_cm=0,
            snow48_cm=0,
            overnight_cm=None,
            rain_mm=0,
            temp_min=-4,
            temp_max=-3,
            wind_max=12,
            slush_risk=False,
            rain_risk=False,
            daily_snowfall_cm=18,
        )

        line = format_resort_weather_line(ranked, mixed_snow_features)

        assert "snow24 0cm" in line
        assert "daily 18cm" in line
        assert "depth 50cm" in line

    def test_blocks_spacing(self):
        """Resort blocks are separated by exactly one blank line."""
        r1 = make_ranked(make_resort("a", "alpine"), 80)
        r2 = make_ranked(make_resort("b", "alpine"), 75)
        r3 = make_ranked(make_resort("c", "alpine"), 70)
        
        features: Dict[str, ResortFeatures] = {
            "a": make_features(),
            "b": make_features(),
            "c": make_features(),
        }
        costs = Costs(ferry_konstanz_meersburg_rt_eur=24, at_vignette_1day_eur=10)
        
        message = format_message(
            date(2025, 1, 15),
            [r1, r2, r3],
            make_discipline_weekly(),
            features,
            costs,
        )
        
        lines = message.split("\n")
        
        # Find header section end (blank line after header)
        header_end = None
        for i, line in enumerate(lines):
            if line == "" and i > 0:
                header_end = i
                break
        assert header_end is not None, "Should have blank line after header"
        
        # After header blank line, get rest of message
        resort_section = "\n".join(lines[header_end + 1:])
        
        # Between resort blocks there should be exactly \n\n (one blank line)
        # Within a block (resort + costs) there's just \n
        # This means we should see patterns of: resort_line\n↳ costs_line\n\n
        assert "\n\n\n" not in resort_section, "Should not have multiple blank lines"
        assert "\n\n" in resort_section, "Should have blank lines between blocks"
    
    def test_costs_prefix(self):
        """Costs line starts with ↳ 💶 prefix."""
        alpine_resort = make_resort("alpine1", "alpine")
        
        cost_line = format_costs_line(alpine_resort)
        
        assert cost_line is not None
        assert cost_line.startswith("↳ 💶 ")
    
    def test_costs_inside_block_single_newline(self):
        """Inside a block, costs is separated from resort by single newline."""
        r1 = make_ranked(make_resort("a", "alpine"), 80)
        
        features: Dict[str, ResortFeatures] = {"a": make_features()}
        costs = Costs(ferry_konstanz_meersburg_rt_eur=24, at_vignette_1day_eur=10)
        
        message = format_message(
            date(2025, 1, 15),
            [r1],
            make_discipline_weekly(),
            features,
            costs,
        )
        
        # Find the resort line and costs line
        assert "Resort a" in message
        assert "↳ 💶" in message
        
        # There should be exactly one \n between resort and costs (no blank line)
        lines = message.split("\n")
        for i, line in enumerate(lines):
            if "Resort a" in line and "🎿" in line:
                # Next line should be costs (if exists)
                if i + 1 < len(lines) and lines[i + 1].startswith("↳"):
                    # Good - directly next line, no empty line in between
                    pass
                break

    def test_no_usloviya_zavtra_line(self):
        """Message should NOT contain 'Условия завтра:' line - it was misleading."""
        r1 = make_ranked(make_resort("a"), 80)
        
        features: Dict[str, ResortFeatures] = {"a": make_features()}
        costs = Costs(ferry_konstanz_meersburg_rt_eur=24, at_vignette_1day_eur=10)
        
        message = format_message(
            date(2025, 1, 15),
            [r1],
            make_discipline_weekly(),
            features,
            costs,
        )
        
        # This line should NOT exist in the message
        assert "Условия завтра:" not in message

    def test_header_structure_with_disciplines(self):
        """Header: title line + discipline lines + blank line + first resort."""
        r1 = make_ranked(make_resort("a"), 80)
        
        features: Dict[str, ResortFeatures] = {"a": make_features()}
        costs = Costs(ferry_konstanz_meersburg_rt_eur=24, at_vignette_1day_eur=10)
        
        message = format_message(
            date(2025, 1, 15),
            [r1],
            make_discipline_weekly(),
            features,
            costs,
        )
        
        lines = message.split("\n")
        
        # Line 0: title
        assert lines[0].startswith("🟦 Ski forecast")
        
        # Line 1: alpine discipline (starts with ✅, ⚠️, or ⛔️)
        assert lines[1].startswith("✅") or lines[1].startswith("⚠️") or lines[1].startswith("⛔️")
        assert "Горные:" in lines[1]
        
        # Line 2: xc discipline
        assert lines[2].startswith("✅") or lines[2].startswith("⚠️") or lines[2].startswith("⛔️")
        assert "Беговые:" in lines[2]
        
        # Line 3: blank line
        assert lines[3] == ""
        
        # Line 4: first resort (🎿 or ⛷️)
        assert "🎿" in lines[4] or "⛷️" in lines[4]


# Tests for discipline header line formatting
class TestDisciplineHeaderLine:
    def test_header_line_tomorrow_is_best(self):
        """When tomorrow is best day, show '— завтра лучший день недели: <score>'."""
        tomorrow = date(2025, 1, 15)
        summary = DisciplineWeekly(
            discipline="alpine",
            tomorrow_score=85,
            best_day=tomorrow,
            best_day_score=85,
        )
        
        line = format_discipline_header_line(summary, tomorrow)
        
        assert "— завтра лучший день недели: 85" in line
        assert "Горные: стоит" in line
        # Must NOT contain "но лучший день" when tomorrow is best
        assert "но лучший день" not in line
    
    def test_header_line_tomorrow_worse(self):
        """When tomorrow is worse than best (large gap), show 'но лучший день <DAY>: <score>'."""
        tomorrow = date(2025, 1, 15)
        summary = DisciplineWeekly(
            discipline="alpine",
            tomorrow_score=74,
            best_day=date(2025, 1, 18),  # Saturday
            best_day_score=84,
        )
        
        line = format_discipline_header_line(summary, tomorrow)
        
        # gap=10 > 2: "— завтра 74, но лучший день СБ: 84"
        assert ", но лучший день СБ: 84" in line
        assert "Горные: стоит" in line
        # No delta tokens
        assert "(-" not in line
        assert "(+" not in line
        assert "хуже" not in line
        # Day must be uppercase
        assert "СБ" in line
    
    def test_header_verdict_threshold_stoit(self):
        """Score >= 70 shows 'стоит' with ✅."""
        tomorrow = date(2025, 1, 15)
        for score in [70, 75, 85, 100]:
            summary = DisciplineWeekly(
                discipline="alpine",
                tomorrow_score=score,
                best_day=tomorrow,
                best_day_score=score,
            )
            line = format_discipline_header_line(summary, tomorrow)
            assert "стоит" in line
    
    def test_header_verdict_threshold_somnitelno(self):
        """Score 60-69 shows 'сомнительно' with ⚠️."""
        tomorrow = date(2025, 1, 15)
        for score in [60, 65, 69]:
            summary = DisciplineWeekly(
                discipline="alpine",
                tomorrow_score=score,
                best_day=tomorrow,
                best_day_score=score,
            )
            line = format_discipline_header_line(summary, tomorrow)
            assert "сомнительно" in line
    
    def test_header_verdict_threshold_skip(self):
        """Score < 60 shows ⛔️ verdict."""
        tomorrow = date(2025, 1, 15)
        for score in [55, 50, 30, 0]:
            summary = DisciplineWeekly(
                discipline="alpine",
                tomorrow_score=score,
                best_day=tomorrow,
                best_day_score=score,
            )
            line = format_discipline_header_line(summary, tomorrow)
            assert "не стоит" in line
    
    def test_header_xc_label(self):
        """XC discipline shows 'Беговые' label."""
        tomorrow = date(2025, 1, 15)
        summary = DisciplineWeekly(
            discipline="xc",
            tomorrow_score=75,
            best_day=tomorrow,
            best_day_score=75,
        )
        
        line = format_discipline_header_line(summary, tomorrow)
        
        assert "Беговые:" in line

    def test_header_xc_thresholds(self):
        """XC uses dedicated thresholds: >=68 ok, 58-67 warning, <58 skip."""
        tomorrow = date(2025, 1, 15)

        ok = DisciplineWeekly(
            discipline="xc",
            tomorrow_score=68,
            best_day=tomorrow,
            best_day_score=68,
        )
        warning = DisciplineWeekly(
            discipline="xc",
            tomorrow_score=58,
            best_day=tomorrow,
            best_day_score=58,
        )
        skip = DisciplineWeekly(
            discipline="xc",
            tomorrow_score=57,
            best_day=tomorrow,
            best_day_score=57,
        )

        assert "стоит" in format_discipline_header_line(ok, tomorrow)
        assert "сомнительно" in format_discipline_header_line(warning, tomorrow)
        assert "не стоит" in format_discipline_header_line(skip, tomorrow)
    
    def test_header_has_one_line_per_present_discipline_alpine_only(self):
        """If only alpine data exists, only 1 discipline line."""
        r1 = make_ranked(make_resort("a", "alpine"), 80)
        
        features: Dict[str, ResortFeatures] = {"a": make_features()}
        costs = Costs(ferry_konstanz_meersburg_rt_eur=24, at_vignette_1day_eur=10)
        
        # Only alpine in discipline_weekly
        discipline_weekly = {
            "alpine": DisciplineWeekly(
                discipline="alpine",
                tomorrow_score=80,
                best_day=date(2025, 1, 15),
                best_day_score=80,
            )
        }
        
        message = format_message(
            date(2025, 1, 15),
            [r1],
            discipline_weekly,
            features,
            costs,
        )
        
        lines = message.split("\n")
        
        # Line 0: title
        assert lines[0].startswith("🟦 Ski forecast")
        # Line 1: alpine only
        assert "Горные:" in lines[1]
        # Line 2: should be blank (no xc line)
        assert lines[2] == ""
        # No Беговые line anywhere before the blank
        assert "Беговые:" not in lines[1]
    
    def test_header_has_one_line_per_present_discipline_both(self):
        """If both disciplines have data, 2 lines in order: Горные then Беговые."""
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
            make_discipline_weekly(),
            features,
            costs,
        )
        
        lines = message.split("\n")
        
        # Line 1: alpine
        assert "Горные:" in lines[1]
        # Line 2: xc
        assert "Беговые:" in lines[2]
    
    def test_header_does_not_include_old_strings(self):
        """Header should NOT contain old format strings."""
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
            make_discipline_weekly(alpine_is_best=False, xc_is_best=False),
            features,
            costs,
        )
        
        # Old format patterns should NOT exist
        assert "ℹ️ Лучший день:" not in message  # old weekly-best format with icon
        assert "Условия завтра:" not in message  # old conditions line
        
        # New format "Лучший день <day>:" IS allowed
        # (this appears in the new format: "Лучший день чт: 90")


def test_xc_costs_still_present_e2e():
    """XC resorts with ferry show costs line, no skipass."""
    xc_resort = make_resort("xc1", "xc")
    
    ranked = [make_ranked(xc_resort, 70)]
    features: Dict[str, ResortFeatures] = {"xc1": make_features()}
    costs = Costs(ferry_konstanz_meersburg_rt_eur=24, at_vignette_1day_eur=10)
    
    # Only xc discipline
    discipline_weekly = {
        "xc": DisciplineWeekly(
            discipline="xc",
            tomorrow_score=70,
            best_day=date(2025, 1, 15),
            best_day_score=70,
        )
    }
    
    message = format_message(
        date(2025, 1, 15),
        ranked,
        discipline_weekly,
        features,
        costs,
    )
    
    assert "↳ 💶" in message
    assert "ferry" in message
    assert "Skipass" not in message


class TestVerdictDependentTemplates:
    """Tests for verdict-dependent header templates (P1.HEADER.9)."""
    
    def test_ok_small_gap(self):
        """✅ small gap: t=82, b=84 → 'почти лучший день недели: 82'."""
        tomorrow = date(2025, 1, 15)
        summary = DisciplineWeekly(
            discipline="alpine",
            tomorrow_score=82,
            best_day=date(2025, 1, 18),  # Saturday
            best_day_score=84,
        )
        line = format_discipline_header_line(summary, tomorrow)
        
        assert "почти лучший день недели: 82" in line
        assert "стоит" in line
    
    def test_ok_large_gap(self):
        """✅ large gap: t=72, b=80 → 'но лучший день СБ: 80'."""
        tomorrow = date(2025, 1, 15)
        summary = DisciplineWeekly(
            discipline="alpine",
            tomorrow_score=72,
            best_day=date(2025, 1, 18),  # Saturday
            best_day_score=80,
        )
        line = format_discipline_header_line(summary, tomorrow)
        
        assert "но лучший день СБ: 80" in line
        assert "стоит" in line
    
    def test_warning_non_tie(self):
        """⚠️ non-tie: t=61, b=62 → exact template with 'Лучший вариант на неделе'."""
        tomorrow = date(2025, 1, 15)
        summary = DisciplineWeekly(
            discipline="xc",
            tomorrow_score=61,
            best_day=date(2025, 1, 18),  # Saturday
            best_day_score=62,
        )
        line = format_discipline_header_line(summary, tomorrow)
        
        assert "Беговые: сомнительно — завтра 61. Лучший вариант на неделе: 62 (СБ)" in line
        assert "почти лучший день" not in line
    
    def test_warning_tie(self):
        """⚠️ tie: t=61, b=61 → 'завтра лучший вариант на неделе: 61'."""
        tomorrow = date(2025, 1, 15)
        summary = DisciplineWeekly(
            discipline="xc",
            tomorrow_score=61,
            best_day=tomorrow,
            best_day_score=61,
        )
        line = format_discipline_header_line(summary, tomorrow)
        
        assert "завтра лучший вариант на неделе: 61" in line
        assert "сомнительно" in line
    
    def test_skip_good_day_soon(self):
        """⛔️ good day soon: t=56, b=80, days_to_best=2 → 'подождать до СР (80)'."""
        tomorrow = date(2025, 1, 15)  # Wednesday is 2 days later
        summary = DisciplineWeekly(
            discipline="alpine",
            tomorrow_score=56,
            best_day=date(2025, 1, 17),  # Friday, 2 days later
            best_day_score=80,
        )
        line = format_discipline_header_line(summary, tomorrow)
        
        assert "подождать до ПТ (80)" in line
        assert "лучше не завтра" in line
    
    def test_skip_not_best_weak_best_day(self):
        """⛔️ not best tomorrow + weak best day: t=56, b=62 → 'тоже слабый'."""
        tomorrow = date(2025, 1, 15)
        summary = DisciplineWeekly(
            discipline="alpine",
            tomorrow_score=56,
            best_day=date(2025, 1, 19),  # Sunday, 4 days later
            best_day_score=62,
        )
        line = format_discipline_header_line(summary, tomorrow)
        
        assert "не стоит — завтра 56; лучший день ВС тоже слабый: 62" in line
        assert "подождать" not in line
    
    def test_skip_best_day_in_past(self):
        """⛔️ best day in past relative to tomorrow → no crash, uses 'не стоит'."""
        tomorrow = date(2025, 1, 15)
        summary = DisciplineWeekly(
            discipline="alpine",
            tomorrow_score=45,
            best_day=date(2025, 1, 14),  # Yesterday
            best_day_score=80,
        )
        line = format_discipline_header_line(summary, tomorrow)
        
        # Should not crash, should use "не стоит" fallback
        assert "не стоит — завтра 45" in line
        assert "подождать" not in line
    
    def test_warning_large_gap(self):
        """⚠️ large gap: t=61, b=80 → still uses 'Лучший вариант на неделе', no 'почти лучший'."""
        tomorrow = date(2025, 1, 15)
        summary = DisciplineWeekly(
            discipline="xc",
            tomorrow_score=61,
            best_day=date(2025, 1, 18),  # Saturday
            best_day_score=80,
        )
        line = format_discipline_header_line(summary, tomorrow)
        
        assert "Лучший вариант на неделе: 80 (СБ)" in line
        assert "почти лучший" not in line
        assert "сомнительно" in line
    
    def test_skip_tomorrow_is_best(self):
        """⛔️ tomorrow IS best (gap=0) → 'не стоит — завтра {t}', no 'лучший день'."""
        tomorrow = date(2025, 1, 15)
        summary = DisciplineWeekly(
            discipline="alpine",
            tomorrow_score=55,
            best_day=tomorrow,
            best_day_score=55,
        )
        line = format_discipline_header_line(summary, tomorrow)
        
        assert "не стоит — завтра 55" in line
        assert "лучший день" not in line
        assert "подождать" not in line
    
    def test_wait_rule_up_to_7_days(self):
        """⛔️ good day within 7 days: t=57, b=78, days_to_best=6 → 'подождать до СБ (78)'."""
        tomorrow = date(2025, 1, 15)  # Wednesday
        summary = DisciplineWeekly(
            discipline="xc",
            tomorrow_score=57,
            best_day=date(2025, 1, 21),  # Tuesday, 6 days later
            best_day_score=78,
        )
        line = format_discipline_header_line(summary, tomorrow)
        
        assert "подождать до ВТ (78)" in line
        assert "лучше не завтра" in line
    
    def test_wait_rule_over_7_days_no_best_mention(self):
        """⛔️ good day beyond 7 days: t=57, b=78, days_to_best=8 → no 'подождать', no 'лучший день'."""
        tomorrow = date(2025, 1, 15)  # Wednesday
        summary = DisciplineWeekly(
            discipline="xc",
            tomorrow_score=57,
            best_day=date(2025, 1, 23),  # Thursday, 8 days later
            best_day_score=78,
        )
        line = format_discipline_header_line(summary, tomorrow)
        
        assert "не стоит — завтра 57" in line
        assert "подождать" not in line
        assert "лучший день" not in line
    
    def test_day_abbreviation_uppercase(self):
        """Day abbreviation in output is uppercase (СБ, not сб)."""
        tomorrow = date(2025, 1, 15)  # Wednesday
        summary = DisciplineWeekly(
            discipline="alpine",
            tomorrow_score=56,
            best_day=date(2025, 1, 18),  # Saturday
            best_day_score=62,
        )
        line = format_discipline_header_line(summary, tomorrow)
        
        # Day should be uppercase СБ in the output
        assert "СБ" in line
        # Ensure lowercase "сб" is not in the original line
        assert "сб" not in line
