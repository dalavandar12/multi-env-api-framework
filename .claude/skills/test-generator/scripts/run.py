"""Single entry point for the test-generator skill.

Three input modes — pick whichever fits the task:

    # 1. xlsx spec sheet (from the testcase-generator skill)
    python run.py --source file <name.xlsx>          # bare name → looks in input/
    python run.py --source file                       # no name  → newest .xlsx in input/
    python run.py --source file /absolute/path.xlsx   # absolute path

    # 2. CLI args — minimal one-endpoint spec, expanded via testcase-generator taxonomy
    python run.py --source cli \
        --endpoint https://restcountries.com/v3.1/name/{name} \
        --method GET \
        --response-fields name,capital,population \
        --component countries

    # 3. JSON file — single dict OR list of dicts, same shape as CLI args
    python run.py --source json <name.json>           # bare name → looks in input/
    python run.py --source json                        # no name  → newest .json in input/

For the xlsx mode (1), input is a spec sheet of pre-expanded rows. For cli/json
modes (2, 3), the input is a thin endpoint definition that gets piped through
the testcase-generator skill's case-expansion taxonomy so the resulting pytest
module covers positive / negative / schema / boundary just like the xlsx path.

Output:
    .claude/skills/test-generator/output/test_<component>_generated_<ts>.py
    .claude/skills/test-generator/output/test_data_<component>_generated_<ts>.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
import subprocess
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPT_DIR.parent
_INPUT_DIR = _SKILL_ROOT / "received_spec_sheets"
_OUTPUT_DIR = _SKILL_ROOT / "generated_pytest_modules"
_REPO_TESTS_DIR = _SKILL_ROOT.parent.parent.parent / "tests"
_REPO_TEST_DATA_DIR = _SKILL_ROOT.parent.parent.parent / "test_data"
_GT_ROOT = _SKILL_ROOT.parent / "testcase-generator"
_GT_FETCH_URL = _GT_ROOT / "scripts" / "fetch_url.py"
_GT_GENERATE_CASES = _GT_ROOT / "scripts" / "generate_cases.py"
_TDG_SCRIPTS_DIR = _SKILL_ROOT.parent / "test-data-generator" / "scripts"


def _die(msg: str, code: int = 2) -> None:
    print(f"[test-generator] {msg}", file=sys.stderr)
    sys.exit(code)


def _run_python(script: Path, args: list[str], stdin: str | None = None) -> str:
    cmd = [sys.executable, str(script), *args]
    LOG.info("subprocess: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, input=stdin, capture_output=True, text=True, check=False)
    except OSError as exc:
        _die(f"failed to spawn {script}: {exc}")
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        sys.exit(result.returncode)
    return result.stdout


# ---------------------------------------------------------------------------
# File / URL helpers
# ---------------------------------------------------------------------------


def _latest_with_suffix(suffix: str) -> Path:
    if not _INPUT_DIR.exists():
        _die(f"received_spec_sheets/ directory missing: {_INPUT_DIR}")
    candidates = [
        p for p in _INPUT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() == suffix
        and not p.name.startswith("~$") and p.name != ".gitkeep"
    ]
    if not candidates:
        _die(f"received_spec_sheets/ has no {suffix} files: {_INPUT_DIR}")
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    LOG.info("input/ has %d %s file(s); picked latest: %s",
             len(candidates), suffix, latest.name)
    return latest


def _resolve_input(name: str | None, suffix: str) -> Path:
    if not name:
        return _latest_with_suffix(suffix)
    p = Path(name)
    if p.is_absolute() or p.exists():
        return p
    candidate = _INPUT_DIR / name
    if candidate.exists():
        return candidate
    _die(f"{suffix} not found: tried {p} and {candidate}")
    return p  # unreachable


def _resolve_file_locator(name: str) -> Path:
    """Resolve a user-provided file locator from cwd or skill input folder."""
    p = Path(name)
    if p.is_absolute() or p.exists():
        return p
    candidate = _INPUT_DIR / name
    if candidate.exists():
        return candidate
    _die(f"file not found: tried {p} and {candidate}")
    return p  # unreachable


def _fetch_xlsx_url(url: str) -> Path:
    if not _GT_FETCH_URL.exists():
        _die(f"reused guardrail missing: {_GT_FETCH_URL}")
    LOG.info("Fetching %s through reused guardrail", url)
    raw = _run_python(_GT_FETCH_URL, [url])
    if raw.startswith("Content-Type:"):
        raw = raw.split("\n\n", 1)[1] if "\n\n" in raw else raw
    tmp = Path(tempfile.gettempdir()) / "test_generator_remote.xlsx"
    tmp.write_bytes(raw.encode("latin-1", errors="ignore"))
    LOG.info("Saved remote xlsx to %s", tmp)
    return tmp


# ---------------------------------------------------------------------------
# CLI / JSON → endpoint dicts (matching testcase-generator parse_openapi shape)
# ---------------------------------------------------------------------------


def _infer_component(url: str, override: str | None) -> str:
    if override:
        return override
    host = re.match(r"https?://([^/]+)", url or "")
    if not host:
        return "unknown"
    parts = host.group(1).split(".")
    return parts[-2] if len(parts) >= 2 else parts[0]


def _endpoint_from_fields(
    *, endpoint: str, method: str, response_fields: list[str],
    component: str | None,
    params_required: list[dict[str, Any]] | None = None,
    params_optional: list[dict[str, Any]] | None = None,
    status_codes: list[int] | None = None,
    summary: str | None = None,
    traceability: str | None = None,
) -> dict[str, Any]:
    """Normalize a thin endpoint spec into the dict shape generate_cases.py expects."""
    if not endpoint or not endpoint.startswith(("http://", "https://")):
        _die(f"endpoint must be an absolute http(s) URL — got {endpoint!r}")
    inferred_component = _infer_component(endpoint, component)
    # Auto-discover {placeholder} path params if user didn't supply them
    placeholders = re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", endpoint)
    if params_required is None:
        params_required = [
            {"name": n, "in": "path", "type": "string", "format": None,
             "enum": None, "description": ""}
            for n in placeholders
        ]
    properties = {
        f: {"type": "string"} for f in (response_fields or [])
    }
    return {
        "method": method.upper(),
        "path": endpoint,
        "summary": summary or f"{method.upper()} {endpoint}",
        "tags": [inferred_component],
        "params_required": params_required or [],
        "params_optional": params_optional or [],
        "request_schema": {},
        "response_schema": (
            {"type": "object", "properties": properties} if properties else {}
        ),
        "status_codes": status_codes or [200],
        "examples": {},
        "source_excerpt": f"Provided via test-generator {method.upper()} {endpoint}",
        "traceability": traceability or "cli-or-json-input",
    }


def _endpoints_from_cli(args: argparse.Namespace) -> list[dict[str, Any]]:
    if not args.endpoint:
        _die("--source cli requires --endpoint <URL>")
    response_fields = [
        f.strip() for f in (args.response_fields or "").split(",") if f.strip()
    ]
    LOG.info("CLI mode: endpoint=%s method=%s fields=%s",
             args.endpoint, args.method, response_fields)
    return [_endpoint_from_fields(
        endpoint=args.endpoint,
        method=args.method or "GET",
        response_fields=response_fields,
        component=args.component,
    )]


def _endpoints_from_json(json_path: Path, component_override: str | None) -> list[dict[str, Any]]:
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _die(f"could not parse JSON {json_path}: {exc}")
    entries = raw if isinstance(raw, list) else [raw]
    out: list[dict[str, Any]] = []
    for i, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            _die(f"JSON entry #{i} is not an object")
        endpoint_val = (
            entry.get("endpoint_url")
            or entry.get("endpoint")
            or entry.get("url")
            or entry.get("path")
        )
        method_val = entry.get("method") or entry.get("http_method")
        if not endpoint_val or not method_val:
            _die(
                "JSON entry #{i} missing required key(s): "
                "need endpoint_url/endpoint/url/path and method/http_method".format(i=i)
            )
        fields_val = (
            entry.get("response_fields")
            or entry.get("responsefield")
            or entry.get("responseField")
            or entry.get("response")
            or []
        )
        if isinstance(fields_val, str):
            fields_val = [f.strip() for f in fields_val.split(",") if f.strip()]
        out.append(_endpoint_from_fields(
            endpoint=str(endpoint_val),
            method=str(method_val),
            response_fields=list(fields_val),
            component=entry.get("component") or component_override,
            params_required=entry.get("params_required"),
            params_optional=entry.get("params_optional"),
            status_codes=entry.get("status_codes"),
            summary=entry.get("summary"),
            traceability=entry.get("traceability") or f"json:{json_path.name}#{i}",
        ))
    LOG.info("JSON mode: loaded %d endpoint(s) from %s", len(out), json_path)
    return out


# ---------------------------------------------------------------------------
# Endpoint list → rows → parsed-shape for generate_pytest.py
# ---------------------------------------------------------------------------


def _expand_endpoints_to_rows(endpoints: list[dict[str, Any]],
                              component_override: str | None) -> list[dict[str, Any]]:
    """Pipe endpoints through testcase-generator' generate_cases.py."""
    if not _GT_GENERATE_CASES.exists():
        _die(f"reused case generator missing: {_GT_GENERATE_CASES}")
    args: list[str] = []
    if component_override:
        args.extend(["--component", component_override])
    raw = _run_python(_GT_GENERATE_CASES, args, stdin=json.dumps(endpoints))
    return list(json.loads(raw))


