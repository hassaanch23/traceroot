"""Unit tests for request_traceroot_rca_handler (mocked ClickHouse + Postgres)."""

from __future__ import annotations

from datetime import datetime

from mcp_server.tools import request_traceroot_rca_handler


def _ch_with_finding(fakes, finding_id: str | None):
    rows = [(finding_id,)] if finding_id is not None else []
    return fakes.ClickHouse(on_query=lambda q, p: fakes.Result(result_rows=rows))


def _readers(fakes, finding_id, pg_conn):
    calls = {"pg": 0}

    def connect():
        calls["pg"] += 1
        return pg_conn

    readers = fakes.Readers(
        trace_reader=fakes.TraceReader(),
        clickhouse=_ch_with_finding(fakes, finding_id),
        pg_connect=connect,
    )
    return readers, calls


def test_not_requested_when_trace_has_no_finding(fakes):
    pg = fakes.PgConn(row=None)
    readers, calls = _readers(fakes, finding_id=None, pg_conn=pg)

    out = request_traceroot_rca_handler(readers, "p1", "t1")

    assert out["status"] == "not_requested"
    assert out["result"] is None
    # No finding -> Postgres is never touched.
    assert calls["pg"] == 0


def test_not_requested_when_finding_but_no_rca_row(fakes):
    pg = fakes.PgConn(row=None)
    readers, _ = _readers(fakes, finding_id="f1", pg_conn=pg)

    out = request_traceroot_rca_handler(readers, "p1", "t1")

    assert out["status"] == "not_requested"
    assert pg.closed is True


def test_done_returns_result_and_iso_completed_at(fakes):
    completed = datetime(2026, 1, 2, 3, 4, 5)
    pg = fakes.PgConn(row=("done", "the root cause was X", completed, "sess-1"))
    readers, _ = _readers(fakes, finding_id="f1", pg_conn=pg)

    out = request_traceroot_rca_handler(readers, "p1", "t1")

    assert out == {
        "status": "done",
        "result": "the root cause was X",
        "completed_at": "2026-01-02T03:04:05",
        "session_id": "sess-1",
    }
    assert pg.closed is True


def test_pending_passes_through_with_nulls(fakes):
    pg = fakes.PgConn(row=("pending", None, None, "sess-2"))
    readers, _ = _readers(fakes, finding_id="f1", pg_conn=pg)

    out = request_traceroot_rca_handler(readers, "p1", "t1")

    assert out["status"] == "pending"
    assert out["result"] is None
    assert out["completed_at"] is None
    assert out["session_id"] == "sess-2"


def test_failed_status_passes_through(fakes):
    pg = fakes.PgConn(row=("failed", None, None, None))
    readers, _ = _readers(fakes, finding_id="f1", pg_conn=pg)

    out = request_traceroot_rca_handler(readers, "p1", "t1")

    assert out["status"] == "failed"


def test_rca_read_is_parameterized(fakes):
    pg = fakes.PgConn(row=("running", None, None, None))
    readers, _ = _readers(fakes, finding_id="f1", pg_conn=pg)

    request_traceroot_rca_handler(readers, "proj-1", "t1")

    sql, params = pg.cursor().executed[0]
    assert params == ("f1", "proj-1")
    assert "%s" in sql  # bound, not string-formatted


def test_finding_lookup_is_project_scoped_and_bound(fakes):
    # The ClickHouse finding lookup must stay project-scoped and parameterized —
    # dropping either would let one tenant resolve another tenant's RCA.
    ch = fakes.ClickHouse(on_query=lambda q, p: fakes.Result(result_rows=[("f1",)]))
    pg = fakes.PgConn(row=("done", "x", None, None))
    readers = fakes.Readers(trace_reader=fakes.TraceReader(), clickhouse=ch, pg_connect=lambda: pg)

    request_traceroot_rca_handler(readers, "proj-1", "trace-1")

    query, params = ch.calls[0]
    assert params == {"trace_id": "trace-1", "project_id": "proj-1"}
    assert "project_id" in query  # scoped to the caller's project
    assert "FINAL" in query  # dedups ReplacingMergeTree rows
