"""OpenAPI / Swagger 2.0 / 3.x → normalized endpoint list.

Reads a local YAML/JSON file or a URL (delegates to fetch_url.py).
Emits a list of endpoint dicts on stdout (JSON), one per path × method.
"""
import json
import logging
import sys
from pathlib import Path
from typing import Any

import yaml

from fetch_url import fetch

LOG = logging.getLogger(__name__)


def _load(source: str) -> dict[str, Any]:
    if source.startswith("https://"):
        ctype, body = fetch(source)
        text = body.decode("utf-8", errors="replace")
        if "json" in ctype:
            return dict(json.loads(text))
        return dict(yaml.safe_load(text))
    path = Path(source)
    if not path.exists():
        print(f"[parse_openapi] file not found: {source}", file=sys.stderr)
        sys.exit(2)
    text = path.read_text()
    if path.suffix.lower() == ".json":
        return dict(json.loads(text))
    return dict(yaml.safe_load(text))


def _params(op: dict[str, Any], path_item: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    required: list[dict[str, Any]] = []
    optional: list[dict[str, Any]] = []
    all_params = list(path_item.get("parameters", [])) + list(op.get("parameters", []))
    for p in all_params:
        entry = {
            "name": p.get("name"),
            "in": p.get("in"),
            "type": (p.get("schema") or {}).get("type") or p.get("type"),
            "format": (p.get("schema") or {}).get("format") or p.get("format"),
            "enum": (p.get("schema") or {}).get("enum") or p.get("enum"),
            "description": p.get("description", ""),
        }
        (required if p.get("required") else optional).append(entry)
    return required, optional


def _response_schema(op: dict[str, Any]) -> dict[str, Any]:
    responses = op.get("responses", {})
    for code in ("200", "201", "default"):
        if code in responses:
            resp = responses[code]
            content = resp.get("content", {}) if isinstance(resp, dict) else {}
            for media_type in ("application/json", "*/*"):
                if media_type in content:
                    return dict(content[media_type].get("schema") or {})
            if "schema" in resp:
                return dict(resp["schema"])
    return {}


def _status_codes(op: dict[str, Any]) -> list[int]:
    codes: list[int] = []
    for code in op.get("responses", {}):
        try:
            codes.append(int(code))
        except (ValueError, TypeError):
            continue
    return sorted(set(codes))


def normalize(spec: dict[str, Any], traceability: str) -> list[dict[str, Any]]:
    endpoints: list[dict[str, Any]] = []
    base = ""
    if "servers" in spec and spec["servers"]:
        base = str(spec["servers"][0].get("url", "")).rstrip("/")
    elif "basePath" in spec:
        base = f"{spec.get('schemes', ['https'])[0]}://{spec.get('host', '')}{spec.get('basePath', '')}"

    for path, item in spec.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete"):
            if method not in item:
                continue
            op = item[method]
            req, opt = _params(op, item)
            tags = op.get("tags") or []
            endpoints.append({
                "method": method.upper(),
                "path": f"{base}{path}",
                "summary": op.get("summary") or op.get("operationId", ""),
                "tags": tags,
                "params_required": req,
                "params_optional": opt,
                "request_schema": ((op.get("requestBody") or {}).get("content", {})
                                   .get("application/json", {}).get("schema") or {}),
                "response_schema": _response_schema(op),
                "status_codes": _status_codes(op),
                "examples": {},
                "source_excerpt": op.get("description", "") or op.get("summary", ""),
                "traceability": traceability,
            })
    return endpoints


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: parse_openapi.py <path-or-url>", file=sys.stderr)
        sys.exit(64)
    source = sys.argv[1]
    spec = _load(source)
    endpoints = normalize(spec, traceability=source)
    json.dump(endpoints, sys.stdout, indent=2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