def _rows_to_parsed_shape(rows: list[dict[str, Any]], origin: str) -> dict[str, Any]:
    """Group flat rows into the parse_spec_sheet output shape."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    workflow_rows: list[dict[str, Any]] = []
    for row in rows:
        if (row.get("category") or "") == "cross_api_workflow":
            workflow_rows.append(row)
            continue
        key = (
            str(row.get("component") or "unknown"),
            str(row.get("endpoint_url") or ""),
            str(row.get("method") or "GET").upper(),
        )
        groups[key].append(row)
    out_groups: list[dict[str, Any]] = []
    for (component, endpoint_url, method), entries in groups.items():
        marker = entries[0].get("pytest_marker") or f"@pytest.mark.{component}"
        summary = (entries[0].get("title") or "").split(":")[0].strip()
        out_groups.append({
            "component": component,
            "endpoint_url": endpoint_url,
            "method": method,
            "pytest_marker": marker,
            "summary": summary,
            "rows": entries,
        })
    return {"spec_sheet": origin, "groups": out_groups, "workflow_rows": workflow_rows}


def _drop_workflow_rows(parsed: dict[str, Any]) -> dict[str, Any]:
    """Return parsed copy with workflow rows removed."""
    out = dict(parsed)
    out["workflow_rows"] = []
    return out


def _seed_hydrated_test_data(
    parsed: dict[str, Any],
    fanout: bool = False,
) -> dict[str, Any] | None:
    """Build user-test-data payload using test-data-generator seeds and substitution rules."""
    if not _TDG_SCRIPTS_DIR.exists():
        LOG.warning("Seed hydration skipped; test-data-generator scripts not found at %s",
                    _TDG_SCRIPTS_DIR)
        return None

    if str(_TDG_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_TDG_SCRIPTS_DIR))

    try:
        from load_seeds import SeedError, load_endpoint_param_map, load_seeds  # type: ignore
        from substitute import substitute_groups  # type: ignore
    except Exception as exc:
        LOG.warning("Seed hydration skipped; imports failed: %s", exc)
        return None

    components = sorted({str(g.get("component") or "") for g in parsed.get("groups", []) if g})
    if not components:
        return None

    try:
        seeds_by_component = {component: load_seeds(component) for component in components}
        param_map_by_component = load_endpoint_param_map()
    except SeedError as exc:
        LOG.warning("Seed hydration skipped: %s", exc)
        return None

    payload, warnings = substitute_groups(
        parsed,
        seeds_by_component,
        param_map_by_component,
        fanout=fanout,
    )
    for warning in warnings:
        LOG.warning("Seed hydration: %s", warning)
    return payload


# ---------------------------------------------------------------------------
# Output paths + main
# ---------------------------------------------------------------------------


def _sanitize_output_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_-")
    if not safe:
        _die("--output-name must contain at least one alphanumeric character")
    return safe.lower()


def _output_paths(component: str, output_name: str | None = None) -> tuple[Path, Path]:
    if output_name:
        safe_name = _sanitize_output_name(output_name)
        return (
            _OUTPUT_DIR / f"test_{safe_name}.py",
            _OUTPUT_DIR / f"{safe_name}.json",
        )
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    safe = (component or "mixed").replace("+", "_")
    return (
        _OUTPUT_DIR / f"test_{safe}_generated_{ts}.py",
        _OUTPUT_DIR / f"test_data_{safe}_generated_{ts}.json",
    )


def _component_from_filename(name: str) -> str:
    match = re.match(r"^test_(.+?)_generated_\d{8}_\d{6}Z\.py$", name)
    if match:
        return match.group(1)
    return "misc"


def _rewrite_cases_path(
    target_py: Path,
    json_name: str,
    component: str | None = None,
) -> None:
    """Point copied test module to companion JSON in repo test_data/."""
    content = target_py.read_text(encoding="utf-8")
    pattern = r'_CASES_PATH = Path\(__file__\).*'
    if component:
        replacement = (
            '_CASES_PATH = Path(__file__).resolve().parents[2] / '
            f'"test_data" / "{component}" / "{json_name}"'
        )
    else:
        replacement = (
            '_CASES_PATH = Path(__file__).resolve().parents[1] / '
            f'"test_data" / "{json_name}"'
        )
    updated = re.sub(pattern, replacement, content, count=1)
    target_py.write_text(updated, encoding="utf-8")


def _autocopy_to_tests(
    out_py: Path,
    out_json: Path,
    flat_output: bool = False,
    component_hint: str | None = None,
) -> tuple[Path, Path]:
    """Copy generated module + data file into repo test folders."""
    if flat_output:
        _REPO_TESTS_DIR.mkdir(parents=True, exist_ok=True)
        _REPO_TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
        target_py = _REPO_TESTS_DIR / out_py.name
        target_json = _REPO_TEST_DATA_DIR / out_json.name
        shutil.copy2(out_py, target_py)
        shutil.copy2(out_json, target_json)
        _rewrite_cases_path(target_py, out_json.name, component=None)
        return target_py, target_json

    component = component_hint or _component_from_filename(out_py.name)
    target_py_dir = _REPO_TESTS_DIR / component
    target_json_dir = _REPO_TEST_DATA_DIR / component
    target_py_dir.mkdir(parents=True, exist_ok=True)
    target_json_dir.mkdir(parents=True, exist_ok=True)

    target_py = target_py_dir / out_py.name
    target_json = target_json_dir / out_json.name
    shutil.copy2(out_py, target_py)
    shutil.copy2(out_json, target_json)
    _rewrite_cases_path(target_py, out_json.name, component=component)
    return target_py, target_json


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate pytest tests from spec sheet / CLI / JSON.")
    ap.add_argument("--source", required=True, choices=["file", "url", "cli", "json"])
    ap.add_argument("locator", nargs="?",
                    help="xlsx/json filename (looked up in input/), URL, or JSON path")
    ap.add_argument("--component", default=None,
                    help="Override component name (default: derived from the input)")
    # CLI-mode args
    ap.add_argument("--endpoint", default=None,
                    help="Full https URL of the endpoint (cli mode)")
    ap.add_argument("--method", default="GET", help="HTTP method (cli mode, default GET)")
    ap.add_argument("--response-fields", default=None, dest="response_fields",
                    help="Comma-separated list of expected response field names (cli mode)")
    ap.add_argument("--test-data", default=None,
                    help="Pre-built JSON from the test-data-generator skill. When passed, "
                         "the generated pytest module references this JSON instead of "
                         "synthesizing companion data from spec-sheet placeholder values.")
    ap.add_argument("--no-autocopy-tests", action="store_true",
                    help="Disable automatic copy of generated .py/.json into repo tests/.")
    ap.add_argument("--flat-output", action="store_true",
                    help="Auto-copy into tests/ and test_data/ root (no component subfolders).")
    ap.add_argument("--output-name", default=None,
                    help="Base filename for generated outputs. Example: cross-env "
                         "-> test_cross-env.py and cross-env.json.")
    ap.add_argument("--use-seed-source", dest="use_seed_source", action="store_true",
                    help="Hydrate generated test_data values from seed YAML + endpoint map "
                         "(default ON when --test-data is not provided).")
    ap.add_argument("--no-seed-source", dest="use_seed_source", action="store_false",
                    help="Disable seed hydration and keep taxonomy placeholder values.")
    ap.add_argument("--seed-fanout", action="store_true",
                    help="When using seed hydration, fan out positive rows across all seed "
                         "records (default preserves row count).")
    ap.set_defaults(use_seed_source=True)
    args = ap.parse_args()

    if args.source == "url":
        xlsx = _fetch_xlsx_url(args.locator or "")
        parsed_json = _run_python(_SCRIPT_DIR / "parse_spec_sheet.py", [str(xlsx)])
        try:
            parsed = json.loads(parsed_json)
        except json.JSONDecodeError as exc:
            _die(f"parser output not JSON: {exc}")
    elif args.source == "file":
        # file mode can load either xlsx specs or JSON endpoint definitions
        if not args.locator:
            xlsx = _resolve_input(None, ".xlsx")
            parsed_json = _run_python(_SCRIPT_DIR / "parse_spec_sheet.py", [str(xlsx)])
            try:
                parsed = json.loads(parsed_json)
            except json.JSONDecodeError as exc:
                _die(f"parser output not JSON: {exc}")
        else:
            resolved = _resolve_file_locator(args.locator)
            suffix = resolved.suffix.lower()
            if suffix == ".xlsx":
                parsed_json = _run_python(_SCRIPT_DIR / "parse_spec_sheet.py", [str(resolved)])
                try:
                    parsed = json.loads(parsed_json)
                except json.JSONDecodeError as exc:
                    _die(f"parser output not JSON: {exc}")
            elif suffix == ".json":
                endpoints = _endpoints_from_json(resolved, args.component)
                rows = _expand_endpoints_to_rows(endpoints, args.component)
                LOG.info("Expanded %d endpoint(s) into %d row(s)", len(endpoints), len(rows))
                parsed = _rows_to_parsed_shape(rows, str(resolved))
                parsed = _drop_workflow_rows(parsed)
                parsed_json = json.dumps(parsed, default=str)
            else:
                _die(
                    f"--source file supports .xlsx or .json, got {resolved.name!r} "
                    f"(suffix {suffix!r})"
                )
    else:
        # cli / json: build endpoint dicts → expand via testcase-generator
        if args.source == "cli":
            endpoints = _endpoints_from_cli(args)
            origin = "cli-input"
        else:  # json
            json_path = _resolve_input(args.locator, ".json")
            endpoints = _endpoints_from_json(json_path, args.component)
            origin = str(json_path)
        rows = _expand_endpoints_to_rows(endpoints, args.component)
        LOG.info("Expanded %d endpoint(s) into %d row(s)", len(endpoints), len(rows))
        parsed = _rows_to_parsed_shape(rows, origin)
        parsed = _drop_workflow_rows(parsed)
        parsed_json = json.dumps(parsed, default=str)

    component_default = "mixed"
    if parsed.get("groups"):
        components = sorted({g["component"] for g in parsed["groups"]})
        component_default = "_".join(components[:3])
    component = args.component or component_default

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_py, out_json = _output_paths(component, args.output_name)

    gen_args = ["--out-py", str(out_py), "--out-json", str(out_json)]
    if args.test_data:
        test_data_path = Path(args.test_data)
        if not test_data_path.exists():
            # Fall back to the test-data-generator inbox lookup
            candidate = _SKILL_ROOT / "received_test_data" / args.test_data
            if candidate.exists():
                test_data_path = candidate
            else:
                _die(f"--test-data not found: tried {Path(args.test_data)} and {candidate}")
        LOG.info("Using pre-built test data: %s", test_data_path)
        gen_args += ["--user-test-data", str(test_data_path)]
    elif args.use_seed_source:
        hydrated_payload = _seed_hydrated_test_data(parsed, fanout=args.seed_fanout)
        if hydrated_payload is not None:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".json",
                prefix="test_generator_seeded_",
                delete=False,
            ) as tmp_file:
                json.dump(hydrated_payload, tmp_file, ensure_ascii=False, indent=2, default=str)
                tmp_path = Path(tmp_file.name)
            LOG.info("Using auto seed-hydrated test data: %s", tmp_path)
            gen_args += ["--user-test-data", str(tmp_path)]

    summary_json = _run_python(
        _SCRIPT_DIR / "generate_pytest.py",
        gen_args,
        stdin=parsed_json,
    )
    try:
        summary: dict[str, Any] = json.loads(summary_json)
    except json.JSONDecodeError as exc:
        _die(f"generator output not JSON: {exc}")

    copied_py = None
    copied_json = None
    if not args.no_autocopy_tests:
        copied_py, copied_json = _autocopy_to_tests(
            out_py,
            out_json,
            args.flat_output,
            component_hint=component,
        )
        LOG.info("Auto-copied generated files to tests/: %s, %s", copied_py, copied_json)

    print(f"\nWrote {summary['out_py']}")
    print(f"Wrote {summary['out_json']}")
    if copied_py and copied_json:
        print(f"Auto-copied {copied_py}")
        print(f"Auto-copied {copied_json}")
    print(f"Classes:               {summary['class_count']}")
    print(f"Workflows:             {summary['workflow_count']}")
    print(f"Cases:                 {summary['case_count']}")
    print(f"Components:            {summary['components']}")
    print(f"Validators referenced: {summary['validators']}")
    print()
    print("Next steps:")
    print("  1. Review the generated .py file in output/.")
    print(f"  2. Ensure each of {summary['validators']} exists in src/validators.py.")
    if args.no_autocopy_tests:
        print("  3. Move the .py file to tests/ and the .json file alongside it.")
    else:
        if args.flat_output:
            print("  3. Files were auto-copied to tests/ and test_data/ roots.")
        else:
            print("  3. Files were auto-copied to tests/<component>/ and test_data/<component>/.")
    print("  4. Run the relevant pytest command, e.g.:")
    for comp in summary["components"]:
        if args.flat_output:
            print(f"     pytest --env {comp} tests/{Path(summary['out_py']).name}")
        else:
            print(f"     pytest --env {comp} tests/{comp}/{Path(summary['out_py']).name}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
