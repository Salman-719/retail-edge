"""Camera overlap graph (Stage 0) and connected-component grouping (Stage 4).

Stage 0: the set of camera pairs that share a covered floor zone. Only pairs in
this set are ever compared during reconciliation — a pair absent from the graph
is never voted on. Sourced from `camera_zone_coverage` (populated by EEP at
version activation).

Stage 4: after spatial + appearance matching produce confirmed cross-camera
links, group every (camera_id, local_id) node into connected components. Each
component is one physical person, possibly seen by cameras that were never
compared directly (transitive linking: A–B and B–C ⇒ {A, B, C}).

networkx is used ONLY for connected_components (hard constraint).
"""
from __future__ import annotations

import networkx as nx


class CameraGraph:
    """Undirected overlap graph over physical camera ids."""

    def __init__(self, edges) -> None:
        # Store as frozenset pairs so (a, b) == (b, a). Self-pairs dropped.
        self._edges: set[frozenset] = {
            frozenset((a, b)) for a, b in edges if a != b
        }

    @property
    def edges(self) -> set[frozenset]:
        return self._edges

    def are_adjacent(self, cam_a: str, cam_b: str) -> bool:
        return frozenset((cam_a, cam_b)) in self._edges

    def overlapping_pairs(self) -> list[tuple[str, str]]:
        """Each overlapping camera pair once, as a sorted (cam_a, cam_b) tuple."""
        return sorted(tuple(sorted(p)) for p in self._edges if len(p) == 2)


def connected_components(nodes, edges) -> list[set]:
    """Group nodes into connected components given confirmed edges.

    nodes: iterable of hashable node ids — here (camera_id, local_id) tuples.
    edges: iterable of (node, node) confirmed links.
    Returns a list of node sets. Nodes with no edges form singleton components
    (a person seen in only one camera).
    """
    graph = nx.Graph()
    graph.add_nodes_from(nodes)
    graph.add_edges_from(edges)
    return [set(component) for component in nx.connected_components(graph)]
