"""End-to-end tests through the FastMCP server (requires the `mcp` SDK).

These verify the SDK wiring — tool registration, schemas, and that each tool
call flows through to its handler and serializes. The handler logic itself is
covered by the sdk-free unit tests; this file is skipped if `mcp` is not
installed.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

pytest.importorskip("mcp.server.fastmcp")

from mcp_server.readers import Readers
from mcp_server.server import build_server

EXPECTED_TOOLS = {
    "get_trace",
    "get_trace_tree",
    "get_detector_findings",
    "request_traceroot_rca",
}

_FINDINGS_COLUMNS = ["finding_id", "project_id", "trace_id", "summary", "payload", "timestamp"]


def _trace_with_spans() -> dict:
    return {
        "trace_id": "t1",
        "project_id": "p1",
        "name": "n",
        "trace_start_time": datetime(2026, 1, 2, 3, 4, 5),
        "spans": [
            {
                "span_id": "s1",
                "parent_span_id": "",
                "name": "root",
                "span_start_time": datetime(2026, 1, 2, 3, 4, 5),
                "span_end_time": None,
            },
            {
                "span_id": "s2",
                "parent_span_id": "s1",
                "name": "child",
                "span_start_time": datetime(2026, 1, 2, 3, 4, 6),
                "span_end_time": None,
            },
        ],
    }


def _server(fakes, *, trace=None, ch=None, pg=None):
    readers = Readers(
        trace_reader=fakes.TraceReader(trace=_trace_with_spans() if trace is None else trace),
        clickhouse=ch if ch is not None else fakes.ClickHouse(),
        pg_connect=(lambda: pg) if pg is not None else (lambda: fakes.PgConn()),
    )
    return build_server(readers)


def _text(call_result):
    """Extract the text payload from a FastMCP call_tool result (list or tuple)."""
    content = call_result[0] if isinstance(call_result, tuple) else call_result
    return content[0].text


async def test_registers_the_four_tools(fakes):
    tools = await _server(fakes).list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS


async def test_get_trace_input_schema_exposes_params(fakes):
    tools = await _server(fakes).list_tools()
    get_trace = next(t for t in tools if t.name == "get_trace")
    props = get_trace.inputSchema.get("properties", {})
    assert {"project_id", "trace_id", "fields"} <= set(props)


async def test_call_get_trace_flows_to_handler(fakes):
    result = await _server(fakes).call_tool("get_trace", {"project_id": "p1", "trace_id": "t1"})
    payload = json.loads(_text(result))
    assert payload["trace_id"] == "t1"
    assert payload["project_id"] == "p1"
    assert payload["trace_start_time"] == "2026-01-02T03:04:05"


async def test_call_get_trace_tree_returns_nested_roots(fakes):
    result = await _server(fakes).call_tool(
        "get_trace_tree", {"project_id": "p1", "trace_id": "t1"}
    )
    payload = json.loads(_text(result))
    assert [n["span_id"] for n in payload["roots"]] == ["s1"]
    assert payload["roots"][0]["children"][0]["span_id"] == "s2"


async def test_call_get_detector_findings_returns_findings(fakes):
    row = ("f1", "p1", "t1", "bad", '[{"detectorId": "d1", "summary": "x"}]', datetime(2026, 1, 2))
    ch = fakes.ClickHouse(
        on_query=lambda q, p: fakes.Result(column_names=_FINDINGS_COLUMNS, result_rows=[row])
    )
    result = await _server(fakes, ch=ch).call_tool(
        "get_detector_findings", {"project_id": "p1", "trace_id": "t1"}
    )
    payload = json.loads(_text(result))
    assert payload["findings"][0]["finding_id"] == "f1"
    assert payload["findings"][0]["detectors"] == [{"detectorId": "d1", "summary": "x"}]


async def test_call_request_rca_returns_status(fakes):
    ch = fakes.ClickHouse(on_query=lambda q, p: fakes.Result(result_rows=[("f1",)]))
    pg = fakes.PgConn(row=("done", "the root cause", datetime(2026, 1, 2, 3, 4, 5), "sess-1"))
    result = await _server(fakes, ch=ch, pg=pg).call_tool(
        "request_traceroot_rca", {"project_id": "p1", "trace_id": "t1"}
    )
    payload = json.loads(_text(result))
    assert payload["status"] == "done"
    assert payload["result"] == "the root cause"
    assert payload["session_id"] == "sess-1"
