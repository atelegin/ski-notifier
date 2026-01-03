"""Tests for fetch module batch API and retry logic."""

import time
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
import requests

from ski_notifier.fetch import (
    _http_get_with_retry,
    _is_url_too_long_error,
    _should_retry,
    _parse_point_weather_from_batch,
    fetch_all_resorts_weather,
    URLTooLongError,
    BatchPoint,
    PointWeather,
)
from ski_notifier.resorts import Resort, Point


class TestShouldRetry:
    """Tests for _should_retry function."""
    
    def test_retry_on_timeout_exception(self):
        """Should retry on timeout exception."""
        exc = requests.Timeout("Connection timed out")
        assert _should_retry(exception=exc) is True
    
    def test_retry_on_connection_error(self):
        """Should retry on connection error."""
        exc = requests.ConnectionError("Connection refused")
        assert _should_retry(exception=exc) is True
    
    def test_retry_on_429(self):
        """Should retry on 429 Too Many Requests."""
        resp = MagicMock()
        resp.status_code = 429
        assert _should_retry(response=resp) is True
    
    def test_retry_on_408(self):
        """Should retry on 408 Request Timeout."""
        resp = MagicMock()
        resp.status_code = 408
        assert _should_retry(response=resp) is True
    
    def test_retry_on_503(self):
        """Should retry on 503 Service Unavailable."""
        resp = MagicMock()
        resp.status_code = 503
        assert _should_retry(response=resp) is True
    
    def test_no_retry_on_400(self):
        """Should not retry on 400 Bad Request."""
        resp = MagicMock()
        resp.status_code = 400
        assert _should_retry(response=resp) is False
    
    def test_no_retry_on_404(self):
        """Should not retry on 404 Not Found."""
        resp = MagicMock()
        resp.status_code = 404
        assert _should_retry(response=resp) is False


class TestIsUrlTooLongError:
    """Tests for _is_url_too_long_error function."""
    
    def test_detects_414(self):
        """Should detect 414 URI Too Long."""
        resp = MagicMock()
        resp.status_code = 414
        assert _is_url_too_long_error(response=resp) is True
    
    def test_detects_400_with_too_long(self):
        """Should detect 400 with 'too long' in body."""
        resp = MagicMock()
        resp.status_code = 400
        resp.text = "Request URI too long"
        assert _is_url_too_long_error(response=resp) is True
    
    def test_ignores_normal_400(self):
        """Should ignore normal 400 error."""
        resp = MagicMock()
        resp.status_code = 400
        resp.text = "Bad request"
        assert _is_url_too_long_error(response=resp) is False
    
    def test_detects_exception_with_too_long(self):
        """Should detect exception with 'too long' in message."""
        exc = Exception("URL is too long for server")
        assert _is_url_too_long_error(exception=exc) is True


