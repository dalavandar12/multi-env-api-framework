# Agent 1: Skill Pipeline Audit Summary

**Date:** 2026-05-22 (re-audit; original: 2026-05-21)
**Audited by:** Agent 1 — Skill Pipeline Agent
**Working directory:** `.claude/skills/`

---

## 1. Skill Existence Check

| Requested skill name   | Actual folder name      | Exists? | Notes |
|------------------------|-------------------------|---------|-------|
| `testcase-generator`   | `testcase-generator/`   | **EXISTS** | Canonical folder; `SKILL.md` `name: testcase-generator`. Companion summary at `.claude/skills/testcase-generator.md`. |
| `test-data-generator`  | `test-data-generator/`  | **EXISTS** | Full folder; `SKILL.md`, `scripts/`, `config/seeds/`, `generated_test_data/`. Companion summary at `.claude/skills/test-data-generator.md`. |
| `validator-generator`  | `validator-generator/`  | **EXISTS** | Full folder; `SKILL.md`, `scripts/`, `received_schemas/`, `generated_validators/`. Companion summary at `.claude/skills/validator-generator.md`. |
| `test-generator`       | `test-generator/`       | **EXISTS** | Full folder; `SKILL.md`, `scripts/`, `generated_pytest_modules/`, `received_test_data/`. Companion summary at `.claude/skills/test-generator.md`. |

**All four skills are present. No skills are missing.**

### Folder layout at `.claude/skills/`

```
testcase-generator/          ← skill folder (canonical)
testcase-generator.md        ← brief companion pointer doc (new since 2026-05-21)
test-data-generator/
test-data-generator.md
validator-generator/
validator-generator.md
test-generator/
test-generator.md
```

**Note on prior name:** The folder was previously named `generate-testcases`. It has been renamed to `testcase-generator` (folder name, SKILL.md `name:` field, and all internal references updated). No `generate-testcases/` folder remains.

**Note on companion `.md` files:** Four new top-level `.md` files were added alongside each skill folder. Each is a one-paragraph pointer doc that says the canonical definition is in the corresponding `SKILL.md`. They do not replace the `SKILL.md` — they are lightweight discovery aids.

### Generated-output state (as of this audit)

All four generated-output directories are **clean** (only `.gitkeep` present). Prior accumulated files from earlier runs were cleared when the skills were reorganised.

---

## 2. What Each Skill Does

### Skill 1 — `testcase-generator`

**Folder:** `.claude/skills/testcase-generator/`
**Role:** *Spec Sheet Generator* — first step of the pipeline

Turns any of five input sources into a structured Excel (or CSV / JSON / txt) test-case spec sheet. Each row represents one test case spanning positive, negative, schema, boundary, i18n, idempotency, cross-env, and performance categories.

**Inputs:** public URL · Jira ticket · Confluence page · local file (txt/md/docx/pdf) · OpenAPI/Swagger spec

**Key behaviours:**
- LLM extraction is the primary path (Claude reads the source semantically); regex heuristics (`--regex-fallback`) are an explicit lossy fallback for CI environments without an LLM.
- Weather generation is constrained to `GET /forecast` only — all other Open-Meteo paths are dropped by `_filter_weather_forecast_only()` in `run.py`.
- Output filenames always include a UTC timestamp: `testcases_<source>_<component>_<YYYYMMDD_HHMMSSZ>.<ext>`.
- Each row carries `validator_ref` (matching a `src/validators.py` function) and `test_data_ref` (matching a `test_data/*.json` key) hints.
- Incremental mode: `--against <prior.xlsx>` produces a Delta sheet and preserves rows marked `Reviewed`/`Approved`.
- `_hint_prior_spec()` in `run.py` auto-prints a `Tip:` message when an existing spec is found for the same component but `--against` was not passed.

**Entry point:** `scripts/run.py`
**Key scripts:** `run.py` → `generate_cases.py` → `write_output.py`; parsers: `parse_openapi.py`, `parse_document.py`, `parse_jira.py`, `parse_confluence.py`, `fetch_url.py`

---

### Skill 2 — `test-data-generator`

**Folder:** `.claude/skills/test-data-generator/`
**Role:** *Realistic Test-Data Hydrator* — second step of the pipeline

Reads a `testcase-generator` spec sheet (xlsx) or thin endpoint JSON and replaces placeholder values (e.g., `"sample"`) with realistic values from curated seed YAMLs. Makes no live API calls.

