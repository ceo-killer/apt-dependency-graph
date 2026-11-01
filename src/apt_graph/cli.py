"""Print a dependency-first order for the requested graph."""

import argparse
import sys

from apt_graph.config import ConfigError, load_config
from apt_graph.graph import build_graph
from apt_graph.order import CycleError, dependency_order
from apt_graph.repository import Repository, RepositoryError

SUCCESS = 0
FAILURE = 1


def _arguments(argv):
    """Accept a path to the JSON configuration."""
    parser = argparse.ArgumentParser(description="Граф зависимостей Ubuntu")
    parser.add_argument("--config", default="examples/demo.json")
    return parser.parse_args(argv)


def _run(arguments):
    """Build a graph and show dependency-first DFS finishing order."""
    config = load_config(arguments.config)
    repository = Repository(config.source, config.test_mode)
    package = repository.get(config.package, config.version)
    graph = build_graph(repository, package, config.max_depth)
    for node in dependency_order(graph):
        package = graph.nodes[node]
        print(f"{package.name}={package.version}")
    if graph.truncated:
        print("Порядок относится только к раскрытой части графа.",
              file=sys.stderr)


def main(argv=None):
    """Run the application and return a process exit code."""
    arguments = _arguments(argv)
    try:
        _run(arguments)
    except (ConfigError, RepositoryError, CycleError, OSError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return FAILURE
    return SUCCESS
