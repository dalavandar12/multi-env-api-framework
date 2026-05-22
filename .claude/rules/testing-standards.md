# Testing Standards

These rules apply to all test code in this framework. They reference actual file paths and
patterns used throughout the project.

---

## 1. Parametrize from JSON — Never Inline Test Data

All test data lives in `test_data/` as JSON files (e.g., `test_data/weather/cities.json`).
Use `@pytest.mark.parametrize` loaded from JSON at module level — never hardcode values
directly in test functions or class bodies.

```python
# CORRECT
import json, pathlib

CITIES = json.loads(pathlib.Path("test_data/weather/cities.json").read_text())

@pytest.mark.parametrize("city", CITIES)
def test_city(city, api_client, env_config): ...

# WRONG — do not do this
@pytest.mark.parametrize("city", ["Paris", "Tokyo"])
def test_city(...): ...
```

---

## 2. Schema Validation Required for Every Endpoint

Every API endpoint under test must have at least one dedicated schema validation test that
calls a validator from `src/validators.py`. Do not write ad-hoc `assert "field" in response`
checks in test bodies; put that logic in `validate_country_schema` or
`validate_weather_response` (or a new validator function added to `src/validators.py`).

```python
from src.validators import validate_country_schema

def test_country_schema(api_client, env_config):
    response = api_client.get("/v3.1/name/germany")
    validate_country_schema(response.json()[0])  # raises AssertionError on violation
```

---

## 3. Response Time Threshold from `env_config`

Never hardcode a timeout or response-time threshold in a test assertion. Always read it from
`env_config["max_response_time"]`, which is sourced from `config/environments.yaml`.

```python
# CORRECT
def test_response_time(api_client, env_config):
    response = api_client.get("/v3.1/all")
    assert response.elapsed.total_seconds() < env_config["max_response_time"]

# WRONG
assert response.elapsed.total_seconds() < 2.0
```

---

## 4. Use `pytest_check` for Multi-Item Validations

When a single test validates multiple independent items (e.g., iterating over all countries
to check population), use `pytest_check` so that all failures accumulate rather than
stopping at the first failure.

```python
import pytest_check as check

def test_all_countries_have_population(api_client):
    countries = api_client.get("/v3.1/all").json()
    for country in countries:
        check.greater(country.get("population", -1), 0,
                      msg=f"{country.get('name')} has invalid population")
```

---

## 5. Cross-Environment Tests for Shared Resources

When a country or geographic resource appears in both the `countries` and `weather`
environments, add a cross-reference test that verifies consistency across both. These tests
must be marked with both `@pytest.mark.countries` and `@pytest.mark.weather`, and must
accept both environment fixtures.

---

## 6. Class-Level Markers Required

Every test class must carry exactly one of:

- `@pytest.mark.countries`
- `@pytest.mark.weather`

These markers are used by `conftest.py:pytest_collection_modifyitems` to filter tests when
`--env countries` or `--env weather` is passed. Tests without the correct marker will be
deselected and will not run for the target environment.

```python
@pytest.mark.countries
class TestCountrySearch:
    ...

@pytest.mark.weather
class TestCurrentWeather:
    ...
```

---

## 7. Allure Decorators on Every Class and Method

Use `@allure.feature` on each test class and `@allure.story` on each test method. This
produces separate, navigable sections per environment in the Allure report.

```python
import allure

@allure.feature("Countries API")
@pytest.mark.countries
class TestCountrySearch:

    @allure.story("Search by name")
    def test_search_germany(self, api_client, env_config): ...

    @allure.story("Schema validation")
    def test_country_schema(self, api_client, env_config): ...
```
