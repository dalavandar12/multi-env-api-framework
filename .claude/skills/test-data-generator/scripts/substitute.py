"""Core substitution logic — replace placeholder values in spec rows with seed values.

For each spec-sheet row:
  - Positive:
      If --fanout is requested, fan out across all seed records.
      If --no-fanout is used, preserve row count and distribute positive rows
      across all seed records without multiplication.
  - Non-positive buckets (schema / performance / edge / negative):
      Preserve row count by using a single deterministic seed record.
  - Negative-*:
      Synthesize an obviously-invalid value (e.g. 'zzzzz_nonexistent_name').
  - negative_server_5xx / negative_rate:
      Cannot be triggered by a single ad-hoc request → mark `skip: true`.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

LOG = logging.getLogger(__name__)

_TEMPLATE_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

_UNRUNNABLE_CATEGORIES = {
    "negative_server_5xx": "5xx responses can't be triggered by a single ad-hoc request",
    "negative_rate": "429 needs sustained burst load — not reachable in a single GET",
}


class SubstitutionError(Exception):
    """Raised when substitution cannot produce a usable value."""


def _render(template: str, record: dict[str, Any]) -> str:
    """Replace {field} with record[field]. Leave plain strings untouched."""
    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in record:
            raise SubstitutionError(
                f"seed field '{key}' missing from record. "
                f"Available: {sorted(record.keys())}"
            )
        return str(record[key])
    return _TEMPLATE_RE.sub(repl, template)


def _apply_param_map(
    endpoint_map: dict[str, dict[str, str]],
    record: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    """Render the path_params / query_params for one endpoint and one seed record."""
    path_params: dict[str, str] = {}
    query_params: dict[str, str] = {}
    for name, tmpl in (endpoint_map.get("path_params") or {}).items():
        path_params[name] = _render(str(tmpl), record)
    for name, tmpl in (endpoint_map.get("query_params") or {}).items():
        query_params[name] = _render(str(tmpl), record)
    return path_params, query_params


def _strip_base_path(endpoint_url: str) -> str:
    """Strip scheme+host so the param map can key on the relative path."""
    if not endpoint_url:
        return ""
    m = re.match(r"https?://[^/]+(.*)$", endpoint_url)
    full = m.group(1) if m else endpoint_url
    # Strip leading /v3.1 or /v1 etc. that may be part of the URL
    return re.sub(r"^/v[0-9]+(\.[0-9]+)*", "", full) or "/"


def _synthesize_invalid(field_name: str) -> str:
    """Generate an obviously-invalid value for a negative test path/query param."""
    return f"zzzzz_nonexistent_{field_name}"


def _seed_value_for_field(
    field: str,
    seed_record: dict[str, Any],
    path_params: dict[str, Any],
    query_params: dict[str, Any],
) -> Any:
    """Best-effort field resolver from seed/path/query values."""
    if field in seed_record:
        return seed_record[field]
    if field in path_params:
        return path_params[field]
    if field in query_params:
        return query_params[field]

    # Common aliases for countries/weather payloads.
    if field == "name" and "country_name" in seed_record:
        return seed_record["country_name"]
    if field == "latlng":
        if "latlng" in seed_record:
            return seed_record["latlng"]
        if "latitude" in seed_record and "longitude" in seed_record:
            return [seed_record["latitude"], seed_record["longitude"]]
    if field == "capital" and "capital" in seed_record:
        # Countries API returns capital as list in many endpoints.
        return [seed_record["capital"]]
    return None


def _seeded_expected_response_body(
    current_body: Any,
    expected_fields: list[Any],
    seed_record: dict[str, Any],
    path_params: dict[str, Any],
    query_params: dict[str, Any],
) -> Any:
    """Fill expected_response_body with seed-derived values for positive cases."""
    if not isinstance(current_body, dict) or not expected_fields:
        return current_body

    updated = dict(current_body)
    for raw_field in expected_fields:
        field = str(raw_field)
        seeded_val = _seed_value_for_field(field, seed_record, path_params, query_params)
        if seeded_val is not None:
            updated[field] = seeded_val
    return updated


def _negative_field_from_equivalence(equivalence_class: str) -> tuple[str, str] | None:
    """Parse negative equivalence class into operation + field name."""
    for prefix in ("missing-required-", "wrong-type-", "enum-violation-"):
        if equivalence_class.startswith(prefix):
            return prefix.rstrip("-"), equivalence_class.replace(prefix, "", 1)
    return None


def _find_endpoint_in_map(
    endpoint_url: str, component_map: dict[str, dict[str, dict[str, str]]],
) -> tuple[str, dict[str, dict[str, str]]] | tuple[None, None]:
    """Match the endpoint's relative path against the keys in the param map."""
    rel = _strip_base_path(endpoint_url)
    if rel in component_map:
        return rel, component_map[rel]
    # Try matching by path-template equivalence: convert {x} to a literal lookup
    for pattern, spec in component_map.items():
        if pattern == rel:
            return pattern, spec
    return None, None


