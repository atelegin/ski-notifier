"""Open-Meteo API client for weather forecasts with batch support."""

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

from .resorts import Point, Resort

# Configure logging
logger = logging.getLogger(__name__)

# Constants
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
TIMEZONE = "Europe/Berlin"
TZ = ZoneInfo(TIMEZONE)

# Batch settings
DEFAULT_BATCH_SIZE = 40  # points per request
FALLBACK_BATCH_SIZES = [20, 10]  # adaptive fallback on URL errors

# Retry settings
MAX_RETRIES = 5
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 90.0
BACKOFF_BASE = 1.0  # seconds

# HTTP codes that trigger retry
RETRY_STATUS_CODES = {408, 429, 500, 502, 503, 504}


@dataclass
class PointWeather:
    """Weather data for a single point on a specific day."""
    date: date
    temp_c_avg_9_16: Optional[float]
    wind_gust_kmh_max_9_16: Optional[float]
    precip_mm_sum_9_16: Optional[float]
    snow_depth_cm: Optional[float]
    snowfall_cm: Optional[float]


@dataclass
class ResortWeather:
    """Weather data for both points of a resort for multiple days."""
    low: Dict[date, PointWeather]  # date -> weather
    high: Dict[date, PointWeather]


@dataclass
class BatchPoint:
    """Point with metadata for batch processing."""
    resort_id: str
    point_type: str  # "low" or "high"
    lat: float
    lon: float
    index: int = 0  # position in batch request


@dataclass
class FetchResult:
    """Result of fetching weather for all resorts."""
    weather: Dict[str, ResortWeather]  # resort_id -> ResortWeather
    failed_resorts: List[str]  # list of resort_ids that failed
    n_points_total: int
    n_points_success: int
    n_batches: int


class URLTooLongError(Exception):
    """Raised when URL is too long for the server."""
    pass


def _is_url_too_long_error(response: Optional[requests.Response] = None, 
                           exception: Optional[Exception] = None) -> bool:
    """Check if error indicates URL is too long."""
    if response is not None:
        if response.status_code == 414:
            return True
        if response.status_code == 400:
            text = response.text.lower()
            if "too long" in text or "uri" in text:
                return True
    if exception is not None:
        msg = str(exception).lower()
        if "too long" in msg:
            return True
    return False


def _should_retry(response: Optional[requests.Response] = None,
                  exception: Optional[Exception] = None) -> bool:
    """Check if request should be retried."""
    if exception is not None:
        # Retry on timeout and connection errors
        if isinstance(exception, (requests.Timeout, requests.ConnectionError)):
            return True
    if response is not None:
        return response.status_code in RETRY_STATUS_CODES
    return False


def _http_get_with_retry(
    url: str,
    params: dict,
    max_retries: int = MAX_RETRIES,
    connect_timeout: float = CONNECT_TIMEOUT,
    read_timeout: float = READ_TIMEOUT,
) -> requests.Response:
    """HTTP GET with exponential backoff and retries.
    
    Raises:
        URLTooLongError: If URL is too long (for adaptive batch sizing).
        RuntimeError: If all retries exhausted or non-retryable error.
    """
    last_exception: Optional[Exception] = None
    
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                url, 
                params=params, 
                timeout=(connect_timeout, read_timeout)
            )
            
            # Check for URL too long
            if _is_url_too_long_error(response=resp):
                raise URLTooLongError(f"URL too long: {resp.status_code}")
            
            # Check if should retry
            if _should_retry(response=resp):
                wait_time = BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    f"Request failed with {resp.status_code}, "
                    f"retry {attempt + 1}/{max_retries} in {wait_time:.1f}s"
                )
                time.sleep(wait_time)
                continue
            
            # Check for other errors
            if resp.status_code != 200:
                raise RuntimeError(f"Open-Meteo returned {resp.status_code}: {resp.text}")
            
            return resp
            
        except URLTooLongError:
            raise
        except requests.RequestException as e:
            if _is_url_too_long_error(exception=e):
                raise URLTooLongError(f"URL too long: {e}") from e
            
            last_exception = e
            if _should_retry(exception=e):
                wait_time = BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    f"Request failed with {e.__class__.__name__}, "
                    f"retry {attempt + 1}/{max_retries} in {wait_time:.1f}s"
                )
                time.sleep(wait_time)
                continue
            raise RuntimeError(f"Open-Meteo request failed: {e}") from e
    
    raise RuntimeError(
        f"Open-Meteo request failed after {max_retries} retries: {last_exception}"
    )


