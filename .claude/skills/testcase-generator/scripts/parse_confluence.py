"""Confluence page fetcher — MCP-backed.

Like parse_jira.py, this script does not call HTTP itself. Claude invokes
the Atlassian MCP tool to fetch the page and pipes the result into stdin.

Usage:
    cat page.json | python parse_confluence.py <PAGE-ID>
"""
import json
import logging
import re
import sys
from typing import Any

from bs4 import BeautifulSoup

LOG = logging.getLogger(__name__)


def _strip_html(html: str) -> str:
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text("\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def normalize(page: dict[str, Any], page_id: str) -> dict[str, Any]:
    title = page.get("title", "")
    body = page.get("body", {})
    storage = body.get("storage", {}).get("value") if isinstance(body, dict) else ""
    view = body.get("view", {}).get("value") if isinstance(body, dict) else ""
    html = storage or view or ""
    return {
        "source_kind": "confluence",
        "page_id": page_id,
        "title": title,
        "raw_text": _strip_html(str(html)),
        "traceability": f"confluence:{page_id}",
    }


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: parse_confluence.py <PAGE-ID> (stdin: page JSON)", file=sys.stderr)
        sys.exit(64)
    raw = sys.stdin.read()
    if not raw.strip():
        print("[parse_confluence] empty stdin — pipe the MCP fetch result in", file=sys.stderr)
        sys.exit(2)
    page = json.loads(raw)
    json.dump(normalize(page, sys.argv[1]), sys.stdout, indent=2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
