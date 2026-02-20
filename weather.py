"""
Open-Meteo weather data module.

Provides geocoding, current weather, and daily forecast via the free
Open-Meteo API (no API key required, CC BY 4.0).

Public functions:
  geocode(city)              → {"name", "country", "latitude", "longitude"}
  get_current(lat, lon)      → current weather dict
  get_forecast(lat, lon, days) → daily forecast list
"""

import httpx
from fastapi import HTTPException

# Reuse connection pool across requests
_client = httpx.AsyncClient(timeout=10.0)

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

CURRENT_VARS = (
    "temperature_2m,relative_humidity_2m,apparent_temperature,"
    "weather_code,wind_speed_10m,wind_direction_10m,precipitation"
)
DAILY_VARS = (
    "weather_code,temperature_2m_max,temperature_2m_min,"
    "precipitation_sum,precipitation_probability_max,wind_speed_10m_max"
)

# WMO Weather Interpretation Codes (WMO 4677)
WMO_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def describe_weather_code(code: int) -> str:
    """Convert WMO weather code to human-readable English text."""
    return WMO_CODES.get(code, f"Unknown ({code})")


async def geocode(city: str) -> dict:
    """Geocode a city name to coordinates.

    Returns: {"name": str, "country": str, "latitude": float, "longitude": float}
    Raises: HTTPException 404 if city not found, 502/504 on upstream errors.
    """
    try:
        resp = await _client.get(
            GEOCODING_URL,
            params={"name": city, "count": 1, "language": "en", "format": "json"},
        )
    except httpx.TimeoutException:
        raise HTTPException(504, "Weather data source timeout")
    except httpx.HTTPError:
        raise HTTPException(502, "Weather data source unavailable")

    if resp.status_code != 200:
        raise HTTPException(502, "Weather data source unavailable")

    data = resp.json()
    results = data.get("results")
    if not results:
        raise HTTPException(404, f"City not found: {city}")

    hit = results[0]
    return {
        "name": hit["name"],
        "country": hit.get("country", ""),
        "latitude": hit["latitude"],
        "longitude": hit["longitude"],
    }


async def get_current(lat: float, lon: float) -> dict:
    """Fetch current weather for given coordinates.

    Returns dict with temperature, humidity, wind, precipitation, etc.
    """
    try:
        resp = await _client.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": CURRENT_VARS,
            },
        )
    except httpx.TimeoutException:
        raise HTTPException(504, "Weather data source timeout")
    except httpx.HTTPError:
        raise HTTPException(502, "Weather data source unavailable")

    if resp.status_code != 200:
        raise HTTPException(502, "Weather data source unavailable")

    data = resp.json()
    try:
        cur = data["current"]
        code = cur["weather_code"]
        return {
            "temperature_c": cur["temperature_2m"],
            "feels_like_c": cur["apparent_temperature"],
            "humidity_pct": cur["relative_humidity_2m"],
            "wind_speed_kmh": cur["wind_speed_10m"],
            "wind_direction_deg": cur["wind_direction_10m"],
            "precipitation_mm": cur["precipitation"],
            "condition": describe_weather_code(code),
            "weather_code": code,
            "observation_time": cur["time"],
        }
    except (KeyError, TypeError, IndexError) as exc:
        raise HTTPException(502, f"Unexpected weather data format: {exc}")


async def get_forecast(lat: float, lon: float, days: int) -> list[dict]:
    """Fetch daily forecast for given coordinates.

    Args:
        days: Number of forecast days (1-7).

    Returns list of daily forecast dicts.
    """
    try:
        resp = await _client.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": DAILY_VARS,
                "forecast_days": days,
            },
        )
    except httpx.TimeoutException:
        raise HTTPException(504, "Weather data source timeout")
    except httpx.HTTPError:
        raise HTTPException(502, "Weather data source unavailable")

    if resp.status_code != 200:
        raise HTTPException(502, "Weather data source unavailable")

    data = resp.json()
    try:
        daily = data["daily"]
        result = []
        for i in range(len(daily["time"])):
            code = daily["weather_code"][i]
            result.append(
                {
                    "date": daily["time"][i],
                    "condition": describe_weather_code(code),
                    "weather_code": code,
                    "temp_max_c": daily["temperature_2m_max"][i],
                    "temp_min_c": daily["temperature_2m_min"][i],
                    "precipitation_mm": daily["precipitation_sum"][i],
                    "precipitation_probability_pct": daily["precipitation_probability_max"][i],
                    "wind_max_kmh": daily["wind_speed_10m_max"][i],
                }
            )
        return result
    except (KeyError, TypeError, IndexError) as exc:
        raise HTTPException(502, f"Unexpected weather data format: {exc}")
