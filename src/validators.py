"""
Response validators for all API domains.

Per framework-rules: all validation logic lives here — never inline in test files.
"""
from typing import Any

COUNTRY_REQUIRED_FIELDS = ("name", "capital", "population", "currencies", "languages")


def validate_country_schema(country: dict[str, Any]) -> None:
    """Assert all required top-level fields are present in a country object."""
    missing = [f for f in COUNTRY_REQUIRED_FIELDS if f not in country]
    assert not missing, (
        f"Country response missing required fields: {missing}. "
        f"Got keys: {list(country.keys())}"
    )


def validate_population_positive(country: dict[str, Any]) -> None:
    """Assert population is a non-negative integer for a country object.

    Uses >= 0 to accommodate legitimately uninhabited territories (e.g.
    Bouvet Island, South Georgia) that the REST Countries API reports as
    population=0.  The intent is to verify the field is present and numeric,
    not to exclude uninhabited places.
    """
    name = country.get("name", {})
    common_name = name.get("common", "<unknown>") if isinstance(name, dict) else str(name)
    population = country.get("population")
    assert isinstance(population, (int, float)) and population >= 0, (
        f"Country '{common_name}' has invalid population: {population!r}"
    )


def validate_weather_response(
    data: dict[str, Any], *, temp_min: float, temp_max: float
) -> None:
    """Assert the forecast response has timezone, non-empty hourly temperatures.

    Temperature range is supplied by the caller (from env_config). The validator
    holds no environment-specific thresholds.
    """
    assert "timezone" in data, (
        f"Missing 'timezone' in weather response. Got keys: {list(data.keys())}"
    )
    assert data["timezone"], "Field 'timezone' is present but empty"

    assert "hourly" in data, (
        f"Missing 'hourly' in weather response. Got keys: {list(data.keys())}"
    )
    temps: list[float | None] = data["hourly"].get("temperature_2m", [])
    assert len(temps) > 0, "Hourly temperature list is empty"

    for temp in temps:
        if temp is not None:
            assert temp_min <= temp <= temp_max, (
                f"Temperature {temp}°C is outside valid range [{temp_min}, {temp_max}]"
            )

# === auto-generated validators (DO NOT EDIT) ===


def validate_countries_schema(data: dict[str, Any]) -> None:
    """Validates a single country object returned by REST Countries v3.1"""
    assert isinstance(data, dict), f"data must be dict, got {type(data).__name__}"
    for _required in ('name', 'capital', 'population', 'currencies', 'languages',):
        assert _required in data, f"missing required field: data.{_required}"
    assert isinstance(data['name'], dict), f"data['name'] must be dict, got {type(data['name']).__name__}"
    for _required in ('common', 'official',):
        assert _required in data['name'], f"missing required field: data['name'].{_required}"
    assert isinstance(data['name']['common'], str), "data['name']['common'] must be str"
    assert len(data['name']['common']) > 0, "data['name']['common'] must be non-empty string"
    assert isinstance(data['name']['official'], str), "data['name']['official'] must be str"
    assert len(data['name']['official']) > 0, "data['name']['official'] must be non-empty string"
    assert isinstance(data['capital'], list), f"data['capital'] must be list, got {type(data['capital']).__name__}"
    assert len(data['capital']) > 0, "data['capital'] must be non-empty"
    for _item in data['capital']:
        assert isinstance(_item, str), "_item must be str"
    assert isinstance(data['population'], int), "data['population'] must be int"
    assert data['population'] >= 0, "data['population'] must be >= 0"
    assert isinstance(data['currencies'], dict), f"data['currencies'] must be dict, got {type(data['currencies']).__name__}"
    assert isinstance(data['languages'], dict), f"data['languages'] must be dict, got {type(data['languages']).__name__}"
    if 'region' in data:
        assert isinstance(data['region'], str), "data['region'] must be str"
    if 'subregion' in data:
        assert isinstance(data['subregion'], str), "data['subregion'] must be str"
    if 'latlng' in data:
        assert isinstance(data['latlng'], list), f"data['latlng'] must be list, got {type(data['latlng']).__name__}"
        assert len(data['latlng']) >= 2, "data['latlng'] must have at least 2 items"
        assert len(data['latlng']) <= 2, "data['latlng'] must have at most 2 items"
        for _item in data['latlng']:
            assert isinstance(_item, (int, float)), "_item must be number"
    if 'independent' in data:
        assert isinstance(data['independent'], bool), "data['independent'] must be bool"


def validate_weather_schema(data: dict[str, Any]) -> None:
    """Validates an Open-Meteo /v1/forecast response object"""
    assert isinstance(data, dict), f"data must be dict, got {type(data).__name__}"
    for _required in ('latitude', 'longitude', 'timezone', 'hourly',):
        assert _required in data, f"missing required field: data.{_required}"
    assert isinstance(data['latitude'], (int, float)), "data['latitude'] must be number"
    assert data['latitude'] >= -90, "data['latitude'] must be >= -90"
    assert data['latitude'] <= 90, "data['latitude'] must be <= 90"
    assert isinstance(data['longitude'], (int, float)), "data['longitude'] must be number"
    assert data['longitude'] >= -180, "data['longitude'] must be >= -180"
    assert data['longitude'] <= 180, "data['longitude'] must be <= 180"
    if 'elevation' in data:
        assert isinstance(data['elevation'], (int, float)), "data['elevation'] must be number"
    if 'generationtime_ms' in data:
        assert isinstance(data['generationtime_ms'], (int, float)), "data['generationtime_ms'] must be number"
        assert data['generationtime_ms'] >= 0, "data['generationtime_ms'] must be >= 0"
    if 'utc_offset_seconds' in data:
        assert isinstance(data['utc_offset_seconds'], int), "data['utc_offset_seconds'] must be int"
    assert isinstance(data['timezone'], str), "data['timezone'] must be str"
    assert len(data['timezone']) > 0, "data['timezone'] must be non-empty string"
    if 'timezone_abbreviation' in data:
        assert isinstance(data['timezone_abbreviation'], str), "data['timezone_abbreviation'] must be str"
    assert isinstance(data['hourly'], dict), f"data['hourly'] must be dict, got {type(data['hourly']).__name__}"
    for _required in ('time', 'temperature_2m',):
        assert _required in data['hourly'], f"missing required field: data['hourly'].{_required}"
    assert isinstance(data['hourly']['time'], list), f"data['hourly']['time'] must be list, got {type(data['hourly']['time']).__name__}"
    assert len(data['hourly']['time']) > 0, "data['hourly']['time'] must be non-empty"
    for _item in data['hourly']['time']:
        assert isinstance(_item, str), "_item must be str"
    assert isinstance(data['hourly']['temperature_2m'], list), f"data['hourly']['temperature_2m'] must be list, got {type(data['hourly']['temperature_2m']).__name__}"
    assert len(data['hourly']['temperature_2m']) > 0, "data['hourly']['temperature_2m'] must be non-empty"
    for _item in data['hourly']['temperature_2m']:
        assert _item is None or isinstance(_item, (int, float)), "_item must be number or null"
    if 'hourly_units' in data:
        assert isinstance(data['hourly_units'], dict), f"data['hourly_units'] must be dict, got {type(data['hourly_units']).__name__}"
# === end auto-generated ===
