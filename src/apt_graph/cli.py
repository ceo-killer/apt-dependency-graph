"""Render the requested Ubuntu dependency graph as SVG."""

import argparse
import sys

from apt_graph.config import ConfigError, load_config
from apt_graph.graph import build_graph
from apt_graph.repository import Repository, RepositoryError
from apt_graph.visualize import RenderError, render_svg

SUCCESS = 0
FAILURE = 1


def _arguments(argv):
    """Accept a path to the JSON configuration."""
    parser = argparse.ArgumentParser(description="Граф зависимостей Ubuntu")
    parser.add_argument("--config", default="examples/demo.json")
    return parser.parse_args(argv)


def _run(arguments):
    """Read package metadata, build the graph and save its diagram."""
    config = load_config(arguments.config)
    repository = Repository(config.source, config.test_mode)
    package = repository.get(config.package, config.version)
    graph = build_graph(repository, package, config.max_depth)
    output = render_svg(graph, config.output)
    print(f"SVG: {output}")
    if graph.truncated:
        print("Вершины на границе глубины не раскрыты.",
              file=sys.stderr)


def main(argv=None):
    """Run the application and return a process exit code."""
    arguments = _arguments(argv)
    try:
        _run(arguments)
    except (ConfigError, RepositoryError, RenderError, OSError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return FAILURE
    return SUCCESS
