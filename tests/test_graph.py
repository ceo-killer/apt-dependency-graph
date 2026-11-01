"""Exercise bounded DFS with small repositories and adversarial paths."""

import unittest
from dataclasses import dataclass

from apt_graph.graph import build_graph, key


@dataclass(frozen=True)
class Package:
    """Minimal package used to keep graph tests independent of parsing."""

    name: str
    version: str = "1"
    architecture: str = "all"


class Repository:
    """In-memory repository recording the order of metadata requests."""

    def __init__(self, edges):
        """Store named edges and a log of calls made by the traversal."""
        self.edges = edges
        self.calls = []

    def dependencies(self, package):
        """Return declared neighbours in their original order."""
        self.calls.append(package.name)
        return [Package(name) for name in self.edges.get(package.name, [])]


def named_edges(graph):
    """Convert opaque graph identifiers into readable test assertions."""
    return {
        graph.nodes[parent].name: [graph.nodes[x].name for x in children]
        for parent, children in graph.edges.items()
    }


class GraphTests(unittest.TestCase):
    """Check graph content as well as the required DFS traversal."""

    def test_single_package(self):
        """A package without dependencies remains visible."""
        graph = build_graph(Repository({}), Package("A"), 1)
        self.assertEqual(named_edges(graph), {"A": []})
        self.assertEqual(graph.root, key(Package("A")))
        self.assertFalse(graph.truncated)

    def test_depth_zero_does_not_query_dependencies(self):
        """The root is the entire graph when the limit is zero."""
        repository = Repository({"A": ["B"]})
        graph = build_graph(repository, Package("A"), 0)
        self.assertEqual(named_edges(graph), {"A": []})
        self.assertEqual(graph.truncated, {key(Package("A"))})
        self.assertEqual(repository.calls, [])

    def test_boundary_nodes_are_present_but_not_expanded(self):
        """A depth-one run includes direct dependencies only."""
        repository = Repository({"A": ["B"], "B": ["C"]})
        graph = build_graph(repository, Package("A"), 1)
        self.assertEqual(named_edges(graph), {"A": ["B"], "B": []})
        self.assertEqual(repository.calls, ["A"])

    def test_expansion_is_depth_first(self):
        """The first child's branch is explored before its sibling."""
        repository = Repository({"A": ["B", "C"], "B": ["D"]})
        build_graph(repository, Package("A"), 5)
        self.assertEqual(repository.calls, ["A", "B", "D", "C"])

    def test_shared_dependency_keeps_both_edges(self):
        """A diamond keeps both incoming edges without repeated expansion."""
        repository = Repository({
            "A": ["B", "C"], "B": ["D"], "C": ["D"],
        })
        graph = build_graph(repository, Package("A"), 5)
        self.assertEqual(named_edges(graph), {
            "A": ["B", "C"], "B": ["D"], "C": ["D"], "D": [],
        })
        self.assertEqual(repository.calls.count("D"), 1)

    def test_shorter_path_reopens_a_depth_limited_node(self):
        """A later shorter path restores the budget to reach Y."""
        repository = Repository({
            "A": ["B", "X"], "B": ["C"], "C": ["X"], "X": ["Y"],
        })
        graph = build_graph(repository, Package("A"), 3)
        self.assertIn("Y", named_edges(graph))
        self.assertEqual(named_edges(graph)["X"], ["Y"])
        self.assertNotIn(key(Package("X")), graph.truncated)

    def test_cycle_preserves_edges_and_terminates(self):
        """Cycles do not lead to repeated expansion or dropped edges."""
        repository = Repository({
            "A": ["B"], "B": ["C"], "C": ["A", "D"],
        })
        graph = build_graph(repository, Package("A"), 20)
        self.assertEqual(named_edges(graph)["C"], ["A", "D"])
        self.assertEqual(repository.calls, ["A", "B", "C", "D"])

    def test_self_dependency(self):
        """A package may point to itself without hanging the traversal."""
        repository = Repository({"A": ["A"]})
        graph = build_graph(repository, Package("A"), 5)
        self.assertEqual(named_edges(graph), {"A": ["A"]})
        self.assertEqual(repository.calls, ["A"])

    def test_long_chain_does_not_use_recursion(self):
        """The traversal survives a chain beyond Python's recursion limit."""
        edges = {str(index): [str(index + 1)] for index in range(1800)}
        graph = build_graph(Repository(edges), Package("0"), 2000)
        self.assertEqual(len(graph.nodes), 1801)
        self.assertEqual(named_edges(graph)["1800"], [])

    def test_invalid_depth(self):
        """Reject booleans, negative values and non-integer depths."""
        for depth in [-1, True, 1.5, "1", None]:
            with self.subTest(depth=depth), self.assertRaises(ValueError):
                build_graph(Repository({}), Package("A"), depth)

    def test_package_identity_includes_version_and_architecture(self):
        """Different package records cannot overwrite one graph node."""
        packages = [
            Package("A", "1", "amd64"), Package("A", "2", "amd64"),
            Package("A", "1", "arm64"),
        ]
        self.assertEqual(len({key(package) for package in packages}), 3)
