"""
x402 Weather API — Global weather data for AI agents

Current weather and daily forecasts via x402 micropayments (USDC on Base).

Endpoints:
  GET /weather/current   — Current weather for a city or coordinates
  GET /weather/forecast  — Daily forecast (1-7 days)
  GET /health            — Health check (free, no payment)
"""

import os
import sys
import time

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig, UnpaidResponseResult
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.schemas import Network
from x402.extensions.bazaar import bazaar_resource_server_extension
from x402.server import x402ResourceServer

from weather import geocode, get_current, get_forecast

load_dotenv()

# --- Config ---
EVM_ADDRESS = os.getenv("EVM_ADDRESS")
NETWORK: Network = os.getenv("NETWORK", "eip155:8453")
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


class HealthResponse(BaseModel):
    status: str
    service: str
    network: str


# --- App ---
app = FastAPI(
    title="Weather API",
    description="Instant weather data by city name — no API keys, no geocoding setup, no rate limits. "
    "Current conditions and daily forecasts for any city worldwide in structured JSON, "
    "ready for agent consumption.",
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

# Payment logging — records settlements to shared SQLite DB
from payment_logger import PaymentLogger
_pay_logger = PaymentLogger("weather")
server.on_after_settle(_pay_logger.log_settlement)
server.on_settle_failure(_pay_logger.log_failure)

# Solana support (Dexter market — activated by SOLANA_PAY_TO env var)
SOLANA_PAY_TO = os.getenv("SOLANA_PAY_TO", "")
if SOLANA_PAY_TO:
    from x402.mechanisms.svm.constants import SOLANA_MAINNET_CAIP2
    from x402.mechanisms.svm.exact import ExactSvmServerScheme
    server.register(SOLANA_MAINNET_CAIP2, ExactSvmServerScheme())

INTERNAL_KEY = os.getenv("INTERNAL_KEY", "")

PRICE = "$0.01"
PAYMENT = PaymentOption(scheme="exact", pay_to=EVM_ADDRESS, price=PRICE, network=NETWORK)
ACCEPTS = [PAYMENT]
if SOLANA_PAY_TO:
    ACCEPTS.append(PaymentOption(scheme="exact", pay_to=SOLANA_PAY_TO, price=PRICE, network=SOLANA_MAINNET_CAIP2))


# --- 402 Sample Responses (show agents what they'd get if they paid) ---
_ALTERNATIVES = {
    "mcp_gateway": {
        "info": "Access this and 2300+ x402 APIs via a single MCP server. Payment brokered for you — supports API keys (no wallet), free trial (World ID), or x402.",
        "url": "https://mcp.hugen.tokyo/mcp",
        "transport": "streamable-http",
    },
    "api_key": {
        "info": "Get a free API key with $0.05 credit — covers search and broker calls, no wallet needed",
        "create": "POST https://discovery.hugen.tokyo/keys/create",
        "then": "POST /broker/call with X-API-Key header to call any x402 API",
        "docs": "https://discovery.hugen.tokyo/llms.txt",
    },
    "sdk": {
        "info": "One-line Python access — no wallet, no setup",
        "install": "pip install x402-pay",
        "usage": "import x402_pay; r = x402_pay.get('https://weather.hugen.tokyo/weather/current?city=Tokyo')",
    },
    "intel": {
        "info": "Need deeper analysis? Intel combines 4+ data sources with AI risk verdict in one call ($0.50)",
        "example": "https://intel.hugen.tokyo/intel/token-report?address=0xdac17f958d2ee523a2206206994597c13d831ec7&chain=base",
    },
}


def _sample(example: dict):
    """Factory: returns unpaid_response_body callback with sample data."""
    body = {"_notice": f"Payment required ({PRICE} USDC on Base). Sample response below.", "_alternatives": _ALTERNATIVES, **example}
    def callback(_ctx):
        return UnpaidResponseResult(content_type="application/json", body=body)
    return callback


routes = {
    "GET /weather/current": RouteConfig(
        accepts=ACCEPTS,
        mime_type="application/json",
        description="Instant weather by city name — temperature, feels-like, humidity, wind speed, precipitation, and condition. "
        "Just pass a city name; geocoding, data fetching, and response structuring are handled in one call. "
        "Global coverage updated every 15 minutes. No API keys, no geocoding setup, no rate limits. "
        "Accepts USDC payments on Base and Solana",
        unpaid_response_body=_sample({
            "city": "Tokyo", "country": "Japan",
            "temperature_c": 12.5, "condition": "Partly cloudy",
            "humidity_pct": 65, "wind_speed_kmh": 15.3,
        }),
        extensions={
            "bazaar": {
                "discoverable": True,
                "category": "weather",
                "tags": ["weather", "forecast", "real-time", "geocoding"],
                "info": {
                    "input": {
                        "type": "http",
                        "method": "GET",
                        "queryParams": {"city": "Tokyo"},
                    },
                    "output": {
                        "type": "json",
                        "example": {
                            "city": "Tokyo",
                            "temperature_c": 12.5,
                            "condition": "Partly cloudy",
                            "humidity_pct": 65,
                            "wind_speed_kmh": 15.3,
                        },
                    },
                },
            },
        },
    ),
    "GET /weather/forecast": RouteConfig(
        accepts=ACCEPTS,
        mime_type="application/json",
        description="Daily weather forecast (1-7 days) by city name — max/min temperature, precipitation amount and probability, "
        "peak wind speed per day. Automatic geocoding from city name to coordinates. "
        "Structured JSON ready for immediate use in agent workflows. "
        "No API keys, no coordinate lookups, no setup needed. "
        "Accepts USDC payments on Base and Solana",
        unpaid_response_body=_sample({
            "city": "Tokyo", "country": "Japan",
            "latitude": 35.6895, "longitude": 139.6917,
            "days": [{"date": "2026-03-04", "condition": "Slight rain", "weather_code": 61,
                      "temp_max_c": 15.2, "temp_min_c": 8.1, "precipitation_mm": 12.5,
                      "precipitation_probability_pct": 85, "wind_max_kmh": 22.0}],
        }),
        extensions={
            "bazaar": {
                "discoverable": True,
                "category": "weather",
                "tags": ["weather", "forecast", "7-day", "daily"],
                "info": {
                    "input": {
                        "type": "http",
                        "method": "GET",
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
                        },
                    },
                },
            },
        },
    ),
}

