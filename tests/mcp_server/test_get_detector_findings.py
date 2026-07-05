"""Unit tests for get_detector_findings_handler (mocked ClickHouse)."""

from __future__ import annotations

from datetime import datetime

from mcp_server.tools import get_detector_findings_handler

_COLUMNS = ["finding_id", "project_id", "trace_id", "summary", "payload", "timestamp"]


def _readers(fakes, result):
    return fakes.Readers(
        trace_reader=fakes.TraceReader(),
        clickhouse=fakes.ClickHouse(on_query=lambda q, p: result),
        pg_connect=lambda: fakes.PgConn(),
    )


def test_maps_rows_parses_payload_and_iso_timestamp(fakes):
    payload = '[{"detectorId": "d1", "summary": "bad tool call"}]'
    result = fakes.Result(
        column_names=_COLUMNS,
        result_rows=[
            ("f1", "p1", "t1", "trace looks wrong", payload, datetime(2026, 1, 2, 3, 4, 5)),
        ],
    )

    out = get_detector_findings_handler(_readers(fakes, result), "p1", "t1")

    assert len(out["findings"]) == 1
    finding = out["findings"][0]
    assert finding["finding_id"] == "f1"
    assert finding["summary"] == "trace looks wrong"
    assert finding["timestamp"] == "2026-01-02T03:04:05"
    # payload parsed into a structured list for agents, raw string preserved
    assert finding["payload"] == payload
    assert finding["detectors"] == [{"detectorId": "d1", "summary": "bad tool call"}]


def test_empty_when_no_findings(fakes):
    out = get_detector_findings_handler(_readers(fakes, fakes.Result()), "p1", "t1")
    assert out == {"findings": []}


def test_binds_parameters_not_string_formatting(fakes):
    ch = fakes.ClickHouse(on_query=lambda q, p: fakes.Result())
    readers = fakes.Readers(
        trace_reader=fakes.TraceReader(), clickhouse=ch, pg_connect=lambda: fakes.PgConn()
    )

    get_detector_findings_handler(readers, "proj-9", "trace-9")

    query, params = ch.calls[0]
    assert params == {"trace_id": "trace-9", "project_id": "proj-9"}
    assert "FINAL" in query  # dedups ReplacingMergeTree rows


def test_malformed_payload_yields_empty_detectors(fakes):
    result = fakes.Result(
        column_names=_COLUMNS,
        result_rows=[("f1", "p1", "t1", "s", "not-json", datetime(2026, 1, 2))],
    )

    out = get_detector_findings_handler(_readers(fakes, result), "p1", "t1")

    assert out["findings"][0]["detectors"] == []
    assert out["findings"][0]["payload"] == "not-json"
