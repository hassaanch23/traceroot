"""Fakes for the MCP server tools — no real ClickHouse/Postgres/LLM involved.

Every fake mimics only the small surface the tools use (see
``mcp_server.readers`` Protocols), so handlers run entirely in-process.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_server.readers import Readers


class FakeResult:
    """Mimics a clickhouse-connect query result."""

    def __init__(
        self,
        column_names: list[str] | None = None,
        result_rows: list[tuple] | None = None,
    ) -> None:
        self.column_names = column_names or []
        self.result_rows = result_rows or []


class FakeClickHouse:
    """Records queries and returns a canned/derived result."""

    def __init__(self, on_query: Callable[[str, dict | None], FakeResult] | None = None) -> None:
        self._on_query = on_query or (lambda query, params: FakeResult())
        self.calls: list[tuple[str, dict | None]] = []

    def query(self, query: str, parameters: dict[str, Any] | None = None) -> FakeResult:
        self.calls.append((query, parameters))
        return self._on_query(query, parameters)


class FakeTraceReader:
    """Returns a canned trace and per-span I/O map."""

    def __init__(self, trace: dict | None = None, spans_io: dict[str, dict] | None = None) -> None:
        self._trace = trace
        self._spans_io = spans_io or {}
        self.trace_calls: list[tuple[str, str]] = []
        self.io_calls: list[tuple[str, str, frozenset[str]]] = []

    def get_trace(self, project_id: str, trace_id: str) -> dict | None:
        self.trace_calls.append((project_id, trace_id))
        return self._trace

    def get_trace_spans_io(
        self, project_id: str, trace_id: str, columns: frozenset[str]
    ) -> dict[str, dict]:
        self.io_calls.append((project_id, trace_id, columns))
        # Return only the requested columns, mirroring the real projection.
        return {
            span_id: {col: values.get(col) for col in columns}
            for span_id, values in self._spans_io.items()
        }


class FakeCursor:
    def __init__(self, row: tuple | None) -> None:
        self._row = row
        self.executed: list[tuple[str, tuple | None]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> tuple | None:
        return self._row


class FakePgConn:
    def __init__(self, row: tuple | None = None) -> None:
        self._cursor = FakeCursor(row)
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fakes() -> SimpleNamespace:
    """Expose the fake classes + Readers so tests can wire exactly what they need."""
    return SimpleNamespace(
        Result=FakeResult,
        ClickHouse=FakeClickHouse,
        TraceReader=FakeTraceReader,
        PgConn=FakePgConn,
        Readers=Readers,
    )