def _convert_to_cm(value: Optional[float], unit: str) -> Optional[float]:
    """Convert snow values to cm based on unit from API."""
    if value is None:
        return None
    if unit == "m":
        return value * 100
    elif unit == "cm":
        return value
    elif unit == "mm":
        return value / 10
    else:
        return value


def _parse_point_weather_from_batch(
    data: Dict[str, Any],
    hourly_units: Dict[str, str],
    daily_units: Dict[str, str],
) -> Dict[date, PointWeather]:
    """Parse weather data for a single point from batch response."""
    hourly = data.get("hourly", {})
    daily = data.get("daily", {})
    
    if not hourly or "time" not in hourly:
        return {}
    
    # Parse hourly times
    hourly_times = [datetime.fromisoformat(t) for t in hourly["time"]]
    
    result: Dict[date, PointWeather] = {}
    dates = sorted(set(dt.date() for dt in hourly_times))
    
    for d in dates:
        # Filter hours for this date between 09:00 and 16:00
        indices = [
            i for i, dt in enumerate(hourly_times)
            if dt.date() == d and 9 <= dt.hour <= 16
        ]
        
        if not indices:
            continue
        
        # Calculate averages/max/sum for the skiing window
        temps = [hourly["temperature_2m"][i] for i in indices 
                 if hourly["temperature_2m"][i] is not None]
        gusts = [hourly["wind_gusts_10m"][i] for i in indices 
                 if hourly["wind_gusts_10m"][i] is not None]
        precip = [hourly["precipitation"][i] for i in indices 
                  if hourly["precipitation"][i] is not None]
        
        temp_avg = sum(temps) / len(temps) if temps else None
        gust_max = max(gusts) if gusts else None
        precip_sum = sum(precip) if precip else None
        
        snowfall_cm: Optional[float] = None
        snow_depth_cm: Optional[float] = None
        
        # Try daily snowfall_sum (primary source for full-day snowfall)
        if "snowfall_sum" in daily and daily["snowfall_sum"]:
            daily_dates = [datetime.fromisoformat(t).date() for t in daily.get("time", [])]
            if d in daily_dates:
                idx = daily_dates.index(d)
                val = daily["snowfall_sum"][idx]
                if val is not None:
                    unit = daily_units.get("snowfall_sum", "cm")
                    snowfall_cm = _convert_to_cm(val, unit)
        
        # Fallback: sum hourly snowfall for FULL calendar day (not just 09-16 window)
        # This captures overnight/nighttime snowfall when daily data is unavailable
        if snowfall_cm is None:
            # Get all hourly indices for this calendar day (00:00-23:00)
            full_day_indices = [
                i for i, dt in enumerate(hourly_times)
                if dt.date() == d
            ]
            snowfall_hourly_full_day = [
                hourly["snowfall"][i] for i in full_day_indices
                if hourly["snowfall"][i] is not None
            ]
            if snowfall_hourly_full_day:
                unit = hourly_units.get("snowfall", "cm")
                snowfall_cm = _convert_to_cm(sum(snowfall_hourly_full_day), unit)
        
        # Snow depth from daily
        if "snow_depth_max" in daily and daily["snow_depth_max"]:
            daily_dates = [datetime.fromisoformat(t).date() for t in daily.get("time", [])]
            if d in daily_dates:
                idx = daily_dates.index(d)
                val = daily["snow_depth_max"][idx]
                if val is not None:
                    unit = daily_units.get("snow_depth_max", "m")
                    snow_depth_cm = _convert_to_cm(val, unit)
        
        result[d] = PointWeather(
            date=d,
            temp_c_avg_9_16=round(temp_avg, 1) if temp_avg is not None else None,
            wind_gust_kmh_max_9_16=round(gust_max, 1) if gust_max is not None else None,
            precip_mm_sum_9_16=round(precip_sum, 1) if precip_sum is not None else None,
            snow_depth_cm=round(snow_depth_cm, 1) if snow_depth_cm is not None else None,
            snowfall_cm=round(snowfall_cm, 1) if snowfall_cm is not None else None,
        )
    
    return result


