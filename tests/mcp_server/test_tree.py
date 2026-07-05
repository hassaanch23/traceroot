"""Unit tests for build_trace_tree (pure function, no fakes needed)."""

from __future__ import annotations

from mcp_server.tree import build_trace_tree


def _span(span_id: str, parent: str | None) -> dict:
    return {"span_id": span_id, "parent_span_id": parent, "name": span_id}


def test_empty_list_yields_no_roots():
    assert build_trace_tree([]) == []


def test_single_root_span():
    tree = build_trace_tree([_span("a", None)])
    assert len(tree) == 1
    assert tree[0]["span_id"] == "a"
    assert tree[0]["children"] == []


def test_linear_chain_nests():
    tree = build_trace_tree([_span("a", None), _span("b", "a"), _span("c", "b")])
    assert [n["span_id"] for n in tree] == ["a"]
    assert tree[0]["children"][0]["span_id"] == "b"
    assert tree[0]["children"][0]["children"][0]["span_id"] == "c"


def test_branching_preserves_input_order():
    tree = build_trace_tree([_span("root", None), _span("c1", "root"), _span("c2", "root")])
    assert [c["span_id"] for c in tree[0]["children"]] == ["c1", "c2"]


def test_empty_string_parent_is_a_root():
    # ClickHouse stores an absent parent as "" rather than None.
    tree = build_trace_tree([_span("a", ""), _span("b", "a")])
    assert [n["span_id"] for n in tree] == ["a"]
    assert tree[0]["children"][0]["span_id"] == "b"


def test_orphan_parent_is_promoted_to_root():
    # 'b' points at a parent that isn't in the trace -> treat 'b' as a root so it
    # is never silently dropped.
    tree = build_trace_tree([_span("a", None), _span("b", "missing")])
    assert sorted(n["span_id"] for n in tree) == ["a", "b"]


def test_multiple_roots():
    tree = build_trace_tree([_span("r1", None), _span("r2", None), _span("c", "r1")])
    roots = [n["span_id"] for n in tree]
    assert roots == ["r1", "r2"]
    assert tree[0]["children"][0]["span_id"] == "c"


def test_every_span_appears_exactly_once():
    spans = [_span("a", None), _span("b", "a"), _span("c", "a"), _span("d", "c")]
    tree = build_trace_tree(spans)

    seen: list[str] = []

    def walk(nodes):
        for n in nodes:
            seen.append(n["span_id"])
            walk(n["children"])

    walk(tree)
    assert sorted(seen) == ["a", "b", "c", "d"]


def test_cycle_terminates_and_keeps_every_span():
    # a -> b -> a: a pathological parent cycle with no real root. The build must
    # terminate (no infinite recursion) AND still surface both spans exactly once.
    tree = build_trace_tree([_span("a", "b"), _span("b", "a")])

    seen: list[str] = []

    def walk(nodes):
        for n in nodes:
            seen.append(n["span_id"])
            walk(n["children"])

    walk(tree)
    assert sorted(seen) == ["a", "b"]


def test_does_not_mutate_input_spans():
    spans = [_span("a", None)]
    build_trace_tree(spans)
    assert "children" not in spans[0]
