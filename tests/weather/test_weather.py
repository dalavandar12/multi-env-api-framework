"""
Test suite for the Open-Meteo Weather Forecast API.

Parametrized over five representative cities loaded from
test_data/weather/cities.json.  Covers response schema validation, hourly
temperature entry count, and timezone field presence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import allure
import pytest

from src.client import ApiClient
from src.validators import validate_weather_response


def _load_cities() -> list[dict[str, Any]]:
    """Return the list of city fixtures from test_data/weather/cities.json."""
    cities_path: Path = (
        Path(__file__).resolve().parents[2]
        / "test_data"
        / "weather"
        / "cities.json"
    )
    with cities_path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _forecast_params(city: dict[str, Any]) -> dict[str, Any]:
    """Build the query-parameter dict for the /forecast endpoint."""
    return {
        "latitude": city["latitude"],
        "longitude": city["longitude"],
        "hourly": "temperature_2m",
        "timezone": "auto",
    }


@allure.feature("Weather API")
@pytest.mark.weather
@pytest.mark.smoke
class TestWeather:
    """Tests for the Open-Meteo v1 forecast endpoint."""

    @allure.story("Forecast temperature range validation")
    @pytest.mark.parametrize("city", _load_cities(), ids=lambda c: c["name"])
    def test_forecast_temperature_range(
        self,
        api_client: ApiClient,
        env_config: dict[str, Any],
        city: dict[str, Any],
    ) -> None:
        """GET /forecast must return a response whose hourly temperatures all
        fall within the physically plausible range defined in env_config."""
        data: dict[str, Any] = api_client.get("/forecast", params=_forecast_params(city))

        validate_weather_response(
            data,
            temp_min=float(env_config["temperature_min_c"]),
            temp_max=float(env_config["temperature_max_c"]),
        )

    @allure.story("Forecast hourly entry count")
    @pytest.mark.parametrize("city", _load_cities(), ids=lambda c: c["name"])
    def test_forecast_hourly_entry_count(
        self, api_client: ApiClient, env_config: dict[str, Any], city: dict[str, Any]
    ) -> None:
        """GET /forecast must return at least min_results_count hourly
        temperature entries."""
        data: dict[str, Any] = api_client.get("/forecast", params=_forecast_params(city))

        entry_count: int = len(data["hourly"]["temperature_2m"])
        assert entry_count > env_config["min_results_count"], (
            f"Expected more than {env_config['min_results_count']} hourly entries "
            f"for {city['name']}, got {entry_count}"
        )

    @allure.story("Forecast timezone field presence")
    @pytest.mark.parametrize("city", _load_cities(), ids=lambda c: c["name"])
    def test_forecast_timezone_present(
        self, api_client: ApiClient, city: dict[str, Any]
    ) -> None:
        """GET /forecast must include a non-empty 'timezone' field in the
        response body."""
        data: dict[str, Any] = api_client.get("/forecast", params=_forecast_params(city))

        assert "timezone" in data, (
            f"'timezone' key missing from forecast response for {city['name']}"
        )
        assert isinstance(data["timezone"], str) and data["timezone"], (
            f"'timezone' must be a non-empty string for {city['name']}, "
            f"got {data['timezone']!r}"
        )