def _fetch_batch(
    points: List[BatchPoint],
    forecast_days: int,
    batch_size: int,
) -> Tuple[Dict[int, Dict[date, PointWeather]], List[int]]:
    """Fetch weather for a batch of points.
    
    Returns:
        Tuple of (success_map, failed_indices) where:
        - success_map: index -> weather data
        - failed_indices: list of indices that failed
    """
    if not points:
        return {}, []
    
    # Build CSV lists
    latitudes = ",".join(str(p.lat) for p in points)
    longitudes = ",".join(str(p.lon) for p in points)
    
    params = {
        "latitude": latitudes,
        "longitude": longitudes,
        "hourly": "temperature_2m,wind_gusts_10m,precipitation,snowfall",
        "daily": "snow_depth_max,snowfall_sum",
        "timezone": TIMEZONE,
        "forecast_days": forecast_days,
    }
    
    try:
        resp = _http_get_with_retry(OPEN_METEO_URL, params)
    except URLTooLongError:
        raise
    except RuntimeError as e:
        logger.error(f"Batch request failed: {e}")
        return {}, [p.index for p in points]
    
    data = resp.json()
    
    # Handle single vs multiple locations
    # Single location: data is the response directly
    # Multiple locations: data is a list
    if isinstance(data, list):
        responses = data
    else:
        responses = [data]
    
    # Validate response length
    if len(responses) != len(points):
        logger.warning(
            f"Response length mismatch: got {len(responses)}, expected {len(points)}"
        )
        # Try to process what we got, mark rest as failed
        if len(responses) < len(points):
            failed = [p.index for p in points[len(responses):]]
        else:
            failed = []
    else:
        failed = []
    
    # Parse responses
    success_map: Dict[int, Dict[date, PointWeather]] = {}
    
    for i, point in enumerate(points[:len(responses)]):
        point_data = responses[i]
        
        if not point_data or "hourly" not in point_data:
            failed.append(point.index)
            continue
        
        hourly_units = point_data.get("hourly_units", {})
        daily_units = point_data.get("daily_units", {})
        
        try:
            weather = _parse_point_weather_from_batch(point_data, hourly_units, daily_units)
            if weather:
                success_map[point.index] = weather
            else:
                failed.append(point.index)
        except Exception as e:
            logger.warning(f"Failed to parse weather for point {point.index}: {e}")
            failed.append(point.index)
    
    return success_map, failed


