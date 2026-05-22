---
name: test-generator
description: Generate a runnable pytest test module + companion JSON test-data file from a testcase-generator spec sheet (xlsx). Outputs are written in generated_pytest_modules and auto-copied into the repo tests/ folder by default.
---

# test-generator

Companion to the `testcase-generator` skill. Reads a spec-sheet xlsx and emits:

1. `generated_pytest_modules/test_<component>_generated_<YYYYMMDD_HHMMSSZ>.py` — pytest module that mirrors this repo's existing `tests/countries/test_countries.py` / `tests/weather/test_weather.py` patterns.
2. `generated_pytest_modules/test_data_<component>_generated_<YYYYMMDD_HHMMSSZ>.json` — companion data file referenced by parametrize.

By default, `run.py` also auto-copies generated files into component folders:

- `tests/<component>/test_<component>_generated_<timestamp>.py`
- `test_data/<component>/test_data_<component>_generated_<timestamp>.json`

You can also generate one shared module at repo root paths:

- `tests/test_<name>.py`
- `test_data/<name>.json`

with `--flat-output --output-name <name>`.

## When to invoke

- `/test-generator`
- "generate pytest from spec sheet"
- "convert testcases.xlsx into a pytest module"

## Inputs

| Source | How to pass | Notes |
|---|---|---|
| Local xlsx | `--source file <name.xlsx>` | Looks up in `received_spec_sheets/`; absolute paths also accepted |
| Local xlsx (latest) | `--source file` (no locator) | Auto-picks newest `.xlsx` in `received_spec_sheets/` |
| Local endpoint JSON | `--source file <name.json>` | JSON entries with `endpoint_url`, `method`, optional `response_fields` |
| Remote xlsx | `--source url <https://...xlsx>` | Reuses `testcase-generator/scripts/fetch_url.py` for the safety guardrail (no duplication) |

The xlsx must follow the `testcase-generator` column format (a `TestCases` sheet whose headers match `testcase-generator/templates/testcase_columns.yaml`).

### Seed-backed test_data (default for generated JSON path)

If you do **not** pass `--test-data`, the generator now auto-hydrates row values from:

- `.claude/skills/test-data-generator/config/seeds/<component>.yaml`
- `.claude/skills/test-data-generator/config/endpoint_param_map.yaml`

This removes placeholder values like `"sample"` in request params and includes `seed_source`.
Use `--no-seed-source` to disable this fallback, or `--seed-fanout` to multiply positive rows across all seeds.

### Response body validation (generated tests)

Successful `test_positive` / `test_edge` paths now call validators from `src/validators.py` (not inline asserts):

- **weather** `/forecast` → `validate_weather_response(...)` (timezone, hourly temps, env thresholds)
- **countries** → `validate_countries_schema(payload)` on first list item when applicable
- **schema** bucket → same validator path as positive

## Reuse map — nothing is duplicated

| Reused asset | Source | How |
|---|---|---|
| URL safety guardrail | `.claude/skills/testcase-generator/scripts/fetch_url.py` | subprocess call |
| Canonical column order | `.claude/skills/testcase-generator/templates/testcase_columns.yaml` | YAML read |
| Component → marker map | `.claude/skills/testcase-generator/config/component_markers.yaml` | YAML read |
| Test patterns | `tests/weather/test_weather.py`, `tests/countries/test_countries.py` | structure mirrored exactly |
| Framework rules | `.claude/rules/*.md` | enforced in generated code |

## Output guarantees

The generated pytest module follows every framework rule from `.claude/rules/`:

- `from src.client import ApiClient` — no `import requests`.
- `from src.validators import validate_<component>_schema` — per-component validators; no inline assertions.
- `_load_cases()` reads the companion JSON at module level — no inline data literals.
- Class-level `@allure.feature(...)` + `@pytest.mark.<component>`; module-level `pytestmark = pytest.mark.regression` on copies under `tests/`.
- Method-level `@allure.story(...)`.
- Type hints on every signature.
- `LOG = logging.getLogger(__name__)` at the top — no `print()`.
- Negative cases assert on `ApiError.status_code == expected_status`.
- Performance cases pull threshold from `env_config["max_response_time"]` — never hardcoded.

## Validator naming convention

The skill uses **per-component** validator names derived from each row's `component` field:

| Component | Validator referenced |
|---|---|
| `countries` | `validate_countries_schema` |
| `weather` | `validate_weather_schema` |
| anything else | `validate_<component>_schema` |

