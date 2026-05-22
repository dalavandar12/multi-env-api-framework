"""Read the input spec — either xlsx (spec sheet) or JSON (thin endpoint defs).

For xlsx: delegates to test-generator/scripts/parse_spec_sheet.py via subprocess
so we never duplicate that logic. Returns the parsed structure verbatim.

For JSON: accepts the same shape as test-generator's JSON mode (single dict OR
list of {endpoint_url, method, ...}) and converts it into the grouped shape
parse_spec_sheet.py would have produced.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPT_DIR.parent
_TEST_GEN_PARSER = (
    _SKILL_ROOT.parent / "test-generator" / "scripts" / "parse_spec_sheet.py"
)


class InputError(Exception):
    """Raised when the input spec is missing or malformed."""


def _infer_component(url: str) -> str:
    host = re.match(r"https?://([^/]+)", url or "")
    if not host:
        return "unknown"
    parts = host.group(1).split(".")
    # restcountries.com → restcountries → countries (heuristic)
    if "restcountries" in parts:
        return "countries"
    if "open-meteo" in parts or "openmeteo" in parts:
        return "weather"
    return parts[-2] if len(parts) >= 2 else parts[0]


def from_spec_sheet(path: Path) -> dict[str, Any]:
    """Run test-generator's parser and return its JSON output."""
    if not _TEST_GEN_PARSER.exists():
        raise InputError(
            f"reused spec-sheet parser missing: {_TEST_GEN_PARSER}. "
            "test-data-generator depends on test-generator being installed."
        )
    LOG.info("Delegating spec-sheet parse to %s", _TEST_GEN_PARSER)
    result = subprocess.run(
        [sys.executable, str(_TEST_GEN_PARSER), str(path)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise InputError(
            f"spec-sheet parser failed (exit {result.returncode}):\n{result.stderr}"
        )
    return dict(json.loads(result.stdout))


def from_json(path: Path) -> dict[str, Any]:
    """Convert a thin endpoint JSON into the same grouped shape parse_spec_sheet.py emits.

    Each entry becomes ONE class group with a single synthetic 'positive' row so the
    downstream substitution still has something to act on.
    """
    if not path.exists():
        raise InputError(f"JSON input not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InputError(f"could not parse {path}: {exc}") from exc
    entries = raw if isinstance(raw, list) else [raw]
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for i, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or "endpoint_url" not in entry or "method" not in entry:
            raise InputError(f"JSON entry #{i} missing endpoint_url or method")
        component = entry.get("component") or _infer_component(entry["endpoint_url"])
        method = str(entry["method"]).upper()
        url = str(entry["endpoint_url"])
        row = {
            "tc_id": f"TC_{component.upper()}_JSON_{i:03d}",
            "title": f"{method} {url}: positive",
            "category": "positive",
            "case_type": "positive",
            "priority": "P1",
            "component": component,
            "pytest_marker": f"@pytest.mark.{component}",
            "endpoint_url": url,
            "method": method,
            "path_params": {},
            "query_params": {},
            "headers": {"Accept": "application/json"},
            "request_body": {},
            "preconditions": "",
            "expected_status": (entry.get("status_codes") or [200])[0],
            "expected_response_fields": entry.get("response_fields") or [],
            "expected_response_body": {},
            "expected_response_time_ms": 0,
            "equivalence_class": "happy",
            "test_data_ref": f"test_data/{component}.json#json-mode",
            "validator_ref": f"validate_{component}_schema",
            "traceability": str(path),
            "source_excerpt": "",
            "workflow_steps": [],
            "review_status": "Draft",
            "notes": "",
        }
        groups[(component, url, method)].append(row)

    out_groups = []
    for (component, url, method), rows in groups.items():
        out_groups.append({
            "component": component,
            "endpoint_url": url,
            "method": method,
            "pytest_marker": f"@pytest.mark.{component}",
            "summary": rows[0]["title"],
            "rows": rows,
        })
    LOG.info("Loaded %d endpoint group(s) from JSON %s", len(out_groups), path)
    return {"spec_sheet": str(path), "groups": out_groups, "workflow_rows": []}