# --- Access Log (analytics) ---
class AccessLogMiddleware:
    """ASGI middleware — logs requests to paid endpoints for analytics."""

    _SKIP = frozenset({"/health", "/.well-known/x402", "/openapi.json", "/llms.txt", "/docs", "/redoc"})

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "/")
        if path in self._SKIP or scope.get("method") == "OPTIONS":
            return await self.app(scope, receive, send)

        t0 = time.monotonic()
        status = 0

        async def _send(msg):
            nonlocal status
            if msg["type"] == "http.response.start":
                status = msg["status"]
            await send(msg)

        try:
            await self.app(scope, receive, _send)
        except Exception:
            status = 500
            raise
        finally:
            ms = (time.monotonic() - t0) * 1000
            hdrs = dict(scope.get("headers", []))
            raw_ip = hdrs.get(b"x-forwarded-for", b"").decode(errors="replace")
            ip = raw_ip.split(",")[0].strip() if raw_ip else "direct"
            ua = hdrs.get(b"user-agent", b"").decode(errors="replace")[:80]
            qs = scope.get("query_string", b"").decode(errors="replace")
            url = f"{path}?{qs}" if qs else path

            ik = hdrs.get(b"x-internal-key", b"").decode(errors="replace")
            if ik and ik == INTERNAL_KEY:
                ch = "mcp-gateway"
            elif hdrs.get(b"x-rapidapi-proxy-secret"):
                ch = "rapidapi"
            elif status == 402:
                ch = "no-pay"
            else:
                ch = "x402"

            print(
                f"[access] {scope.get('method', '?')} {url} {status} "
                f"{ms:.0f}ms from={ip} ch={ch} ua={ua}",
                file=sys.stderr,
            )


# --- Internal bypass (MCP gateway calls with X-Internal-Key) ---
class PaymentWithInternalBypass:
    """Wraps PaymentMiddlewareASGI: skip payment if X-Internal-Key matches."""

    def __init__(self, app_inner, *, routes, server):
        self.raw_app = app_inner
        self.payment_app = PaymentMiddlewareASGI(app_inner, routes=routes, server=server)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and INTERNAL_KEY:
            headers = dict(scope.get("headers", []))
            key = headers.get(b"x-internal-key", b"").decode(errors="replace")
            if key and key == INTERNAL_KEY:
                scope.setdefault("state", {})["_channel"] = "mcp-gateway"
                return await self.raw_app(scope, receive, send)
        return await self.payment_app(scope, receive, send)


app.add_middleware(PaymentWithInternalBypass, routes=routes, server=server)
app.add_middleware(AccessLogMiddleware)


# --- x402 Discovery (for x402scan, RelAI, etc.) ---
@app.get("/.well-known/x402")
async def x402_discovery(request: Request):
    """x402 discovery document — lists all paid endpoints for auto-cataloging."""
    origin = f"{request.url.scheme}://{request.url.netloc}"
    return {
        "version": 1,
        "resources": [
            f"{origin}/weather/current",
            f"{origin}/weather/forecast",
        ],
        "instructions": (
            "# Weather API\n\n"
            "Instant weather data by city name — no API keys, no geocoding setup, no rate limits.\n\n"
            "## Why use this instead of a free weather API?\n"
            "- Free weather APIs require geocoding setup + API key management + response parsing\n"
            "- This API: pass a city name, get structured JSON. One call, one payment, done\n\n"
            "## Endpoints\n"
            "- `GET /weather/current?city=Tokyo` — Current weather\n"
            "- `GET /weather/forecast?city=Tokyo&days=3` — Daily forecast (1-7 days)\n\n"
            "## Pricing\n"
            "All endpoints: $0.01/request (USDC on Base)\n"
        ),
    }


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


@app.get("/llms.txt")
async def llms_txt():
    """Machine-readable API description for LLM agents."""
    content = """\
# Weather API — Instant Weather by City Name

> Pass a city name, get structured weather data. No API keys, no geocoding setup, no rate limits. Current conditions and daily forecasts for any city worldwide. $0.01 per request.

## API Base URL

https://weather.hugen.tokyo

## Authentication

x402 micropayments (USDC on Base, eip155:8453).

## Why This Instead of a Free Weather API?

Free weather APIs require separate geocoding, API key registration, rate limit management, and response parsing. This API handles all of that — pass a city name, get structured JSON in one call.

## Endpoints — $0.01/request

- GET /weather/current?city={name} — Current weather (temperature, humidity, wind, precipitation)
- GET /weather/current?lat={lat}&lon={lon} — Current weather by coordinates
- GET /weather/forecast?city={name}&days={1-7} — Daily forecast
- GET /weather/forecast?lat={lat}&lon={lon}&days={1-7} — Forecast by coordinates
"""
    return Response(content=content, media_type="text/plain; charset=utf-8")


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
