"""Jira ticket fetcher — MCP-backed.

This script does NOT make HTTP calls itself. It is invoked by Claude during
skill execution; Claude calls the Atlassian MCP tool and pipes the JSON
issue payload into this script's stdin for normalization.

Usage:
    cat issue.json | python parse_jira.py <ISSUE-KEY>

If the MCP server is missing, Claude prints the install steps from
references/mcp_setup.md and exits — never produces an empty sheet silently.
"""
import json
import logging
import sys
from typing import Any

LOG = logging.getLogger(__name__)


def normalize(issue: dict[str, Any], key: str) -> dict[str, Any]:
    fields = issue.get("fields", {})
    summary = fields.get("summary", "")
    description = fields.get("description", "") or ""
    components = [c.get("name") for c in fields.get("components", []) if c.get("name")]
    acceptance = ""
    for cf_name, cf_val in fields.items():
        if "acceptance" in cf_name.lower() and isinstance(cf_val, str):
            acceptance = cf_val
            break

    return {
        "source_kind": "jira",
        "key": key,
        "title": summary,
        "components": components,
        "raw_text": "\n\n".join(p for p in [summary, description, acceptance] if p),
        "traceability": f"jira:{key}",
    }


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: parse_jira.py <ISSUE-KEY> (stdin: issue JSON)", file=sys.stderr)
        sys.exit(64)
    raw = sys.stdin.read()
    if not raw.strip():
        print("[parse_jira] empty stdin — pipe the MCP fetch result in", file=sys.stderr)
        sys.exit(2)
    issue = json.loads(raw)
    json.dump(normalize(issue, sys.argv[1]), sys.stdout, indent=2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
