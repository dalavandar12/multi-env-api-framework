# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
make install          # install dependencies
make lint             # flake8 + mypy
make test             # run all tests (both environments)
make test-countries   # pytest --env countries
make test-weather     # pytest --env weather
make test-cross-env   # pytest --env cross-env (Countries → Weather workflow)
make report           # allure serve (HTML report at http://localhost:4040)
make clean            # remove allure-results and cache
make clean-skills     # remove timestamped skill outputs under .claude/skills/ (manual)
```

Run a single test file:
```bash
pytest --env countries tests/countries/test_countries.py
pytest --env weather tests/weather/test_weather.py::TestWeather::test_forecast_temperature_range
pytest --env cross-env tests/test_cross-env.py
pytest --env weather -m smoke -v          # baseline hand-written tests only
pytest --env weather -m regression -v     # skill-generated extension only
```

## Architecture

The framework tests two live REST APIs plus one cross-environment workflow:
- **Countries** — restcountries.com/v3.1 (selected via `--env countries`)
- **Weather** — api.open-meteo.com/v1 (selected via `--env weather`)
- **Cross-env** — `tests/test_cross-env.py`: Countries lookup → Weather forecast (`--env cross-env`, `@pytest.mark("cross-env")`)

**Request path:** `conftest.py` → `api_client` fixture → `src/client.py:ApiClient` → external API  
**Validation path:** test calls `src/validators.py` functions; no assertions inline in test bodies

`conftest.py` owns three concerns: registers the `--env` CLI flag (`countries`, `weather`, `cross-env`), deselects tests whose marker doesn't match the active environment, and provides `api_client` / `env_config` (single-env) plus `countries_api_client` / `weather_api_client` (cross-env workflow).

`config/environments.yaml` is the single source of truth for `base_url`, `max_response_time`, and `min_results_count` per environment. No environment-specific values anywhere in Python code.

`utils/poller.py` provides a `@poller(max_attempts, delay)` decorator for retry/polling — no manual `time.sleep()` loops in tests.

## YAML Compliance Evidence

- Environment routing and thresholds are read from `config/environments.yaml` via `conftest.py` fixtures; tests do not hardcode environment URLs.
- Response-time and count assertions use `env_config` values (`max_response_time`, `min_results_count`, `region_min_country_count`), not literals.
- Weather temperature bounds are sourced from YAML (`temperature_min_c`, `temperature_max_c`) and passed into validators from tests.
- Test inputs (cities, regions, projections) live in `test_data/` JSON files; runtime environment policy lives in YAML.

## Test generation (incremental releases)

- Prefer **delta** work per release: extend the spec sheet (`testcase-generator`, use `--against` when updating; if a prior sheet exists for the component, `run.py` prints a TIP with the latest path), generate test data and pytest only for **new/changed** rows, and auto-copy a **new** timestamped module — do not full-regenerate an entire component unless intentional. Timestamped files under `tests/<component>/` accumulate by design; retire or merge superseded `test_*_*Z.py` after review so pytest does not run duplicate coverage. See `.claude/skills/test-generator/SKILL.md` → *Incremental release workflow*.

## Rules (enforced in `.claude/rules/`)

**Code style**
- All HTTP calls go through `ApiClient` — never import `requests` directly in tests
- All validation logic lives in `src/validators.py` — never assert inline in test bodies
- Type hints required on every function/method signature (`mypy --strict`)
- `LOG = logging.getLogger(__name__)` everywhere — no `print()`
- Max line length 100 (flake8)
- Import order: stdlib → third-party → project (blank line between blocks)

**Testing standards**
- Test data in `test_data/*.json`, loaded at module level via `@pytest.mark.parametrize` — no hardcoded values
- Response-time assertions must use `env_config["max_response_time"]`, never a literal
- Multi-item validations use `pytest_check` so all failures accumulate
- Every test class carries `@pytest.mark.countries` or `@pytest.mark.weather`, plus `@pytest.mark.smoke` (hand-written baseline) or `@pytest.mark.regression` (skill-generated modules such as `test_*_generated_<YYYYMMDD_HHMMSSZ>.py`)
- Every test class has `@allure.feature`, every test method has `@allure.story`

**Framework rules**
- `ApiClient` is only ever instantiated via the `api_client` fixture — never directly in tests
- No imports between test files; shared helpers go in `src/` or `utils/`
- Use `--env` flag to select environment — not `-m marker` expressions
- Adding a new API domain requires all four: `src/<name>_client.py`, new validators in `src/validators.py`, new entry in `config/environments.yaml`, new marker in `pytest.ini`

## CI

`.github/workflows/ci.yml` runs `lint` then `test` (both environments sequentially), uploading `allure-results/` as an artifact. Do not add parallel workflow files or duplicate test steps outside this file.

## Build Log Maintenance

After any significant change — design, workflow, architecture, CI, skill, or agent-based work — append a short dated entry to `CLAUDE_LOG.md` under a new `## Session N: <title>` heading. Do not rewrite earlier sessions; append only. Each entry should briefly cover: what changed, why, any Claude suggestion followed/overridden, and follow-up items. Use "Manual review needed" instead of guessing when a detail is uncertain.
