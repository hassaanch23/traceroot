"""TraceRoot MCP server.

A TraceRoot-native `Model Context Protocol <https://modelcontextprotocol.io>`_
server that exposes read-only tools so MCP-compatible agents can ask TraceRoot
what happened during a run — fetch a trace, walk its span tree, read detector
findings, and read the existing root-cause-analysis (RCA) state for a trace.

The package is deliberately layered so the tool logic is testable without the
MCP SDK, a live database, or any LLM:

- ``tree`` / ``rca`` — pure helpers over plain data.
- ``tools`` — transport-agnostic handler functions ``(readers, **inputs) -> dict``.
- ``readers`` — the single data-access seam (ClickHouse + Postgres + the trace
  reader service); tests inject fakes here.
- ``server`` — wires the handlers onto a FastMCP instance (imports the SDK).
- ``__main__`` — the stdio entrypoint.

Only ``server`` and ``__main__`` import the ``mcp`` SDK, so the handlers can be
unit-tested in isolation.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
