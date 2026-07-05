"""Run the TraceRoot MCP server over stdio.

    python -m mcp_server

Reads configuration (ClickHouse, Postgres, etc.) from the environment via
``shared.config``. Loads ``.env`` first, matching the other backend entrypoints,
because ``shared.config`` does not auto-load it.
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from .readers import default_readers  # noqa: E402  (must follow load_dotenv)
from .server import build_server  # noqa: E402


def main() -> None:
    server = build_server(default_readers())
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
