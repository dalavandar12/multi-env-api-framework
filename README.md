# API Test Automation Framework

A Python pytest framework that runs the **same test logic against two independent live APIs** — REST Countries and Open-Meteo Weather — selected at run time via a single `--env` CLI flag. A third environment, `cross-env`, exercises chained workflows that span both APIs. Environment configuration (base URLs, response-time thresholds, count minimums) lives entirely in YAML, so tests are **API-agnostic**.

Ships with a **4-skill auto-generation pipeline** that turns API documentation (URL / PDF / Swagger / Jira) into runnable, reviewer-ready pytest modules without writing test code by hand.

| Environment | Target | What it tests |
|---|---|---|
| `countries` | `https://restcountries.com/v3.1` | Country lookup, region filtering, schema validation |
| `weather` | `https://api.open-meteo.com/v1` | Forecast endpoint, temperature ranges, timezone fields |
| `cross-env` | both | Country lookup → extract coordinates → Weather forecast (chained workflow) |

> **Deep dive:** for architecture, folder map, skill internals, agent summaries, conventions, troubleshooting, and design notes, see **[ARCHITECTURE.md](ARCHITECTURE.md)**.

---

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | 3.11 or later | Type-hint syntax used throughout (`list[X]`, `dict[K, V]`, `X \| None`) |
| `pip` | latest | Dependency installer |
| `make` | any recent | Convenience commands in the Makefile |
| Node.js | 18 or later | Required only for local Allure CLI via `npx` (`make report`) |
| Git | any recent | Cloning the repo |
| Internet access | required | The two target APIs are public; tests hit them live |

> **Note:** No API keys are required. Both REST Countries and Open-Meteo are free, no-auth public APIs.

---

## Installation

```bash
# 1. Clone
git clone <repo-url> api_automation
cd api_automation

# 2. Create and activate a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate            # macOS / Linux
# .venv\Scripts\activate              # Windows PowerShell

# 3. Install all dependencies (production + dev + skill tools)
make install
# equivalent: pip install -U pip && pip install -r requirements.txt

# 4. Verify the install
pytest --collect-only -q             # should list ~19 tests
make lint                            # flake8 + mypy --strict; should be clean
```

### What's in `requirements.txt`

| Group | Packages |
|---|---|
| **Core test runtime** | `pytest`, `pytest-check`, `requests`, `pyyaml` |
| **Reporting** | `allure-pytest` |
| **Static analysis** | `flake8`, `mypy`, `types-requests`, `types-PyYAML` |
| **Skill-pipeline tooling** | `openpyxl`, `python-docx`, `pypdf`, `reportlab`, `markdown`, `beautifulsoup4` |

