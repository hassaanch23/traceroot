"""Build a parent/child span forest from a flat span list.

There is no server-side tree on the backend — ``TraceReaderService.get_trace``
returns a flat, ``span_start_time``-ordered list of span skeletons. Agents doing
root-cause analysis need the hierarchy, so the ``get_trace_tree`` tool assembles
it here from each span's ``parent_span_id``.
"""

from __future__ import annotations

from typing import Any


def build_trace_tree(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assemble flat spans into a forest of nodes, each with a ``children`` list.

    A span is a **root** when its ``parent_span_id`` is falsy (``None`` or the
    empty string — ClickHouse stores an absent parent as ``""``) OR points to a
    span that is not present in this trace (an orphan whose parent wasn't
    ingested). Every input span appears exactly once in the output, so the tree
    never silently drops spans that ``spans.jsonl`` would contain.

    Child order follows the input order (spans arrive sorted by
    ``span_start_time`` ascending), and each node is a shallow copy of the span
    dict plus a ``children`` key, so the caller's spans are not mutated. A
    ``parent_span_id`` cycle cannot loop forever — a span already on the current
    path is not re-expanded.
    """
    by_id: dict[str, dict[str, Any]] = {}
    children: dict[str, list[str]] = {}
    for span in spans:
        span_id = span["span_id"]
        by_id[span_id] = span
        parent_id = span.get("parent_span_id") or None
        if parent_id is not None:
            children.setdefault(parent_id, []).append(span_id)

    known = set(by_id)
    visited: set[str] = set()

    def build_node(span_id: str, path: frozenset[str]) -> dict[str, Any]:
        visited.add(span_id)
        node = dict(by_id[span_id])
        child_nodes: list[dict[str, Any]] = []
        for child_id in children.get(span_id, []):
            if child_id in path:
                # Cyclic parent reference — stop descending to avoid recursion.
                continue
            child_nodes.append(build_node(child_id, path | {child_id}))
        node["children"] = child_nodes
        return node

    roots: list[dict[str, Any]] = []
    for span in spans:
        span_id = span["span_id"]
        parent_id = span.get("parent_span_id") or None
        if (parent_id is None or parent_id not in known) and span_id not in visited:
            roots.append(build_node(span_id, frozenset({span_id})))

    # Completeness guard: a pathological parent cycle (a -> b -> a) leaves spans
    # with no reachable root. Promote any span not yet placed so the forest still
    # contains every input span exactly once, in input order.
    for span in spans:
        span_id = span["span_id"]
        if span_id not in visited:
            roots.append(build_node(span_id, frozenset({span_id})))

    return roots
