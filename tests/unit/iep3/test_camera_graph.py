"""Unit tests for the camera overlap graph (Stage 0) and connected components (Stage 4)."""
from app.camera_graph import CameraGraph, connected_components


def test_edges_are_undirected_and_deduped():
    g = CameraGraph([("a", "b"), ("b", "a"), ("a", "b")])
    assert len(g.edges) == 1
    assert g.are_adjacent("a", "b")
    assert g.are_adjacent("b", "a")
    assert not g.are_adjacent("a", "c")


def test_self_pairs_dropped():
    g = CameraGraph([("a", "a"), ("a", "b")])
    assert g.overlapping_pairs() == [("a", "b")]


def test_overlapping_pairs_sorted():
    g = CameraGraph([("c", "a"), ("b", "a")])
    assert g.overlapping_pairs() == [("a", "b"), ("a", "c")]


def test_transitive_component():
    # A–B and B–C confirmed, A and C never compared → one component {A,B,C}.
    nodes = [("camA", 1), ("camB", 3), ("camC", 7), ("camB", 9)]
    edges = [(("camA", 1), ("camB", 3)), (("camB", 3), ("camC", 7))]
    comps = connected_components(nodes, edges)
    big = [c for c in comps if len(c) > 1][0]
    assert big == {("camA", 1), ("camB", 3), ("camC", 7)}
    # The unlinked node is its own singleton.
    assert {("camB", 9)} in comps


def test_isolated_nodes_are_singletons():
    nodes = [("camA", 1), ("camB", 2)]
    comps = connected_components(nodes, [])
    assert {("camA", 1)} in comps and {("camB", 2)} in comps
    assert len(comps) == 2
