"""
Test suite for the REST Countries API.

All test inputs (region names, country names, field projections) and the
region count threshold come from test_data/countries/countries.json and
config/environments.yaml respectively — no inline literals.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import allure
import pytest
import pytest_check as check

from src.client import ApiClient
from src.validators import validate_country_schema, validate_population_positive


def _load_data() -> dict[str, Any]:
    """Return parametrize fixtures from test_data/countries/countries.json."""
    data_path: Path = (
        Path(__file__).resolve().parents[2]
        / "test_data"
        / "countries"
        / "countries.json"
    )
    with data_path.open(encoding="utf-8") as fh:
        return dict(json.load(fh))


_DATA = _load_data()


@allure.feature("Countries API")
@pytest.mark.countries
@pytest.mark.smoke
class TestCountries:
    """Tests for the REST Countries v3.1 API."""

    @allure.story("Region count threshold")
    @pytest.mark.parametrize("region", _DATA["regions"], ids=lambda r: r["name"])
    def test_region_country_count(
        self,
        api_client: ApiClient,
        env_config: dict[str, Any],
        region: dict[str, Any],
    ) -> None:
        """GET /region/{name} must return at least region_min_country_count results."""
        results: list[dict[str, Any]] = api_client.get(f"/region/{region['name']}")
        threshold: int = int(env_config["region_min_country_count"])
        assert len(results) > threshold, (
            f"Expected more than {threshold} {region['name']} countries, "
            f"got {len(results)}"
        )
        assert len(results) >= env_config["min_results_count"], (
            f"Result count {len(results)} is below min_results_count "
            f"{env_config['min_results_count']}"
        )

    @allure.story("Country schema validation")
    @pytest.mark.parametrize("country", _DATA["name_lookups"], ids=lambda c: c["name"])
    def test_country_schema(
        self, api_client: ApiClient, country: dict[str, Any]
    ) -> None:
        """GET /name/{name} must return a result whose first entry satisfies
        the required country schema (name, capital, population, currencies, languages)."""
        results: list[dict[str, Any]] = api_client.get(f"/name/{country['name']}")
        validate_country_schema(results[0])

    @allure.story("All countries population integrity")
    @pytest.mark.parametrize(
        "projection", _DATA["all_field_projections"], ids=lambda p: p["fields"]
    )
    def test_all_countries_population(
        self, api_client: ApiClient, projection: dict[str, Any]
    ) -> None:
        """GET /all with the given field projection must return every country
        with a non-negative population.  All failures are accumulated via
        pytest_check so the full picture is visible in a single run."""
        results: list[dict[str, Any]] = api_client.get(
            "/all", params={"fields": projection["fields"]}
        )
        for country in results:
            with check.check:
                validate_population_positive(country)

    @allure.story("Cross-reference: name lookup ↔ region listing")
    @pytest.mark.parametrize("country", _DATA["name_lookups"], ids=lambda c: c["name"])
    @pytest.mark.parametrize("region", _DATA["regions"], ids=lambda r: r["name"])
    def test_cross_reference(
        self,
        api_client: ApiClient,
        country: dict[str, Any],
        region: dict[str, Any],
    ) -> None:
        """The country returned by GET /name/{name} must also appear in the
        list returned by GET /region/{region}, matched on name.common."""
        country_results: list[dict[str, Any]] = api_client.get(f"/name/{country['name']}")
        country_common_name: str = country_results[0]["name"]["common"]

        region_results: list[dict[str, Any]] = api_client.get(f"/region/{region['name']}")
        region_common_names: list[str] = [
            item["name"]["common"] for item in region_results
        ]

        assert country_common_name in region_common_names, (
            f"'{country_common_name}' not found in {region['name']} region results"
        )