**Inputs:**
- Spec sheet xlsx (from `testcase-generator`) → looked up in `received_spec_sheets/`
- Seed data: `config/seeds/countries.yaml` (Germany, Brazil, Japan, Australia, Argentina), `config/seeds/weather.yaml`
- Routing rules: `config/endpoint_param_map.yaml` — maps each endpoint pattern to the seed field feeding each param

**Key behaviours:**
- Two output files per run: `test_data_<component>_generated_<ts>.json` + `report_<component>_<ts>.txt`.
- `--fanout` (default ON) multiplies positive rows across all seed records; `--no-fanout` preserves row count while still distributing positives across seeds.
- `--chain` auto-copies the JSON into `test-generator/received_test_data/`.
- `negative_server_5xx` and `negative_rate` rows get `"skip": true` — the API cannot be made to return these codes by a single request.
- Reuses `test-generator/scripts/parse_spec_sheet.py` and `testcase-generator/templates/` via subprocess — no duplication.

**Entry point:** `scripts/run.py`
**Key scripts:** `run.py` → `parse_input.py` → `load_seeds.py` + `substitute.py` → `write_test_data.py`

---

### Skill 3 — `validator-generator`

**Folder:** `.claude/skills/validator-generator/`
**Role:** *Python Validator Emitter* — runs in parallel with or after Skill 2

Converts a hand-curated schema YAML into a `validate_<component>_schema(data)` function that matches the assert-based, recursive style of this repo's `src/validators.py`. Output is review-first; `--write-to-validators` appends it automatically.

**Inputs:** `received_schemas/<component>.yaml` (currently: `countries.yaml`, `weather.yaml`)

**Supported field types:** `string`, `integer`, `number`, `boolean`, `number_or_null`, `string_or_null`, `object` (recursive), `array`

**Key behaviours:**
- Output: `generated_validators/validate_<component>_<YYYYMMDD_HHMMSSZ>.py`.
- `--write-to-validators` inserts the function inside the `# === auto-generated validators (DO NOT EDIT) ===` … `# === end auto-generated ===` block in `src/validators.py`.
- `--force` required to overwrite an existing same-named function inside the block.
- Refuses to overwrite a hand-written function that exists **outside** the block without `--force` — protects manually authored validators.
- Makes no network calls.

**Entry point:** `scripts/run.py`
**Key scripts:** `run.py` → `parse_schema.py` → `emit_validator.py`

---

### Skill 4 — `test-generator`

**Folder:** `.claude/skills/test-generator/`
**Role:** *Pytest Module Emitter* — final step of the pipeline

Reads a spec-sheet xlsx (from `testcase-generator`) plus optional pre-built test-data JSON (from `test-data-generator`) and emits a fully compliant pytest module + companion JSON. If no test-data JSON is provided, it auto-hydrates values from seeds via `test-data-generator`'s substitution logic.

**Key behaviours:**
- Three input modes: `--source file` (xlsx or endpoint JSON), `--source cli` (single endpoint via flags), `--source json` (endpoint list JSON).
- Generated code follows all framework rules: `ApiClient` via fixture, `from src.validators import …`, `@allure.feature`/`@allure.story`, type hints, `LOG = logging.getLogger(...)`, `pytest_check` for multi-item loops, `env_config["max_response_time"]` for thresholds.
- Output: `generated_pytest_modules/test_<component>_<ts>.py` + `test_data_<component>_<ts>.json`.
- **Auto-copies** both files to `tests/<component>/` and `test_data/<component>/` by default; suppress with `--no-autocopy-tests`.
- Reuses `testcase-generator/scripts/fetch_url.py` for safety-checking remote xlsx URLs.
- Console summary lists every `validate_*` function referenced so missing validators are caught before the test run.

**Entry point:** `scripts/run.py`
**Key scripts:** `run.py` → `parse_spec_sheet.py` → `generate_pytest.py`

---

## 3. Pipeline Flow

```
[1] testcase-generator
        input : URL / Jira / Confluence / local file / OpenAPI spec
        output: generated_spec_sheets/testcases_<src>_<comp>_<YYYYMMDD_HHMMSSZ>.xlsx
                          │
                          ▼
[2] test-data-generator
        input : spec sheet xlsx  +  config/seeds/<comp>.yaml  +  config/endpoint_param_map.yaml
        output: generated_test_data/test_data_<comp>_generated_<ts>.json
                          │                        │
                          │                        ▼ (optional, parallel)
                          │              [3] validator-generator
                          │                  input : received_schemas/<comp>.yaml
                          │                  output: generated_validators/validate_<comp>_<ts>.py
                          │                          → (opt) src/validators.py (auto-gen block)
                          ▼
[4] test-generator
        input : spec sheet xlsx  +  test_data JSON  (or auto-seed hydration)
        output: generated_pytest_modules/test_<comp>_<ts>.py
                auto-copied → tests/<comp>/test_<comp>_<ts>.py
                auto-copied → test_data/<comp>/test_data_<comp>_<ts>.json
```

