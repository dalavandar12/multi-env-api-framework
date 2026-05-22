"""Expand a normalized endpoint list into test-case rows.

Walks the taxonomy in references/test_case_taxonomy.md. Each row carries a
deterministic tc_id (sha1-based), a source_excerpt, and traceability so
re-runs are idempotent.

Input  (stdin): JSON list of endpoint dicts (see SKILL.md "Normalize")
Output (stdout): JSON list of test-case row dicts
"""
import argparse
import hashlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

import yaml

LOG = logging.getLogger(__name__)

_SKILL_ROOT = Path(__file__).parent.parent
_COMPONENT_CFG = _SKILL_ROOT / "config" / "component_markers.yaml"
_WORKFLOWS_CFG = _SKILL_ROOT / "config" / "cross_api_workflows.yaml"
_REPO_ENV = _SKILL_ROOT.parent.parent.parent / "config" / "environments.yaml"

_PII_PATTERNS = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    re.compile(r"\b\+?\d[\d\s().-]{7,}\b"),
    re.compile(r"\b(?:bearer|token|api[_-]?key)\s*[:=]\s*\S+", re.I),
]


_PRIMITIVE_SAMPLE = {
    "integer": 0,
    "number": 0.0,
    "boolean": True,
    "string": "string",
}


def _render_schema_sample(schema: dict[str, Any]) -> Any:
    """Walk a JSON Schema and emit a representative sample value."""
    if not isinstance(schema, dict):
        return None
    if "enum" in schema and isinstance(schema["enum"], list) and schema["enum"]:
        return schema["enum"][0]
    t = schema.get("type")
    if t == "array":
        return [_render_schema_sample(schema.get("items") or {})]
    if t == "object":
        props = schema.get("properties") or {}
        return {k: _render_schema_sample(v) for k, v in props.items()}
    if isinstance(t, str):
        return _PRIMITIVE_SAMPLE.get(t)
    if schema.get("properties"):
        return {k: _render_schema_sample(v) for k, v in schema["properties"].items()}
    return None


