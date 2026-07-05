"""Wire the TraceRoot tool handlers onto a FastMCP server.

This is the only module besides ``__main__`` that imports the ``mcp`` SDK. Each
``@mcp.tool()`` is a thin shell that forwards to the transport-agnostic handler
in ``tools``; the docstrings and type hints here become the tools' MCP schema.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import tools
from .readers import Readers


def build_server(readers: Readers) -> FastMCP:
    """Build a FastMCP server exposing the read-only TraceRoot tools.

    ``readers`` is injected so the same server can be built over real services
    (``__main__``) or fakes (tests).
    """
    mcp = FastMCP("traceroot")

    @mcp.tool()
    def get_trace(project_id: str, trace_id: str, fields: str | None = None) -> dict:
        """Fetch one trace: metadata plus its span skeletons.

        Args:
            project_id: Project that owns the trace.
            trace_id: Trace to fetch.
            fields: Optional projection. Omit for lightweight skeletons; pass
                "full" to hydrate per-span input/output/metadata, or a
                comma-separated list of "io" / "metadata".
        """
        return tools.get_trace_handler(readers, project_id, trace_id, fields)

    @mcp.tool()
    def get_trace_tree(project_id: str, trace_id: str) -> dict:
        """Fetch a trace as a parent/child span forest (under `roots`).

        Args:
            project_id: Project that owns the trace.
            trace_id: Trace whose span hierarchy to return.
        """
        return tools.get_trace_tree_handler(readers, project_id, trace_id)

    @mcp.tool()
    def get_detector_findings(project_id: str, trace_id: str) -> dict:
        """List detector findings recorded for a trace (newest first).

        Args:
            project_id: Project that owns the trace.
            trace_id: Trace whose findings to return.
        """
        return tools.get_detector_findings_handler(readers, project_id, trace_id)

    @mcp.tool()
    def request_traceroot_rca(project_id: str, trace_id: str) -> dict:
        """Return the existing root-cause-analysis state for a trace.

        Read-only: returns an existing RCA result or a status of pending /
        running / done / failed, or not_requested when none exists. Does not
        start a new analysis.

        Args:
            project_id: Project that owns the trace.
            trace_id: Trace whose RCA state to return.
        """
        return tools.request_traceroot_rca_handler(readers, project_id, trace_id)

    return mcp
