# Test Case Taxonomy

Every endpoint discovered by the skill produces rows across the categories below.
`generate_cases.py` walks this taxonomy in order.

---

## 1. Positive (`category: positive`)

| Sub-type | What it covers |
|---|---|
| Happy path | All required params with canonical sample values |
| All-optional variant | Required + every optional param populated |
| Minimum-required-only | Only required params, optionals omitted |

Expected status: 2xx. Validator hint: `validate_<resource>_schema`.

---

## 2. Negative — Validation (`category: negative_validation`, status 400)

One row per required param (missing) + one row per type/format mismatch.

| Sub-type | Equivalence class |
|---|---|
| Missing required field `<X>` | `missing-required-<X>` |
| Wrong type for field `<X>` (int → string) | `wrong-type-<X>` |
| Wrong format (e.g., date not ISO-8601) | `wrong-format-<X>` |
| Out-of-enum value for field `<X>` | `enum-violation-<X>` |
| Extra unknown field | `extra-field` |

---

## 3. Negative — Auth (`category: negative_auth`, status 401 / 403)

Generated only if source mentions authentication, bearer, OAuth, or API key.

| Sub-type | Expected status |
|---|---|
| Missing token | 401 |
| Expired token | 401 |
| Wrong scope / insufficient permission | 403 |

---

## 4. Negative — Not Found (`category: negative_not_found`, status 404)

| Sub-type |
|---|
| Non-existent ID |
| Deleted resource |

---

## 5. Negative — Conflict / State (`category: negative_conflict`, status 409 / 422)

| Sub-type | Status |
|---|---|
| Duplicate create | 409 |
| State-transition violation | 422 |

Only emitted for `POST`/`PUT`/`PATCH` endpoints that imply state.

---

## 6. Negative — Rate / Throttle (`category: negative_rate`, status 429)

Generated only if source mentions rate limit, throttle, or quota.

---

## 7. Schema Validation (`category: schema`)

| Sub-type |
|---|
| All required response fields present |
| Type correctness for every field |
| Enum membership for every enum field |
| Nested object shape |

---

## 8. Boundary / BVA (`category: boundary`)

For each numeric / string / array field:

| Equivalence class |
|---|
| min |
| min - 1 |
| max |
| max + 1 |
| empty string |
| single char |
| max length |
| max length + 1 |
| empty array |
| single-element array |
| max-size array |
| whitespace-only |
| null value |
| missing field (distinct from null) |

---

## 9. Special Characters / i18n (`category: i18n`)

| Equivalence class |
|---|
| UTF-8 multibyte (é, ü, ç) |
| Emoji (🌍, 🚀) |
| RTL script (مرحبا, שלום) |
| SQL injection (`' OR '1'='1`) |
| HTML/XSS (`<script>alert(1)</script>`) |
| Very long Unicode (10k chars) |

---

## 10. Idempotency (`category: idempotency`)

| Sub-type | Applies to |
|---|---|
| GET stable across N calls | GET |
| PUT re-application same result | PUT |
| DELETE re-application returns 404 or 200 idempotently | DELETE |

---

## 11. Cross-env / Integration (`category: cross_env`)

Emitted when the same resource name appears in two or more components
(detected by string match on the endpoint path or example body). The row
carries multiple markers (e.g., `@pytest.mark.countries` and
`@pytest.mark.weather`) and lists both component base URLs.

---

## 12. Performance (`category: performance`)

One row per endpoint. `expected_response_time_ms` is pulled from this
repo's `config/environments.yaml` so it always matches the live threshold.

---

## 13. Status-code coverage (auto-expanded)

For every status code declared in the source's `responses` block that the
preceding categories didn't already cover, generate_cases.py emits one row.
Mapping table:

| Code | Category | Default priority |
|---|---|---|
| 202 | `async_accepted` | P1 |
| 400 | `negative_validation` | P1 |
| 401 / 403 | `negative_auth` | P0 |
| 404 | `negative_not_found` | P1 |
| 405 / 406 / 410 / 415 | `negative_client_4xx` | P2 |
| 409 / 422 | `negative_conflict` | P1 |
| 429 | `negative_rate` | P1 |
| 500 / 503 | `negative_server_5xx` | P0 |
| 502 / 504 | `negative_server_5xx` | P1 |
| any other 4xx | `negative_client_4xx` | P2 |
| any other 5xx | `negative_server_5xx` | P1 |

---

## 14. Cross-API workflow (`category: cross_api_workflow`)

Chained multi-component tests defined in `config/cross_api_workflows.yaml`.
A workflow emits one row only when **all** required components are present
in the endpoint list for the run.

The `workflow_steps` column carries the ordered call sequence:

```
[
  {component, method, path, path_params, query_params,
   expect_status, extract: [{from_response, as}],
   validate: [{field, assertion, tolerance?}]},
  ...
]
```

Example shipped recipe — `country_lookup_to_weather`:

1. `GET /v3.1/name/{name}` (countries) → extract `latlng[0]` as `latitude`, `latlng[1]` as `longitude`
2. `GET /v1/forecast` (weather) with `${latitude}` and `${longitude}` → validate `timezone` present, `hourly.temperature_2m` non-empty, response coordinates within 0.5° of input.

Add more recipes by editing `config/cross_api_workflows.yaml`.

---

## Hallucination guardrail

Every generated row MUST carry:
- `source_excerpt` — the exact quoted snippet from the source that justified the case (PII-scrubbed)
- `traceability` — URL, Jira key, Confluence page, or `file:line`

If a category can't be supported by a concrete excerpt, the row is **not emitted** —
the skill prefers under-generation over fabrication.
