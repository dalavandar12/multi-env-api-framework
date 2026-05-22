# Architecture & Reference

Deep technical reference for the API Test Automation Framework. The [README](README.md) covers install + quick start. This document covers everything else.

---

## Table of contents

1. [Architecture diagram](#architecture-diagram)
2. [Folder map](#folder-map)
3. [Running tests](#running-tests)
4. [The 4 skills (auto-generation agents)](#the-4-skills-auto-generation-agents)
   - [Skill 1: testcase-generator](#skill-1-testcase-generator)
   - [Skill 2: test-data-generator](#skill-2-test-data-generator)
   - [Skill 3: validator-generator](#skill-3-validator-generator)
   - [Skill 4: test-generator](#skill-4-test-generator)
   - [End-to-end pipeline example](#end-to-end-pipeline-example)
5. [agent_outputs — build-audit summaries](#agent_outputs--build-audit-summaries)
6. [Adding a new test the simple way](#adding-a-new-test-the-simple-way)
7. [Adding a new API domain](#adding-a-new-api-domain)
8. [Conventions enforced by the framework](#conventions-enforced-by-the-framework)
9. [Reporting with Allure](#reporting-with-allure)
10. [Continuous integration](#continuous-integration)
11. [Troubleshooting](#troubleshooting)
12. [Glossary](#glossary)
13. [Design notes](#design-notes)

---

## Architecture diagram

> Screenshot-friendly. The whole flow on one page.

```
+----------------------------------------------------------------------+
|                                                                      |
|                    pytest --env countries                            |
|                                                                      |
+----------------------------------------------------------------------+
                              |
                              v
+----------------------------------------------------------------------+
|                          conftest.py                                 |
|                                                                      |
|   * pytest_addoption(--env)                                          |
|   * env_config        (loads config/environments.yaml, picks env)    |
|   * api_client        (constructs ApiClient with base_url + cfg)     |
|   * pytest_collection_modifyitems                                    |
|       (deselects tests whose marker != --env)                        |
|                                                                      |
+----------------------------------------------------------------------+
            |                                          |
            v                                          v
+------------------------+              +---------------------------+
|  config/               |              |  test_data/               |
|    environments.yaml   |              |    cities.json            |
|                        |              |    countries.json         |
|  Per env:              |              |                           |
|    base_url            |              |  Parametrize fixtures     |
|    max_response_time   |              |  for every test           |
|    min_results_count   |              |                           |
|    region_min_country_ |              |                           |
|    temperature_min_c   |              |                           |
|    temperature_max_c   |              |                           |
+------------------------+              +---------------------------+
            |
            v
+----------------------------------------------------------------------+
|                       tests/test_*.py                                |
|                                                                      |
|   @pytest.mark.<component>                                           |
|   @allure.feature("...")                                             |
|   class TestX:                                                       |
|     @pytest.mark.parametrize("case", _DATA["..."], ...)              |
|     @allure.story("...")                                             |
|     def test_y(self, api_client, env_config, case):                  |
|         data = api_client.get("/path/{x}", params=...)               |
|         validate_<component>_schema(data)                            |
+----------------------------------------------------------------------+
       |  HTTP                                          |  assertion
       v                                                v
+------------------------+              +---------------------------+
|  src/client.py         |              |  src/validators.py        |
|  ApiClient + ApiError  |              |  validate_country_schema  |
|                        |              |  validate_weather_response|
|  - requests.Session    |              |  validate_population_pos. |
|  - prepends base_url   |              |  validate_countries_schema|
|  - times every request |              |  validate_weather_schema  |
|  - enforces            |              |                           |
|    max_response_time   |              |  (no inline asserts in    |
|  - raises ApiError on  |              |   test bodies, anywhere)  |
|    non-2xx             |              |                           |
+------------------------+              +---------------------------+
            |
            v
+----------------------------------------------------------------------+
|                        External live APIs                            |
|                                                                      |
|   restcountries.com/v3.1            api.open-meteo.com/v1            |
+----------------------------------------------------------------------+
```

---

## Folder map

```
api_automation/
|
|-- README.md                                quick start
|-- ARCHITECTURE.md                          you are here
|-- CLAUDE.md                                project conventions (loaded by Claude Code)
|-- CLAUDE_LOG.md                            dated build journal
|
|-- conftest.py                              --env flag, fixtures
|-- pytest.ini                               markers, logging config
|-- setup.cfg                                flake8 + mypy --strict
|-- requirements.txt                         pinned deps
|-- Makefile                                 install / lint / test / report / clean
|-- Dockerfile                               reproducible image
|
|-- config/
|   |-- environments.yaml                    single source of truth for env values
|
|-- src/
|   |-- client.py                            ApiClient + ApiError
|   |-- validators.py                        all assertion logic (hand + auto-gen block)
|
|-- utils/
|   |-- poller.py                            @poller decorator for retries/polling
|
|-- test_data/
|   |-- cities.json                          5 cities (weather)
|   |-- countries.json                       regions, name lookups, field projections
|
|-- tests/
|   |-- countries/
|   |   |-- test_countries.py                REST Countries baseline suite
|   |-- weather/
|   |   |-- test_weather.py                  Open-Meteo baseline suite
|   |-- test_cross-env.py                    cross-env chained workflow
|
|-- agent_outputs/                           build-audit summaries (3 files)
|-- allure-results/                          run artifacts (gitignored)
|-- allure-report/                           static HTML report (make report-generate)
|-- reports/                                 misc HTML reports
|
|-- .github/workflows/ci.yml                 lint -> test -> upload allure artifact
|
|-- .claude/
|   |-- rules/                               3 rule files (enforced)
|   |   |-- code-style.md
|   |   |-- framework-rules.md
|   |   |-- testing-standards.md
|   |
|   |-- skills/                              the 4-skill auto-generation pipeline
|       |-- testcase-generator/              Skill 1 -- produces spec sheets
|       |-- testcase-generator.md            wrapper pointer (evaluator compat)
|       |-- test-data-generator/             Skill 2 -- fills realistic values
|       |-- test-data-generator.md
|       |-- validator-generator/             Skill 3 -- emits validator functions
|       |-- validator-generator.md
|       |-- test-generator/                  Skill 4 -- emits pytest modules
|       |-- test-generator.md
```

---

## Running tests

### By environment

```bash
# A single environment
pytest --env countries
pytest --env weather
pytest --env cross-env

# All environments at once (no flag)
pytest
```

### By file or method

```bash
# A single test file
pytest --env weather tests/weather/test_weather.py
pytest --env countries tests/countries/test_countries.py

# A single test method
pytest --env weather \
       tests/weather/test_weather.py::TestWeather::test_forecast_temperature_range

# Cross-env chained workflow
pytest --env cross-env tests/test_cross-env.py
```

### By marker (combine with `--env`)

```bash
# Baseline hand-written tests
pytest --env weather -m smoke -v

# Skill-generated extension modules
pytest --env weather -m regression -v
```

### Convenience flags

```bash
# Stop on first failure
pytest --env countries -x

# Verbose with live logs
pytest --env weather -v --log-cli-level=INFO

# Filter by name pattern
pytest -k "capital and not negative"
```

### Marker convention

| Marker | Meaning |
|---|---|
| `@pytest.mark.countries` | Test targets the Countries API. Collected under `--env countries`. |
| `@pytest.mark.weather` | Test targets the Weather API. Collected under `--env weather`. |
| `@pytest.mark.cross-env` | Test spans both APIs. Collected under `--env cross-env`. |
| `@pytest.mark.smoke` | Hand-curated baseline test — must pass for the suite to be considered healthy. |
| `@pytest.mark.regression` | Skill-generated test — broader coverage, may have known flakes. |

> `--env` is the **only** mechanism for selecting an environment. Don't use bare `-m countries` to switch envs — markers handle collection filtering, but the `--env` flag also injects the right `env_config` values into fixtures. Using `-m` alone would point `api_client` at the wrong base URL.

---

## The 4 skills (auto-generation agents)

Each skill is an **autonomous Claude Code agent** with a single responsibility, a defined input format, and a defined output format. They chain naturally:

```
            +-------------------+    +-------------------+    +-------------------+    +-------------------+
            |  Skill 1          |    |  Skill 2          |    |  Skill 3          |    |  Skill 4          |
SOURCE ---->|  testcase-        |--->|  test-data-       |--->|  validator-       |--->|  test-generator   |---> pytest --env
            |  generator        |    |  generator        |    |  generator        |    |                   |
            +-------------------+    +-------------------+    +-------------------+    +-------------------+
                     |                         |                       |                          |
              spec sheet (xlsx)        test_data.json          validate_*.py            tests/test_*.py
              "what to test"           "with what values"      "with what asserts"      "as runnable code"
```

Each folder uses a **self-documenting** naming convention:

- `received_*/` — files the skill **consumes** (drop inputs here)
- `generated_*/` — files the skill **produces**
- `config/` — internal config (seeds, schemas, maps)
- `scripts/` — implementation

Each skill is also addressable as a slash command in Claude Code (e.g., `/testcase-generator`, `/test-data-generator`, `/validator-generator`, `/test-generator`). The `.md` wrapper files next to each skill folder are brief pointer docs for evaluators that don't traverse subdirectories.

---

### Skill 1: testcase-generator

> Discover endpoints from any documentation source and produce a reviewer-ready Excel spec sheet.

| Property | Value |
|---|---|
| Trigger | `/testcase-generator`, "generate test cases for ..." |
| Inputs | URL, OpenAPI YAML/JSON, local doc (md/pdf/docx/txt), Jira ticket, Confluence page |
| Default output | Excel xlsx in `generated_spec_sheets/` |
| Other formats | csv / json / txt / docx / pdf |
| Live API calls? | Yes — only to fetch the source URL (guarded with HTTPS-only, no-private-IP, robots.txt) |

**Folder layout**

```
.claude/skills/testcase-generator/
|-- SKILL.md
|-- received_sources/             URLs, OpenAPI files, local docs
|-- generated_spec_sheets/        Excel spec sheets land here
|-- config/                       url_guardrail.yaml, component_markers.yaml,
|                                 cross_api_workflows.yaml
|-- templates/                    testcase_columns.yaml (canonical 27 columns)
|-- references/                   taxonomy, priority rubric, MCP setup
|-- scripts/                      run.py + 8 helpers
```

**CLI examples**

```bash
# From a public URL
python .claude/skills/testcase-generator/scripts/run.py \
  --source url https://restcountries.com --component countries

# From a Swagger spec
python .claude/skills/testcase-generator/scripts/run.py \
  --source openapi https://petstore3.swagger.io/api/v3/openapi.json

# From a local PDF
python .claude/skills/testcase-generator/scripts/run.py \
  --source file api_spec.pdf --component myapi

# Multiple URLs in one shot
python .claude/skills/testcase-generator/scripts/run.py \
  --source url "https://restcountries.com,https://open-meteo.com/en/docs" \
  --component mixed
```

**Spec-sheet columns (27 total)**

`tc_id` · `title` · `description` · `case_type` (positive/negative/edge) · `category` (12 sub-types) · `priority` (P0/P1/P2) · `component` · `pytest_marker` · `endpoint_url` · `method` · `path_params` · `query_params` · `headers` · `request_body` · `preconditions` · `expected_status` · `expected_response_fields` · `expected_response_body` · `expected_response_time_ms` · `equivalence_class` · `test_data_ref` · `validator_ref` · `traceability` · `source_excerpt` · `workflow_steps` · `review_status` · `notes`

---

### Skill 2: test-data-generator

> Replace placeholder values in a spec sheet with real curated values from a seed YAML — **fully offline, no live API calls**.

| Property | Value |
|---|---|
| Trigger | `/test-data-generator`, "generate test data from this spec sheet" |
| Inputs | xlsx spec sheet (from Skill 1) **OR** thin endpoint JSON |
| Outputs | JSON keyed by `component__METHOD__/path` |
| Live API calls? | **None** |

**Folder layout**

```
.claude/skills/test-data-generator/
|-- SKILL.md
|-- received_spec_sheets/         drop Skill 1's xlsx outputs here
|-- generated_test_data/          test_data_<component>_<ts>.json + report.txt
|-- config/
|   |-- seeds/
|   |   |-- countries.yaml        5 curated countries (Germany, Brazil, Japan, ...)
|   |   |-- weather.yaml          5 curated cities (Berlin, Tokyo, Sydney, ...)
|   |-- endpoint_param_map.yaml   tells which seed field feeds which endpoint param
|-- scripts/                      run.py + 4 helpers
```

**Seed YAML example (`config/seeds/countries.yaml`)**

```yaml
records:
  - country_name: Germany
    capital: Berlin
    currency_name: Euro
    currency_code: EUR
    alpha_2: DE
    alpha_3: DEU
    language: German
    demonym: German
    region: Europe
    subregion: Western Europe
    translation_es: Alemania
    latitude: 51.0
    longitude: 10.0
  # ... 4 more records
```

**Endpoint-param map example (`config/endpoint_param_map.yaml`)**

```yaml
countries:
  "/name/{name}":
    path_params: { name: "{country_name}" }
  "/region/{region}":
    path_params: { region: "{region}" }
```

**CLI examples**

```bash
# Auto-pick newest xlsx, write JSON to own output folder
python .claude/skills/test-data-generator/scripts/run.py --source file

# Auto-pick + chain into Skill 4's inbox
python .claude/skills/test-data-generator/scripts/run.py --source file --chain

# Multiply rows by seed count (default in current build is fan-out ON)
python .claude/skills/test-data-generator/scripts/run.py --source file --fanout

# Preserve row count exactly, distribute positives across seeds
python .claude/skills/test-data-generator/scripts/run.py --source file --no-fanout
```

**Output JSON shape**

```json
{
  "countries__GET__/name/{name}": {
    "positive": [
      {"tc_id": "TC_COUNTRIES_521fe7",
       "path_params": {"name": "Germany"},
       "expected_status": 200,
       "seed_source": "Germany@index_0"}
    ],
    "negative": [
      {"tc_id": "TC_COUNTRIES_3e7ad0",
       "path_params": {"name": "zzzzz_nonexistent_name"},
       "expected_status": 404}
    ]
  }
}
```

5xx and 429 rows automatically get `"skip": true, "skip_reason": "..."` so downstream pytest tests `pytest.skip(...)` cleanly instead of failing on unrunnable categories.

---

### Skill 3: validator-generator

> Turn a hand-curated **schema YAML** into a runnable Python validator function with recursive, typed assert-based checks.

| Property | Value |
|---|---|
| Trigger | `/validator-generator`, "generate validator from schema" |
| Inputs | YAML schema in `received_schemas/<component>.yaml` |
| Outputs | Python `.py` file with `validate_<component>_schema(data)` function |
| Live API calls? | **None** |

**Folder layout**

```
.claude/skills/validator-generator/
|-- SKILL.md
|-- received_schemas/             countries.yaml, weather.yaml, ...
|-- generated_validators/         validate_<component>_<ts>.py
|-- scripts/                      run.py + parse_schema.py + emit_validator.py
```

**Schema YAML example (`received_schemas/countries.yaml`)**

```yaml
component: countries
validator_name: validate_countries_schema
description: "Validates a single country object from REST Countries v3.1"

shape:
  type: object
  required: [name, capital, population, currencies, languages]
  fields:
    name:
      type: object
      required: [common, official]
      fields:
        common:   { type: string, non_empty: true }
        official: { type: string, non_empty: true }
    capital:    { type: array, item_type: string, non_empty: true }
    population: { type: integer, min: 0 }
    currencies: { type: object }
    languages:  { type: object }
```

**Supported types**

| Type | Modifiers |
|---|---|
| `string` | `non_empty: true` |
| `integer` | `min: N`, `max: N` |
| `number` | `min: N`, `max: N` |
| `boolean` | — |
| `number_or_null` | — |
| `string_or_null` | — |
| `object` | `required: [...]`, `fields: {...}` (recursive) |
| `array` | `item_type: <any-other-type>`, `min_length`, `max_length`, `non_empty` |

**CLI examples**

```bash
# Generate validators for every schema in received_schemas/
python .claude/skills/validator-generator/scripts/run.py

# One specific schema
python .claude/skills/validator-generator/scripts/run.py --schema countries

# Also append into src/validators.py inside the marked auto-gen block
python .claude/skills/validator-generator/scripts/run.py \
  --schema countries --write-to-validators

# Force overwrite an existing function inside the auto-gen block
python .claude/skills/validator-generator/scripts/run.py \
  --schema countries --write-to-validators --force
```

When `--write-to-validators` is used, the function lands inside `src/validators.py` between these markers — re-runs replace cleanly without touching hand-written code above:

```python
# === auto-generated validators (DO NOT EDIT) ===
def validate_countries_schema(data: dict[str, Any]) -> None:
    ...
# === end auto-generated ===
```

---

### Skill 4: test-generator

> Turn a spec sheet (+ optionally Skill 2's test data) into a runnable pytest module with markers, allure decorators, parametrize, and validator calls.

| Property | Value |
|---|---|
| Trigger | `/test-generator`, "generate pytest from this spec sheet" |
| Inputs | xlsx spec sheet **OR** endpoint JSON **OR** CLI args (`--endpoint --method --response-fields`) |
| Outputs | `.py` pytest module + companion `.json` |
| Live API calls? | None during generation. Generated tests obviously call the live API at run time. |

**Folder layout**

```
.claude/skills/test-generator/
|-- SKILL.md
|-- received_spec_sheets/         Skill 1's xlsx (or thin JSON) lands here
|-- received_test_data/           Skill 2's JSON lands here (often via --chain)
|-- generated_pytest_modules/     test_<component>_<ts>.py + companion JSON
|-- scripts/                      run.py + parse_spec_sheet.py + generate_pytest.py
```

**Generated structure**

```python
@allure.feature("Countries API - GET /name/{name}")
@pytest.mark.countries
@pytest.mark.regression
class TestGetNameName:
    """Tests for GET /name/{name} - generated from spec sheet."""

    _CLASS_KEY = "countries__GET__/name/{name}"

    @allure.story("Happy path")
    @pytest.mark.parametrize(
        "case", _cases(_CLASS_KEY, "positive"), ids=lambda c: c["tc_id"],
    )
    def test_positive(self, api_client, env_config, case):
        if case.get("skip"):
            pytest.skip(case.get("skip_reason", "auto-skipped"))
        LOG.info("[%s] positive: %s", case["tc_id"], case["title"])
        data = api_client.get(_safe_path("/name/{name}", case["path_params"]),
                              params=case["query_params"])
        assert data is not None, case["tc_id"]

    # test_schema, test_negative, test_edge, test_performance follow
```

> Generated classes carry `@pytest.mark.regression` so they're collected separately from hand-written smoke tests.

**CLI examples**

```bash
# From a spec sheet (auto-synthesizes JSON if no --test-data passed)
python .claude/skills/test-generator/scripts/run.py \
  --source file testcases_url_countries_*.xlsx

# From a spec sheet + Skill 2's real test data
python .claude/skills/test-generator/scripts/run.py \
  --source file testcases_url_countries_*.xlsx \
  --test-data test_data_countries_*.json

# From CLI args (no spec sheet at all)
python .claude/skills/test-generator/scripts/run.py --source cli \
  --endpoint https://restcountries.com/v3.1/name/{name} \
  --method GET \
  --response-fields name,capital,population \
  --component countries

# From a thin JSON listing endpoints
python .claude/skills/test-generator/scripts/run.py --source json endpoints.json
```

**Auto-copy behavior**

By default, generated files also land in `tests/<component>/` and `test_data/<component>/`. Pass `--no-autocopy-tests` to keep them only in `generated_pytest_modules/`.

---

### End-to-end pipeline example

Build an extension countries suite from scratch and chain into the framework:

```bash
# 1. Skill 1 - discover endpoints from a doc URL
python .claude/skills/testcase-generator/scripts/run.py \
  --source url https://restcountries.com --component countries
# -> .claude/skills/testcase-generator/generated_spec_sheets/testcases_url_countries_<ts>.xlsx

# 2. Skill 2 - fill placeholders with real curated values; chain to Skill 4
cp .claude/skills/testcase-generator/generated_spec_sheets/testcases_url_countries_<ts>.xlsx \
   .claude/skills/test-data-generator/received_spec_sheets/
python .claude/skills/test-data-generator/scripts/run.py --source file --chain

# 3. Skill 3 - build typed validator from schema YAML
python .claude/skills/validator-generator/scripts/run.py \
  --schema countries --write-to-validators

# 4. Skill 4 - emit pytest module (auto-copies to tests/countries/)
cp .claude/skills/testcase-generator/generated_spec_sheets/testcases_url_countries_<ts>.xlsx \
   .claude/skills/test-generator/received_spec_sheets/
python .claude/skills/test-generator/scripts/run.py \
  --source file --test-data test_data_countries_<ts>.json

# 5. Run baseline + extension together
pytest --env countries
```

Result: baseline `tests/countries/test_countries.py` (smoke) + generated `tests/countries/test_countries_<ts>.py` (regression) collected under one `--env countries` invocation.

---

## agent_outputs — build-audit summaries

The `agent_outputs/` folder holds historical artifacts from a **multi-agent build/audit process** used during the framework's construction. They are read-only references — not consumed by the runtime or CI — but they're useful when you need to understand "why is the framework the way it is?" or "has this been audited recently?".

```
agent_outputs/
|-- agent1_skill_pipeline_summary.md       Skill pipeline audit
|-- agent2_test_execution_summary.md       Baseline test execution audit
|-- agent3_documentation_summary.md        Documentation + delivery audit
```

### Agent 1 — Skill Pipeline Agent

**File:** [`agent_outputs/agent1_skill_pipeline_summary.md`](agent_outputs/agent1_skill_pipeline_summary.md) (~14 KB)
**Latest audit date:** 2026-05-22 (re-audit; original 2026-05-21)
**Working directory:** `.claude/skills/`

**What it audits:**

- Existence of all four skill folders (`testcase-generator`, `test-data-generator`, `validator-generator`, `test-generator`)
- Companion `.md` wrapper files for evaluator compatibility
- `SKILL.md` frontmatter completeness (`name:` and `description:` fields)
- Scripts present per skill (`run.py`, `parse_*`, `emit_*`, etc.)
- Config files present (`seeds/`, `endpoint_param_map.yaml`, `received_schemas/`, etc.)
- Generated artefact folders exist and use the `received_*/` + `generated_*/` naming convention

**When to read it:**

- After running any skill, to confirm the pipeline is still intact
- When onboarding (it lists every skill folder's full contents)
- When evaluating the project for skill-compliance

### Agent 2 — Test Execution Agent

**File:** [`agent_outputs/agent2_test_execution_summary.md`](agent_outputs/agent2_test_execution_summary.md) (~4 KB)
**Latest audit date:** 2026-05-22
**Working directory:** repo root
**Python:** 3.11.13 in `.venv` · pytest 9.0.3
**Mode:** read-only — no code or test data modified

**What it audits:**

- `make lint` exit status (flake8 + mypy --strict)
- Counts of errors/warnings per linter
- Whether previously flagged issues (duplicate validators, E999 syntax errors, E501 line-length) are still present
- Whether the baseline 19 tests still pass under both `--env countries` and `--env weather`

**When to read it:**

- After a refactor, to confirm lint/typecheck status hasn't regressed
- When debugging CI failures locally
- To get a "last known good" snapshot of the framework

### Agent 3 — Documentation Agent

**File:** [`agent_outputs/agent3_documentation_summary.md`](agent_outputs/agent3_documentation_summary.md) (~10 KB)
**Latest audit date:** 2026-05-21
**Scope:** `CLAUDE.md`, `CLAUDE_LOG.md`, `Makefile`, `Dockerfile`, `.github/workflows/ci.yml`

**What it documents:**

- How to run the framework locally (prereqs, setup, test commands)
- All Makefile targets and what each runs
- The CI pipeline structure (lint job, test job, artifact upload)
- The Dockerfile layer breakdown
- Original assumptions and design decisions (fixture-driven env abstraction, YAML-only thresholds, validator centralization, JSON test data, smoke vs regression markers)

**When to read it:**

- For the original design rationale — why was the framework built this way?
- When you're about to change `Makefile`, `Dockerfile`, or CI — to confirm you understand what's already in place
- To extract content for new docs (the design-decisions section is reusable)

### How these are produced

Each summary was produced by an agent run under Claude Code with a specific scope. They're committed to git as audit trail, not regenerated automatically. To refresh one, re-run the same agent against the current repo state and overwrite the file in place. New audits should bump the **Date** line at the top.

---

## Adding a new test the simple way

Suppose you want a new test: **"GET /name/{name} returns a non-empty `capital` array."**

**Step 1 — add a row to `test_data/countries.json`**

```json
{
  "name_lookups": [
    {"name": "germany"},
    {"name": "japan"}
  ]
}
```

**Step 2 — add a method to `tests/countries/test_countries.py`**

```python
@allure.story("Non-empty capital array")
@pytest.mark.parametrize("country", _DATA["name_lookups"], ids=lambda c: c["name"])
def test_capital_non_empty(self, api_client: ApiClient,
                            country: dict[str, Any]) -> None:
    """GET /name/{name} must return a non-empty list under 'capital'."""
    results = api_client.get(f"/name/{country['name']}")
    validate_country_has_capital(results[0])
```

**Step 3 — add the validator to `src/validators.py`**

```python
def validate_country_has_capital(country: dict[str, Any]) -> None:
    """Assert 'capital' is a non-empty list."""
    capital = country.get("capital")
    assert isinstance(capital, list) and capital, (
        f"Country '{country.get('name', {}).get('common', '?')}' "
        f"has invalid capital: {capital!r}"
    )
```

**Step 4 — run**

```bash
pytest --env countries -k test_capital_non_empty -v
```

Done. **No new files**, no inline assertions, no hardcoded country list, fully type-hinted.

---

## Adding a new API domain

Onboarding a third API (e.g., GitHub) requires four coordinated changes — partial additions fail review:

1. **New endpoint module** — `src/github_client.py` with typed methods wrapping `ApiClient.get()`
2. **New validators** — add `validate_github_*` functions to `src/validators.py`
3. **New environment entry** — add `github:` block in `config/environments.yaml` with at minimum `base_url`, `max_response_time`, `min_results_count`
4. **New pytest marker** — register `github` in `pytest.ini` under `[pytest] markers`

The four skills can produce all of these:

```bash
python .claude/skills/testcase-generator/scripts/run.py \
  --source openapi github-openapi.yaml --component github
# author seeds/github.yaml + add github to endpoint_param_map.yaml
python .claude/skills/test-data-generator/scripts/run.py --source file --chain
# author received_schemas/github.yaml
python .claude/skills/validator-generator/scripts/run.py --schema github --write-to-validators
python .claude/skills/test-generator/scripts/run.py --source file \
  --test-data test_data_github_<ts>.json
```

---

## Conventions enforced by the framework

Not stylistic preferences — enforced by `flake8`, `mypy --strict`, and reviewed against `.claude/rules/*.md`.

| Rule | Why |
|---|---|
| HTTP only via `ApiClient` (never `import requests` in tests) | One point of timing, error handling, base-URL composition |
| All assertions in `src/validators.py` (never inline) | One canonical definition per check; reusable |
| Test data only in `test_data/*.json` (never inline literals) | Parametrize at module level, not hand-typed in test bodies |
| Thresholds only in YAML (never hardcoded) | Same test runs against multiple envs with different thresholds |
| `--env` is the only mechanism for env selection | Filter + fixture inject in one place |
| `@pytest.mark.<component>` on every class | Used by `pytest_collection_modifyitems` to filter |
| `@pytest.mark.smoke` / `@pytest.mark.regression` on every class | Distinguishes baseline from auto-generated extensions |
| `@allure.feature` on class + `@allure.story` on method | Report grouping by component, then story |
| Type hints on every signature (`mypy --strict`) | Catches contract violations early |
| `LOG = logging.getLogger(__name__)` — no `print()` | Uniform logging |
| Max line length 100 | flake8 |
| Import order: stdlib -> third-party -> project | isort-style |
| Retries via `@poller` — no manual `time.sleep` loops | Backoff strategy in one place |

Read the three rule files in `.claude/rules/` if you plan to contribute.

---

## Reporting with Allure

Every test emits Allure-compatible result files into `allure-results/`. Two ways to view:

```bash
# Live server (requires Node.js)
make report
# -> npx allure serve allure-results
# -> opens http://localhost:4040 in your browser

# Static HTML (CI-friendly)
make report-generate
# -> npx allure generate allure-results -o allure-report --clean
# -> open allure-report/index.html
```

In CI, both `allure-results/` and `allure-report/` are uploaded as build artifacts so you can download and inspect them per run.

The report groups tests by:

- **Feature** (from `@allure.feature`) — Countries API · Weather API · Cross-API workflows
- **Story** (from `@allure.story`) — Happy path · Schema validation · Boundary · etc.

Each step includes the request URL, response status, elapsed time, and any assertion failures with full diff.

---

## Continuous integration

`.github/workflows/ci.yml` runs two jobs on every push and PR:

1. **lint** — `flake8` + `mypy --strict`
2. **test** — runs `pytest --env countries`, `pytest --env weather`, `pytest --env cross-env` sequentially, then uploads `allure-results/` and `allure-report/` as build artifacts

Do not add parallel workflow files or duplicate test steps. The single workflow file is the authoritative CI definition.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ApiError: HTTP 4xx ...` on first run | Remote API is rate-limiting or temporarily down | Wait, re-run with `pytest --env <env> -v` |
| `pytest` collects 0 tests | The `--env` flag doesn't match any marker, or path filter is too narrow | Confirm `pytest.ini` has the marker; drop `-k` filter |
| `mypy` complains about missing types | A new function lacks annotations | Add `-> None`, `dict[str, Any]`, etc. per `.claude/rules/code-style.md` |
| Generated test fails on import | A `validate_*_schema` function is missing | Run Skill 3 with `--write-to-validators`, or add the function manually |
| `make report` says `npx: command not found` | Node.js not installed | `brew install node` (macOS) / `apt install nodejs npm` (Linux) |
| `allure serve` shows nothing | `allure-results/` is empty | Run tests first; confirm `pytest.ini` has `--alluredir=allure-results` |
| Generated test calls the wrong host | Endpoint URL is on a subdomain not in `base_url` | Either narrow the spec sheet to single-host endpoints, or extend `ApiClient` to accept absolute URLs |
| `pip install` is slow | No wheel cache | `pip install -U pip` first; subsequent installs cache wheels |

---

## Glossary

| Term | Meaning |
|---|---|
| **Environment** | One target API. Currently `countries`, `weather`, and `cross-env`. Selected with `--env`. |
| **Component** | Synonym for environment in skill/code context (e.g., `@pytest.mark.countries`). |
| **Spec sheet** | xlsx file produced by Skill 1, lists every test case as a row. |
| **Test data JSON** | Companion file produced by Skill 2, holds real input values keyed by class + bucket. |
| **Validator** | A function in `src/validators.py` that asserts on a response. |
| **Bucket** | One of `positive`, `negative`, `schema`, `edge`, `performance`, `workflow` — groups test rows by category for parametrize. |
| **Smoke** | Hand-curated baseline test marked `@pytest.mark.smoke`. Must pass for the suite to be healthy. |
| **Regression** | Skill-generated extension test marked `@pytest.mark.regression`. Broader coverage; may have known flakes. |
| **`@poller`** | Retry/timeout decorator in `utils/poller.py`. No manual sleep loops. |
| **Auto-gen block** | Section in `src/validators.py` between `# === auto-generated validators ===` markers. Skill 3 writes here. |
| **Skill** | An autonomous Claude Code agent under `.claude/skills/<name>/` with its own `SKILL.md`, `scripts/`, `config/`. Invoked via `/<skill-name>` or direct `python run.py`. |
| **agent_outputs** | Folder of historical audit summaries — one per agent that built or audited the framework. Read-only reference, not consumed by runtime. |

---

## Design notes

Distilled from `agent_outputs/agent3_documentation_summary.md`:

- **Environment abstraction is fixture-driven** (`conftest.py` + `--env`), so the same framework pattern applies across APIs.
- **Environment policy values** (base URL, response-time thresholds, min result counts, and env-specific limits) live in YAML, never inline.
- **Validation logic is centralized** in `src/validators.py`; tests avoid inline schema assertions.
- **Test data lives in `test_data/`** JSON files and is loaded via parametrization.
- **CI is split** into `lint` then `test` jobs; the test job runs weather, countries, and cross-env, then publishes Allure artifacts.
- **Skills are folder-based** (`.claude/skills/*/SKILL.md`); wrapper markdown files exist for evaluator compatibility.
- **Smoke vs Regression** marker distinction lets baseline and auto-generated extension tests coexist while staying clearly separable.

---

## Contributing

1. Read `.claude/rules/code-style.md`, `framework-rules.md`, `testing-standards.md`.
2. Run `make lint test` before pushing.
3. Append a dated entry to `CLAUDE_LOG.md` for any architectural, workflow, or skill change.
4. Open a PR; CI must pass before merge.
