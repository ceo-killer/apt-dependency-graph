"""Read and validate application settings."""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from apt_graph.versions import split_version

ROOT_DEPTH = 0
FIELDS = {
    "package", "source", "test_mode", "version", "output", "max_depth",
}
PACKAGE_NAME = r"[a-z0-9][a-z0-9+.-]*"
TEST_NAME = r"[A-Z]+"


class ConfigError(ValueError):
    """Report an invalid configuration file or setting."""


@dataclass(frozen=True)
class Config:
    """Store validated settings with resolved file paths."""

    package: str
    source: str
    test_mode: bool
    version: str
    output: Path
    max_depth: int


def _read_object(path):
    """Read a JSON object and translate file errors."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ConfigError(f"Не удалось прочитать JSON: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError("Конфигурация должна быть объектом JSON")
    missing = FIELDS - data.keys()
    extra = data.keys() - FIELDS
    if missing or extra:
        raise ConfigError(
            f"Отсутствуют поля: {sorted(missing)}; лишние: {sorted(extra)}"
        )
    return data


def _text(data, field):
    """Require a nonempty string without surrounding whitespace."""
    value = data[field]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field}: требуется непустая строка")
    if value != value.strip():
        raise ConfigError(f"{field}: пробелы по краям недопустимы")
    return value


def _validate_options(data):
    """Check mode, package name, version and analysis depth."""
    if type(data["test_mode"]) is not bool:
        raise ConfigError("test_mode: требуется true или false")
    pattern = TEST_NAME if data["test_mode"] else PACKAGE_NAME
    if not re.fullmatch(pattern, _text(data, "package")):
        raise ConfigError("package: недопустимое имя пакета")
    version = _text(data, "version")
    try:
        split_version(version)
    except ValueError as error:
        raise ConfigError(f"version: {error}") from error
    depth = data["max_depth"]
    if type(depth) is not int or depth < ROOT_DEPTH:
        raise ConfigError("max_depth: требуется целое число от 0")


def _source(data, base):
    """Resolve a test file or validate a repository index URL."""
    source = _text(data, "source")
    if data["test_mode"]:
        path = (base / source).resolve()
        if not path.is_file() or not os.access(path, os.R_OK):
            raise ConfigError(f"source: файл недоступен: {path}")
        return str(path)
    url = urlparse(source)
    if url.scheme not in {"http", "https"} or not url.hostname:
        raise ConfigError("source: требуется HTTP(S) URL индекса Packages")
    try:
        url.port
    except ValueError as error:
        raise ConfigError("source: недопустимый порт URL") from error
    if url.username or url.password or url.fragment:
        raise ConfigError("source: URL не должен содержать вход или фрагмент")
    return source


def _output(data, base):
    """Resolve an SVG destination and check its existing parent."""
    path = (base / _text(data, "output")).resolve()
    if path.suffix.lower() != ".svg" or path.is_dir():
        raise ConfigError("output: требуется имя файла с расширением .svg")
    parent = path.parent
    while not parent.exists():
        parent = parent.parent
    if not parent.is_dir() or not os.access(parent, os.W_OK):
        raise ConfigError("output: каталог недоступен для записи")
    if path.exists() and not os.access(path, os.W_OK):
        raise ConfigError("output: файл недоступен для записи")
    return path


def _load_config(path):
    """Build settings from a resolved JSON file path."""
    data = _read_object(path)
    _validate_options(data)
    return Config(
        package=data["package"],
        source=_source(data, path.parent),
        test_mode=data["test_mode"],
        version=data["version"],
        output=_output(data, path.parent),
        max_depth=data["max_depth"],
    )


def load_config(filename):
    """Load settings and report malformed paths or URLs as config errors."""
    try:
        return _load_config(Path(filename).resolve())
    except ConfigError:
        raise
    except (OSError, ValueError) as error:
        raise ConfigError(f"Некорректный путь или URL: {error}") from error
