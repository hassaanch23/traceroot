"""Unit tests for get_trace_handler and get_trace_tree_handler."""

from __future__ import annotations

from datetime import datetime

import pytest

from mcp_server.tools import (
    InvalidFieldsError,
    TraceNotFoundError,
    get_trace_handler,
    get_trace_tree_handler,
)


def _trace() -> dict:
    return {
        "trace_id": "t1",
        "project_id": "p1",
        "name": "my-trace",
        "trace_start_time": datetime(2026, 1, 2, 3, 4, 5),
        "user_id": None,
        "session_id": None,
        "git_ref": None,
        "git_repo": None,
        "input": None,
        "output": None,
        "metadata": None,
        "spans": [
            {
                "span_id": "s1",
                "trace_id": "t1",
                "parent_span_id": "",
                "name": "root",
                "span_start_time": datetime(2026, 1, 2, 3, 4, 5),
                "span_end_time": datetime(2026, 1, 2, 3, 4, 6),
            },
            {
                "span_id": "s2",
                "trace_id": "t1",
                "parent_span_id": "s1",
                "name": "child",
                "span_start_time": datetime(2026, 1, 2, 3, 4, 5, 500000),
                "span_end_time": None,
            },
        ],
    }


def _readers(fakes, trace=None, spans_io=None):
    return fakes.Readers(
        trace_reader=fakes.TraceReader(trace=trace, spans_io=spans_io or {}),
        clickhouse=fakes.ClickHouse(),
        pg_connect=lambda: fakes.PgConn(),
    )


def test_get_trace_returns_header_and_iso_spans(fakes):
    out = get_trace_handler(_readers(fakes, trace=_trace()), "p1", "t1")

    assert out["trace_id"] == "t1"
    assert out["trace_start_time"] == "2026-01-02T03:04:05"
    assert "spans" in out and len(out["spans"]) == 2
    # datetimes are ISO strings, and skeleton spans carry no I/O
    assert out["spans"][0]["span_start_time"] == "2026-01-02T03:04:05"
    assert out["spans"][1]["span_end_time"] is None
    assert "input" not in out["spans"][0]


def test_get_trace_not_found_raises(fakes):
    with pytest.raises(TraceNotFoundError):
        get_trace_handler(_readers(fakes, trace=None), "p1", "missing")


def test_get_trace_full_fields_hydrate_io(fakes):
    reader = fakes.TraceReader(
        trace=_trace(),
        spans_io={"s1": {"input": "in-1", "output": "out-1", "metadata": "m-1"}},
    )
    readers = fakes.Readers(
        trace_reader=reader, clickhouse=fakes.ClickHouse(), pg_connect=lambda: fakes.PgConn()
    )

    out = get_trace_handler(readers, "p1", "t1", fields="full")

    # get_trace_spans_io was asked for all three blob columns
    assert reader.io_calls
    assert reader.io_calls[0][2] == frozenset({"input", "output", "metadata"})
    # s1 hydrated; s2 absent from the io map -> None for each requested column
    assert out["spans"][0]["input"] == "in-1"
    assert out["spans"][0]["metadata"] == "m-1"
    assert out["spans"][1]["input"] is None


def test_get_trace_io_group_requests_only_input_output(fakes):
    reader = fakes.TraceReader(trace=_trace(), spans_io={})
    readers = fakes.Readers(
        trace_reader=reader, clickhouse=fakes.ClickHouse(), pg_connect=lambda: fakes.PgConn()
    )

    get_trace_handler(readers, "p1", "t1", fields="io")

    assert reader.io_calls[0][2] == frozenset({"input", "output"})


def test_get_trace_skeleton_does_not_hydrate(fakes):
    reader = fakes.TraceReader(trace=_trace())
    readers = fakes.Readers(
        trace_reader=reader, clickhouse=fakes.ClickHouse(), pg_connect=lambda: fakes.PgConn()
    )

    get_trace_handler(readers, "p1", "t1", fields="skeleton")

    assert reader.io_calls == []


def test_get_trace_invalid_fields_raises(fakes):
    with pytest.raises(InvalidFieldsError):
        get_trace_handler(_readers(fakes, trace=_trace()), "p1", "t1", fields="bogus")


def test_get_trace_tree_builds_hierarchy_with_iso_times(fakes):
    out = get_trace_tree_handler(_readers(fakes, trace=_trace()), "p1", "t1")

    assert "spans" not in out
    assert out["trace_start_time"] == "2026-01-02T03:04:05"
    assert [n["span_id"] for n in out["roots"]] == ["s1"]
    child = out["roots"][0]["children"][0]
    assert child["span_id"] == "s2"
    assert child["span_start_time"] == "2026-01-02T03:04:05.500000"


def test_get_trace_tree_not_found_raises(fakes):
    with pytest.raises(TraceNotFoundError):
        get_trace_tree_handler(_readers(fakes, trace=None), "p1", "missing")


def _reader_for_fields(fakes):
    reader = fakes.TraceReader(trace=_trace(), spans_io={})
    readers = fakes.Readers(
        trace_reader=reader, clickhouse=fakes.ClickHouse(), pg_connect=lambda: fakes.PgConn()
    )
    return reader, readers


def test_get_trace_metadata_only_requests_metadata(fakes):
    reader, readers = _reader_for_fields(fakes)
    get_trace_handler(readers, "p1", "t1", fields="metadata")
    assert reader.io_calls[0][2] == frozenset({"metadata"})


def test_get_trace_combined_tokens_union_columns(fakes):
    reader, readers = _reader_for_fields(fakes)
    get_trace_handler(readers, "p1", "t1", fields="io,metadata")
    assert reader.io_calls[0][2] == frozenset({"input", "output", "metadata"})


def test_get_trace_fields_tolerates_whitespace_and_empty_tokens(fakes):
    reader, readers = _reader_for_fields(fakes)
    get_trace_handler(readers, "p1", "t1", fields=" io , ")
    assert reader.io_calls[0][2] == frozenset({"input", "output"})
