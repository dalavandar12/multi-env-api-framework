"""
Cross-environment workflow tests.

Flow (single test):
  1) GET Countries /name/{country} and validate country payload.
  2) Use case coordinates to GET Weather /forecast and validate the response.

Run only these tests:
  pytest --env cross-env tests/test_cross-env.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import allure
import pytest

from src.client import ApiClient
from src.validators import validate_country_schema, validate_weather_response

LOG = logging.getLogger(__name__)

pytestmark = [
    pytest.MarkDecorator(pytest.Mark("cross-env", (), {})),
    pytest.mark.smoke,
]


def _load_cases() -> list[dict[str, Any]]:
    """Load workflow cases from test_data/cross-env.json."""
    cases_path = Path(__file__).resolve().parents[1] / "test_data" / "cross-env.json"
    with cases_path.open(encoding="utf-8") as fh:
        return list(json.load(fh))


@allure.feature("Cross-environment workflows")
class TestCrossEnvCountryWeather:
    """Countries API output feeds Weather API verification in one flow."""

    @allure.story("Country lookup feeds weather forecast")
    @pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["country_name"])
    def test_country_to_weather_forecast(
        self,
        countries_api_client: ApiClient,
        weather_api_client: ApiClient,
        weather_env_config: dict[str, Any],
        case: dict[str, Any],
    ) -> None:
        """Country capital and coordinates should support a valid weather forecast."""
        LOG.info("[%s] cross-env workflow for %s", case["country_name"], case["country_name"])

        countries_result = countries_api_client.get(f"/name/{case['country_name']}")
        country = countries_result[0]
        validate_country_schema(country)

        capitals = country.get("capital") or []
        assert case["expected_capital"] in capitals, (
            f"{case['country_name']} capital mismatch: expected {case['expected_capital']}, "
            f"got {capitals}"
        )

        weather_result = weather_api_client.get(
            "/forecast",
            params={
                "latitude": case["latitude"],
                "longitude": case["longitude"],
                "hourly": "temperature_2m",
                "timezone": "auto",
            },
        )
        validate_weather_response(
            weather_result,
            temp_min=float(weather_env_config["temperature_min_c"]),
            temp_max=float(weather_env_config["temperature_max_c"]),
        )
