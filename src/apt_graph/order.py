"""Compute dependency-first order by iterative DFS finishing times."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apt_graph.graph import DependencyGraph

ACTIVE = 1
FINISHED = 2


class CycleError(ValueError):
    """A graph contains a cycle and has no strict dependency-first order."""

    def __init__(self, cycle: list[str]):
        """Retain the closed path for diagnostics and independent checks."""
        self.cycle = cycle
        super().__init__("Dependency cycle: " + " -> ".join(cycle))


def _finish_branch(graph, start, state, result):
    """Finish one component using a stack of neighbour iterators."""
    path = [start]
    positions = {start: 0}
    state[start] = ACTIVE
    stack = [iter(graph.edges.get(start, []))]
    while stack:
        child = next(stack[-1], None)
        if child is None:
            node = path.pop()
            positions.pop(node)
            stack.pop()
            state[node] = FINISHED
            result.append(node)
        elif state.get(child) == ACTIVE:
            raise CycleError(path[positions[child]:] + [child])
        elif state.get(child) != FINISHED:
            positions[child] = len(path)
            path.append(child)
            state[child] = ACTIVE
            stack.append(iter(graph.edges.get(child, [])))


def dependency_order(graph: DependencyGraph) -> list[str]:
    """Return dependencies before consumers, or report an actual cycle."""
    result = []
    state = {}
    for node in graph.nodes:
        if node not in state:
            _finish_branch(graph, node, state, result)
    return result