_ERROR_MESSAGES = {
    202: "Accepted; processing asynchronously",
    400: "Bad Request — validation failed",
    401: "Unauthorized — missing or invalid credentials",
    403: "Forbidden — insufficient permission",
    404: "Not Found",
    405: "Method Not Allowed",
    406: "Not Acceptable",
    409: "Conflict — duplicate or state violation",
    410: "Gone",
    415: "Unsupported Media Type",
    422: "Unprocessable Entity — validation failed",
    429: "Too Many Requests — rate limit exceeded",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


def _sample_response_body(schema: dict[str, Any], status: int) -> Any:
    """Positive → render schema sample. Error → standard error envelope."""
    if 200 <= status < 300 and status != 202:
        return _render_schema_sample(schema)
    if status == 202:
        return {"status": 202, "job_id": "<job-handle>", "message": _ERROR_MESSAGES[202]}
    if 400 <= status < 600:
        return {"status": status, "message": _ERROR_MESSAGES.get(status, "Error")}
    return None


def _flatten_field_paths(schema: dict[str, Any], prefix: str = "") -> list[str]:
    """Walk schema and return dot-paths for every property (handles array items)."""
    if not isinstance(schema, dict):
        return []
    t = schema.get("type")
    if t == "array":
        return _flatten_field_paths(schema.get("items") or {}, prefix)
    props = schema.get("properties") or {}
    out: list[str] = []
    for name, sub in props.items():
        path = f"{prefix}{name}"
        out.append(path)
        if isinstance(sub, dict) and sub.get("type") in ("object", "array"):
            out.extend(_flatten_field_paths(sub, prefix=f"{path}."))
    return out


def _scrub(text: str) -> str:
    for pat in _PII_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text[:500]


def _load_components() -> dict[str, Any]:
    return dict(yaml.safe_load(_COMPONENT_CFG.read_text()))


def _load_env_thresholds() -> dict[str, float]:
    if not _REPO_ENV.exists():
        return {}
    data = yaml.safe_load(_REPO_ENV.read_text())
    envs = data.get("environments", {}) if isinstance(data, dict) else {}
    return {name: float(cfg.get("max_response_time", 0))
            for name, cfg in envs.items()
            if isinstance(cfg, dict) and "max_response_time" in cfg}


def _resolve_component(endpoint: dict[str, Any], components_cfg: dict[str, Any],
                       override: str | None) -> tuple[str, str]:
    if override:
        marker = components_cfg["components"].get(override, {}).get("marker", override)
        return override, marker
    haystack = " ".join([
        endpoint.get("path", ""), " ".join(endpoint.get("tags") or []),
        endpoint.get("summary", ""),
    ]).lower()
    for name, cfg in components_cfg["components"].items():
        if cfg.get("base_url_hint", "").lower() in haystack or name.lower() in haystack:
            return name, cfg["marker"]
    return "unknown", components_cfg["default"]["marker"]


_CASE_TYPE_MAP = {
    "positive": "positive",
    "schema": "positive",
    "performance": "positive",
    "idempotency": "positive",
    "cross_env": "positive",
    "cross_api_workflow": "positive",
    "async_accepted": "positive",
    "negative_validation": "negative",
    "negative_auth": "negative",
    "negative_not_found": "negative",
    "negative_conflict": "negative",
    "negative_rate": "negative",
    "negative_client_4xx": "negative",
    "negative_server_5xx": "negative",
    "boundary": "edge",
    "i18n": "edge",
}

_STATUS_CODE_CATEGORY = {
    202: ("async_accepted",      "P1"),
    400: ("negative_validation", "P1"),
    401: ("negative_auth",       "P0"),
    403: ("negative_auth",       "P0"),
    404: ("negative_not_found",  "P1"),
    405: ("negative_client_4xx", "P2"),
    406: ("negative_client_4xx", "P2"),
    409: ("negative_conflict",   "P1"),
    410: ("negative_client_4xx", "P2"),
    415: ("negative_client_4xx", "P2"),
    422: ("negative_conflict",   "P1"),
    429: ("negative_rate",       "P1"),
    500: ("negative_server_5xx", "P0"),
    502: ("negative_server_5xx", "P1"),
    503: ("negative_server_5xx", "P0"),
    504: ("negative_server_5xx", "P1"),
}


def _case_type(category: str) -> str:
    return _CASE_TYPE_MAP.get(category, "positive")


def _tc_id(component: str, key: str) -> str:
    digest = hashlib.sha1(f"{component}|{key}".encode()).hexdigest()[:6]
    return f"TC_{component.upper()}_{digest}"


def _describe(category: str, equivalence_class: str, endpoint: dict[str, Any],
              extra_status: int) -> str:
    """Produce a one-line human-readable description from category + class."""
    method = endpoint.get("method", "GET")
    path = endpoint.get("path", "")
    if category == "positive":
        return f"Send valid required params to {method} {path}; expect 2xx with documented fields."
    if category == "negative_validation":
        if equivalence_class.startswith("missing-required-"):
            name = equivalence_class.replace("missing-required-", "", 1)
            return f"Omit required parameter '{name}'; expect HTTP {extra_status} validation error."
        if equivalence_class.startswith("wrong-type-"):
            name = equivalence_class.replace("wrong-type-", "", 1)
            return f"Send wrong-type value for '{name}' (e.g. string for int); expect HTTP {extra_status}."
        if equivalence_class.startswith("enum-violation-"):
            name = equivalence_class.replace("enum-violation-", "", 1)
            return f"Send value outside the enum for '{name}'; expect HTTP {extra_status}."
        return f"Invalid input; expect HTTP {extra_status}."
    if category == "negative_auth":
        return f"Auth scenario '{equivalence_class}'; expect HTTP {extra_status}."
    if category == "negative_not_found":
        return f"Use non-existent resource id; expect HTTP {extra_status}."
    if category == "negative_conflict":
        return f"Trigger duplicate / state-conflict; expect HTTP {extra_status}."
    if category == "negative_rate":
        return f"Send burst above documented rate limit; expect HTTP {extra_status}."
    if category == "schema":
        return "Verify response contains every required schema field with the correct type."
    if category == "boundary":
        return f"Boundary value '{equivalence_class}' for the first numeric required field."
    if category == "i18n":
        return "Send UTF-8 / emoji / RTL / injection inputs; expect graceful handling (no 500)."
    if category == "idempotency":
        return f"{method} re-application — verify identical result across repeated calls."
    if category == "cross_env":
        return "Verify the same resource is consistent across the components listed in pytest_marker."
    if category == "performance":
        ms = endpoint.get("expected_response_time_ms") or 0
        return f"Verify response time <= {ms} ms (from config/environments.yaml)."
    if category == "async_accepted":
        return f"Trigger async/queued response from {method} {path}; expect HTTP 202 with job handle."
    if category == "negative_client_4xx":
        return f"Trigger documented {extra_status} from {method} {path}; verify error body matches spec."
    if category == "negative_server_5xx":
        return f"Simulate upstream/server failure for {method} {path}; expect HTTP {extra_status} surfaced cleanly."
    if category == "cross_api_workflow":
        return "Chained multi-API workflow — see workflow_steps column for the call sequence."
    return ""


def _row(endpoint: dict[str, Any], component: str, marker: str, category: str,
         title: str, key: str, *, status: int, priority: str,
         equivalence_class: str, threshold_ms: int, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    endpoint_with_threshold = {**endpoint, "expected_response_time_ms": threshold_ms}
    base = {
        "tc_id": _tc_id(component, key),
        "title": title,
        "description": _describe(category, equivalence_class, endpoint_with_threshold, status),
        "case_type": _case_type(category),
        "category": category,
        "priority": priority,
        "component": component,
        "pytest_marker": f"@pytest.mark.{marker}",
        "endpoint_url": endpoint.get("path", ""),
        "method": endpoint.get("method", "GET"),
        "path_params": {},
        "query_params": {},
        "headers": {"Accept": "application/json"},
        "request_body": {},
        "preconditions": "",
        "expected_status": status,
        "expected_response_fields": _flatten_field_paths(endpoint.get("response_schema") or {}),
        "expected_response_body": _sample_response_body(endpoint.get("response_schema") or {}, status),
        "expected_response_time_ms": threshold_ms,
        "equivalence_class": equivalence_class,
        "test_data_ref": f"test_data/{component}.json#{equivalence_class or 'happy'}",
        "validator_ref": f"validate_{component}_schema",
        "traceability": endpoint.get("traceability", ""),
        "source_excerpt": _scrub(endpoint.get("source_excerpt", "")),
        "workflow_steps": [],
        "review_status": "Draft",
        "notes": "",
    }
    if extra:
        base.update(extra)
    return base


def _categorize_params(endpoint: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    path_p: dict[str, Any] = {}
    query_p: dict[str, Any] = {}
    for p in endpoint.get("params_required", []) + endpoint.get("params_optional", []):
        sample = _sample_for(p)
        target = path_p if p.get("in") == "path" else query_p
        target[p.get("name")] = sample
    return path_p, query_p


def _sample_for(param: dict[str, Any]) -> Any:
    t = (param.get("type") or "").lower()
    if param.get("enum"):
        return param["enum"][0]
    return {"integer": 1, "number": 1.0, "boolean": True,
            "array": [], "object": {}}.get(t, "sample")


def _has_auth(endpoint: dict[str, Any]) -> bool:
    blob = json.dumps(endpoint).lower()
    return any(k in blob for k in ("bearer", "oauth", "apikey", "api_key", "authorization"))


def _has_rate_limit(endpoint: dict[str, Any]) -> bool:
    return "rate" in json.dumps(endpoint).lower() or "throttle" in json.dumps(endpoint).lower()


def _load_workflows() -> list[dict[str, Any]]:
    if not _WORKFLOWS_CFG.exists():
        return []
    data = yaml.safe_load(_WORKFLOWS_CFG.read_text()) or {}
    return list(data.get("workflows", []))


def _components_present(endpoints: list[dict[str, Any]],
                        components_cfg: dict[str, Any]) -> set[str]:
    present: set[str] = set()
    for ep in endpoints:
        haystack = " ".join([
            ep.get("path", ""), " ".join(ep.get("tags") or []),
            ep.get("summary", ""),
        ]).lower()
        for name, cfg in components_cfg["components"].items():
            if cfg.get("base_url_hint", "").lower() in haystack or name.lower() in haystack:
                present.add(name)
    return present


def _emit_workflow_rows(endpoints: list[dict[str, Any]],
                        components_cfg: dict[str, Any],
                        thresholds: dict[str, float]) -> list[dict[str, Any]]:
    workflows = _load_workflows()
    if not workflows:
        return []
    present = _components_present(endpoints, components_cfg)
    rows: list[dict[str, Any]] = []
    for wf in workflows:
        required = set(wf.get("requires_components") or [])
        if not required.issubset(present):
            continue
        comps = sorted(required)
        markers = " ".join(
            f"@pytest.mark.{components_cfg['components'].get(c, {}).get('marker', c)}"
            for c in comps
        )
        # Threshold is the max across involved components (slowest hop wins)
        threshold_ms = int(max((thresholds.get(c, 0) for c in comps), default=0) * 1000)
        steps = wf.get("steps") or []
        rows.append({
            "tc_id": _tc_id("xapi", wf["name"]),
            "title": f"Cross-API workflow: {wf['name']}",
            "description": (wf.get("description") or "").strip()
                          or "Chained multi-API workflow — see workflow_steps column.",
            "case_type": "positive",
            "category": "cross_api_workflow",
            "priority": wf.get("priority", "P0"),
            "component": "+".join(comps),
            "pytest_marker": markers,
            "endpoint_url": " → ".join(f"{s.get('method', 'GET')} {s.get('path', '')}" for s in steps),
            "method": "WORKFLOW",
            "path_params": {},
            "query_params": {},
            "headers": {"Accept": "application/json"},
            "request_body": {},
            "preconditions": f"Components live: {comps}",
            "expected_status": steps[-1].get("expect_status", 200) if steps else 200,
            "expected_response_fields": [v.get("field") for s in steps for v in (s.get("validate") or []) if v.get("field")],
            "expected_response_body": {
                "step_responses": [
                    {"step": s.get("id"), "expect_status": s.get("expect_status", 200),
                     "extracts": {ex.get("as"): f"<from {ex.get('from_response')}>"
                                  for ex in (s.get("extract") or [])}}
                    for s in steps
                ],
                "final_validations": [v for s in steps for v in (s.get("validate") or [])],
            },
            "expected_response_time_ms": threshold_ms,
            "equivalence_class": "cross-api-workflow",
            "test_data_ref": f"test_data/workflows.json#{wf['name']}",
            "validator_ref": "validate_cross_api_workflow",
            "traceability": f"cross_api_workflows.yaml#{wf['name']}",
            "source_excerpt": (wf.get("description") or "").strip()[:400],
            "workflow_steps": steps,
            "review_status": "Draft",
            "notes": "",
        })
    return rows


def expand(endpoints: list[dict[str, Any]], component_override: str | None,
           priority_floor: str | None) -> list[dict[str, Any]]:
    components_cfg = _load_components()
    thresholds = _load_env_thresholds()
    rows: list[dict[str, Any]] = []

    for ep in endpoints:
        component, marker = _resolve_component(ep, components_cfg, component_override)
        threshold_s = thresholds.get(component, 0)
        threshold_ms = int(threshold_s * 1000) if threshold_s else 0
        path_p, query_p = _categorize_params(ep)
        method = ep.get("method", "GET")
        title_prefix = f"{method} {ep.get('path', '')}"

        # 1. Positive — happy path
        rows.append(_row(ep, component, marker, "positive",
                         f"{title_prefix}: happy path", f"{method}|{ep.get('path')}|happy",
                         status=200, priority="P0", equivalence_class="happy",
                         threshold_ms=threshold_ms,
                         extra={"path_params": path_p, "query_params": query_p}))

        # 2. Negative validation — one per required param
        for p in ep.get("params_required", []):
            name = p.get("name")
            rows.append(_row(ep, component, marker, "negative_validation",
                             f"{title_prefix}: missing required '{name}'",
                             f"{method}|{ep.get('path')}|miss|{name}",
                             status=400, priority="P1",
                             equivalence_class=f"missing-required-{name}",
                             threshold_ms=threshold_ms))
            rows.append(_row(ep, component, marker, "negative_validation",
                             f"{title_prefix}: wrong type for '{name}'",
                             f"{method}|{ep.get('path')}|wrongtype|{name}",
                             status=400, priority="P1",
                             equivalence_class=f"wrong-type-{name}",
                             threshold_ms=threshold_ms))
            if p.get("enum"):
                rows.append(_row(ep, component, marker, "negative_validation",
                                 f"{title_prefix}: enum violation '{name}'",
                                 f"{method}|{ep.get('path')}|enum|{name}",
                                 status=400, priority="P1",
                                 equivalence_class=f"enum-violation-{name}",
                                 threshold_ms=threshold_ms))

        # 3. Negative auth
        if _has_auth(ep):
            for sub, status in (("missing-token", 401), ("expired-token", 401), ("wrong-scope", 403)):
                rows.append(_row(ep, component, marker, "negative_auth",
                                 f"{title_prefix}: {sub}",
                                 f"{method}|{ep.get('path')}|auth|{sub}",
                                 status=status, priority="P0", equivalence_class=sub,
                                 threshold_ms=threshold_ms))

        # 4. Negative not found
        if any(p.get("in") == "path" for p in ep.get("params_required", [])):
            rows.append(_row(ep, component, marker, "negative_not_found",
                             f"{title_prefix}: non-existent resource",
                             f"{method}|{ep.get('path')}|404|nonexistent",
                             status=404, priority="P1",
                             equivalence_class="nonexistent-id",
                             threshold_ms=threshold_ms))

        # 5. Negative conflict (POST/PUT/PATCH only)
        if method in ("POST", "PUT", "PATCH"):
            rows.append(_row(ep, component, marker, "negative_conflict",
                             f"{title_prefix}: duplicate / state-violation",
                             f"{method}|{ep.get('path')}|conflict",
                             status=409, priority="P1",
                             equivalence_class="duplicate-create",
                             threshold_ms=threshold_ms))

        # 6. Negative rate
        if _has_rate_limit(ep):
            rows.append(_row(ep, component, marker, "negative_rate",
                             f"{title_prefix}: burst rate limit",
                             f"{method}|{ep.get('path')}|rate",
                             status=429, priority="P2",
                             equivalence_class="burst",
                             threshold_ms=threshold_ms))

        # 7. Schema
        if (ep.get("response_schema") or {}).get("properties"):
            rows.append(_row(ep, component, marker, "schema",
                             f"{title_prefix}: response schema validation",
                             f"{method}|{ep.get('path')}|schema",
                             status=200, priority="P0",
                             equivalence_class="schema-required-fields",
                             threshold_ms=threshold_ms))

        # 8. Boundary — applied to first numeric required param if any
        for p in ep.get("params_required", []):
            if (p.get("type") or "").lower() in ("integer", "number"):
                for cls in ("min", "min-1", "max", "max+1"):
                    rows.append(_row(ep, component, marker, "boundary",
                                     f"{title_prefix}: {p.get('name')} {cls}",
                                     f"{method}|{ep.get('path')}|bva|{p.get('name')}|{cls}",
                                     status=200 if cls in ("min", "max") else 400,
                                     priority="P1", equivalence_class=cls,
                                     threshold_ms=threshold_ms))
                break

        # 9. i18n — emitted once per endpoint
        rows.append(_row(ep, component, marker, "i18n",
                         f"{title_prefix}: UTF-8 / emoji / RTL inputs",
                         f"{method}|{ep.get('path')}|i18n",
                         status=200, priority="P2", equivalence_class="utf8-emoji-rtl",
                         threshold_ms=threshold_ms))

        # 10. Idempotency
        if method in ("GET", "PUT", "DELETE"):
            rows.append(_row(ep, component, marker, "idempotency",
                             f"{title_prefix}: idempotent re-application",
                             f"{method}|{ep.get('path')}|idem",
                             status=200, priority="P2",
                             equivalence_class=f"{method.lower()}-idempotent",
                             threshold_ms=threshold_ms))

        # 11. Performance
        if threshold_ms:
            rows.append(_row(ep, component, marker, "performance",
                             f"{title_prefix}: response time ≤ {threshold_ms}ms",
                             f"{method}|{ep.get('path')}|perf",
                             status=200, priority="P0",
                             equivalence_class="response-time-threshold",
                             threshold_ms=threshold_ms))

        # 12. Status-code coverage — emit a row for every documented code
        #     that the standard taxonomy didn't already cover.
        covered_statuses: set[int] = {
            r["expected_status"] for r in rows
            if r["endpoint_url"] == ep.get("path") and r["method"] == method
        }
        for code in ep.get("status_codes", []):
            if code in covered_statuses:
                continue
            if 200 <= code < 300 and code != 202:
                continue  # 2xx other than 202 already handled by positive row
            mapped = _STATUS_CODE_CATEGORY.get(code)
            if mapped is None:
                # Fall back to bucket by class
                if 400 <= code < 500:
                    mapped = ("negative_client_4xx", "P2")
                elif 500 <= code < 600:
                    mapped = ("negative_server_5xx", "P1")
                else:
                    continue
            cat, pri = mapped
            rows.append(_row(ep, component, marker, cat,
                             f"{title_prefix}: documented {code}",
                             f"{method}|{ep.get('path')}|status|{code}",
                             status=code, priority=pri,
                             equivalence_class=f"status-{code}",
                             threshold_ms=threshold_ms))
            covered_statuses.add(code)

    # 13. Cross-API workflows (chained multi-component recipes)
    rows.extend(_emit_workflow_rows(endpoints, components_cfg, thresholds))

    # Cross-env: same path across two components in the SAME run
    by_path: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r["category"] == "positive":
            by_path.setdefault(r["endpoint_url"].rsplit("/", 1)[-1], []).append(r)
    for resource, group in by_path.items():
        comps = sorted({r["component"] for r in group})
        if len(comps) >= 2:
            rows.append({
                **group[0],
                "tc_id": _tc_id("xenv", resource),
                "title": f"Cross-env consistency for resource '{resource}' across {comps}",
                "description": "Verify the same resource is consistent across the components listed in pytest_marker.",
                "case_type": "positive",
                "category": "cross_env",
                "priority": "P0",
                "pytest_marker": " ".join(f"@pytest.mark.{c}" for c in comps),
                "component": "+".join(comps),
                "equivalence_class": "cross-env-consistency",
            })

    if priority_floor:
        order = {"P0": 0, "P1": 1, "P2": 2}
        floor_val = order.get(priority_floor.upper(), 2)
        for r in rows:
            if order.get(r["priority"], 2) > floor_val:
                r["priority"] = priority_floor.upper()

    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--component", default=None)
    ap.add_argument("--priority-bias", default=None, choices=["p0", "p1", "p2", "P0", "P1", "P2"])
    args = ap.parse_args()

    raw = sys.stdin.read()
    if not raw.strip():
        print("[generate_cases] empty stdin — pipe endpoints JSON in", file=sys.stderr)
        sys.exit(2)
    endpoints = json.loads(raw)
    rows = expand(endpoints, args.component, args.priority_bias)
    json.dump(rows, sys.stdout, indent=2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