class TestHttpGetWithRetry:
    """Tests for _http_get_with_retry function."""
    
    @patch("ski_notifier.fetch.requests.get")
    @patch("ski_notifier.fetch.time.sleep")
    def test_success_first_try(self, mock_sleep, mock_get):
        """Should return response on first successful try."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        
        result = _http_get_with_retry("http://test.com", {"a": 1})
        
        assert result == mock_resp
        mock_get.assert_called_once()
        mock_sleep.assert_not_called()
    
    @patch("ski_notifier.fetch.requests.get")
    @patch("ski_notifier.fetch.time.sleep")
    def test_retry_on_timeout_then_success(self, mock_sleep, mock_get):
        """Should retry and succeed after timeout."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        
        mock_get.side_effect = [
            requests.Timeout("timeout"),
            requests.Timeout("timeout"),
            mock_resp,
        ]
        
        result = _http_get_with_retry("http://test.com", {}, max_retries=5)
        
        assert result == mock_resp
        assert mock_get.call_count == 3
        assert mock_sleep.call_count == 2
    
    @patch("ski_notifier.fetch.requests.get")
    @patch("ski_notifier.fetch.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep, mock_get):
        """Should raise RuntimeError after max retries."""
        mock_get.side_effect = requests.Timeout("timeout")
        
        with pytest.raises(RuntimeError, match="failed after"):
            _http_get_with_retry("http://test.com", {}, max_retries=3)
        
        assert mock_get.call_count == 3
    
    @patch("ski_notifier.fetch.requests.get")
    def test_raises_url_too_long_immediately(self, mock_get):
        """Should raise URLTooLongError on 414 without retrying."""
        mock_resp = MagicMock()
        mock_resp.status_code = 414
        mock_get.return_value = mock_resp
        
        with pytest.raises(URLTooLongError):
            _http_get_with_retry("http://test.com", {})
        
        assert mock_get.call_count == 1


class TestParsePointWeatherFromBatch:
    """Tests for _parse_point_weather_from_batch function."""
    
    def test_parses_complete_data(self):
        """Should parse complete weather data."""
        data = {
            "hourly": {
                "time": [
                    "2025-01-15T09:00",
                    "2025-01-15T10:00",
                    "2025-01-15T11:00",
                ],
                "temperature_2m": [-5.0, -4.0, -3.0],
                "wind_gusts_10m": [20.0, 25.0, 30.0],
                "precipitation": [0.0, 0.0, 0.0],
                "snowfall": [0.5, 0.3, 0.2],
            },
            "daily": {
                "time": ["2025-01-15"],
                "snow_depth_max": [0.5],  # meters
            },
        }
        hourly_units = {"snowfall": "cm"}
        daily_units = {"snow_depth_max": "m"}
        
        result = _parse_point_weather_from_batch(data, hourly_units, daily_units)
        
        assert date(2025, 1, 15) in result
        weather = result[date(2025, 1, 15)]
        assert weather.temp_c_avg_9_16 == -4.0  # average of -5, -4, -3
        assert weather.wind_gust_kmh_max_9_16 == 30.0
        assert weather.snow_depth_cm == 50.0  # 0.5m * 100
    
    def test_handles_missing_hourly(self):
        """Should return empty dict when hourly data missing."""
        data = {"daily": {"time": [], "snow_depth_max": []}}
        result = _parse_point_weather_from_batch(data, {}, {})
        assert result == {}
    
    def test_handles_none_values(self):
        """Should handle None values in data arrays."""
        data = {
            "hourly": {
                "time": ["2025-01-15T10:00"],
                "temperature_2m": [None],
                "wind_gusts_10m": [None],
                "precipitation": [None],
                "snowfall": [None],
            },
        }
        result = _parse_point_weather_from_batch(data, {}, {})
        
        assert date(2025, 1, 15) in result
        weather = result[date(2025, 1, 15)]
        assert weather.temp_c_avg_9_16 is None
        assert weather.wind_gust_kmh_max_9_16 is None

    def test_daily_snowfall_sum_priority(self):
        """Should use daily snowfall_sum when available, even if hourly exists."""
        data = {
            "hourly": {
                "time": [
                    "2025-01-15T09:00",
                    "2025-01-15T10:00",
                    "2025-01-15T11:00",
                ],
                "temperature_2m": [-5.0, -4.0, -3.0],
                "wind_gusts_10m": [20.0, 25.0, 30.0],
                "precipitation": [0.0, 0.0, 0.0],
                "snowfall": [1.0, 1.0, 1.0],  # Total 3.0 cm (but should be ignored)
            },
            "daily": {
                "time": ["2025-01-15"],
                "snow_depth_max": [0.5],
                "snowfall_sum": [15.5],  # This should be used
            },
        }
        hourly_units = {"snowfall": "cm"}
        daily_units = {"snow_depth_max": "m", "snowfall_sum": "cm"}
        
        result = _parse_point_weather_from_batch(data, hourly_units, daily_units)
        
        assert date(2025, 1, 15) in result
        weather = result[date(2025, 1, 15)]
        assert weather.snowfall_cm == 15.5  # Daily value, not hourly sum

    def test_hourly_fallback_sums_full_calendar_day(self):
        """Should sum hourly snowfall for FULL calendar day, not just 09-16 window."""
        # Snowfall at night (02:00, 04:00, 06:00) should be captured
        data = {
            "hourly": {
                "time": [
                    "2025-01-15T02:00",  # Night
                    "2025-01-15T04:00",  # Night
                    "2025-01-15T06:00",  # Early morning
                    "2025-01-15T10:00",  # Day
                    "2025-01-15T14:00",  # Day
                    "2025-01-15T20:00",  # Night
                ],
                "temperature_2m": [-8.0, -7.0, -6.0, -4.0, -3.0, -5.0],
                "wind_gusts_10m": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
                "precipitation": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                "snowfall": [3.0, 4.0, 2.0, 0.5, 0.5, 1.0],  # Total 11.0 cm
            },
            "daily": {
                "time": ["2025-01-15"],
                "snow_depth_max": [0.5],
                # No snowfall_sum - should trigger hourly fallback
            },
        }
        hourly_units = {"snowfall": "cm"}
        daily_units = {"snow_depth_max": "m"}
        
        result = _parse_point_weather_from_batch(data, hourly_units, daily_units)
        
        assert date(2025, 1, 15) in result
        weather = result[date(2025, 1, 15)]
        # Should be 11.0 cm (all hours), not just 1.0 cm (09-16 window)
        assert weather.snowfall_cm == 11.0

    def test_overnight_snowfall_not_missed(self):
        """Snowfall only outside 09-16 window should still be captured."""
        data = {
            "hourly": {
                "time": [
                    "2025-01-15T01:00",
                    "2025-01-15T03:00", 
                    "2025-01-15T05:00",
                    "2025-01-15T10:00",  # Only this is in 09-16 window
                    "2025-01-15T22:00",
                ],
                "temperature_2m": [-10.0, -10.0, -10.0, -5.0, -8.0],
                "wind_gusts_10m": [5.0, 5.0, 5.0, 10.0, 5.0],
                "precipitation": [0.0, 0.0, 0.0, 0.0, 0.0],
                "snowfall": [5.0, 5.0, 3.0, 0.0, 2.0],  # 15 cm total, 0 in 09-16
            },
            "daily": {
                "time": ["2025-01-15"],
                "snow_depth_max": [1.0],
            },
        }
        hourly_units = {"snowfall": "cm"}
        daily_units = {"snow_depth_max": "m"}
        
        result = _parse_point_weather_from_batch(data, hourly_units, daily_units)
        
        assert date(2025, 1, 15) in result
        weather = result[date(2025, 1, 15)]
        # Should be 15.0 cm (full day), not 0 (09-16 window only)
        assert weather.snowfall_cm == 15.0


class TestFetchAllResortsWeather:
    """Integration tests for fetch_all_resorts_weather."""
    
    @patch("ski_notifier.fetch._http_get_with_retry")
    def test_batch_response_mapping(self, mock_http):
        """Should correctly map batch response to resorts."""
        # Create 2 test resorts
        resorts = [
            Resort(
                id="resort_a", name="Resort A", country="CH", type="alpine",
                drive_time_min=60, point_low=Point(lat=47.0, lon=8.0),
                point_high=Point(lat=47.1, lon=8.1),
                requires_ferry=False, requires_at_vignette=False,
                requires_ch_vignette=False, ferry_roundtrip_eur=0, at_vignette_eur=0,
            ),
            Resort(
                id="resort_b", name="Resort B", country="CH", type="alpine",
                drive_time_min=60, point_low=Point(lat=47.2, lon=8.2),
                point_high=Point(lat=47.3, lon=8.3),
                requires_ferry=False, requires_at_vignette=False,
                requires_ch_vignette=False, ferry_roundtrip_eur=0, at_vignette_eur=0,
            ),
        ]
        
        # Mock response with 4 points (2 per resort: low, high)
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            # Resort A - low
            {
                "hourly": {
                    "time": ["2025-01-15T10:00"],
                    "temperature_2m": [-5.0],
                    "wind_gusts_10m": [20.0],
                    "precipitation": [0.0],
                    "snowfall": [1.0],
                },
            },
            # Resort A - high
            {
                "hourly": {
                    "time": ["2025-01-15T10:00"],
                    "temperature_2m": [-10.0],
                    "wind_gusts_10m": [30.0],
                    "precipitation": [0.0],
                    "snowfall": [2.0],
                },
            },
            # Resort B - low
            {
                "hourly": {
                    "time": ["2025-01-15T10:00"],
                    "temperature_2m": [-3.0],
                    "wind_gusts_10m": [15.0],
                    "precipitation": [0.0],
                    "snowfall": [0.5],
                },
            },
            # Resort B - high
            {
                "hourly": {
                    "time": ["2025-01-15T10:00"],
                    "temperature_2m": [-8.0],
                    "wind_gusts_10m": [25.0],
                    "precipitation": [0.0],
                    "snowfall": [1.5],
                },
            },
        ]
        mock_http.return_value = mock_resp
        
        result = fetch_all_resorts_weather(resorts, forecast_days=7)
        
        assert result.n_batches == 1
        assert result.n_points_total == 4
        assert result.n_points_success == 4
        assert len(result.failed_resorts) == 0
        assert "resort_a" in result.weather
        assert "resort_b" in result.weather
        
        # Check resort A data
        resort_a_weather = result.weather["resort_a"]
        assert date(2025, 1, 15) in resort_a_weather.low
        assert resort_a_weather.low[date(2025, 1, 15)].temp_c_avg_9_16 == -5.0
        assert date(2025, 1, 15) in resort_a_weather.high
        assert resort_a_weather.high[date(2025, 1, 15)].temp_c_avg_9_16 == -10.0
    
    @patch("ski_notifier.fetch._http_get_with_retry")
    def test_handles_partial_failure(self, mock_http):
        """Should handle partial batch failure gracefully."""
        resorts = [
            Resort(
                id="resort_a", name="Resort A", country="CH", type="alpine",
                drive_time_min=60, point_low=Point(lat=47.0, lon=8.0),
                point_high=Point(lat=47.1, lon=8.1),
                requires_ferry=False, requires_at_vignette=False,
                requires_ch_vignette=False, ferry_roundtrip_eur=0, at_vignette_eur=0,
            ),
        ]
        
        # Mock response with only 1 point (should fail resort A)
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {
                "hourly": {
                    "time": ["2025-01-15T10:00"],
                    "temperature_2m": [-5.0],
                    "wind_gusts_10m": [20.0],
                    "precipitation": [0.0],
                    "snowfall": [1.0],
                },
            },
            {},  # Empty response for high point
        ]
        mock_http.return_value = mock_resp
        
        result = fetch_all_resorts_weather(resorts, forecast_days=7)
        
        # Resort should still have low point data
        assert "resort_a" in result.weather
        assert date(2025, 1, 15) in result.weather["resort_a"].low