def substitute_row(
    row: dict[str, Any],
    seed_record: dict[str, Any],
    component_map: dict[str, dict[str, dict[str, str]]],
    seed_index: int,
    component: str,
) -> dict[str, Any]:
    """Produce one concrete test-data entry from a spec row + one seed record."""
    endpoint_url = row.get("endpoint_url", "")
    endpoint_rel = _strip_base_path(endpoint_url)
    category = (row.get("category") or "").strip()
    case_type = (row.get("case_type") or "").strip()

    pattern, ep_map = _find_endpoint_in_map(endpoint_url, component_map)
    if ep_map is None:
        # No param map entry — keep the row's existing values; downstream test will
        # likely fail to substitute placeholders, so log a warning.
        LOG.warning(
            "No param-map entry for endpoint %s — leaving row values as-is",
            endpoint_url,
        )
        path_params = dict(row.get("path_params") or {})
        query_params = dict(row.get("query_params") or {})
    else:
        try:
            path_params, query_params = _apply_param_map(ep_map, seed_record)
        except SubstitutionError as exc:
            LOG.warning("Substitution failed for %s (%s) — using raw row values",
                        endpoint_url, exc)
            path_params = dict(row.get("path_params") or {})
            query_params = dict(row.get("query_params") or {})

    # Tweak per category
    skip_flag: dict[str, Any] = {}
    expected_status = row.get("expected_status")
    expected_response_body = row.get("expected_response_body")
    if category in _UNRUNNABLE_CATEGORIES:
        skip_flag = {"skip": True, "skip_reason": _UNRUNNABLE_CATEGORIES[category]}
    elif case_type == "negative":
        # Preserve expected_status from the testcase row; mutate only target params.
        eq = str(row.get("equivalence_class") or "")
        parsed = _negative_field_from_equivalence(eq)
        if parsed:
            operation, field = parsed
            if operation == "missing-required":
                path_params.pop(field, None)
                query_params.pop(field, None)
            elif operation == "wrong-type":
                if field in path_params:
                    path_params[field] = "not-a-number"
                elif field in query_params:
                    query_params[field] = "not-a-number"
            elif operation == "enum-violation":
                if field in path_params:
                    path_params[field] = "__INVALID_ENUM__"
                elif field in query_params:
                    query_params[field] = "__INVALID_ENUM__"
        elif eq == "nonexistent-id":
            if path_params:
                key = next(iter(path_params))
                path_params[key] = _synthesize_invalid(key)
                if component == "countries" and endpoint_rel.startswith("/alpha"):
                    expected_status = 400
                    expected_response_body = {
                        "status": 400,
                        "message": "Bad Request — validation failed",
                    }
            elif expected_status == 404:
                # Query-only endpoints (e.g., /independent) typically won't 404
                # for ad-hoc "not found" probes.
                if component == "countries" and endpoint_rel == "/alpha":
                    query_params["codes"] = _synthesize_invalid("codes")
                    expected_status = 400
                    expected_response_body = {
                        "status": 400,
                        "message": "Bad Request — validation failed",
                    }
                else:
                    skip_flag = {
                        "skip": True,
                        "skip_reason": (
                            "404 is not triggerable for this query-only endpoint in a single request"
                        ),
                    }

        if (
            component == "countries"
            and expected_status == 400
            and not endpoint_rel.startswith("/alpha")
        ):
            # RestCountries validation failures typically surface as 404 for non-alpha endpoints
            # (including missing required path values like /name/{name}).
            expected_status = 404
            expected_response_body = {"status": 404, "message": "Not Found"}

    seed_source = (
        f"{seed_record.get('country_name') or seed_record.get('city') or 'record'}"
        f"@index_{seed_index}"
    )

    if case_type == "positive":
        expected_response_body = _seeded_expected_response_body(
            expected_response_body,
            list(row.get("expected_response_fields") or []),
            seed_record,
            path_params,
            query_params,
        )

    return {
        "tc_id":                    row.get("tc_id"),
        "title":                    row.get("title"),
        "description":              row.get("description"),
        "category":                 category,
        "case_type":                case_type,
        "priority":                 row.get("priority"),
        "equivalence_class":        row.get("equivalence_class"),
        "path_params":              path_params,
        "query_params":             query_params,
        "headers":                  row.get("headers") or {"Accept": "application/json"},
        "request_body":             row.get("request_body") or {},
        "preconditions":            row.get("preconditions") or "",
        "expected_status":          expected_status,
        "expected_response_fields": row.get("expected_response_fields") or [],
        "expected_response_body":   expected_response_body,
        "expected_response_time_ms": row.get("expected_response_time_ms"),
        "traceability":             row.get("traceability"),
        "seed_source":              seed_source,
        **skip_flag,
    }


