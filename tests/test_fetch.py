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