If a referenced validator doesn't yet exist in `src/validators.py`, pytest's collection will fail. The console summary lists every validator the generated file imports so you can confirm they're in place before running the tests.

## Execution flow

```bash
python .claude/skills/test-generator/scripts/run.py --source file <xlsx>
```

Internally:

1. `run.py` resolves the xlsx path (local lookup or URL fetch through the reused guardrail).
2. `parse_spec_sheet.py` reads the `TestCases` sheet, validates the column header, and groups rows by `(component, endpoint_url, method)`. Cross-API workflow rows are pulled out separately.
3. `generate_pytest.py` emits one class per endpoint group, parametrized by `case_type` bucket (positive / negative / edge / schema / performance), and a `TestCrossApiWorkflows` class for the chained recipes.
4. The companion JSON is written with the same per-class bucket structure so a single `_load_cases()` helper can drive every `@pytest.mark.parametrize`.
5. `run.py` prints a structured summary.

## Logging & exception handling

- Every script uses `LOG = logging.getLogger(__name__)`. INFO for milestones (file read, group count, output written); WARNING for skipped rows; ERROR with exit code 2 for unrecoverable problems.
- All filesystem and YAML/xlsx reads are wrapped — missing files exit with `[test-generator] file not found: ...`, malformed sheets exit with `[test-generator] spec sheet missing required column: ...`.
- Subprocess calls forward child stderr verbatim and propagate exit codes.

## Output + auto-copy behavior

Default behavior:

- write artifacts to `.claude/skills/test-generator/generated_pytest_modules/`
- auto-copy `.py` into `tests/<component>/`
- auto-copy `.json` into `test_data/<component>/`

If you want draft-only generation, disable auto-copy:

```bash
python .claude/skills/test-generator/scripts/run.py --source file <xlsx> --no-autocopy-tests
```

## Incremental release workflow (default intent)

This skill is designed for **additive** automation per release, not full re-generation of an entire component on every sprint.

| Release | Test plan | Spec sheet | Automation |
|---------|-----------|------------|------------|
| R1 — feature X | Cases for X | Rows for X (`testcase-generator`) | One timestamped module for X |
| R2 — feature Y | **Delta** cases for Y only | **Add** rows for Y; keep X rows reviewed/approved | **New** timestamped module for Y only |

**Do by default**

- Grow the spec sheet incrementally; use `testcase-generator --against <previous.xlsx>` when updating from the same source.
- Feed `test-generator` only **new or changed** rows (filtered xlsx, thin endpoint JSON, or a delta sheet) — not the full historical sheet unless you intend a wholesale refresh.
- Treat each auto-copied `test_<component>_generated_<timestamp>.py` as an audit artifact for that generation event; keep `@pytest.mark.regression` on modules under `tests/`.
- After review, merge stable cases into baseline modules (`tests/weather/test_weather.py`, `tests/countries/test_countries.py`) or keep **one** active generated module per component in CI; retire superseded `*Z.py` files manually when they overlap.

**Do not assume**

- Full-component regen every release — rare; only for taxonomy changes, generator fixes, or deliberate refactors.
- Automatic dedup/replace on auto-copy — timestamped filenames are intentional; deleting prior modules is a **human** curation step.

**Why no auto-dedup on copy**

Re-running the skill always adds a new `test_*_<YYYYMMDD_HHMMSSZ>.py` under `tests/<component>/`. That matches release-by-release additions. The risk is accidental **full** regen (duplicate coverage in pytest), not adding Release 2 tests. Guard with scoped input and post-review cleanup, not replace-before-copy.

**Optional draft flow**

```bash
python .claude/skills/test-generator/scripts/run.py --source file <delta.xlsx> --no-autocopy-tests
# review under generated_pytest_modules/, then copy or merge into tests/ once approved
```

## Verification

After running once on each trimmed xlsx:
- `.py` parses cleanly via `ast.parse`.
- `flake8 --select=E9,F` reports no syntax or import errors on the generated file.
- The class count equals the number of unique `(component, endpoint_url, method)` tuples in the xlsx.
- The total parametrize entry count equals the row count in the xlsx (minus cross-API workflow rows, which become dedicated methods).
- Every class has exactly one `@pytest.mark.<component>` and one `@allure.feature`.
- Every method has `@allure.story`.
- Imports include `from src.validators import validate_<component>_schema` for each component present in the sheet.
