"""Show direct dependencies of the requested package version."""

import argparse
import sys

from apt_graph.config import ConfigError, load_config
from apt_graph.repository import Repository, RepositoryError

SUCCESS = 0
FAILURE = 1


def _arguments(argv):
    """Accept a path to the JSON configuration."""
    parser = argparse.ArgumentParser(description="Граф зависимостей Ubuntu")
    parser.add_argument("--config", default="examples/demo.json")
    return parser.parse_args(argv)


def _run(arguments):
    """Load the requested version and print its direct dependencies."""
    config = load_config(arguments.config)
    repository = Repository(config.source, config.test_mode)
    package = repository.get(config.package, config.version)
    for dependency in repository.dependencies(package):
        print(f"{dependency.name}={dependency.version}")


def main(argv=None):
    """Run the application and return a process exit code."""
    arguments = _arguments(argv)
    try:
        _run(arguments)
    except (ConfigError, RepositoryError, OSError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return FAILURE
    return SUCCESS
