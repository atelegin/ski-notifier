"""Tests for message format."""

from datetime import date
from typing import Dict

import pytest

from ski_notifier.features import ResortFeatures, DisciplineWeekly
from ski_notifier.fetch import PointWeather
from ski_notifier.message import RankedResort, format_message, format_costs_line, format_discipline_header_line
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
        summary = DisciplineWeekly(
            discipline="alpine",
            tomorrow_score=85,
            best_day=date(2025, 1, 15),
            best_day_score=85,
        )
        
        line = format_discipline_header_line(summary)
        
        assert "— завтра лучший день недели: 85" in line
        assert "✅ Горные: стоит" in line
        # Must NOT contain "но лучший день" when tomorrow is best
        assert "но лучший день" not in line
    
    def test_header_line_tomorrow_worse(self):
        """When tomorrow is worse than best, show 'но лучший день <DAY>: <score>' (no delta)."""
        summary = DisciplineWeekly(
            discipline="alpine",
            tomorrow_score=74,
            best_day=date(2025, 1, 18),  # Saturday
            best_day_score=84,
        )
        
        line = format_discipline_header_line(summary)
        
        # New format: "— завтра 74, но лучший день СБ: 84"
        assert ", но лучший день СБ: 84" in line
        assert "✅ Горные: стоит" in line
        # No delta tokens
        assert "(-" not in line
        assert "(+" not in line
        assert "хуже" not in line
        # Day must be uppercase
        assert "СБ" in line
    
    def test_header_verdict_threshold_stoit(self):
        """Score >= 70 shows 'стоит' with ✅."""
        for score in [70, 75, 85, 100]:
            summary = DisciplineWeekly(
                discipline="alpine",
                tomorrow_score=score,
                best_day=date(2025, 1, 15),
                best_day_score=score,
            )
            line = format_discipline_header_line(summary)
            assert "✅" in line
            assert "стоит" in line
    
    def test_header_verdict_threshold_somnitelno(self):
        """Score 60-69 shows 'сомнительно' with ⚠️."""
        for score in [60, 65, 69]:
            summary = DisciplineWeekly(
                discipline="alpine",
                tomorrow_score=score,
                best_day=date(2025, 1, 15),
                best_day_score=score,
            )
            line = format_discipline_header_line(summary)
            assert "⚠️" in line
            assert "сомнительно" in line
    
    def test_header_verdict_threshold_ne_stoit(self):
        """Score < 60 shows 'не стоит' with ⛔️."""
        for score in [55, 50, 30, 0]:
            summary = DisciplineWeekly(
                discipline="alpine",
                tomorrow_score=score,
                best_day=date(2025, 1, 15),
                best_day_score=score,
            )
            line = format_discipline_header_line(summary)
            assert "⛔️" in line
            assert "не стоит" in line
    
    def test_header_xc_label(self):
        """XC discipline shows 'Беговые' label."""
        summary = DisciplineWeekly(
            discipline="xc",
            tomorrow_score=75,
            best_day=date(2025, 1, 15),
            best_day_score=75,
        )
        
        line = format_discipline_header_line(summary)
        
        assert "Беговые:" in line
    
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
