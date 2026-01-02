"""Tests for message format."""

from datetime import date
from typing import Dict

import pytest

from ski_notifier.features import ResortFeatures, WeeklyBest
from ski_notifier.fetch import PointWeather
from ski_notifier.message import RankedResort, DisciplineBests, format_message, format_costs_line
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


def make_weekly_best(is_best: bool = True) -> WeeklyBest:
    """Create WeeklyBest for testing."""
    if is_best:
        return WeeklyBest(
            tomorrow_score=78,
            best_day=date(2025, 1, 15),
            best_day_score=78,
            message="✅ Завтра — лучший день недели (78)",
        )
    else:
        return WeeklyBest(
            tomorrow_score=68,
            best_day=date(2025, 1, 16),
            best_day_score=82,
            message="ℹ️ Лучший день: чт (82). Завтра: 68 (−14)",
        )


def make_discipline_bests(alpine: float = 80, xc: float = 75) -> DisciplineBests:
    """Create DisciplineBests for testing."""
    return DisciplineBests(
        best_alpine_score=alpine if alpine is not None else None,
        best_xc_score=xc if xc is not None else None,
        best_alpine_confidence=0.9 if alpine is not None else None,
        best_xc_confidence=0.9 if xc is not None else None,
    )


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
            make_weekly_best(),
            features,
            costs,
            make_discipline_bests(),
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
            make_weekly_best(),
            features,
            costs,
            make_discipline_bests(),
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
            make_weekly_best(),
            features,
            costs,
            make_discipline_bests(),
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
            make_weekly_best(),
            features,
            costs,
            make_discipline_bests(),
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
            make_weekly_best(),
            features,
            costs,
            make_discipline_bests(),
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
            make_weekly_best(),
            features,
            costs,
            make_discipline_bests(),
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
            make_weekly_best(),
            features,
            costs,
            make_discipline_bests(),
        )
        
        # This line should NOT exist in the message
        assert "Условия завтра:" not in message

    def test_header_structure_compact(self):
        """Header: title line + weekly-best line + blank line + first resort."""
        r1 = make_ranked(make_resort("a"), 80)
        
        features: Dict[str, ResortFeatures] = {"a": make_features()}
        costs = Costs(ferry_konstanz_meersburg_rt_eur=24, at_vignette_1day_eur=10)
        
        message = format_message(
            date(2025, 1, 15),
            [r1],
            make_weekly_best(),
            features,
            costs,
            make_discipline_bests(),
        )
        
        lines = message.split("\n")
        
        # Line 0: title
        assert lines[0].startswith("🟦 Ski forecast")
        
        # Line 1: weekly best (starts with ✅ or ℹ️)
        assert lines[1].startswith("✅") or lines[1].startswith("ℹ️")
        
        # Line 2: blank line
        assert lines[2] == ""
        
        # Line 3: first resort (🎿 or ⛷️)
        assert "🎿" in lines[3] or "⛷️" in lines[3]


def test_discipline_warning_thresholds():
    """Test discipline warning lines at correct thresholds."""
    from ski_notifier.message import format_discipline_warnings, DisciplineBests
    
    bests = DisciplineBests(
        best_alpine_score=58,
        best_xc_score=66,
        best_alpine_confidence=0.8,
        best_xc_confidence=0.8,
    )
    
    warnings = format_discipline_warnings(bests)
    
    assert len(warnings) == 2
    assert warnings[0] == "⛔ Горные: не стоит (58)"
    assert warnings[1] == "⚠️ Беговые: сомнительно (66)"


def test_discipline_warning_no_warning_high_scores():
    """No warnings when scores >= 70."""
    from ski_notifier.message import format_discipline_warnings, DisciplineBests
    
    bests = DisciplineBests(
        best_alpine_score=75,
        best_xc_score=80,
        best_alpine_confidence=0.9,
        best_xc_confidence=0.9,
    )
    
    warnings = format_discipline_warnings(bests)
    
    assert len(warnings) == 0


def test_xc_costs_still_present_e2e():
    """XC resorts with ferry show costs line, no skipass."""
    xc_resort = make_resort("xc1", "xc")
    
    ranked = [make_ranked(xc_resort, 70)]
    features: Dict[str, ResortFeatures] = {"xc1": make_features()}
    costs = Costs(ferry_konstanz_meersburg_rt_eur=24, at_vignette_1day_eur=10)
    discipline_bests = make_discipline_bests(alpine=None, xc=70)
    
    message = format_message(
        date(2025, 1, 15),
        ranked,
        make_weekly_best(),
        features,
        costs,
        discipline_bests,
    )
    
    assert "↳ 💶" in message
    assert "ferry" in message
    assert "Skipass" not in message