Full breakdown with per-package justification: see [ARCHITECTURE.md → Troubleshooting](ARCHITECTURE.md#troubleshooting) (linked in the deep doc).

---

## Quick start

```bash
make install                # one-time setup
make test-countries         # tests against restcountries.com/v3.1
make test-weather           # tests against api.open-meteo.com/v1
make test-cross-env         # chained workflow (Countries -> Weather)
make test                   # full suite (countries + weather + cross-env)
make report                 # open Allure report at http://localhost:4040
make report-generate        # write static HTML to allure-report/
make lint                   # flake8 + mypy --strict
make clean                  # remove allure-results and __pycache__
```

Expected first-run output:

```
========================== 19 passed in ~12s ===========================
```

Single test file / single method:

```bash
pytest --env countries tests/countries/test_countries.py
pytest --env weather tests/weather/test_weather.py::TestWeather::test_forecast_temperature_range
pytest --env cross-env tests/test_cross-env.py
```

Marker-focused:

```bash
pytest --env weather -m smoke -v       # hand-written baseline
pytest --env weather -m regression -v  # skill-generated extension
```

More patterns: [ARCHITECTURE.md → Running tests](ARCHITECTURE.md#running-tests).

---

## The 4-skill auto-generation pipeline (at a glance)

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

| # | Skill | Trigger | One-liner |
|---|---|---|---|
| 1 | `testcase-generator` | `/testcase-generator` | URL / OpenAPI / PDF → Excel spec sheet (27 columns) |
| 2 | `test-data-generator` | `/test-data-generator` | spec sheet + seed YAML → realistic test_data JSON (offline) |
| 3 | `validator-generator` | `/validator-generator` | schema YAML → `validate_<component>_schema(data)` Python function |
| 4 | `test-generator` | `/test-generator` | spec sheet + test_data → pytest module + companion JSON |

Each skill lives in `.claude/skills/<name>/` with `received_*/` (inputs) and `generated_*/` (outputs) folders. Full details, YAML examples, CLI flags, and the end-to-end recipe: [ARCHITECTURE.md → The 4 skills](ARCHITECTURE.md#the-4-skills-auto-generation-agents).

---

## Build-audit artifacts (`agent_outputs/`)

Three historical audit summaries from the multi-agent build process. Read-only references — not consumed by runtime or CI, but useful for design rationale and "last known good" snapshots.

| File | Scope | Date |
|---|---|---|
| `agent1_skill_pipeline_summary.md` | All four skill folders, scripts, config, naming conventions | 2026-05-22 |
| `agent2_test_execution_summary.md` | `make lint` + baseline pytest pass/fail | 2026-05-22 |
| `agent3_documentation_summary.md` | Original design rationale, Makefile/CI/Dockerfile audit | 2026-05-21 |

Full breakdown of each agent's role and what to read when: [ARCHITECTURE.md → agent_outputs](ARCHITECTURE.md#agent_outputs--build-audit-summaries).

---

## Folder layout (top-level)

```
api_automation/
|-- README.md                quick start (this file)
|-- ARCHITECTURE.md          deep technical reference
|-- conftest.py              --env flag, fixtures
|-- pytest.ini               markers
|-- requirements.txt         pinned deps
|-- Makefile                 install / lint / test / report / clean
|-- config/environments.yaml single source of truth for env values
|-- src/                     ApiClient + validators
|-- utils/                   poller decorator
|-- test_data/               JSON parametrize fixtures
|-- tests/                   countries/, weather/, test_cross-env.py
|-- agent_outputs/           build-audit summaries
|-- .github/workflows/ci.yml lint -> test -> Allure artifact
|-- .claude/
|   |-- rules/               3 enforced rule files
|   |-- skills/              4-skill auto-generation pipeline
```

Full tree: [ARCHITECTURE.md → Folder map](ARCHITECTURE.md#folder-map).

---

## Interpreting test results

- `--env countries` / `--env weather` / `--env cross-env` run only tests marked for that environment.
- No `--env` flag → all environments collected.
- `smoke` marks baseline hand-written suites; `regression` marks skill-generated extension suites.
- Response-time thresholds are enforced through `ApiClient` using YAML values (`max_response_time`) — never hardcoded in test bodies.
- Allure output goes to `allure-results/` and can be viewed with `make report` (live server) or `make report-generate` (static HTML in `allure-report/`).

In CI, both `allure-results/` and `allure-report/` are uploaded as build artifacts.

---

## Design highlights

- **Environment abstraction is fixture-driven** (`conftest.py` + `--env` flag), so the same test pattern applies across both APIs without per-API forking.
- **Environment policy values** (base URLs, response-time thresholds, min result counts) live in YAML — `config/environments.yaml` is the single source of truth.
- **Validation logic is centralized** in `src/validators.py`. Tests never assert inline.
- **Test data lives in `test_data/*.json`** and is loaded via `@pytest.mark.parametrize` — no inline literals in test bodies.
- **CI is split** into `lint` and `test` jobs; the test job runs all three environments sequentially and uploads Allure artifacts.
- **Skills are folder-based** (`.claude/skills/*/SKILL.md`); wrapper `.md` files exist for evaluator compatibility.

Full rationale and original audit: see [ARCHITECTURE.md → Design notes](ARCHITECTURE.md#design-notes) and the [`agent_outputs/`](agent_outputs/) folder.

---

## Troubleshooting (top 4)

| Symptom | Fix |
|---|---|
| `ApiError: HTTP 4xx ...` on first run | Wait — remote API rate-limit. Re-run with `pytest --env <env> -v`. |
| `make report` says `npx: command not found` | `brew install node` (macOS) / `apt install nodejs npm` (Linux) |
| `pytest` collects 0 tests | Check `pytest.ini` markers and drop any `-k` filter. |
| Generated test fails on import | Run `validator-generator --write-to-validators`, or add the function manually. |

Full list: [ARCHITECTURE.md → Troubleshooting](ARCHITECTURE.md#troubleshooting).

---

## Contributing

1. Read `.claude/rules/code-style.md`, `framework-rules.md`, `testing-standards.md`.
2. Run `make lint test` before pushing.
3. Append a dated entry to `CLAUDE_LOG.md` for any architectural, workflow, or skill change.
4. Open a PR; CI must pass before merge.

Conventions enforced by the framework: [ARCHITECTURE.md → Conventions](ARCHITECTURE.md#conventions-enforced-by-the-framework).