class TestSnow24To9:
    """Tests for compute_snow24_to_9 computation (P0 - must implement before merge)."""
    
    def test_normal_day_sum(self):
        """Sum hourly snowfall for [D-24h, D 09:00). Always 24 slots."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from ski_notifier.fetch import compute_snow24_to_9
        
        tz = ZoneInfo("Europe/Berlin")
        target_day = date(2025, 1, 15)
        
        # Create 24h of hourly data ending at 09:00 on target day
        # Window: 2025-01-14 09:00 to 2025-01-15 09:00 (exclusive)
        end_dt = datetime(2025, 1, 15, 9, 0, tzinfo=tz)
        
        hourly_unix_times = []
        hourly_snowfall = []
        for i in range(24):
            t = end_dt.timestamp() - (24 - i) * 3600
            hourly_unix_times.append(int(t))
            hourly_snowfall.append(1.0)  # 1 cm per hour
        
        snow24, quality = compute_snow24_to_9(
            hourly_unix_times, hourly_snowfall, target_day, "cm"
        )
        
        assert snow24 == 24.0  # 24 hours * 1 cm
        assert quality == "ok"
    
    def test_boundary_start_included(self):
        """Unix timestamp == start should be included."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from ski_notifier.fetch import compute_snow24_to_9
        
        tz = ZoneInfo("Europe/Berlin")
        target_day = date(2025, 1, 15)
        
        # Only the start timestamp (09:00 yesterday)
        end_dt = datetime(2025, 1, 15, 9, 0, tzinfo=tz)
        start_unix = int((end_dt.timestamp() - 24 * 3600))
        
        snow24, quality = compute_snow24_to_9(
            [start_unix], [5.0], target_day, "cm"
        )
        
        assert snow24 == 5.0  # Start is included
        assert quality == "partial"  # Only 1 of 24 slots
    
    def test_boundary_end_excluded(self):
        """Unix timestamp == end (09:00) should be excluded."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from ski_notifier.fetch import compute_snow24_to_9
        
        tz = ZoneInfo("Europe/Berlin")
        target_day = date(2025, 1, 15)
        
        # Only the end timestamp (09:00 today) - should be excluded
        end_unix = int(datetime(2025, 1, 15, 9, 0, tzinfo=tz).timestamp())
        
        snow24, quality = compute_snow24_to_9(
            [end_unix], [5.0], target_day, "cm"
        )
        
        assert snow24 is None  # End is excluded
        assert quality == "missing"
    
    def test_dst_forward_robust(self):
        """DST spring forward: function works correctly, returns reasonable result."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from ski_notifier.fetch import compute_snow24_to_9
        
        tz = ZoneInfo("Europe/Berlin")
        # DST forward in Germany: last Sunday of March (2025-03-30)
        # Clocks jump from 02:00 to 03:00
        target_day = date(2025, 3, 30)
        
        end_dt = datetime(2025, 3, 30, 9, 0, tzinfo=tz)
        
        # Generate slots using Unix time (may be 23 or 24 depending on window)
        hourly_unix_times = []
        hourly_snowfall = []
        for i in range(24):
            t = end_dt.timestamp() - (24 - i) * 3600
            hourly_unix_times.append(int(t))
            hourly_snowfall.append(0.5)
        
        snow24, quality = compute_snow24_to_9(
            hourly_unix_times, hourly_snowfall, target_day, "cm"
        )
        
        # Verify function handles DST without crashing
        assert snow24 is not None
        assert snow24 > 10.0  # At least most of the data should be counted
        assert quality in ("ok", "partial")  # May be partial due to DST
    
    def test_dst_backward_robust(self):
        """DST fall back: function works correctly, handles potential collision."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from ski_notifier.fetch import compute_snow24_to_9
        
        tz = ZoneInfo("Europe/Berlin")
        # DST back in Germany: last Sunday of October (2025-10-26)
        # Clocks go from 03:00 back to 02:00
        target_day = date(2025, 10, 26)
        
        end_dt = datetime(2025, 10, 26, 9, 0, tzinfo=tz)
        
        hourly_unix_times = []
        hourly_snowfall = []
        for i in range(24):
            t = end_dt.timestamp() - (24 - i) * 3600
            hourly_unix_times.append(int(t))
            hourly_snowfall.append(0.5)
        
        snow24, quality = compute_snow24_to_9(
            hourly_unix_times, hourly_snowfall, target_day, "cm"
        )
        
        # Verify function handles DST without crashing
        assert snow24 is not None
        assert snow24 > 10.0  # At least most of the data should be counted
        assert quality in ("ok", "partial")  # May be partial due to DST
    
    def test_partial_missing_data(self):
        """Missing some slots → quality=partial."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from ski_notifier.fetch import compute_snow24_to_9
        
        tz = ZoneInfo("Europe/Berlin")
        target_day = date(2025, 1, 15)
        
        end_dt = datetime(2025, 1, 15, 9, 0, tzinfo=tz)
        
        # Only provide 12 of 24 expected slots
        hourly_unix_times = []
        hourly_snowfall = []
        for i in range(12):
            t = end_dt.timestamp() - (24 - i) * 3600
            hourly_unix_times.append(int(t))
            hourly_snowfall.append(1.0)
        
        snow24, quality = compute_snow24_to_9(
            hourly_unix_times, hourly_snowfall, target_day, "cm"
        )
        
        assert snow24 == 12.0  # Sum of available data
        assert quality == "partial"  # Missing 12 slots
    
    def test_fully_missing_data(self):
        """No data in window → quality=missing, snow24=None."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from ski_notifier.fetch import compute_snow24_to_9
        
        tz = ZoneInfo("Europe/Berlin")
        target_day = date(2025, 1, 15)
        
        # Provide data outside the window (after 09:00)
        outside_window = int(datetime(2025, 1, 15, 10, 0, tzinfo=tz).timestamp())
        
        snow24, quality = compute_snow24_to_9(
            [outside_window], [5.0], target_day, "cm"
        )
        
        assert snow24 is None
        assert quality == "missing"
    
    def test_unit_conversion_mm(self):
        """Snowfall in mm should be converted to cm."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from ski_notifier.fetch import compute_snow24_to_9
        
        tz = ZoneInfo("Europe/Berlin")
        target_day = date(2025, 1, 15)
        
        end_dt = datetime(2025, 1, 15, 9, 0, tzinfo=tz)
        start_unix = int((end_dt.timestamp() - 24 * 3600))
        
        # 10mm should become 1cm
        snow24, quality = compute_snow24_to_9(
            [start_unix], [10.0], target_day, "mm"
        )
        
        assert snow24 == 1.0  # 10mm = 1cm
        assert quality == "partial"
