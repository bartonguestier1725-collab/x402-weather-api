"""Endpoint tests — verify x402 middleware returns 402 for paid routes."""

import pytest
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
def _mock_weather():
    """Mock weather module to avoid real HTTP calls during API tests."""
    with (
        patch("main.geocode", new_callable=AsyncMock) as mock_geo,
        patch("main.get_current", new_callable=AsyncMock) as mock_cur,
        patch("main.get_forecast", new_callable=AsyncMock) as mock_fc,
    ):
        mock_geo.return_value = {
            "name": "Tokyo",
            "country": "Japan",
            "latitude": 35.6895,
            "longitude": 139.6917,
        }
        mock_cur.return_value = {
            "temperature_c": 12.5,
            "feels_like_c": 10.2,
            "humidity_pct": 65,
            "wind_speed_kmh": 15.3,
            "wind_direction_deg": 270,
            "precipitation_mm": 0.0,
            "condition": "Partly cloudy",
            "weather_code": 2,
            "observation_time": "2026-02-20T15:00",
        }
        mock_fc.return_value = [
            {
                "date": "2026-02-21",
                "condition": "Slight rain",
                "weather_code": 61,
                "temp_max_c": 15.2,
                "temp_min_c": 8.1,
                "precipitation_mm": 12.5,
                "precipitation_probability_pct": 85,
                "wind_max_kmh": 22.0,
            }
        ]
        yield


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealthEndpoint:
    async def test_health_returns_200(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "weather-api"
        assert "network" in data


@pytest.mark.integration
class TestPaidEndpoints:
    """These tests verify x402 middleware returns 402.

    Requires valid .env with EVM_ADDRESS and CDP keys.
    """

    async def test_current_returns_402(self, client, _mock_weather):
        resp = await client.get("/weather/current", params={"city": "Tokyo"})
        assert resp.status_code == 402

    async def test_forecast_returns_402(self, client, _mock_weather):
        resp = await client.get(
            "/weather/forecast", params={"city": "Tokyo", "days": 3}
        )
        assert resp.status_code == 402
