"""Regex / heuristic endpoint extractor for free-form text.

Lossy by design — produces the same endpoint dict shape as parse_openapi.py
but only catches patterns that look like API docs:

  * "GET /v1/forecast"
  * "https://api.example.com/v1/forecast?latitude=...&longitude=..."
  * "Required parameters: latitude, longitude"
  * "Status codes: 200, 400, 404"
  * Backticked params:  `latitude`, `hourly`
  * "values: celsius, fahrenheit" → enum

Emits a warning to stderr summarizing how many endpoints were extracted so the
caller can fall back to LLM extraction if the harvest is thin.

CLI:
    cat raw.txt | python heuristic_extract.py [--traceability <ref>]
"""
import argparse
import json
import logging
import re
import sys
from typing import Any
from urllib.parse import urlparse

LOG = logging.getLogger(__name__)

_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

# 1) "GET /path" or "POST /path"
_METHOD_PATH_RE = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_./{}-]+)"
)

# 2) Bare full URLs that look like API endpoints
_FULL_URL_RE = re.compile(
    r"https?://[A-Za-z0-9.-]+(?:\:[0-9]+)?/[A-Za-z0-9_./{}-]+"
)

# 3) Query parameter mentions
_QUERY_PARAM_RE = re.compile(r"[?&]([a-zA-Z_][a-zA-Z0-9_]*)\s*=")

# 4) Path parameters: {petId}, :petId
_PATH_PARAM_RE = re.compile(r"[{:]([a-zA-Z_][a-zA-Z0-9_]*)\}?")

# 5) Backticked identifiers — usually parameter names in markdown/HTML docs
_BACKTICK_RE = re.compile(r"`([a-zA-Z_][a-zA-Z0-9_]{1,40})`")

# 6) Status codes
_STATUS_RE = re.compile(r"\b([1-5][0-9]{2})\b")

# 7) "Required:" / "Optional:" sections
_SECTION_RE = re.compile(
    r"(?im)^(?P<label>required|optional|mandatory)[\s:]+parameters?[:\s]*"
)

# 8) Enum hint: "values: a, b, c" or "one of: a | b | c"
_ENUM_RE = re.compile(
    r"(?im)(?:values?|one\s+of|allowed)[\s:]+([a-z0-9_,\s|/-]+)"
)


def _scan_methods_paths(text: str) -> list[tuple[str, str]]:
    return [(m.group(1).upper(), m.group(2)) for m in _METHOD_PATH_RE.finditer(text)]


def _scan_full_urls(text: str) -> list[tuple[str, str]]:
    """Treat full URLs as GET /<path> unless an adjacent method appears."""
    out: list[tuple[str, str]] = []
    for m in _FULL_URL_RE.finditer(text):
        url = m.group(0).rstrip(".,);")
        # Skip robots/sitemap/asset URLs
        if any(seg in url for seg in ("robots.txt", "sitemap", ".css", ".js", ".png", ".jpg", ".svg")):
            continue
        out.append(("GET", url))
    return out


def _params_near(text: str, position: int, window: int = 800) -> tuple[list[str], list[str]]:
    """Look forward 'window' chars from position for parameter mentions."""
    chunk = text[position:position + window]
    required: set[str] = set()
    optional: set[str] = set()

    # Query params from the same chunk's URL fragments
    for q in _QUERY_PARAM_RE.findall(chunk):
        optional.add(q)

    # Section-driven classification
    section: str | None = None
    for line in chunk.splitlines():
        sec = _SECTION_RE.match(line.strip())
        if sec:
            label = sec.group("label").lower()
            section = "required" if label in ("required", "mandatory") else "optional"
            continue
        # Pick up backticked identifiers under each section
        for ident in _BACKTICK_RE.findall(line):
            if len(ident) < 3 or ident in _METHODS:
                continue
            (required if section == "required" else optional).add(ident)

    return sorted(required), sorted(optional - required)


def _status_codes_near(text: str, position: int, window: int = 1200) -> list[int]:
    chunk = text[position:position + window]
    codes = {int(c) for c in _STATUS_RE.findall(chunk) if 100 <= int(c) <= 599}
    return sorted(codes)


def _enum_for_param(text: str, param: str, window: int = 400) -> list[str] | None:
    """Look near the first backticked occurrence of `param` for an enum hint."""
    idx = text.find(f"`{param}`")
    if idx < 0:
        return None
    chunk = text[idx:idx + window]
    m = _ENUM_RE.search(chunk)
    if not m:
        return None
    raw = m.group(1)
    tokens = re.split(r"[,\s|/]+", raw)
    values = [t.strip() for t in tokens if 2 <= len(t.strip()) <= 30 and t.strip().isascii()]
    return values[:8] or None


def _path_params(path: str) -> set[str]:
    return set(_PATH_PARAM_RE.findall(path))


def _build_param_dict(text: str, name: str, in_loc: str, required: bool) -> dict[str, Any]:
    enum = _enum_for_param(text, name)
    return {
        "name": name,
        "in": in_loc,
        "type": "string",
        "format": None,
        "enum": enum,
        "description": "",
        "_required": required,
    }


def extract(text: str, traceability: str) -> list[dict[str, Any]]:
    candidates: dict[tuple[str, str], int] = {}
    for method, path in _scan_methods_paths(text):
        candidates.setdefault((method, path), text.find(path))
    for method, url in _scan_full_urls(text):
        path = url
        candidates.setdefault((method, path), text.find(url))

    endpoints: list[dict[str, Any]] = []
    for (method, path), position in candidates.items():
        required_names, optional_names = _params_near(text, position)
        path_params = _path_params(path)
        statuses = _status_codes_near(text, position) or [200]

        params_required: list[dict[str, Any]] = []
        params_optional: list[dict[str, Any]] = []
        for n in sorted(path_params | set(required_names)):
            params_required.append(_build_param_dict(text, n, "path" if n in path_params else "query", True))
        for n in sorted(set(optional_names) - path_params - set(required_names)):
            params_optional.append(_build_param_dict(text, n, "query", False))

        host = urlparse(path).hostname or ""
        tags: list[str] = []
        if host:
            tags.append(host.split(".")[0])

        endpoints.append({
            "method": method,
            "path": path,
            "summary": text[max(0, position - 120):position].strip().splitlines()[-1] if position > 0 else "",
            "tags": tags,
            "params_required": params_required,
            "params_optional": params_optional,
            "request_schema": {},
            "response_schema": {},
            "status_codes": statuses,
            "examples": {},
            "source_excerpt": text[max(0, position - 80):position + 200].strip()[:400],
            "traceability": traceability,
        })

    return endpoints


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--traceability", default="heuristic")
    args = ap.parse_args()
    text = sys.stdin.read()
    if not text.strip():
        print("[heuristic_extract] empty stdin", file=sys.stderr)
        sys.exit(2)
    endpoints = extract(text, args.traceability)
    print(f"[heuristic_extract] extracted {len(endpoints)} endpoint(s) — lossy, review the spec sheet",
          file=sys.stderr)
    if len(endpoints) == 0:
        print("[heuristic_extract] no endpoints found — consider LLM extraction or a different source",
              file=sys.stderr)
        sys.exit(3)
    json.dump(endpoints, sys.stdout, indent=2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