def substitute_groups(
    parsed: dict[str, Any],
    seeds_by_component: dict[str, list[dict[str, Any]]],
    param_map_by_component: dict[str, dict[str, dict[str, dict[str, str]]]],
    fanout: bool,
) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], list[str]]:
    """Walk every group and emit the test_data payload + a list of warning lines."""
    payload: dict[str, dict[str, list[dict[str, Any]]]] = {}
    warnings: list[str] = []

    component_positive_quota: dict[str, list[int]] = {}
    component_positive_idx: dict[str, int] = {}

    for component, seeds in seeds_by_component.items():
        seed_count = len(seeds)
        if seed_count == 0:
            component_positive_quota[component] = []
            component_positive_idx[component] = 0
            continue
        positive_total = 0
        for g in parsed.get("groups", []):
            if g.get("component") != component:
                continue
            positive_total += sum(
                1
                for r in g.get("rows", [])
                if _bucket_for(
                    (r.get("case_type") or "").strip(),
                    (r.get("category") or "").strip(),
                )
                == "positive"
            )
        base = positive_total // seed_count
        remainder = positive_total % seed_count
        quota = [base] * seed_count
        if seed_count:
            # Keep allocation deterministic: any remainder goes to the last seed.
            quota[-1] += remainder
        component_positive_quota[component] = quota
        component_positive_idx[component] = 0

    for group in parsed.get("groups", []):
        component = group["component"]
        seeds = seeds_by_component.get(component)
        if not seeds:
            warnings.append(
                f"no seed records loaded for component '{component}' — "
                f"every row in {group['endpoint_url']} gets default 'unseeded'"
            )
            continue
        component_map = param_map_by_component.get(component) or {}
        if not component_map:
            warnings.append(
                f"no endpoint param map for component '{component}' — "
                f"rows may keep their placeholder values"
            )

        class_key = (
            f"{component}__{group['method']}__"
            f"{_strip_base_path(group['endpoint_url'])}"
        )
        buckets: dict[str, list[dict[str, Any]]] = {}
        positive_quota = component_positive_quota.get(component, [])
        positive_seed_idx = component_positive_idx.get(component, 0)
        seed_count = len(seeds)

        for row in group["rows"]:
            endpoint_rel = _strip_base_path(str(row.get("endpoint_url") or ""))
            equivalence_class = str(row.get("equivalence_class") or "")
            category = (row.get("category") or "").strip()
            case_type = (row.get("case_type") or "").strip()
            bucket_name = _bucket_for(case_type, category)

            # Open-Meteo /forecast accepts missing 'hourly' and still returns 200.
            # Reclassify to positive so generated tests do not expect ApiError.
            row_for_sub = row
            if (
                component == "weather"
                and endpoint_rel == "/forecast"
                and equivalence_class == "missing-required-hourly"
            ):
                row_for_sub = dict(row)
                row_for_sub["category"] = "positive"
                row_for_sub["case_type"] = "positive"
                row_for_sub["expected_status"] = 200
                bucket_name = "positive"
            if fanout:
                targets: list[tuple[int, dict[str, Any]]] = list(enumerate(seeds))
            elif bucket_name == "positive":
                while (
                    positive_seed_idx < seed_count - 1
                    and positive_quota[positive_seed_idx] == 0
                ):
                    positive_seed_idx += 1
                idx = positive_seed_idx
                positive_quota[idx] -= 1
                targets = [(idx, seeds[idx])]
            else:
                targets = [(0, seeds[0])]
            for i, rec in targets:
                buckets.setdefault(bucket_name, []).append(
                    substitute_row(row_for_sub, rec, component_map, i, component)
                )
            component_positive_idx[component] = positive_seed_idx
        payload[class_key] = buckets

    return payload, warnings


def _bucket_for(case_type: str, category: str) -> str:
    if category == "cross_api_workflow":
        return "workflow"
    if category == "performance":
        return "performance"
    if category == "schema":
        return "schema"
    return case_type or "positive"
