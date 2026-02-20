"""Unit tests for weather.py — Open-Meteo logic."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from weather import (
    WMO_CODES,
    describe_weather_code,
    geocode,
    get_current,
    get_forecast,
)


# --- WMO code mapping ---


class TestWMOCodes:
    def test_all_known_codes_have_descriptions(self):
        for code, desc in WMO_CODES.items():
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_clear_sky(self):
        assert describe_weather_code(0) == "Clear sky"

    def test_thunderstorm(self):
        assert describe_weather_code(95) == "Thunderstorm"

    def test_unknown_code_fallback(self):
        result = describe_weather_code(999)
        assert "Unknown" in result
        assert "999" in result

    @pytest.mark.parametrize(
        "code,expected",
        [
            (1, "Mainly clear"),
            (2, "Partly cloudy"),
            (3, "Overcast"),
            (45, "Fog"),
            (61, "Slight rain"),
            (65, "Heavy rain"),
            (71, "Slight snow fall"),
            (75, "Heavy snow fall"),
            (80, "Slight rain showers"),
            (82, "Violent rain showers"),
        ],
    )
    def test_common_codes(self, code, expected):
        assert describe_weather_code(code) == expected


# --- Geocode ---


def _mock_response(status_code: int, json_data: dict) -> httpx.Response:
    """Create a mock httpx.Response."""
    resp = httpx.Response(status_code, json=json_data)
    return resp


class TestGeocode:
    @pytest.fixture(autouse=True)
    def _patch_client(self):
        self.mock_get = AsyncMock()
        with patch("weather._client") as mock_client:
            mock_client.get = self.mock_get
            yield

    async def test_geocode_success(self):
        self.mock_get.return_value = _mock_response(
            200,
            {
                "results": [
                    {
                        "name": "Tokyo",
                        "country": "Japan",
                        "latitude": 35.6895,
                        "longitude": 139.6917,
                    }
                ]
            },
        )
        result = await geocode("Tokyo")
        assert result["name"] == "Tokyo"
        assert result["country"] == "Japan"
        assert result["latitude"] == 35.6895
        assert result["longitude"] == 139.6917

    async def test_geocode_not_found(self):
        self.mock_get.return_value = _mock_response(200, {"results": None})
        with pytest.raises(Exception) as exc_info:
            await geocode("NonexistentCity123")
        assert exc_info.value.status_code == 404

    async def test_geocode_no_results_key(self):
        self.mock_get.return_value = _mock_response(200, {})
        with pytest.raises(Exception) as exc_info:
            await geocode("Empty")
        assert exc_info.value.status_code == 404

    async def test_geocode_upstream_error(self):
        self.mock_get.return_value = _mock_response(500, {})
        with pytest.raises(Exception) as exc_info:
            await geocode("Tokyo")
        assert exc_info.value.status_code == 502

    async def test_geocode_timeout(self):
        self.mock_get.side_effect = httpx.TimeoutException("timeout")
        with pytest.raises(Exception) as exc_info:
            await geocode("Tokyo")
        assert exc_info.value.status_code == 504

    async def test_geocode_connection_error(self):
        self.mock_get.side_effect = httpx.ConnectError("connection refused")
        with pytest.raises(Exception) as exc_info:
            await geocode("Tokyo")
        assert exc_info.value.status_code == 502


# --- Current Weather ---


class TestGetCurrent:
    @pytest.fixture(autouse=True)
    def _patch_client(self):
        self.mock_get = AsyncMock()
        with patch("weather._client") as mock_client:
            mock_client.get = self.mock_get
            yield

    async def test_current_success(self):
        self.mock_get.return_value = _mock_response(
            200,
            {
                "current": {
                    "temperature_2m": 12.5,
                    "apparent_temperature": 10.2,
                    "relative_humidity_2m": 65,
                    "wind_speed_10m": 15.3,
                    "wind_direction_10m": 270,
                    "precipitation": 0.0,
                    "weather_code": 2,
                    "time": "2026-02-20T15:00",
                }
            },
        )
        result = await get_current(35.69, 139.69)
        assert result["temperature_c"] == 12.5
        assert result["feels_like_c"] == 10.2
        assert result["humidity_pct"] == 65
        assert result["condition"] == "Partly cloudy"
        assert result["weather_code"] == 2
        assert result["observation_time"] == "2026-02-20T15:00"

    async def test_current_upstream_error(self):
        self.mock_get.return_value = _mock_response(500, {})
        with pytest.raises(Exception) as exc_info:
            await get_current(35.69, 139.69)
        assert exc_info.value.status_code == 502

    async def test_current_timeout(self):
        self.mock_get.side_effect = httpx.TimeoutException("timeout")
        with pytest.raises(Exception) as exc_info:
            await get_current(35.69, 139.69)
        assert exc_info.value.status_code == 504

    async def test_current_malformed_response(self):
        """200 but missing expected keys → 502 (not KeyError/500)."""
        self.mock_get.return_value = _mock_response(200, {"error": True, "reason": "bad"})
        with pytest.raises(Exception) as exc_info:
            await get_current(35.69, 139.69)
        assert exc_info.value.status_code == 502


# --- Forecast ---


class TestGetForecast:
    @pytest.fixture(autouse=True)
    def _patch_client(self):
        self.mock_get = AsyncMock()
        with patch("weather._client") as mock_client:
            mock_client.get = self.mock_get
            yield

    async def test_forecast_success(self):
        self.mock_get.return_value = _mock_response(
            200,
            {
                "daily": {
                    "time": ["2026-02-21", "2026-02-22", "2026-02-23"],
                    "weather_code": [61, 0, 2],
                    "temperature_2m_max": [15.2, 18.0, 16.5],
                    "temperature_2m_min": [8.1, 9.5, 7.8],
                    "precipitation_sum": [12.5, 0.0, 0.2],
                    "precipitation_probability_max": [85, 5, 20],
                    "wind_speed_10m_max": [22.0, 10.0, 14.5],
                }
            },
        )
        result = await get_forecast(35.69, 139.69, 3)
        assert len(result) == 3
        assert result[0]["date"] == "2026-02-21"
        assert result[0]["condition"] == "Slight rain"
        assert result[0]["temp_max_c"] == 15.2
        assert result[0]["precipitation_probability_pct"] == 85
        assert result[1]["condition"] == "Clear sky"
        assert result[2]["condition"] == "Partly cloudy"

    async def test_forecast_upstream_error(self):
        self.mock_get.return_value = _mock_response(500, {})
        with pytest.raises(Exception) as exc_info:
            await get_forecast(35.69, 139.69, 3)
        assert exc_info.value.status_code == 502

    async def test_forecast_malformed_response(self):
        """200 but missing expected keys → 502 (not KeyError/500)."""
        self.mock_get.return_value = _mock_response(200, {"error": True, "reason": "bad"})
        with pytest.raises(Exception) as exc_info:
            await get_forecast(35.69, 139.69, 3)
        assert exc_info.value.status_code == 502
