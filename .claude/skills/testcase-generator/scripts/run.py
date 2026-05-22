"""Single entry point for the testcase-generator skill.

QA runs ONE command — the script picks the right parser based on --source.

    python run.py --source openapi    <path-or-url>
    python run.py --source url        <https-url>
    python run.py --source file       <filename-in-input-dir>
    python run.py --source jira       <ISSUE-KEY>     # needs Atlassian MCP
    python run.py --source confluence <PAGE-ID>       # needs Atlassian MCP

Extraction strategy for non-OpenAPI sources (URL / file / jira / confluence):

  1. PRIMARY  — LLM extraction (DEFAULT, no flag). The script saves the raw text
                and emits a JSON instruction; Claude reads the text, builds the
                endpoint list semantically, and re-invokes with --endpoints.
                Highest quality — does not miss endpoints.

  2. FALLBACK — Regex/heuristic extraction (--regex-fallback). Used only when
                no LLM is available (e.g. CI runs, scripted automation). Lossy:
                misses endpoints that don't match obvious patterns. The script
                prints a loud warning when this path is taken.

Optional:
    --format xlsx|csv|json|txt|docx|pdf  (default: xlsx)
    --component <name>                    (default: auto-detect)
    --priority-bias p0|p1|p2              (default: none)
    --against <path-to-previous.xlsx>     (diff mode)
    --force                               (overwrite Reviewed/Approved rows)
    --endpoints <path>                    (skip extraction; use pre-built endpoints.json)
    --regex-fallback                      (fallback only — see "FALLBACK" above)
"""
import argparse
import json
import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

LOG = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).parent
_SKILL_ROOT = _SCRIPT_DIR.parent
_INPUT_DIR = _SKILL_ROOT / "received_sources"
_OUTPUT_DIR = _SKILL_ROOT / "generated_spec_sheets"

_OPENAPI_EXTS = {".yaml", ".yml", ".json"}
_DOC_EXTS = {".txt", ".md", ".markdown", ".pdf", ".docx"}


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _run_python(script: str, args: list[str], stdin: str | None = None) -> str:
    """Run a sibling Python script and return its stdout (raises on non-zero)."""
    cmd = [sys.executable, str(_SCRIPT_DIR / script), *args]
    result = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        sys.exit(result.returncode)
    return result.stdout


def _latest_in_input() -> Path:
    """Pick the most recently modified file in the skill's input/ directory."""
    candidates = [p for p in _INPUT_DIR.iterdir()
                  if p.is_file() and p.name != ".gitkeep"]
    if not candidates:
        _die(f"[run] received_sources/ is empty: {_INPUT_DIR}")
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    print(f"[run] input/ contains {len(candidates)} file(s); picked latest: {latest.name}",
          file=sys.stderr)
    return latest


def _resolve_file(name: str | None) -> Path:
    """Resolve a locator to a Path.

    Rules:
      - No name given        → latest file in input/
      - Bare filename        → look in input/
      - Existing path        → use as-is
    """
    if not name:
        return _latest_in_input()
    p = Path(name)
    if p.is_absolute() or p.exists():
        return p
    candidate = _INPUT_DIR / name
    if candidate.exists():
        return candidate
    _die(f"[run] file not found: tried {p} and {candidate}")
    return p  # unreachable


def _produce_endpoints_openapi(locator: str | None) -> str:
    """Run parse_openapi.py → endpoints JSON."""
    if locator and locator.startswith("https://"):
        return _run_python("parse_openapi.py", [locator])
    path = _resolve_file(locator)
    return _run_python("parse_openapi.py", [str(path)])


