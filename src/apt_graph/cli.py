"""Read a configuration and show its settings."""

import argparse
import sys
from dataclasses import asdict

from apt_graph.config import ConfigError, load_config

SUCCESS = 0
FAILURE = 1


def main(argv=None):
    """Run the configuration prototype."""
    parser = argparse.ArgumentParser(description="Граф зависимостей Ubuntu")
    parser.add_argument("--config", default="examples/demo.json")
    arguments = parser.parse_args(argv)
    try:
        config = load_config(arguments.config)
        for name, value in asdict(config).items():
            print(f"{name}={value}")
    except (ConfigError, OSError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return FAILURE
    return SUCCESS
