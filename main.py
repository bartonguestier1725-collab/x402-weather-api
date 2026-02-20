"""
x402 Weather API — Global weather data for AI agents

Current weather and daily forecasts powered by Open-Meteo (CC BY 4.0),
monetized via x402 micropayments (USDC on Base).

Endpoints:
  GET /weather/current   — Current weather for a city or coordinates
  GET /weather/forecast  — Daily forecast (1-7 days)
  GET /health            — Health check (free, no payment)
"""

import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.schemas import Network
from x402.extensions.bazaar import bazaar_resource_server_extension
from x402.server import x402ResourceServer

from weather import geocode, get_current, get_forecast

load_dotenv()

# --- Config ---
EVM_ADDRESS = os.getenv("EVM_ADDRESS")
NETWORK: Network = os.getenv("NETWORK", "eip155:84532")
FACILITATOR_URL = os.getenv("FACILITATOR_URL", "https://x402.org/facilitator")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "4022"))

if not EVM_ADDRESS:
    import warnings

    warnings.warn("EVM_ADDRESS not set — payment middleware will be non-functional", stacklevel=1)
    EVM_ADDRESS = "0x0000000000000000000000000000000000000000"


# --- Response schemas ---
class CurrentWeatherResponse(BaseModel):
    city: str
    country: str
    latitude: float
    longitude: float
    temperature_c: float
    feels_like_c: float
    humidity_pct: int
    wind_speed_kmh: float
    wind_direction_deg: int
    precipitation_mm: float
    condition: str
    weather_code: int
    observation_time: str
    attribution: str = "Weather data by Open-Meteo.com"


class ForecastDay(BaseModel):
    date: str
    condition: str
    weather_code: int
    temp_max_c: float
    temp_min_c: float
    precipitation_mm: float
    precipitation_probability_pct: int
    wind_max_kmh: float


class ForecastResponse(BaseModel):
    city: str
    country: str
    latitude: float
    longitude: float
    days: list[ForecastDay]
    attribution: str = "Weather data by Open-Meteo.com"


class HealthResponse(BaseModel):
    status: str
    service: str
    network: str


# --- App ---
app = FastAPI(
    title="Weather API",
    description="Global weather data for AI agents. "
    "Current conditions and daily forecasts for any city worldwide, "
    "powered by Open-Meteo and monetized via x402 micropayments (USDC on Base).",
    version="0.1.0",
)

# --- x402 Payment Middleware ---
CDP_API_KEY_ID = os.getenv("CDP_API_KEY_ID")
CDP_API_KEY_SECRET = os.getenv("CDP_API_KEY_SECRET")

if CDP_API_KEY_ID and CDP_API_KEY_SECRET:
    from cdp.x402 import create_facilitator_config as create_cdp_config

    facilitator = HTTPFacilitatorClient(create_cdp_config())
else:
    facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))

server = x402ResourceServer(facilitator)
server.register(NETWORK, ExactEvmServerScheme())
server.register_extension(bazaar_resource_server_extension)

PRICE = "$0.001"
PAYMENT = PaymentOption(scheme="exact", pay_to=EVM_ADDRESS, price=PRICE, network=NETWORK)