def fetch_all_resorts_weather(
    resorts: List[Resort],
    forecast_days: int = 7,
) -> FetchResult:
    """Fetch weather for all resorts using batch requests.
    
    Args:
        resorts: List of resorts to fetch weather for.
        forecast_days: Number of days to forecast.
        
    Returns:
        FetchResult with weather data and statistics.
    """
    # Collect all points (flat_map: low + high per resort)
    all_points: List[BatchPoint] = []
    for resort in resorts:
        all_points.append(BatchPoint(
            resort_id=resort.id,
            point_type="low",
            lat=resort.point_low.lat,
            lon=resort.point_low.lon,
            index=len(all_points),
        ))
        all_points.append(BatchPoint(
            resort_id=resort.id,
            point_type="high",
            lat=resort.point_high.lat,
            lon=resort.point_high.lon,
            index=len(all_points),
        ))
    
    n_points_total = len(all_points)
    logger.info(f"Fetching weather for {n_points_total} points ({len(resorts)} resorts)")
    
    # Process in batches with adaptive sizing
    all_weather: Dict[int, Dict[date, PointWeather]] = {}
    all_failed: List[int] = []
    n_batches = 0
    batch_size = DEFAULT_BATCH_SIZE
    
    i = 0
    while i < len(all_points):
        batch = all_points[i:i + batch_size]
        
        try:
            success_map, failed = _fetch_batch(batch, forecast_days, batch_size)
            all_weather.update(success_map)
            all_failed.extend(failed)
            n_batches += 1
            i += len(batch)
            
        except URLTooLongError:
            # Try smaller batch size
            if batch_size in FALLBACK_BATCH_SIZES:
                idx = FALLBACK_BATCH_SIZES.index(batch_size)
                if idx + 1 < len(FALLBACK_BATCH_SIZES):
                    batch_size = FALLBACK_BATCH_SIZES[idx + 1]
                    logger.warning(f"URL too long, reducing batch size to {batch_size}")
                    continue
            elif batch_size == DEFAULT_BATCH_SIZE and FALLBACK_BATCH_SIZES:
                batch_size = FALLBACK_BATCH_SIZES[0]
                logger.warning(f"URL too long, reducing batch size to {batch_size}")
                continue
            
            # All fallbacks exhausted, mark batch as failed
            logger.error("URL too long even with minimum batch size")
            all_failed.extend([p.index for p in batch])
            i += len(batch)
    
    logger.info(f"Open-Meteo: {n_batches} batches, {len(all_weather)}/{n_points_total} points OK")
    
    # Build ResortWeather objects
    weather_by_resort: Dict[str, ResortWeather] = {}
    failed_resorts: List[str] = []
    
    # Create index -> point mapping
    index_to_point = {p.index: p for p in all_points}
    
    # Group weather by resort
    resort_weather_data: Dict[str, Dict[str, Dict[date, PointWeather]]] = {}
    for idx, weather_data in all_weather.items():
        point = index_to_point[idx]
        if point.resort_id not in resort_weather_data:
            resort_weather_data[point.resort_id] = {}
        resort_weather_data[point.resort_id][point.point_type] = weather_data
    
    # Build final result
    for resort in resorts:
        resort_data = resort_weather_data.get(resort.id, {})
        low_weather = resort_data.get("low", {})
        high_weather = resort_data.get("high", {})
        
        if not low_weather and not high_weather:
            failed_resorts.append(resort.id)
        else:
            weather_by_resort[resort.id] = ResortWeather(
                low=low_weather,
                high=high_weather,
            )
    
    if failed_resorts:
        logger.warning(f"Failed resorts: {failed_resorts}")
    
    return FetchResult(
        weather=weather_by_resort,
        failed_resorts=failed_resorts,
        n_points_total=n_points_total,
        n_points_success=len(all_weather),
        n_batches=n_batches,
    )


# Legacy function for backward compatibility
def fetch_point_weather(point: Point, forecast_days: int = 7) -> Dict[date, PointWeather]:
    """Fetch weather forecast for a point (legacy single-point API).
    
    Args:
        point: Geographic point with lat/lon.
        forecast_days: Number of days to forecast.
        
    Returns:
        Dict mapping date to PointWeather.
        
    Raises:
        RuntimeError: If API request fails or returns unexpected data.
    """
    params = {
        "latitude": point.lat,
        "longitude": point.lon,
        "hourly": "temperature_2m,wind_gusts_10m,precipitation,snowfall",
        "daily": "snow_depth_max,snowfall_sum",
        "timezone": TIMEZONE,
        "forecast_days": forecast_days,
    }
    
    resp = _http_get_with_retry(OPEN_METEO_URL, params)
    data = resp.json()
    
    if "hourly" not in data:
        raise RuntimeError(f"Open-Meteo response missing 'hourly' data: {data}")
    
    hourly_units = data.get("hourly_units", {})
    daily_units = data.get("daily_units", {})
    
    return _parse_point_weather_from_batch(data, hourly_units, daily_units)


def fetch_resort_weather(point_low: Point, point_high: Point, forecast_days: int = 7) -> ResortWeather:
    """Fetch weather for both points of a resort (legacy API).
    
    Args:
        point_low: Base station point.
        point_high: Summit point.
        forecast_days: Number of days to forecast.
        
    Returns:
        ResortWeather with data for both points.
    """
    return ResortWeather(
        low=fetch_point_weather(point_low, forecast_days),
        high=fetch_point_weather(point_high, forecast_days),
    )
