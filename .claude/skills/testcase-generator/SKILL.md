---
name: testcase-generator
description: Generate a reviewer-ready API test-case spec sheet from a URL, Jira ticket, Confluence page, local document (txt/md/docx/pdf), or OpenAPI/Swagger spec. Default output is xlsx in the skill's generated_spec_sheets/ folder.
---

# testcase-generator

Turn any of five input sources into a structured test-case spec sheet. The sheet is the **input artifact** for hand-authoring pytest tests in this framework — the skill never writes pytest code or `test_data/*.json` directly (that stays human-curated).

## When to invoke

Trigger phrases:
- "generate test cases from <source>"
- "create testcases for <ticket / url / file>"
- "/testcase-generator"

## Inputs (one required)

| Source | How to pass |
|---|---|
| Public URL | `--source url <https://...>` (HTTPS only, see guardrail below) |
| Multiple URLs | `--source url <https://a,https://b>` (comma-separated) OR `--source url urls.txt` (one URL per line; lookup in received_sources/) |
| Jira ticket | `--source jira <PROJ-123>` (needs Atlassian MCP — see `references/mcp_setup.md`) |
| Confluence page | `--source confluence <pageId-or-url>` (needs Atlassian MCP) |
| Local file | drop into `received_sources/`, then `--source file <name.pdf\|.md\|.docx\|.txt>` |
| OpenAPI/Swagger | drop into `received_sources/` or pass URL, then `--source openapi <path-or-url>` |

## Options

- `--format xlsx|csv|txt|pdf|docx|json` — default `xlsx`
- `--component <name>` — overrides auto-detected component (e.g., `weather`, `countries`)
- `--priority-bias p0|p1|p2` — shift generation toward a priority floor
- `--against generated_spec_sheets/<file>` — diff mode; produces a "Delta" sheet vs the previous run. If omitted and a prior sheet exists for the same source/component, `run.py` prints: `Tip: A previous spec sheet was found. Re-run with --against <path> to compare new/changed test cases.` (hint only — does not auto-enable diff).
- `--force` — allow overwriting rows marked `Reviewed`/`Approved` (default refuses)

## Output

- Path: `.claude/skills/testcase-generator/generated_spec_sheets/testcases_<source>_<component>_<YYYYMMDD_HHMMSSZ>.<ext>`
- Filenames are **always unique** because of the UTC timestamp suffix.
- xlsx contains two sheets: `TestCases` (one row per case) and `Coverage` (endpoints × categories matrix).

## Execution flow

**Single entry point:** `scripts/run.py`. QA never invokes the individual parsers — `run.py` dispatches by `--source`.

```bash
python .claude/skills/testcase-generator/scripts/run.py --source <type> <locator> [options]
```

### Extraction strategy — LLM is primary, regex is fallback

For **OpenAPI/Swagger** sources the endpoint structure is parsed deterministically — no extraction step needed.

For **URL / file / Jira / Confluence** sources, the doc is free-form text and endpoints must be extracted. Two paths:

| Path | When | Quality | How to invoke |
|---|---|---|---|
| **LLM (primary, default)** | Claude session is available (interactive `claude` runs, IDE) | High — reads the doc semantically, won't miss endpoints | No flag. `run.py` emits a `needs_llm_extraction` instruction; Claude reads the saved raw text, builds `endpoints.json`, and re-invokes `run.py --endpoints <path>` |
| **Regex (fallback)** | No LLM available (CI, scripted automation) | Lossy — only catches obvious patterns (`GET /path`, backticked params, status-code lists). May miss endpoints. | `--regex-fallback` flag. Prints a loud warning. |

**Rule:** never use `--regex-fallback` if an LLM is available. It exists only as a last-resort path so the script doesn't block automated environments.

### Under the hood

`run.py` does:

1. **Source validation** —
   - URL: calls `fetch_url.py` (exits non-zero if guardrail fails)
   - File: looks up the name in `received_sources/`, falls back to absolute path
   - Jira/Confluence: emits a JSON instruction for Claude to call Atlassian MCP and re-invoke with `--endpoints <path>`
2. **Extract** — dispatches internally to `parse_openapi.py`, `parse_document.py`, `parse_jira.py`, `parse_confluence.py`, `fetch_url.py`, or (only with `--regex-fallback`) `heuristic_extract.py`.
3. **Normalize** — every parser returns a list of endpoint dicts with this shape:
   ```json
   {
     "method": "GET",
     "path": "/v3.1/name/{name}",
     "summary": "...",
     "params_required": [...],
     "params_optional": [...],
     "request_schema": {...},
     "response_schema": {...},
     "status_codes": [200, 404],
     "examples": {"valid": {...}, "invalid": {...}},
     "source_excerpt": "...",
     "traceability": "<url-or-key>"
   }
   ```