def _html_to_text(raw: str) -> str:
    """Strip the Content-Type header and HTML tags from fetch_url.py output."""
    from bs4 import BeautifulSoup
    body = raw.split("\n\n", 1)[1] if "\n\n" in raw else raw
    soup = BeautifulSoup(body, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return str(soup.get_text("\n"))


def _maybe_auto_extract(raw_text: str, traceability: str, regex_fallback: bool,
                        source: str) -> str:
    """Default path is LLM extraction. Regex is the fallback (lossy)."""
    if regex_fallback:
        print(
            "[run] WARNING: --regex-fallback enabled. Regex extraction is lossy and may "
            "MISS endpoints that don't match obvious patterns (GET /path, backticked "
            "params, etc.). Prefer LLM extraction (default, no flag) unless no LLM is "
            "available. Review the output sheet carefully.",
            file=sys.stderr,
        )
        endpoints_json = _run_python(
            "heuristic_extract.py",
            ["--traceability", traceability],
            stdin=raw_text,
        )
        if not endpoints_json.strip():
            _die(
                "[run] regex fallback produced no endpoints. Re-run WITHOUT "
                "--regex-fallback so the LLM can extract them properly."
            )
        return endpoints_json

    # Primary path: LLM extraction. Save raw text and instruct Claude.
    tmp = Path(tempfile.gettempdir()) / "generate_testcases_raw.txt"
    tmp.write_text(raw_text, encoding="utf-8")
    print(json.dumps({
        "status": "needs_llm_extraction",
        "source": source,
        "locator": traceability,
        "raw_text_path": str(tmp),
        "preferred_path": "LLM",
        "why_llm_preferred": (
            "LLM extraction reads the full document semantically and does not miss "
            "endpoints that aren't written in obvious patterns. Regex fallback is "
            "lossy by design — only use it when no LLM is available (e.g. CI)."
        ),
        "next_step_llm": (
            f"Claude: read {tmp}, build endpoints.json matching the schema in SKILL.md "
            f"(Normalize step), then re-run: python {_SCRIPT_DIR / 'run.py'} "
            f"--endpoints <endpoints.json> --source {source} --component <name>"
        ),
        "next_step_regex_fallback_only_if_no_llm": (
            f"python {_SCRIPT_DIR / 'run.py'} --source {source} {traceability} "
            "--regex-fallback   # lossy; not recommended when an LLM is available"
        ),
    }, indent=2))
    sys.exit(10)
    return ""  # unreachable


def _expand_url_locator(locator: str) -> list[str]:
    """Resolve a locator into a list of URLs.

    Accepts:
      * a single URL (https://...)
      * comma-separated URLs (https://a,https://b)
      * a path to a .txt / .list file with one URL per line (# comments allowed)
      * a bare filename — looked up in input/

    """
    # File on disk
    candidate = Path(locator) if Path(locator).exists() else (_INPUT_DIR / locator)
    if candidate.exists() and candidate.is_file() and candidate.suffix.lower() in (".txt", ".list"):
        urls = [
            line.strip()
            for line in candidate.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if not urls:
            _die(f"[run] {candidate} contains no URLs")
        print(f"[run] read {len(urls)} URL(s) from {candidate}", file=sys.stderr)
        return urls
    # Comma-separated
    if "," in locator:
        urls = [u.strip() for u in locator.split(",") if u.strip()]
        print(f"[run] expanded comma-separated list to {len(urls)} URL(s)", file=sys.stderr)
        return urls
    return [locator]


def _relative_path(raw_path: str) -> str:
    """Normalize a path or URL to a version-stripped relative API path."""
    path = raw_path.strip()
    if path.startswith("http://") or path.startswith("https://"):
        path = urlparse(path).path or ""
    path = re.sub(r"^/v[0-9]+(?:\.[0-9]+)*", "", path)
    if not path:
        return "/"
    if not path.startswith("/"):
        return f"/{path}"
    return path


def _filter_weather_forecast_only(
    endpoints: list[dict[str, Any]], component: str | None
) -> list[dict[str, Any]]:
    """When component=weather, keep only GET /forecast endpoints."""
    if component != "weather":
        return endpoints
    filtered: list[dict[str, Any]] = []
    for endpoint in endpoints:
        method = str(endpoint.get("method", "GET")).upper()
        raw_path = str(endpoint.get("path") or endpoint.get("endpoint_url") or "")
        rel_path = _relative_path(raw_path)
        if method == "GET" and rel_path == "/forecast":
            endpoint["path"] = rel_path
            filtered.append(endpoint)
    print(
        f"[run] weather filter enabled: kept {len(filtered)} of "
        f"{len(endpoints)} endpoint(s) (GET /forecast only)",
        file=sys.stderr,
    )
    return filtered


def _produce_endpoints_url(locator: str, auto: bool) -> str:
    """Fetch one or more URLs and extract endpoints.

    With --regex-fallback: runs heuristic_extract on every URL and combines them.
    Without: saves raw text per URL and emits a needs_llm_extraction batch message.
    """
    urls = _expand_url_locator(locator)

    if not auto:
        raw_paths: list[dict[str, str]] = []
        for i, url in enumerate(urls, 1):
            raw = _run_python("fetch_url.py", [url])
            text = _html_to_text(raw)
            tmp = Path(tempfile.gettempdir()) / f"generate_testcases_raw_{i}.txt"
            tmp.write_text(text, encoding="utf-8")
            raw_paths.append({"url": url, "raw_text_path": str(tmp)})
        print(json.dumps({
            "status": "needs_llm_extraction",
            "source": "url",
            "url_count": len(urls),
            "raw_texts": raw_paths,
            "preferred_path": "LLM",
            "why_llm_preferred": (
                "LLM extraction reads each page semantically and does not miss endpoints."
            ),
            "next_step_llm": (
                f"Claude: read each raw_text_path, build one endpoints JSON per URL, "
                f"then re-run with multiple --endpoints flags so cross-API workflow "
                f"recipes can match. Example: python {_SCRIPT_DIR / 'run.py'} "
                f"--endpoints ep1.json --endpoints ep2.json --source url --component <name>"
            ),
            "next_step_regex_fallback_only_if_no_llm": (
                f"python {_SCRIPT_DIR / 'run.py'} --source url \"{locator}\" "
                "--regex-fallback  # lossy"
            ),
        }, indent=2))
        sys.exit(10)

    # Regex fallback path: extract from every URL and combine
    combined: list[Any] = []
    for url in urls:
        raw = _run_python("fetch_url.py", [url])
        text = _html_to_text(raw)
        try:
            endpoints_json = _run_python(
                "heuristic_extract.py", ["--traceability", url], stdin=text
            )
        except SystemExit:
            print(f"[run] regex fallback found 0 endpoints in {url} — skipping",
                  file=sys.stderr)
            continue
        if endpoints_json.strip():
            combined.extend(json.loads(endpoints_json))
    if not combined:
        _die("[run] regex fallback produced no endpoints across any URL. "
             "Re-run WITHOUT --regex-fallback so the LLM can extract them properly.")
    print(f"[run] regex fallback combined {len(urls)} URL(s) → {len(combined)} endpoint(s)",
          file=sys.stderr)
    return json.dumps(combined)


def _produce_endpoints_file(locator: str | None, auto: bool) -> str:
    """Local document — dispatch by extension. Picks latest from input/ if no locator."""
    path = _resolve_file(locator)
    if path.suffix.lower() in _OPENAPI_EXTS:
        return _run_python("parse_openapi.py", [str(path)])
    if path.suffix.lower() in _DOC_EXTS:
        raw = _run_python("parse_document.py", [str(path)])
        return _maybe_auto_extract(raw, str(path), auto, "file")
    _die(f"[run] unsupported file extension: {path.suffix}")
    return ""  # unreachable


def _produce_endpoints_mcp(kind: str, locator: str) -> str:
    """Jira / Confluence — both require Atlassian MCP fetch driven by Claude."""
    print(json.dumps({
        "status": "needs_mcp_fetch",
        "source": kind,
        "locator": locator,
        "next_step": (
            f"Claude: call Atlassian MCP to fetch the {kind} payload for '{locator}', "
            f"pipe the JSON into scripts/parse_{kind}.py {locator}, then build "
            "endpoints.json per SKILL.md, then re-run: "
            f"python {_SCRIPT_DIR / 'run.py'} --endpoints <endpoints.json> "
            f"--source {kind} --component <name>"
        ),
        "mcp_setup_help": str(_SKILL_ROOT / "references" / "mcp_setup.md"),
    }, indent=2))
    sys.exit(10)


_DISPATCH = {
    "openapi":    lambda loc, auto: _produce_endpoints_openapi(loc),
    "url":        _produce_endpoints_url,
    "file":       _produce_endpoints_file,
    "jira":       lambda loc, auto: _produce_endpoints_mcp("jira", loc),
    "confluence": lambda loc, auto: _produce_endpoints_mcp("confluence", loc),
}

# testcases_<source>_<component>_<YYYYMMDD_HHMMSSZ>.xlsx
_PRIOR_SPEC_RE = re.compile(
    r"^testcases_(?P<source>[a-z]+)_(?P<component>[a-z+]+)_"
    r"(?P<ts>\d{8}_\d{6}Z)\.xlsx$"
)


def _find_latest_prior_spec(source: str, component: str, fmt: str) -> Path | None:
    """Return the newest prior spec sheet for the same component (and source if possible)."""
    if fmt != "xlsx" or component in ("mixed", "unknown", ""):
        return None
    if not _OUTPUT_DIR.is_dir():
        return None

    strict: list[tuple[str, Path]] = []
    loose: list[tuple[str, Path]] = []
    for path in _OUTPUT_DIR.iterdir():
        if not path.is_file() or path.name.startswith("~$"):
            continue
        match = _PRIOR_SPEC_RE.match(path.name)
        if not match or match.group("component") != component:
            continue
        ts = match.group("ts")
        if match.group("source") == source:
            strict.append((ts, path))
        else:
            loose.append((ts, path))

    pool = strict if strict else loose
    if not pool:
        return None
    pool.sort(key=lambda item: item[0], reverse=True)
    return pool[0][1]


def _suggest_against_prior(
    source: str, component: str, fmt: str, against: str | None
) -> None:
    """Print a hint when a prior spec exists and --against was not passed (opt-in diff mode)."""
    if against is not None or fmt != "xlsx":
        return
    prior = _find_latest_prior_spec(source, component, fmt)
    if prior is None:
        return
    try:
        rel = prior.relative_to(_SKILL_ROOT)
        against_arg = str(rel)
    except ValueError:
        against_arg = str(prior)
    print(
        f"Tip: A previous spec sheet was found. Re-run with --against {against_arg} "
        "to compare new/changed test cases.",
        file=sys.stderr,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate API test-case spec sheet from any source.")
    ap.add_argument("--source", required=True, choices=list(_DISPATCH))
    ap.add_argument("locator", nargs="?", help="URL / file / ticket / page id")
    ap.add_argument("--endpoints", action="append", default=None,
                    help="Skip extraction; use pre-built endpoints JSON. Pass multiple "
                         "times to combine sources (enables cross-API workflows).")
    ap.add_argument("--format", default="xlsx", choices=["xlsx", "csv", "json", "txt", "docx", "pdf"])
    ap.add_argument("--component", default=None)
    ap.add_argument("--priority-bias", default=None, choices=["p0", "p1", "p2", "P0", "P1", "P2"])
    ap.add_argument("--against", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--regex-fallback", "--auto-extract", action="store_true",
                    dest="regex_fallback",
                    help="FALLBACK ONLY: use regex/heuristic extraction when no LLM is "
                         "available (e.g. CI). LLM-driven extraction (the default) is "
                         "preferred — regex is lossy and may miss endpoints.")
    args = ap.parse_args()

    # Step 1: get endpoints JSON
    if args.endpoints:
        combined: list[Any] = []
        for path_str in args.endpoints:
            data = json.loads(Path(path_str).read_text())
            if isinstance(data, list):
                combined.extend(data)
            else:
                combined.append(data)
        print(f"[run] combined {len(args.endpoints)} endpoints file(s) → "
              f"{len(combined)} endpoint(s) total", file=sys.stderr)
        endpoints_json = json.dumps(combined)
    else:
        # --source file and --source openapi accept missing locator (auto-pick latest in input/)
        if not args.locator and args.source not in ("file", "openapi"):
            _die(f"[run] locator required for --source {args.source}")
        endpoints_json = _DISPATCH[args.source](args.locator, args.regex_fallback)

    parsed_endpoints = json.loads(endpoints_json)
    endpoint_list: list[dict[str, Any]]
    if isinstance(parsed_endpoints, list):
        endpoint_list = [e for e in parsed_endpoints if isinstance(e, dict)]
    elif isinstance(parsed_endpoints, dict):
        endpoint_list = [parsed_endpoints]
    else:
        _die("[run] endpoints payload must be a JSON object or list of objects")

    endpoint_list = _filter_weather_forecast_only(endpoint_list, args.component)
    if not endpoint_list:
        _die("[run] no endpoints left after filtering")
    endpoints_json = json.dumps(endpoint_list)

    # Step 2: expand into rows
    gen_args = []
    if args.component:
        gen_args.extend(["--component", args.component])
    if args.priority_bias:
        gen_args.extend(["--priority-bias", args.priority_bias])
    rows_json = _run_python("generate_cases.py", gen_args, stdin=endpoints_json)

    # Step 3: write output
    rows_tmp = Path(tempfile.gettempdir()) / "generate_testcases_rows.json"
    rows_tmp.write_text(rows_json)
    component_name = args.component or _infer_component(rows_json)
    _suggest_against_prior(args.source, component_name, args.format, args.against)
    write_args = [
        "--rows", str(rows_tmp),
        "--format", args.format,
        "--source", args.source,
        "--component", component_name,
    ]
    if args.against:
        write_args.extend(["--against", args.against])
    if args.force:
        write_args.append("--force")
    out = _run_python("write_output.py", write_args)
    sys.stdout.write(out)


def _infer_component(rows_json: str) -> str:
    try:
        rows: list[dict[str, Any]] = json.loads(rows_json)
        if rows and rows[0].get("component"):
            return str(rows[0]["component"])
    except json.JSONDecodeError:
        pass
    return "mixed"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
