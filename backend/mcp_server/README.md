# TraceRoot MCP Server

A TraceRoot-native [Model Context Protocol](https://modelcontextprotocol.io)
server that lets MCP-compatible agents query TraceRoot. When an agent fails
mid-run, it can ask TraceRoot *what went wrong* — read the trace, walk the span
tree, read detector findings, and read the existing root-cause-analysis (RCA)
state — instead of a human inspecting the dashboard.

Implements the read surface of [#1000](https://github.com/traceroot-ai/traceroot/issues/1000).

## Tools

All tools are **read-only** and scoped to a `project_id` the caller supplies.

| Tool | Description |
| ---- | ----------- |
| `get_trace(project_id, trace_id, fields=None)` | Trace metadata + span skeletons. `fields="full"` (or `"io"` / `"metadata"`) hydrates per-span input/output/metadata. |
| `get_trace_tree(project_id, trace_id)` | The trace's spans as a parent/child forest (under `roots`), built from `parent_span_id`. |
| `get_detector_findings(project_id, trace_id)` | Detector findings for the trace, newest first. `payload` is also parsed into a `detectors` list. |
| `request_traceroot_rca(project_id, trace_id)` | The existing RCA for the trace: an existing result, or a status of `pending` / `running` / `done` / `failed`, or `not_requested`. Does **not** start a new analysis. |

Triggering a *new* RCA runs the LLM agent and is intentionally out of scope here.

## Architecture

The tools read TraceRoot's own data stores directly (the public REST API only
exposes traces today; findings and RCA state are internal-only), so the server
delivers the full tool set without standing up the web app or the agent:

- **traces / tree** → `rest.services.TraceReaderService` (ClickHouse), reused so
  reads match the REST API exactly.
- **detector findings** → ClickHouse `detector_findings`.
- **RCA state** → Postgres `detector_rcas`, resolved via the trace's finding.

The package is layered so tool logic is testable without the MCP SDK, a live
database, or any LLM:

```
tree.py / rca.py   pure helpers over plain data
tools.py           handlers: (readers, **inputs) -> dict   ← unit tests target these
readers.py         the single data-access seam (inject fakes here)
server.py          FastMCP wiring (imports the mcp SDK)
__main__.py        stdio entrypoint
```

`readers.Readers` is the injection point; the handlers depend only on its small
Protocol surface, so a future maintainer can swap in an HTTP-API-backed
implementation per tool without touching tool logic.

## Running

```bash
# from an installed backend (console script)
traceroot-mcp

# or as a module
python -m mcp_server
```

The server speaks the stdio transport. Example MCP client config:

```json
{
  "mcpServers": {
    "traceroot": {
      "command": "traceroot-mcp",
      "env": {
        "CLICKHOUSE_HOST": "localhost",
        "CLICKHOUSE_NATIVE_PORT": "9000",
        "DATABASE_URL": "postgresql://postgres:postgres@localhost:5432/postgres"
      }
    }
  }
}
```

Configuration is read from the environment via `shared.config` (ClickHouse and
Postgres connection settings); `.env` is loaded on startup.

## Tests

```bash
pytest tests/mcp_server
```

The unit tests mock the data layer — no ClickHouse, Postgres, or LLM required.
`test_server.py` additionally exercises the FastMCP wiring and is skipped when
the `mcp` SDK is not installed.
