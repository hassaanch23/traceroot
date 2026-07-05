"""Transport-agnostic tool handlers for the TraceRoot MCP server.

Each handler is a plain function ``(readers, **inputs) -> dict``. It contains no
MCP-SDK, LLM, or direct database imports — all data access goes through the
injected ``Readers`` seam — so the handlers can be unit-tested with fakes. The
FastMCP wiring in ``server`` is a thin shell that forwards to these.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .rca import read_rca, resolve_finding_id
from .tree import build_trace_tree

if TYPE_CHECKING:
    from .readers import Readers

# ClickHouse detector_findings, read FINAL to collapse ReplacingMergeTree
# duplicates. Identical projection to the internal /traces/{id}/findings route.
_FINDINGS_SQL = """
    SELECT finding_id, project_id, trace_id, summary, payload, timestamp
    FROM detector_findings FINAL
    WHERE trace_id = {trace_id:String} AND project_id = {project_id:String}
    ORDER BY timestamp DESC
"""

# Trace-level input/output/metadata blobs the trace reader can hydrate per span.
_IO_COLUMNS = ("input", "output", "metadata")

# fields token -> which I/O blob columns to hydrate. "skeleton"/None omit all
# (the default lightweight read); "full" hydrates everything. Mirrors the public
# GET /traces/{id} projection groups.
_FIELD_GROUPS = {
    "skeleton": frozenset(),
    "full": frozenset(_IO_COLUMNS),
    "io": frozenset({"input", "output"}),
    "metadata": frozenset({"metadata"}),
}


class TraceNotFoundError(ValueError):
    """Raised when a trace is missing or outside the caller's project."""


class InvalidFieldsError(ValueError):
    """Raised when the ``fields`` argument contains an unknown token."""


def _resolve_io_columns(fields: str | None) -> frozenset[str]:
    """Turn a ``fields`` string into the set of I/O columns to hydrate.

    ``None`` or ``"skeleton"`` -> no I/O (lightweight). ``"full"`` -> all three.
    Otherwise a comma-separated list of ``io`` / ``metadata`` (and the aliases
    above). Unknown tokens raise ``InvalidFieldsError``.
    """
    if not fields:
        return frozenset()
    columns: set[str] = set()
    for token in fields.split(","):
        key = token.strip().lower()
        if not key:
            continue
        if key not in _FIELD_GROUPS:
            raise InvalidFieldsError(
                f"Unknown fields token {key!r}. Valid tokens: {', '.join(sorted(_FIELD_GROUPS))}."
            )
        columns |= _FIELD_GROUPS[key]
    return frozenset(columns)


def _iso(value: Any) -> Any:
    """ISO-8601 encode a datetime; pass anything else through unchanged."""
    return value.isoformat() if hasattr(value, "isoformat") else value


def _serialize_span(span: dict[str, Any]) -> dict[str, Any]:
    out = dict(span)
    for key in ("span_start_time", "span_end_time"):
        if key in out:
            out[key] = _iso(out[key])
    return out


def _trace_header(trace: dict[str, Any]) -> dict[str, Any]:
    """Trace-level fields (everything except the spans list), datetimes ISO-ized."""
    header = {key: value for key, value in trace.items() if key != "spans"}
    if "trace_start_time" in header:
        header["trace_start_time"] = _iso(header["trace_start_time"])
    return header


def get_trace_handler(
    readers: Readers,
    project_id: str,
    trace_id: str,
    fields: str | None = None,
) -> dict[str, Any]:
    """Fetch one trace with its span skeletons.

    ``fields`` optionally hydrates per-span input/output/metadata (default is the
    lightweight skeleton). Raises ``TraceNotFoundError`` when the trace does not
    exist in the caller's project.
    """
    io_columns = _resolve_io_columns(fields)
    trace = readers.trace_reader.get_trace(project_id, trace_id)
    if trace is None:
        raise TraceNotFoundError(f"Trace {trace_id!r} not found in project {project_id!r}.")

    spans = trace.get("spans", [])
    if io_columns:
        io_by_span = readers.trace_reader.get_trace_spans_io(project_id, trace_id, io_columns)
        for span in spans:
            hydrated = io_by_span.get(span["span_id"], {})
            for column in io_columns:
                span[column] = hydrated.get(column)

    header = _trace_header(trace)
    header["spans"] = [_serialize_span(span) for span in spans]
    return header


def get_trace_tree_handler(
    readers: Readers,
    project_id: str,
    trace_id: str,
) -> dict[str, Any]:
    """Fetch a trace and return its spans as a parent/child forest under ``roots``."""
    trace = readers.trace_reader.get_trace(project_id, trace_id)
    if trace is None:
        raise TraceNotFoundError(f"Trace {trace_id!r} not found in project {project_id!r}.")

    spans = [_serialize_span(span) for span in trace.get("spans", [])]
    header = _trace_header(trace)
    header["roots"] = build_trace_tree(spans)
    return header


def _parse_payload(payload: Any) -> list[Any]:
    """Parse a finding's ``payload`` (a JSON-array string of per-detector results).

    Returns the parsed list, or ``[]`` when the payload is empty or not valid
    JSON — the raw string is preserved separately by the caller.
    """
    if not payload:
        return []
    try:
        parsed = json.loads(payload)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def get_detector_findings_handler(
    readers: Readers,
    project_id: str,
    trace_id: str,
) -> dict[str, Any]:
    """Return detector findings recorded for a trace, newest first.

    Each finding carries ``finding_id``, ``project_id``, ``trace_id``,
    ``summary``, the ISO ``timestamp``, the raw ``payload`` string, and
    ``detectors`` (the payload parsed into a list of per-detector results for
    easy agent consumption). Empty ``findings`` list when the trace is clean.
    """
    result = readers.clickhouse.query(
        _FINDINGS_SQL,
        parameters={"trace_id": trace_id, "project_id": project_id},
    )
    findings: list[dict[str, Any]] = []
    for row in result.result_rows:
        finding = dict(zip(result.column_names, row))
        finding["timestamp"] = _iso(finding.get("timestamp"))
        finding["detectors"] = _parse_payload(finding.get("payload"))
        findings.append(finding)
    return {"findings": findings}


def request_traceroot_rca_handler(
    readers: Readers,
    project_id: str,
    trace_id: str,
) -> dict[str, Any]:
    """Return the existing RCA state for a trace (read-only; never triggers a run).

    ``status`` is one of ``pending`` / ``running`` / ``done`` / ``failed``, or
    ``not_requested`` when the trace has no finding or no RCA row yet. When
    ``done``, ``result`` holds the RCA text.
    """
    not_requested = {
        "status": "not_requested",
        "result": None,
        "completed_at": None,
        "session_id": None,
    }

    finding_id = resolve_finding_id(readers.clickhouse, project_id, trace_id)
    if finding_id is None:
        return not_requested

    conn = readers.pg_connect()
    try:
        rca = read_rca(conn, finding_id, project_id)
    finally:
        conn.close()
    return rca if rca is not None else not_requested