---

## 4. Duplicate-Generation Guardrails: Audit

### 4a. Present guardrails

| Skill | Guardrail | Mechanism |
|---|---|---|
| `testcase-generator` | **Unique output filenames** | UTC timestamp suffix in `write_output.py:_output_path()`. Filenames never collide across runs. |
| `testcase-generator` | **Reviewed/Approved row preservation** | `write_output.py:_merge_with_previous()` keeps rows with `review_status=Reviewed/Approved` intact unless `--force` is passed. |
| `testcase-generator` | **sha1-based `tc_id`** | `generate_cases.py` uses deterministic sha1 so the same endpoint+category always produces the same ID, enabling merge to detect unchanged rows. |
| `testcase-generator` | **Weather endpoint filter** | `_filter_weather_forecast_only()` drops all non-`GET /forecast` paths, preventing scope creep. |
| `testcase-generator` | **`--against` hint** *(new since 2026-05-21)* | `run.py:_hint_prior_spec()` scans `generated_spec_sheets/` for a prior run with the same component and prints a `Tip:` message suggesting `--against <path>` if found. **This closes the previously-noted gap** about `--against` being opt-in with no nudge. |
| `test-data-generator` | **Unique output filenames** | UTC timestamp + `_generated_` infix in `write_test_data.py:output_paths()` → `test_data_<comp>_generated_<ts>.json`. |
| `test-data-generator` | **`--force` flag** | Required to overwrite if a same-timestamp file already exists. |
| `test-generator` | **Unique output filenames** | UTC timestamp suffix in `run.py:_output_paths()`. |
| `test-generator` | **`--no-autocopy-tests` flag** | Suppresses auto-copy for draft-only generation. |
| `validator-generator` | **Unique output filenames** | UTC timestamp suffix in `emit_validator.py:write_file()`. |
| `validator-generator` | **Auto-gen block fence** | `--write-to-validators` writes only inside the `# === auto-generated validators ===` fence; refuses to touch hand-written functions. |
| `validator-generator` | **`--force` required to overwrite** | Existing same-named function inside the block cannot be silently replaced. |

### 4b. Remaining gaps

| Gap | Location | Risk | Recommendation |
|---|---|---|---|
| **No collision check before auto-copy in `test-generator`** | `run.py:_autocopy_to_tests()` lines 406–434 | `shutil.copy2()` runs unconditionally. Re-running the pipeline for the same spec sheet adds another timestamped `test_<comp>_<ts>.py` to `tests/<comp>/`. pytest collects all of them, duplicating coverage and slowing the run. | Before copying, check whether any `test_<comp>_*.py` already exists in the target directory and either warn the user or skip the copy. Alternatively, switch the default to `--no-autocopy-tests` and require an explicit opt-in flag. |
| **No cross-skill pipeline manifest** | Pipeline-wide | Skills operate independently on files. There is no record linking a spec sheet → test-data JSON → validator → pytest module. Running the pipeline twice on the same source produces duplicate artefacts with no visibility into which inputs were already processed. | Add a lightweight `agent_outputs/pipeline_state.json` that each skill appends to, tracking `{source_hash → spec_sheet → test_data → validator → test_module}` lineage. Any skill invocation can check the manifest before generating a new output. |
| **No stale-file cleanup mechanism in any skill** | All `generated_*/` folders | Although all output dirs are currently clean, repeated pipeline runs will accumulate files again. No `--clean` flag or `max_keep=N` policy exists. | Add `--clean-old` or `max_keep=3` to `write_output.py`, `write_test_data.py`, and `emit_validator.py` to prune older files for the same component automatically. |

---

## 5. Summary

| Item | Status |
|---|---|
| `testcase-generator` exists | ✅ `testcase-generator/` — canonical name, SKILL.md confirmed |
| `test-data-generator` exists | ✅ `test-data-generator/` — full structure present |
| `validator-generator` exists | ✅ `validator-generator/` — full structure present |
| `test-generator` exists | ✅ `test-generator/` — full structure present |
| Missing skills | **None** |
| Companion `.md` pointer docs | ✅ All four present at `.claude/skills/*.md` (new 2026-05-22) |
| Generated output dirs | ✅ Clean — no accumulated artefacts |
| `--against` diff-mode nudge | ✅ Now implemented via `_hint_prior_spec()` in `testcase-generator/scripts/run.py` |

