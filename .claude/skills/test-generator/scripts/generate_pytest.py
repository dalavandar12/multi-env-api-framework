"""Turn parsed spec-sheet rows into a runnable pytest module + companion JSON.

Mirrors the existing tests/weather/test_weather.py and tests/countries/test_countries.py patterns
(same imports, fixture usage, parametrize-from-JSON helper, class markers,
allure decorators). Validators are per-component: validate_<component>_schema.

Stdin (JSON):  output of parse_spec_sheet.py
Args:          --out-py <path>  --out-json <path>
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

LOG = logging.getLogger(__name__)

_REPO_ENV_YAML = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "config" / "environments.yaml"
)


def _env_base_paths() -> dict[str, str]:
    """Return {component: base_url_path} from repo's config/environments.yaml.

    The api_client fixture composes URLs as base_url + relative_path, so the
    generator must strip the env's path prefix from each emitted endpoint URL.
    """
    if not _REPO_ENV_YAML.exists():
        LOG.warning("environments.yaml not found at %s — no base-path stripping",
                    _REPO_ENV_YAML)
        return {}
    data = yaml.safe_load(_REPO_ENV_YAML.read_text(encoding="utf-8")) or {}
    out: dict[str, str] = {}
    for name, cfg in (data.get("environments") or {}).items():
        if not isinstance(cfg, dict):
            continue
        base = str(cfg.get("base_url", ""))
        parsed = urlparse(base)
        out[name] = parsed.path.rstrip("/")
    return out


_ENV_BASE_PATHS = _env_base_paths()


class GenerationError(Exception):
    """Raised when input rows can't be turned into a valid pytest file."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_class_name(method: str, endpoint_url: str) -> str:
    """Build a CamelCase class name from method + path."""
    path_part = re.sub(r"https?://", "", endpoint_url or "")
    path_part = re.sub(r"[^A-Za-z0-9]+", " ", path_part).strip()
    words = [w.capitalize() for w in path_part.split() if w][:6]
    body = "".join(words) or "Endpoint"
    return f"Test{method.capitalize()}{body}"


def _validator_name(component: str) -> str:
    """Per-component validator: countries → validate_countries_schema, etc."""
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", component or "").strip("_").lower() or "endpoint"
    return f"validate_{safe}_schema"


def _register_validators(
    component: str,
    rel_path: str,
    buckets: dict[str, list[dict[str, Any]]],
    validators: set[str],
) -> None:
    """Track validator imports needed for body checks on 2xx paths."""
    needs_body_check = bool(
        buckets.get("positive") or buckets.get("edge") or buckets.get("schema")
    )
    if not needs_body_check:
        return
    if component == "weather":
        validators.add("validate_weather_schema")
        if rel_path == "/forecast":
            validators.add("validate_weather_response")
        return
    if component == "countries":
        if rel_path == "/all":
            validators.add("validate_population_positive")
        else:
            validators.add("validate_countries_schema")
        return
    validators.add(_validator_name(component))


def _body_validation_lines(
    component: str,
    rel_path: str,
    *,
    indent: str = "        ",
    data_var: str = "data",
    use_env_config: bool = False,
) -> list[str]:
    """Emit validator calls for successful response bodies (no inline asserts)."""
    if component == "countries" and rel_path == "/all":
        return [
            f"{indent}items = {data_var} if isinstance({data_var}, list) else [{data_var}]",
            f'{indent}assert items, "expected a non-empty country list"',
            f"{indent}for _country in items:",
            f"{indent}    with check.check:",
            f"{indent}        validate_population_positive(_country)",
        ]
    if component == "weather" and rel_path == "/forecast":
        env_arg = (
            f'{indent}    temp_min=float(env_config["temperature_min_c"]),'
            if use_env_config
            else f"{indent}    temp_min=-90.0,"
        )
        env_arg2 = (
            f'{indent}    temp_max=float(env_config["temperature_max_c"]),'
            if use_env_config
            else f"{indent}    temp_max=60.0,"
        )
        return [
            f"{indent}validate_weather_response(",
            f"{indent}    {data_var},",
            env_arg,
            env_arg2,
            f"{indent})",
        ]
    validator = _validator_name(component)
    return [
        f"{indent}payload = {data_var}[0] if isinstance({data_var}, list) and {data_var} else {data_var}",
        f"{indent}{validator}(payload)",
    ]