4. **Generate cases** — `python scripts/generate_cases.py <endpoints.json>` expands each endpoint into rows per the taxonomy in `references/test_case_taxonomy.md`.
5. **Tag with framework metadata** — map component → pytest marker via `config/component_markers.yaml`. Pull `expected_response_time_ms` from this repo's `config/environments.yaml` (relative path: `../../../config/environments.yaml`).
6. **Deduplicate & protect reviewed rows** — sha1-based deterministic `tc_id`; rows from prior runs marked `Reviewed`/`Approved` are preserved unless `--force`.
7. **Write output** — `python scripts/write_output.py --rows <rows.json> --format <fmt>`.
8. **Print summary** — counts per category and priority, output path, and a one-line coverage hint (e.g., "no auth-negative cases — source had no auth section").

## URL safety guardrail (`scripts/fetch_url.py`)

Heuristic checks only, no external API:
1. `https://` only.
2. Resolve host → reject private/loopback/link-local IPs.
3. Reject TLDs in `config/url_guardrail.yaml` (default: `.zip`, `.mov`).
4. Honor `robots.txt`.
5. Content-Type must be one of `text/html`, `text/plain`, `application/json`, `application/yaml`, `application/pdf`.
6. Stream cap: 10 MB.
7. Max 5 redirects, each re-validated.

On failure, exit non-zero with: `[guardrail] URL rejected: <reason>. See config/url_guardrail.yaml to adjust.`

## Test-case taxonomy

See `references/test_case_taxonomy.md` for the full list. Every endpoint produces rows across these categories:

- **Positive** — happy path, all-optional, minimum-required-only
- **Negative — validation (400)** — missing/wrong-type/wrong-format/out-of-enum/extra field
- **Negative — auth (401/403)** — missing/expired/wrong-scope token (if doc mentions auth)
- **Negative — not found (404)** — non-existent / deleted resource
- **Negative — conflict (409/422)** — duplicate, state-transition violation
- **Schema validation** — required fields, types, enums, nested shape
- **Boundary / BVA** — numeric/string/array min, min−1, max, max+1, null vs missing
- **Special characters / i18n** — UTF-8, emoji, RTL, injection strings
- **Idempotency** — GET/PUT/DELETE re-application
- **Cross-env / integration** — same resource in multiple components → both markers
- **Performance** — response time ≤ `env_config.max_response_time`

## Output column spec

See `templates/testcase_columns.yaml` for the canonical order. Key columns: `tc_id`, `title`, `category`, `priority`, `component`, `pytest_marker`, `endpoint_url`, `method`, `path_params`, `query_params`, `headers`, `request_body`, `preconditions`, `expected_status`, `expected_response_fields`, `expected_response_time_ms`, `test_data_ref`, `validator_ref`, `traceability`, `source_excerpt`, `review_status`, `notes`.

## Framework alignment

Each generated row carries hints toward this repo's existing patterns:
- `validator_ref` suggests a `validate_*` function name in `src/validators.py` (no inline asserts).
- `test_data_ref` suggests a key in `test_data/*.json` (no inline parametrize literals).
- `pytest_marker` resolves to `@pytest.mark.countries` / `@pytest.mark.weather` / etc.
- `expected_response_time_ms` mirrors the active `max_response_time` from `config/environments.yaml`.

## Weather guardrail in this repo

For this repository, Weather testcase generation is intentionally constrained to the
single supported endpoint:

- `GET https://api.open-meteo.com/v1/forecast`

When you run `scripts/run.py` with `--component weather`, the runner keeps only
`GET /forecast` endpoints and drops all other weather paths (`/climate`, `/flood`,
`/seasonal`, `/ensemble`, etc.) before row expansion.

## Verification

After running the skill at least once, confirm:
- Output filename ends in `_<YYYYMMDD_HHMMSSZ>.<ext>` (unique).
- xlsx has both `TestCases` and `Coverage` sheets.
- A bad URL (private IP, `http://`, blocked TLD) exits non-zero with `[guardrail]` prefix.
- Re-running with `--against <previous>.xlsx` produces a `Delta` sheet.
- A row marked `review_status=Approved` survives the next run.
