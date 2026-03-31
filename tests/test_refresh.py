"""Tests for /refresh helpers."""

from datetime import date, datetime
from unittest.mock import patch

from ski_notifier.main import (
    ForecastBundle,
    extract_recommended_resort_names,
    format_refresh_message,
    is_in_season,
    is_refresh_command,
)
from ski_notifier.fetch import PointWeather
from ski_notifier.message import RankedResort
from ski_notifier.resorts import Costs, Point, Resort
from ski_notifier.score import PointScore, ResortScore


def make_resort(resort_id: str, name: str, resort_type: str = "alpine") -> Resort:
    point = Point(lat=47.0, lon=9.0)
    return Resort(
        id=resort_id,
        name=name,
        country="AT",
        type=resort_type,
        drive_time_min=80,
        point_low=point,
        point_high=point,
        requires_ferry=False,
        requires_at_vignette=False,
        requires_ch_vignette=False,
        ferry_roundtrip_eur=0,
        at_vignette_eur=0,
    )


def make_ranked(resort: Resort, score: float) -> RankedResort:
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


def make_bundle(ranked, selected) -> ForecastBundle:
    return ForecastBundle(
        target_date=date(2025, 1, 15),
        resorts=[r.resort for r in ranked],
        costs=Costs(ferry_konstanz_meersburg_rt_eur=24, at_vignette_1day_eur=10),
        ranked_resorts=ranked,
        selected_ranked_resorts=selected,
        discipline_weekly={},
        resort_features={},
        missing_resort_names=[],
        success_rate=1.0,
    )


def test_extract_recommended_resort_names_from_forecast_message():
    text = (
        "🟦 Ski forecast (завтра 15.01 09:00–16:00)\n"
        "✅ Горные: стоит — завтра лучший день недели: 80\n\n"
        "🎿 Flumserberg — 80 — 🚗 90 мин — depth 50cm\n"
        "↳ 💶 Skipass EUR 60\n\n"
        "⛷️ Balderschwang — 72 — 🚗 70 мин — depth 40cm\n"
    )
    assert extract_recommended_resort_names(text) == ["Flumserberg", "Balderschwang"]


def test_is_refresh_command_variants():
    assert is_refresh_command("/refresh")
    assert is_refresh_command("/refresh@my_bot")
    assert is_refresh_command("/refresh please")
    assert not is_refresh_command("/start")


def test_is_in_season_includes_april():
    with patch("ski_notifier.main.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 4, 15, 12, 0)
        assert is_in_season()


def test_is_in_season_excludes_may():
    with patch("ski_notifier.main.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 5, 1, 12, 0)
        assert not is_in_season()


def test_refresh_message_marks_top_unchanged():
    a = make_ranked(make_resort("a", "A"), 80)
    b = make_ranked(make_resort("b", "B", "xc"), 75)
    bundle = make_bundle([a, b], [a, b])

    msg = format_refresh_message(["A", "B"], bundle)

    assert "Ранее рекомендованные курорты" in msg
    assert "Топ на сейчас не изменился." in msg
    assert "Новый топ на сейчас:" not in msg


def test_refresh_message_shows_new_top_when_changed():
    a = make_ranked(make_resort("a", "A"), 80)
    b = make_ranked(make_resort("b", "B", "xc"), 75)
    c = make_ranked(make_resort("c", "C"), 78)
    bundle = make_bundle([a, c, b], [c, b])

    msg = format_refresh_message(["A", "B"], bundle)

    assert "Новый топ на сейчас:" in msg
    assert "Топ на сейчас не изменился." not in msg
    assert "🆕 🎿 C" in msg
    assert "= ⛷️ B" in msg


def test_refresh_message_position_markers_up_and_down():
    a = make_ranked(make_resort("a", "A"), 90)
    b = make_ranked(make_resort("b", "B", "xc"), 88)
    c = make_ranked(make_resort("c", "C"), 86)
    bundle = make_bundle([a, b, c], [b, a, c])

    msg = format_refresh_message(["A", "B", "C"], bundle)

    assert "↑1 ⛷️ B" in msg
    assert "↓1 🎿 A" in msg
    assert "= 🎿 C" in msg
