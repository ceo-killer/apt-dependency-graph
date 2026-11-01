"""Check dependency order and exact cycle diagnostics."""

import unittest
from dataclasses import dataclass

from apt_graph.graph import build_graph
from apt_graph.order import CycleError, dependency_order


@dataclass(frozen=True)
class Package:
    """Package record isolated from the metadata parser."""

    name: str
    version: str = "1"
    architecture: str = "all"


class Repository:
    """Provide named dependencies to the graph builder."""

    def __init__(self, edges):
        """Retain the adjacency list supplied by a test."""
        self.edges = edges

    def dependencies(self, package):
        """Return dependency records in declared order."""
        return [Package(name) for name in self.edges.get(package.name, [])]


def make_graph(edges, root="A", depth=20):
    """Create a graph without coupling order tests to apt metadata."""
    return build_graph(Repository(edges), Package(root), depth)


class OrderTests(unittest.TestCase):
    """Check constraints rather than one arbitrary valid permutation."""

    def assert_dependencies_first(self, graph, order):
        """Each edge must point to an earlier item in a complete order."""
        self.assertEqual(set(order), set(graph.nodes))
        self.assertEqual(len(order), len(graph.nodes))
        positions = {node: index for index, node in enumerate(order)}
        for parent, children in graph.edges.items():
            for child in children:
                self.assertLess(positions[child], positions[parent])

    def test_chain(self):
        """A chain has a unique dependency-first order."""
        graph = make_graph({"A": ["B"], "B": ["C"]})
        order = dependency_order(graph)
        self.assert_dependencies_first(graph, order)
        self.assertEqual([graph.nodes[node].name for node in order],
                         ["C", "B", "A"])

    def test_diamond_is_not_a_cycle(self):
        """A shared dependency is output once before both consumers."""
        graph = make_graph({
            "A": ["B", "C"], "B": ["D"], "C": ["D"],
        })
        self.assert_dependencies_first(graph, dependency_order(graph))

    def test_single_node(self):
        """The root remains in the order even without dependencies."""
        graph = make_graph({})
        self.assertEqual(dependency_order(graph), [graph.root])

    def test_depth_limited_order_only_claims_visible_edges(self):
        """A bounded graph has an order for its visible relationships."""
        graph = make_graph({"A": ["B"], "B": ["C"]}, depth=1)
        self.assert_dependencies_first(graph, dependency_order(graph))
        self.assertEqual(len(dependency_order(graph)), 2)

    def test_cycle_reports_closed_path(self):
        """The diagnostic describes real consecutive edges of a cycle."""
        graph = make_graph({"A": ["B"], "B": ["C"], "C": ["A"]})
        with self.assertRaises(CycleError) as raised:
            dependency_order(graph)
        cycle = raised.exception.cycle
        self.assertEqual(cycle[0], cycle[-1])
        for parent, child in zip(cycle, cycle[1:]):
            self.assertIn(child, graph.edges[parent])

    def test_self_dependency_reports_cycle(self):
        """A self-loop has no strict dependency-first order."""
        graph = make_graph({"A": ["A"]})
        with self.assertRaises(CycleError) as raised:
            dependency_order(graph)
        self.assertEqual(raised.exception.cycle, [graph.root, graph.root])

    def test_long_chain_has_no_recursive_calls(self):
        """Ordering also works beyond Python's usual recursion limit."""
        edges = {str(index): [str(index + 1)] for index in range(1800)}
        graph = make_graph(edges, root="0", depth=2000)
        self.assert_dependencies_first(graph, dependency_order(graph))
