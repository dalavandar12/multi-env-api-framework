# MCP setup for Jira / Confluence / OpenAPI sources

The skill calls MCP servers when `--source jira`, `--source confluence`, or a
remote OpenAPI URL is used. Configure each server **once**, then any future
skill invocation can reach them.

---

## 1. Atlassian (Jira + Confluence) MCP

Official server: `@atlassian/mcp-server-atlassian` (Node package).

### Install

```bash
npm install -g @atlassian/mcp-server-atlassian
```

### Generate an API token

1. Visit https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token", name it `claude-mcp`, copy the value.

### Register with Claude Code

Add to your Claude Code MCP config (`~/.claude/mcp.json` or equivalent):

```json
{
  "mcpServers": {
    "atlassian": {
      "command": "npx",
      "args": ["-y", "@atlassian/mcp-server-atlassian"],
      "env": {
        "ATLASSIAN_SITE_URL": "https://<your-org>.atlassian.net",
        "ATLASSIAN_EMAIL": "<your-email>",
        "ATLASSIAN_API_TOKEN": "<token-from-step-above>"
      }
    }
  }
}
```

### Verify

In a fresh Claude session:

```
list connected MCP servers
```

`atlassian` must appear. Then:

```
fetch Jira issue PROJ-123
```

If both work, the skill's `--source jira PROJ-123` and `--source confluence <pageId>`
will succeed.

---

## 2. OpenAPI / Swagger MCP (optional)

If your OpenAPI spec is published behind auth (e.g., internal SwaggerHub), use the
OpenAPI MCP server:

```bash
npm install -g @modelcontextprotocol/server-openapi
```

Config:

```json
{
  "mcpServers": {
    "openapi": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-openapi"],
      "env": {
        "OPENAPI_BASE_URL": "https://swaggerhub.example.com",
        "OPENAPI_API_KEY": "<token>"
      }
    }
  }
}
```

For **public** OpenAPI specs (e.g., petstore, restcountries' swagger), skip this — the
skill fetches them directly via `scripts/fetch_url.py` or reads them from `input/`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `MCP server "atlassian" not connected` | Restart Claude Code after editing `~/.claude/mcp.json`. |
| 401 from Atlassian | Token expired or wrong email. Re-issue token, update env. |
| 404 on Confluence page | Use the numeric page ID, not the slug. Find it in page URL: `/pages/<id>/`. |
| TLS error to internal URL | The URL guardrail rejects private IPs. Edit `config/url_guardrail.yaml` to add an explicit allowance, or use the Atlassian MCP path instead. |

---

## Fallback if MCP unavailable

Both `parse_jira.py` and `parse_confluence.py` exit with the message:

```
[mcp] Atlassian MCP server not reachable. See references/mcp_setup.md to install.
```

The skill never silently produces an empty sheet — it always fails loudly.
