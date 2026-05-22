# Priority Rubric

`generate_cases.py` assigns each row a default priority via this rubric. Reviewers
can override in the spreadsheet — the skill preserves edits when re-run.

---

## P0 — Block release if failing

- Authentication / authorization paths (401, 403)
- Data-loss risk (DELETE, destructive PUT/PATCH)
- Top-3 happy paths per endpoint
- Schema-validation cases for required fields in the response
- Performance threshold per endpoint (`max_response_time`)
- Cross-env consistency checks where the same resource exists in both

## P1 — Must pass before sign-off

- Negative validation cases for each required parameter
- Boundary cases (min, max, min-1, max+1)
- Common 404 paths (non-existent ID)
- Conflict / state-transition (409 / 422)
- Idempotency for non-GET methods

## P2 — Coverage / regression bucket

- i18n and special-character cases
- GET idempotency
- "extra unknown field" tolerance
- Rare-state edge cases
- Optional-param-only variants

---

## Priority bias (`--priority-bias` flag)

If invoked with `--priority-bias p0`, every row's priority is **clamped to P0**
(useful for smoke generation). `p1` floor and `p2` floor work analogously.
The bias never *lowers* a priority — only raises it.
