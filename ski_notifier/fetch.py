"""Open-Meteo API client for weather forecasts."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import requests

from .resorts import Point

# Constants
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
TIMEZONE = "Europe/Berlin"
TZ = ZoneInfo(TIMEZONE)


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
        # Unknown unit, assume cm
        return value


def fetch_point_weather(point: Point, forecast_days: int = 7) -> Dict[date, PointWeather]:
    """Fetch weather forecast for a point.
    
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
        "daily": "snow_depth_max",  # Note: some locations may not have this
        "timezone": TIMEZONE,
        "forecast_days": forecast_days,
    }
    
    try:
        resp = requests.get(OPEN_METEO_URL, params=params, timeout=30)
    except requests.RequestException as e:
        raise RuntimeError(f"Open-Meteo request failed: {e}") from e
    
    if resp.status_code != 200:
        raise RuntimeError(f"Open-Meteo returned {resp.status_code}: {resp.text}")
    
    data = resp.json()
    
    if "hourly" not in data:
        raise RuntimeError(f"Open-Meteo response missing 'hourly' data: {data}")
    
    hourly = data["hourly"]
    hourly_units = data.get("hourly_units", {})
    daily = data.get("daily", {})
    daily_units = data.get("daily_units", {})
    
    # Parse hourly times
    hourly_times = [datetime.fromisoformat(t) for t in hourly["time"]]
    
    # Group hourly data by date
    result: Dict[date, PointWeather] = {}
    
    # Get unique dates
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
        temps = [hourly["temperature_2m"][i] for i in indices if hourly["temperature_2m"][i] is not None]
        gusts = [hourly["wind_gusts_10m"][i] for i in indices if hourly["wind_gusts_10m"][i] is not None]
        precip = [hourly["precipitation"][i] for i in indices if hourly["precipitation"][i] is not None]
        snowfall_hourly = [hourly["snowfall"][i] for i in indices if hourly["snowfall"][i] is not None]
        
        temp_avg = sum(temps) / len(temps) if temps else None
        gust_max = max(gusts) if gusts else None
        precip_sum = sum(precip) if precip else None
        
        # Snowfall: try daily first, fallback to hourly sum
        snowfall_cm: Optional[float] = None
        snow_depth_cm: Optional[float] = None
        
        # Try daily snowfall_sum (if exists in daily data)
        if "snowfall_sum" in daily and daily["snowfall_sum"]:
            daily_dates = [datetime.fromisoformat(t).date() for t in daily.get("time", [])]
            if d in daily_dates:
                idx = daily_dates.index(d)
                val = daily["snowfall_sum"][idx]
                if val is not None:
                    unit = daily_units.get("snowfall_sum", "cm")
                    snowfall_cm = _convert_to_cm(val, unit)
        
        # Fallback: sum hourly snowfall
        if snowfall_cm is None and snowfall_hourly:
            unit = hourly_units.get("snowfall", "cm")
            snowfall_cm = _convert_to_cm(sum(snowfall_hourly), unit)
        
        # Snow depth from daily
        if "snow_depth_max" in daily and daily["snow_depth_max"]:
            daily_dates = [datetime.fromisoformat(t).date() for t in daily.get("time", [])]
            if d in daily_dates:
                idx = daily_dates.index(d)
                val = daily["snow_depth_max"][idx]
                if val is not None:
                    unit = daily_units.get("snow_depth_max", "m")  # typically in meters
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


def fetch_resort_weather(point_low: Point, point_high: Point, forecast_days: int = 7) -> ResortWeather:
    """Fetch weather for both points of a resort.
    
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
