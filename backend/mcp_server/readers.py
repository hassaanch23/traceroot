"""The single data-access seam for the MCP tools.

``Readers`` bundles the three data sources the tools read from:

- ``trace_reader`` — the backend ``TraceReaderService`` (traces + spans in
  ClickHouse), reused so trace reads stay identical to the REST API.
- ``clickhouse`` — a ClickHouse client for the ``detector_findings`` table.
- ``pg_connect`` — a factory returning a fresh Postgres connection for the
  ``detector_rcas`` table.

The tool handlers depend only on this small surface (the Protocols below), so
tests inject fakes and never touch a real database — and a future maintainer can
swap any source for an HTTP-API-backed implementation without touching tool
logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class TraceReaderLike(Protocol):
    def get_trace(self, project_id: str, trace_id: str) -> dict | None: ...

    def get_trace_spans_io(
        self, project_id: str, trace_id: str, columns: frozenset[str]
    ) -> dict[str, dict]: ...


class ClickHouseLike(Protocol):
    def query(self, query: str, parameters: dict[str, Any] | None = None) -> Any: ...


class PgConnect(Protocol):
    def __call__(self) -> Any: ...


@dataclass
class Readers:
    """Bundle of the tools' data sources; the injection point for tests."""

    trace_reader: TraceReaderLike
    clickhouse: ClickHouseLike
    pg_connect: PgConnect


def default_readers() -> Readers:
    """Build the production ``Readers`` from the backend's real services.

    Imports are local so that unit tests (which inject fake ``Readers``) never
    load the heavy service/driver modules or require a live database.
    """
    import psycopg2

    from db.clickhouse.client import get_clickhouse_client
    from rest.services.trace_reader import get_trace_reader_service
    from shared.config import settings

    return Readers(
        trace_reader=get_trace_reader_service(),
        clickhouse=get_clickhouse_client(),
        pg_connect=lambda: psycopg2.connect(settings.database_url),
    )
