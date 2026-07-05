"""Read existing root-cause-analysis (RCA) state for a trace.

RCA results live in the Postgres ``detector_rcas`` table (Prisma model
``DetectorRca``), keyed by ``finding_id`` (one trace-level finding per trace),
not by ``trace_id``. So resolving a trace's RCA is two reads: find the trace's
``finding_id`` in ClickHouse ``detector_findings``, then read its row in
Postgres. Everything here is read-only — triggering a *new* RCA runs the LLM
agent and is intentionally out of scope for the MCP server.
"""

from __future__ import annotations

from typing import Any

# Latest finding for the trace. detector_findings is a ReplacingMergeTree, so
# read FINAL to collapse pre-merge duplicates (mirrors the internal
# /traces/{trace_id}/findings endpoint). One finding per trace, but ORDER BY /
# LIMIT keeps it deterministic if that ever changes.
_FINDING_ID_SQL = """
    SELECT finding_id
    FROM detector_findings FINAL
    WHERE trace_id = {trace_id:String} AND project_id = {project_id:String}
    ORDER BY timestamp DESC
    LIMIT 1
"""

# Parameterized (psycopg2 %s) — never string-format tenant-supplied ids.
_RCA_SQL = (
    "SELECT status, result, completed_at, session_id "
    "FROM detector_rcas WHERE finding_id = %s AND project_id = %s"
)


def resolve_finding_id(clickhouse: Any, project_id: str, trace_id: str) -> str | None:
    """Return the trace's finding_id, or None when the trace has no finding."""
    result = clickhouse.query(
        _FINDING_ID_SQL,
        parameters={"trace_id": trace_id, "project_id": project_id},
    )
    if not result.result_rows:
        return None
    finding_id: str = result.result_rows[0][0]
    return finding_id


def read_rca(pg_conn: Any, finding_id: str, project_id: str) -> dict[str, Any] | None:
    """Read the RCA row for a finding, or None when no RCA has been requested.

    Returns a dict of ``status`` (``pending``/``running``/``done``/``failed``),
    ``result`` (the RCA text, present when done), ``completed_at`` (ISO-8601 or
    None) and ``session_id`` (the RCA session, or None).
    """
    with pg_conn.cursor() as cur:
        cur.execute(_RCA_SQL, (finding_id, project_id))
        row = cur.fetchone()
    if row is None:
        return None
    status, result, completed_at, session_id = row
    return {
        "status": status,
        "result": result,
        "completed_at": completed_at.isoformat() if completed_at is not None else None,
        "session_id": session_id,
    }
