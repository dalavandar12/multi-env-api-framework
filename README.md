# API Automation Framework

Pytest-based API automation framework for two live public APIs with environment-driven execution:

- Countries API: `https://restcountries.com/v3.1`
- Weather API: `https://api.open-meteo.com/v1`

Configuration is centralized in `config/environments.yaml`, and tests are selected by `--env`.

## Setup

Prerequisites:

- Python 3.11
- `pip`
- Node.js (for local Allure CLI via `npx`)

Install:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
make install
```

## Run Tests Locally

Common commands:

```bash
make lint
make test
make test-countries
make test-weather
make test-cross-env
```

Single file examples:

```bash
pytest --env countries tests/countries/test_countries.py
pytest --env weather tests/weather/test_weather.py::TestWeather::test_forecast_temperature_range
pytest --env cross-env tests/test_cross-env.py
```

Marker-focused examples:

```bash
pytest --env weather -m smoke -v
pytest --env weather -m regression -v
```

## Interpreting Test Results

- `--env countries` / `--env weather` runs only tests marked for that environment.
- No `--env` runs all environments.
- `smoke` marks baseline hand-written suites; `regression` marks skill-generated extension suites.
- Response-time thresholds are enforced through `ApiClient` using YAML values (`max_response_time`), not hardcoded test constants.
- Allure output is written to `allure-results/` and can be viewed with:

```bash
make report
```

Or as static HTML:

```bash
make report-generate
```

In CI, both `allure-results` and `allure-report` are uploaded as artifacts.

## Assumptions and Design Decisions

Reference source: `agent_outputs/agent3_documentation_summary.md`.

- Environment abstraction is fixture-driven (`conftest.py` + `--env`) so the same framework pattern applies across APIs.
- Environment policy values (base URL, response-time thresholds, min result counts, and env-specific limits) live in YAML.
- Validation logic is centralized in `src/validators.py`; tests avoid inline schema assertions.
- Test data lives in `test_data/` JSON files and is loaded via parametrization.
- CI is split into `lint` then `test` jobs; test job runs weather, countries, and cross-env, then publishes Allure artifacts.
- Skills are folder-based (`.claude/skills/*/SKILL.md`) and wrapper markdown files exist for evaluator compatibility.
