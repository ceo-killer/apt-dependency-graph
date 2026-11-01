"""Build bounded dependency graphs with an explicit DFS stack."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apt_graph.repository import Package, Repository

ROOT_DEPTH = 0


@dataclass
class DependencyGraph:
    """Packages, directed edges and nodes left unexpanded at the depth limit."""

    root: str
    nodes: dict[str, Package] = field(default_factory=dict)
    edges: dict[str, list[str]] = field(default_factory=dict)
    truncated: set[str] = field(default_factory=set)


def key(package: Package) -> str:
    """Identify a package independently of labels in a rendered diagram."""
    return f"{package.name}@{package.version}:{package.architecture}"


def _add_dependencies(graph, parent, dependencies):
    """Keep shared and cyclic edges while adding each package only once."""
    for package in dependencies:
        child = key(package)
        graph.nodes[child] = package
        graph.edges.setdefault(child, [])
        if child not in graph.edges[parent]:
            graph.edges[parent].append(child)


def build_graph(repository: Repository, root: Package,
                max_depth: int) -> DependencyGraph:
    """Expand packages by DFS; revisit nodes reached with more depth left."""
    if type(max_depth) is not int or max_depth < ROOT_DEPTH:
        raise ValueError("Maximum depth must be a non-negative integer")
    root_key = key(root)
    graph = DependencyGraph(root_key, {root_key: root}, {root_key: []})
    best_depth = {}
    stack = [(root, ROOT_DEPTH)]
    while stack:
        package, depth = stack.pop()
        node = key(package)
        previous = best_depth.get(node)
        if previous is not None and previous <= depth:
            continue
        best_depth[node] = depth
        if depth == max_depth:
            graph.truncated.add(node)
            continue
        graph.truncated.discard(node)
        dependencies = repository.dependencies(package)
        _add_dependencies(graph, node, dependencies)
        stack.extend((child, depth + 1) for child in reversed(dependencies))
    return graph