def _category_bucket(case_type: str, category: str) -> str:
    if category == "cross_api_workflow":
        return "workflow"
    if category == "performance":
        return "performance"
    if category == "schema":
        return "schema"
    return case_type  # positive | negative | edge


def _strip_base_url(endpoint_url: str, component: str | None = None) -> str:
    """Strip scheme+host AND the env's base-URL path prefix from an endpoint.

    The framework's ApiClient prefixes every request with the env's base_url
    (which already includes the /v3.1 or /v1 path segment), so the generated
    test must use a path relative to that base.
    """
    if not endpoint_url:
        return ""
    m = re.match(r"https?://[^/]+(/.*)$", endpoint_url)
    path = m.group(1) if m else endpoint_url
    if component and component in _ENV_BASE_PATHS:
        base_path = _ENV_BASE_PATHS[component]
        if base_path and path.startswith(base_path + "/"):
            path = path[len(base_path):]
        elif base_path and path == base_path:
            path = "/"
    return path


_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _has_placeholders(path: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(path or ""))


def _build_case_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Reduce one spec-sheet row to the minimum a test method needs at runtime."""
    return {
        "tc_id": row.get("tc_id"),
        "title": row.get("title"),
        "description": row.get("description"),
        "category": row.get("category"),
        "case_type": row.get("case_type"),
        "priority": row.get("priority"),
        "equivalence_class": row.get("equivalence_class"),
        "path_params": row.get("path_params") or {},
        "query_params": row.get("query_params") or {},
        "headers": row.get("headers") or {},
        "request_body": row.get("request_body") or {},
        "preconditions": row.get("preconditions") or "",
        "expected_status": row.get("expected_status"),
        "expected_response_fields": row.get("expected_response_fields") or [],
        "expected_response_body": row.get("expected_response_body"),
        "expected_response_time_ms": row.get("expected_response_time_ms"),
        "traceability": row.get("traceability"),
    }


# ---------------------------------------------------------------------------
# Code emission
# ---------------------------------------------------------------------------


def _emit_module_header(spec_path: str, out_json_relpath: str, validators: set[str],
                        components: list[str]) -> str:
    validator_block = (
        f"from src.validators import {', '.join(sorted(validators))}\n"
        if validators else ""
    )
    check_import = (
        "import pytest_check as check\n"
        if "validate_population_positive" in validators
        else ""
    )
    return f'''"""
Auto-generated by the test-generator skill.
Spec sheet: {spec_path}
Components: {', '.join(components)}

Move this file into tests/ after review. Do NOT hand-edit the copy in output/ —
re-run the skill to regenerate.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import allure
import pytest
{check_import}
from src.client import ApiClient, ApiError
{validator_block}
LOG = logging.getLogger(__name__)

_CASES_PATH = Path(__file__).parent / "{out_json_relpath}"
_PLACEHOLDER_RE = re.compile(r"\\{{([A-Za-z_][A-Za-z0-9_]*)\\}}")


