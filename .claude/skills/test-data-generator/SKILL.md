---
name: test-data-generator
description: Read a testcase-generator spec sheet (xlsx) or a thin endpoint JSON, substitute placeholder values with REALISTIC values from a curated seed YAML, and write a companion test_data JSON that the test-generator skill consumes. Fully offline — no live API calls. Preserves the spec sheet's row count by default; opt-in fan-out is available.
---

# test-data-generator (Skill 2 of 4)

Replaces dummy values like `"sample"` / `"missing"` in a spec sheet with realistic values from a curated seed YAML — so the downstream pytest tests assert against real resources (Germany, Brazil, …) instead of placeholder strings.

## Pipeline position

```
testcase-generator  →  spec sheet (xlsx)
                          ↓
test-data-generator (THIS SKILL) — reads spec + seeds → test_data JSON
                          ↓
validator-generator  →  Python validator functions
                          ↓
test-generator       →  pytest module + companion JSON
```

## When to invoke

- `/test-data-generator`
- "generate test data from this spec sheet"
- "substitute placeholders with real values"

## Inputs

| Source | How to pass | Notes |
|---|---|---|
| Spec sheet (xlsx) | `--source file <name.xlsx>` | Looked up in `received_spec_sheets/`; auto-picks newest if no name |
| Single/multi endpoint JSON | `--source json <name.json>` | Same shape as test-generator's JSON mode |
| **Seed dataset** | `config/seeds/<component>.yaml` | Curated; one file per component. Built-in: countries, weather |
| **Endpoint-param map** | `config/endpoint_param_map.yaml` | Maps each endpoint pattern to the seed field that feeds each path/query param |

## Output

Two files per run, both timestamped:

| File | Location | Contents |
|---|---|---|
| `test_data_<component>_generated_<YYYYMMDD_HHMMSSZ>.json` | `generated_test_data/` | Per-class bucket structure consumed by test-generator's `_load_cases()` helper |
| `report_<component>_<YYYYMMDD_HHMMSSZ>.txt` | `generated_test_data/` | Summary: rows seeded / skipped / endpoints missing from param map / suggested fixes |

### JSON shape

Same shape that test-generator's companion JSON uses — drop-in compatible:

```json
{
  "countries__GET__/name/{name}": {
    "positive": [
      {"tc_id": "TC_COUNTRIES_521fe7",
       "path_params": {"name": "Germany"},
       "query_params": {},
       "expected_status": 200,
       "seed_source": "countries.yaml#0"}
    ],
    "negative": [
      {"tc_id": "TC_COUNTRIES_3e7ad0",
       "path_params": {"name": "zzzzz_nonexistent_name"},
       "expected_status": 404}
    ],
    "performance": [...],
    "edge": [...]
  }
}
```

Categories that the API can't realistically be made to return (`negative_server_5xx`, `negative_rate`) get `"skip": true, "skip_reason": "..."` so the downstream pytest test simply skips them rather than failing.

## CLI

```bash
# Auto-pick newest spec sheet, use built-in seeds & map
python .claude/skills/test-data-generator/scripts/run.py --source file

# Explicit name
python .claude/skills/test-data-generator/scripts/run.py \
  --source file testcases_url_countries_final_20260521_074421Z.xlsx

# Auto-chain output into the next skill's received_test_data/
python .claude/skills/test-data-generator/scripts/run.py --source file --chain

# Multiply rows by seed records (default OFF — preserves spec-sheet row count)
python .claude/skills/test-data-generator/scripts/run.py --source file --fanout

# JSON-mode (single endpoint or list)
python .claude/skills/test-data-generator/scripts/run.py --source json endpoints.json
```

### Flags

- `--source file|json` (required)
- `locator` (optional positional — newest used if omitted)
- `--component <name>` — override the component for output naming and seed lookup
- `--chain` — also copy the output into `../test-generator/received_test_data/`
- `--fanout` — emit one row per (spec-sheet row × seed record) instead of one row per spec-sheet row
- `--force` — overwrite if same-timestamp output already exists (rare)

## How substitution works (no live API)

1. **Load seeds.** `config/seeds/<component>.yaml` provides 5 curated records (e.g., Germany, Brazil, Japan, Australia, Argentina for countries) with all the fields any endpoint needs — country name, alpha codes, capital, currency, language, region, latlng, etc.
2. **Load endpoint param map.** `config/endpoint_param_map.yaml` declares, per endpoint, which seed field feeds which path/query param. Example:
   ```yaml
   "/name/{name}":
     path_params: { name: "{country_name}" }
   ```
3. **Walk each spec-sheet row.** With default fanout ON, rows are multiplied across all seed records. With `--no-fanout`, row count is preserved and **positive rows are distributed across all seed records** (base share per seed; any remainder assigned deterministically) so coverage includes every curated country/city without multiplying total tests. Negative categories still synthesize obviously-invalid values like `"zzzzz_nonexistent_<field>"` so the API returns the expected failure code.
4. **Adjust `expected_status` for negatives** where the taxonomy's documented code can't be triggered by a single ad-hoc request:
   - `negative_server_5xx` (500/502/503/504) → `skip: true`
   - `negative_rate` (429) → `skip: true`
   - All others kept as-is (the negative request is structured to actually elicit the documented code).
5. **Write the JSON + report.**

## Row-count preservation

Default behavior: all rows are fanned out across all curated seed records, so each run covers the full seed set (e.g., all 5 weather seed cities or 5 countries seed records).

Use `--no-fanout` when you need strict row-count preservation (1 spec-sheet row → 1 test_data entry) while still spreading positive rows across the seed set.

## Reuse map (zero duplication)

| Reused | From | How |
|---|---|---|
| Spec-sheet parser | `test-generator/scripts/parse_spec_sheet.py` | subprocess call |
| Column conventions | `testcase-generator/templates/testcase_columns.yaml` | YAML read |
| Component → marker | `testcase-generator/config/component_markers.yaml` | YAML read |

No HTTP client, no URL guardrail used — this skill never makes network calls.

## Logging & exception handling

- `LOG = logging.getLogger(__name__)` in every script.
- INFO logs: "Loaded N seed records", "Mapped K of M endpoints", "Wrote test_data + report".
- WARNING logs: "Endpoint X not in param map — using raw row values".
- All errors raised as `SeedError` / `SubstitutionError` and caught at `run.py` boundary — exit code 2 with `[test-data-generator] <message>` to stderr.

## Verification

After running on the trimmed countries xlsx:
- JSON file lands in `generated_test_data/` with correct timestamp.
- Row count equals input row count (36).
- Sample positive case has `path_params.name == "Germany"` (or another real country).
- `negative_server_5xx` rows carry `"skip": true`.
- `report_*.txt` lists no unmapped endpoints.