routes = {
    "GET /weather/current": RouteConfig(
        accepts=[PAYMENT],
        mime_type="application/json",
        description="Get current weather conditions for any city worldwide. "
        "Returns temperature, humidity, wind, precipitation, and condition description. "
        "Specify city name (geocoded automatically) or latitude/longitude coordinates.",
        extensions={
            "bazaar": {
                "info": {
                    "input": {
                        "type": "http",
                        "queryParams": {"city": "Tokyo"},
                    },
                    "output": {
                        "type": "json",
                        "example": {
                            "city": "Tokyo",
                            "country": "Japan",
                            "latitude": 35.6895,
                            "longitude": 139.6917,
                            "temperature_c": 12.5,
                            "feels_like_c": 10.2,
                            "humidity_pct": 65,
                            "wind_speed_kmh": 15.3,
                            "wind_direction_deg": 270,
                            "precipitation_mm": 0.0,
                            "condition": "Partly cloudy",
                            "weather_code": 2,
                            "observation_time": "2026-02-20T15:00",
                            "attribution": "Weather data by Open-Meteo.com",
                        },
                    },
                },
            },
        },
    ),
    "GET /weather/forecast": RouteConfig(
        accepts=[PAYMENT],
        mime_type="application/json",
        description="Get daily weather forecast (1-7 days) for any city worldwide. "
        "Returns max/min temperature, precipitation probability, and wind speed per day. "
        "Specify city name or latitude/longitude coordinates.",
        extensions={
            "bazaar": {
                "info": {
                    "input": {
                        "type": "http",
                        "queryParams": {"city": "Tokyo", "days": "3"},
                    },
                    "output": {
                        "type": "json",
                        "example": {
                            "city": "Tokyo",
                            "country": "Japan",
                            "latitude": 35.6895,
                            "longitude": 139.6917,
                            "days": [
                                {
                                    "date": "2026-02-21",
                                    "condition": "Slight rain",
                                    "weather_code": 61,
                                    "temp_max_c": 15.2,
                                    "temp_min_c": 8.1,
                                    "precipitation_mm": 12.5,
                                    "precipitation_probability_pct": 85,
                                    "wind_max_kmh": 22.0,
                                },
                            ],
                            "attribution": "Weather data by Open-Meteo.com",
                        },
                    },
                },
            },
        },
    ),
}

app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)


# --- Helper ---
async def _resolve_location(
    city: str | None, lat: float | None, lon: float | None
) -> tuple[str, str, float, float]:
    """Resolve city/lat/lon params to (city_name, country, lat, lon)."""
    if lat is not None and lon is not None:
        return (city or f"{lat},{lon}"), "", lat, lon
    if city:
        geo = await geocode(city)
        return geo["name"], geo["country"], geo["latitude"], geo["longitude"]
    raise HTTPException(400, "Provide 'city' or both 'lat' and 'lon' parameters")


# --- Routes ---
@app.get("/health")
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok", service="weather-api", network=NETWORK)


@app.get("/weather/current")
async def weather_current(
    city: str | None = Query(default=None, description="City name (e.g., Tokyo, London, New York)"),
    lat: float | None = Query(default=None, ge=-90, le=90, description="Latitude (-90 to 90)"),
    lon: float | None = Query(default=None, ge=-180, le=180, description="Longitude (-180 to 180)"),
) -> CurrentWeatherResponse:
    city_name, country, latitude, longitude = await _resolve_location(city, lat, lon)
    data = await get_current(latitude, longitude)
    return CurrentWeatherResponse(
        city=city_name,
        country=country,
        latitude=latitude,
        longitude=longitude,
        **data,
    )


@app.get("/weather/forecast")
async def weather_forecast(
    city: str | None = Query(default=None, description="City name (e.g., Tokyo, London, New York)"),
    lat: float | None = Query(default=None, ge=-90, le=90, description="Latitude (-90 to 90)"),
    lon: float | None = Query(default=None, ge=-180, le=180, description="Longitude (-180 to 180)"),
    days: int = Query(default=3, ge=1, le=7, description="Number of forecast days (1-7)"),
) -> ForecastResponse:
    city_name, country, latitude, longitude = await _resolve_location(city, lat, lon)
    forecast_days = await get_forecast(latitude, longitude, days)
    return ForecastResponse(
        city=city_name,
        country=country,
        latitude=latitude,
        longitude=longitude,
        days=forecast_days,
    )


if __name__ == "__main__":
    if not os.getenv("EVM_ADDRESS"):
        raise SystemExit("ERROR: EVM_ADDRESS not set. Configure .env before starting the server.")

    import asyncio
    import asyncio.runners

    # cdp-sdk → web3 → nest_asyncio patches asyncio.run without loop_factory support.
    # Restore the stdlib version BEFORE importing uvicorn (which captures it at import time).
    asyncio.run = asyncio.runners.run

    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