def _load_cases() -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Load grouped test cases from the companion JSON file."""
    with _CASES_PATH.open(encoding="utf-8") as fh:
        return dict(json.load(fh))


def _safe_path(template: str, params: dict[str, Any] | None) -> str:
    """Substitute {{placeholder}} fields. Missing keys default to 'missing'."""
    params = params or {{}}
    defaults = {{p: str(params.get(p, "missing")) for p in _PLACEHOLDER_RE.findall(template)}}
    return template.format(**defaults)


_ALL_CASES = _load_cases()


def _cases(class_key: str, bucket: str) -> list[dict[str, Any]]:
    """Return the list of parametrize entries for one class + bucket."""
    return list(_ALL_CASES.get(class_key, {{}}).get(bucket, []))


'''


def _emit_class(group: dict[str, Any], class_key: str) -> str:
    component = group["component"]
    marker_token = (group["pytest_marker"] or f"@pytest.mark.{component}").replace(
        "@pytest.mark.", ""
    ).split()[0]
    rel_path = _strip_base_url(group["endpoint_url"], component)
    summary = group.get("summary") or f"{group['method']} {rel_path}"
    class_name = _safe_class_name(group["method"], group["endpoint_url"])
    method_lookup = group["method"].lower()
    has_placeholders = _has_placeholders(rel_path)

    # Bucket rows by category for parametrize blocks
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in group["rows"]:
        bucket = _category_bucket(row.get("case_type") or "", row.get("category") or "")
        buckets.setdefault(bucket, []).append(row)

    path_expr = (
        f'_safe_path("{rel_path}", case.get("path_params"))'
        if has_placeholders
        else f'"{rel_path}"'
    )

    def _call() -> str:
        return f'api_client.{method_lookup}({path_expr}, params=case.get("query_params") or {{}})'

    lines: list[str] = [
        f'@allure.feature("{component.capitalize()} API — {summary}")',
        f"@pytest.mark.{marker_token}",
        f"class {class_name}:",
        f'    """Tests for {group["method"]} {rel_path} — generated from spec sheet."""',
        "",
        f'    _CLASS_KEY = "{class_key}"',
        "",
    ]

    skip_check = [
        '        if case.get("skip"):',
        '            pytest.skip(case.get("skip_reason", "auto-skipped"))',
    ]

    body_check = _body_validation_lines(
        component, rel_path, use_env_config=True,
    )
    body_check_in_try = _body_validation_lines(
        component, rel_path, use_env_config=True, indent="            ",
    )

    if buckets.get("positive"):
        lines += [
            '    @allure.story("Happy path")',
            '    @pytest.mark.parametrize(',
            '        "case", _cases(_CLASS_KEY, "positive"), ids=lambda c: c["tc_id"],',
            "    )",
            "    def test_positive(",
            "        self, api_client: ApiClient, env_config: dict[str, Any], case: dict[str, Any],",
            "    ) -> None:",
            '        """Happy path — one parametrize entry per TC_ in the spec sheet."""',
            *skip_check,
            f'        LOG.info("[%s] positive: %s", case["tc_id"], case["title"])',
            f"        data = {_call()}",
            f'        assert data is not None, case["tc_id"]',
            *body_check,
            "",
        ]

    if buckets.get("schema"):
        schema_check = _body_validation_lines(component, rel_path, use_env_config=True)
        lines += [
            '    @allure.story("Response schema")',
            '    @pytest.mark.parametrize(',
            '        "case", _cases(_CLASS_KEY, "schema"), ids=lambda c: c["tc_id"],',
            "    )",
            "    def test_schema(",
            "        self, api_client: ApiClient, env_config: dict[str, Any], case: dict[str, Any],",
            "    ) -> None:",
            '        """Validate the response body via the per-component validator."""',
            *skip_check,
            f'        LOG.info("[%s] schema: %s", case["tc_id"], case["title"])',
            f"        data = {_call()}",
            f'        assert data is not None, case["tc_id"]',
            *schema_check,
            "",
        ]

    if buckets.get("negative"):
        lines += [
            '    @allure.story("Negative cases")',
            '    @pytest.mark.parametrize(',
            '        "case", _cases(_CLASS_KEY, "negative"), ids=lambda c: c["tc_id"],',
            "    )",
            "    def test_negative(self, api_client: ApiClient, case: dict[str, Any]) -> None:",
            '        """Expect documented non-2xx. ApiClient raises ApiError on !2xx."""',
            *skip_check,
            f'        LOG.info("[%s] negative: %s", case["tc_id"], case["title"])',
            "        with pytest.raises(ApiError) as exc:",
            f"            {_call()}",
            "        assert exc.value.status_code == case[\"expected_status\"], (",
            "            f\"{case['tc_id']}: expected {case['expected_status']}, \"",
            "            f\"got {exc.value.status_code}\"",
            "        )",
            "",
        ]

    if buckets.get("edge"):
        lines += [
            '    @allure.story("Edge / boundary / i18n")',
            '    @pytest.mark.parametrize(',
            '        "case", _cases(_CLASS_KEY, "edge"), ids=lambda c: c["tc_id"],',
            "    )",
            "    def test_edge(",
            "        self, api_client: ApiClient, env_config: dict[str, Any], case: dict[str, Any],",
            "    ) -> None:",
            '        """Boundary and i18n cases — either succeed or surface the documented code."""',
            *skip_check,
            f'        LOG.info("[%s] edge: %s", case["tc_id"], case["title"])',
            "        try:",
            f"            data = {_call()}",
            "            assert data is not None, case[\"tc_id\"]",
            *body_check_in_try,
            "        except ApiError as exc:",
            "            assert exc.status_code == case[\"expected_status\"], (",
            "                f\"{case['tc_id']}: expected {case['expected_status']}, \"",
            "                f\"got {exc.status_code}\"",
            "            )",
            "",
        ]

    if buckets.get("performance"):
        lines += [
            '    @allure.story("Response time threshold")',
            '    @pytest.mark.parametrize(',
            '        "case", _cases(_CLASS_KEY, "performance"), ids=lambda c: c["tc_id"],',
            "    )",
            "    def test_performance(",
            "        self, api_client: ApiClient, env_config: dict[str, Any], case: dict[str, Any],",
            "    ) -> None:",
            '        """Threshold from env_config["max_response_time"] — never hardcoded."""',
            *skip_check,
            f'        LOG.info("[%s] performance: %s", case["tc_id"], case["title"])',
            "        start = time.monotonic()",
            f"        {_call()}",
            "        elapsed_ms = (time.monotonic() - start) * 1000",
            "        threshold_ms = float(env_config[\"max_response_time\"]) * 1000",
            "        assert elapsed_ms <= threshold_ms, (",
            "            f\"{case['tc_id']}: {elapsed_ms:.0f}ms > {threshold_ms:.0f}ms\"",
            "        )",
            "",
        ]

    return "\n".join(lines) + "\n"


def _emit_workflow_class(workflow_rows: list[dict[str, Any]]) -> str:
    if not workflow_rows:
        return ""
    lines = [
        '@allure.feature("Cross-API workflows")',
        "class TestCrossApiWorkflows:",
        '    """Chained multi-component workflows."""',
        "",
    ]
    for i, row in enumerate(workflow_rows, 1):
        steps = row.get("workflow_steps") or []
        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except json.JSONDecodeError:
                steps = []
        markers = row.get("pytest_marker") or ""
        for m in re.findall(r"@pytest\.mark\.(\w+)", markers):
            lines.append(f"    @pytest.mark.{m}")
        lines.append(f'    @allure.story({json.dumps(row.get("title") or f"workflow {i}")})')
        lines.append(f"    def test_workflow_{i}(self, api_client: ApiClient) -> None:")
        lines.append(
            f'        """tc_id: {row.get("tc_id")} | traceability: {row.get("traceability")}"""'
        )
        lines.append(f'        LOG.info("[%s] cross-api workflow", "{row.get("tc_id")}")')
        for j, step in enumerate(steps, 1):
            method = (step.get("method") or "GET").lower()
            path = _strip_base_url(step.get("path", ""))
            qp = json.dumps(step.get("query_params") or {})
            lines.append(
                f"        # Step {j}: {step.get('method')} {path} (component={step.get('component')})"
            )
            lines.append(
                "        # TODO: substitute ${var} placeholders using extracts from prior steps"
            )
            lines.append(
                f'        response_{j} = api_client.{method}("{path}", params={qp or "{}"})'
            )
            for ex in (step.get("extract") or []):
                lines.append(
                    f"        # extract {ex.get('from_response')} -> ${{{ex.get('as')}}}"
                )
        lines.append("        # TODO: implement final_validations from the spec sheet")
        lines.append("        assert response_1 is not None")
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def generate(
    parsed: dict[str, Any],
    out_py: Path,
    out_json: Path,
    user_test_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit pytest module + companion JSON.

    If user_test_data is supplied (from Skill 2 — test-data-generator), it
    REPLACES the synthesized payload entirely. The spec sheet still determines
    which classes get emitted; the user JSON populates their parametrize lists.
    """
    groups = parsed.get("groups") or []
    workflow_rows = parsed.get("workflow_rows") or []
    if not groups and not workflow_rows:
        raise GenerationError("no endpoint groups and no workflow rows — nothing to emit")

    payload: dict[str, dict[str, list[dict[str, Any]]]] = {}
    class_keys: list[tuple[dict[str, Any], str]] = []
    validators: set[str] = set()
    components: set[str] = set()

    for group in groups:
        if not group["rows"]:
            LOG.warning("Skipping group with no rows: %s %s", group["method"], group["endpoint_url"])
            continue
        class_key = (
            f"{group['component']}__{group['method']}__"
            f"{_strip_base_url(group['endpoint_url'], group['component'])}"
        )
        class_keys.append((group, class_key))
        components.add(group["component"])

        if user_test_data is not None and class_key in user_test_data:
            buckets = user_test_data[class_key]
        else:
            if user_test_data is not None:
                LOG.warning(
                    "class_key '%s' not in --test-data — synthesizing from spec sheet",
                    class_key,
                )
            buckets = {}
            for row in group["rows"]:
                bucket = _category_bucket(row.get("case_type") or "", row.get("category") or "")
                buckets.setdefault(bucket, []).append(_build_case_payload(row))

        rel_path = _strip_base_url(group["endpoint_url"], group["component"])
        _register_validators(group["component"], rel_path, buckets, validators)
        payload[class_key] = buckets

    LOG.info("Emitting %d class(es), %d workflow row(s)", len(class_keys), len(workflow_rows))

    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    LOG.info("Wrote companion JSON %s", out_json)

    parts = [
        _emit_module_header(
            parsed.get("spec_sheet", "<unknown>"),
            out_json.name,
            validators,
            sorted(components),
        )
    ]
    for group, class_key in class_keys:
        parts.append(_emit_class(group, class_key))
    parts.append(_emit_workflow_class(workflow_rows))
    out_py.write_text("\n".join(parts))
    LOG.info("Wrote pytest module %s", out_py)

    return {
        "out_py": str(out_py),
        "out_json": str(out_json),
        "class_count": len(class_keys),
        "workflow_count": len(workflow_rows),
        "case_count": sum(len(rows) for buckets in payload.values() for rows in buckets.values()),
        "validators": sorted(validators),
        "components": sorted(components),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-py", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--user-test-data", default=None,
                    help="Pre-built JSON (from test-data-generator) to use instead of "
                         "synthesizing from spec-sheet rows")
    args = ap.parse_args()
    try:
        parsed = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        print(f"[test-generator] could not parse parser output: {exc}", file=sys.stderr)
        sys.exit(2)

    user_test_data: dict[str, Any] | None = None
    if args.user_test_data:
        path = Path(args.user_test_data)
        if not path.exists():
            print(f"[test-generator] --user-test-data not found: {path}", file=sys.stderr)
            sys.exit(2)
        try:
            user_test_data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"[test-generator] --user-test-data invalid JSON: {exc}", file=sys.stderr)
            sys.exit(2)

    try:
        summary = generate(parsed, Path(args.out_py), Path(args.out_json), user_test_data)
    except GenerationError as exc:
        print(f"[test-generator] {exc}", file=sys.stderr)
        sys.exit(2)
    json.dump(summary, sys.stdout, indent=2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
