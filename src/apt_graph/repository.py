"""Read package indices directly, without invoking a package manager."""

import gzip
import io
import json
import lzma
import re
import zlib
from dataclasses import dataclass
from functools import cmp_to_key
from http.client import HTTPException
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .relations import Relation, parse_provides, parse_relations
from .versions import compare_versions, satisfies, split_version

HTTP_TIMEOUT = 30
MAX_DOWNLOAD = 128 * 1024 * 1024
MAX_INDEX = 512 * 1024 * 1024
TEST_NAME = re.compile(r"[A-Z]+")
FIELD_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")
UNRESTRICTED_ARCHES = ("", "any", "native")


class RepositoryError(ValueError):
    """Invalid repository data or an unavailable package requirement."""


@dataclass(frozen=True)
class Package:
    """Package identity and the relationships declared by its metadata."""

    name: str
    version: str
    architecture: str = "all"
    depends: tuple[tuple[Relation, ...], ...] = ()
    provides: tuple[Relation, ...] = ()


def _download(source: str) -> bytes:
    """Download one bounded HTTP(S) index with a finite timeout."""
    if urlsplit(source).scheme not in ("http", "https"):
        raise RepositoryError("Индекс репозитория требует URL HTTP или HTTPS")
    request = Request(source, headers={"User-Agent": "apt-dependency-graph"})
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT) as response:
            data = response.read(MAX_DOWNLOAD + 1)
    except (URLError, OSError, ValueError, HTTPException) as error:
        message = f"Не удалось загрузить индекс: {error}"
        raise RepositoryError(message) from error
    if len(data) > MAX_DOWNLOAD:
        raise RepositoryError("Индекс превышает допустимый размер загрузки")
    return data


def _decode_index(data: bytes) -> str:
    """Decode plain, gzip or xz data, limiting the decompressed size."""
    stream = io.BytesIO(data)
    if data.startswith(b"\x1f\x8b"):
        stream = gzip.GzipFile(fileobj=stream)
    elif data.startswith(b"\xfd7zXZ\x00"):
        stream = lzma.LZMAFile(stream)
    try:
        with stream:
            unpacked = stream.read(MAX_INDEX + 1)
        if len(unpacked) > MAX_INDEX:
            raise RepositoryError("Распакованный индекс слишком большой")
        return unpacked.decode("utf-8")
    except (OSError, EOFError, lzma.LZMAError, UnicodeError,
            zlib.error) as error:
        message = f"Повреждён индекс репозитория: {error}"
        raise RepositoryError(message) from error


def _records(text: str):
    """Yield Debian control paragraphs, preserving folded fields."""
    fields, current = {}, ""
    for line in text.splitlines() + [""]:
        if not line.strip():
            if fields:
                yield fields
            fields, current = {}, ""
        elif line[0].isspace():
            if not current:
                raise RepositoryError("Перенос строки вне поля метаданных")
            fields[current] += "\n" + line.strip()
        else:
            current, separator, value = line.partition(":")
            if not separator or not FIELD_NAME.fullmatch(current):
                raise RepositoryError(f"Некорректная строка индекса: {line}")
            if current in fields:
                raise RepositoryError(f"Повтор поля индекса: {current}")
            fields[current] = value.strip()


def _package(record: dict[str, str]) -> Package:
    """Convert an index paragraph to a validated package record."""
    try:
        name, version = record["Package"], record["Version"]
        if not name or not re.fullmatch(r"[a-z0-9][a-z0-9+.\-]*", name):
            raise ValueError(f"Некорректное имя пакета: {name!r}")
        split_version(version)
        depends = parse_relations(record.get("Pre-Depends", ""))
        depends += parse_relations(record.get("Depends", ""))
        provides = parse_provides(record.get("Provides", ""))
        architecture = record.get("Architecture", "all")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", architecture):
            raise ValueError(f"Некорректная архитектура: {architecture!r}")
        return Package(name, version, architecture, depends, provides)
    except (KeyError, ValueError) as error:
        raise RepositoryError(f"Некорректная запись пакета: {error}") from error


def _test_record(name: str, record: dict) -> Package:
    """Read a node of the deliberately simple test repository format."""
    if not TEST_NAME.fullmatch(name) or not isinstance(record, dict):
        raise RepositoryError("Тестовые пакеты должны иметь имена A–Z")
    if set(record) - {"version", "dependencies"}:
        raise RepositoryError(f"Неизвестное поле тестового пакета {name}")
    version, dependencies = record.get("version"), record.get("dependencies")
    if not isinstance(version, str):
        raise RepositoryError(f"У пакета {name} отсутствует строковая версия")
    _validate_test_dependencies(name, dependencies)
    try:
        split_version(version)
    except ValueError as error:
        raise RepositoryError(str(error)) from error
    depends = tuple((Relation(item),) for item in dependencies)
    return Package(name, version, depends=depends)


def _validate_test_dependencies(name: str, dependencies) -> None:
    """Require a list of upper-case package names in a test record."""
    if not isinstance(dependencies, list):
        raise RepositoryError(f"Зависимости {name} должны быть списком")
    for dependency in dependencies:
        if not isinstance(dependency, str):
            raise RepositoryError(f"Некорректная зависимость пакета {name}")
        if not TEST_NAME.fullmatch(dependency):
            raise RepositoryError(f"Некорректная зависимость пакета {name}")


def _test_packages(source: str) -> list[Package]:
    """Load and validate a JSON graph, including its referenced nodes."""
    try:
        data = json.loads(Path(source).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise RepositoryError(f"Не удалось прочитать тестовый файл: {error}")
    if not isinstance(data, dict) or set(data) != {"packages"}:
        raise RepositoryError("Тестовый файл должен содержать объект packages")
    records = data["packages"]
    if not isinstance(records, dict) or not records:
        raise RepositoryError("Объект packages должен содержать пакеты")
    packages = [_test_record(name, item) for name, item in records.items()]
    for package in packages:
        for group in package.depends:
            if group[0].name not in records:
                raise RepositoryError(f"Неизвестный пакет: {group[0].name}")
    return packages


def _compare_packages(first: Package, second: Package) -> int:
    """Sort versions newest first; use a stable tie-breaker for providers."""
    compared = compare_versions(second.version, first.version)
    if compared:
        return compared
    left = (first.name, first.architecture)
    right = (second.name, second.architecture)
    return (left > right) - (left < right)


def _architecture_matches(package: Package, relation: Relation) -> bool:
    """Resolve qualifiers within the supplied architecture-specific index."""
    return (relation.architecture in UNRESTRICTED_ARCHES
            or package.architecture in ("all", relation.architecture))


class Repository:
    """An index of package versions with deterministic local resolution."""

    def __init__(self, source: str, test_mode: bool = False):
        """Read a test graph or fetch a Packages index directly."""
        self.warnings: list[str] = []
        self._packages: dict[str, list[Package]] = {}
        self._providers: dict[str, list[tuple[Package, Relation]]] = {}
        if test_mode:
            packages = _test_packages(source)
        else:
            text = _decode_index(_download(source))
            packages = [_package(record) for record in _records(text)]
        if not packages:
            raise RepositoryError("Индекс не содержит пакетов")
        for package in packages:
            self._packages.setdefault(package.name, []).append(package)
            for provided in package.provides:
                self._providers.setdefault(provided.name, []).append(
                    (package, provided)
                )
        for entries in self._packages.values():
            entries.sort(key=cmp_to_key(_compare_packages))

    def get(self, name: str, version: str | None = None) -> Package:
        """Find an exact root version, or the newest version if omitted."""
        for package in self._packages.get(name, []):
            if version is None or package.version == version:
                return package
        label = f"{name}={version}" if version is not None else name
        raise RepositoryError(f"Пакет не найден в индексе: {label}")

    def _resolve(self, relation: Relation) -> Package | None:
        """Prefer a real package, then a matching virtual provider."""
        for package in self._packages.get(relation.name, []):
            if (_architecture_matches(package, relation)
                    and satisfies(package.version, relation.operator,
                                  relation.version)):
                return package
        matches = []
        for package, provided in self._providers.get(relation.name, []):
            if not _architecture_matches(package, relation):
                continue
            if relation.operator and not provided.version:
                continue
            if not relation.operator or satisfies(
                    provided.version, relation.operator, relation.version):
                matches.append(package)
        return min(matches, key=cmp_to_key(_compare_packages), default=None)

    def dependencies(self, package: Package) -> list[Package]:
        """Resolve one alternative per group, rejecting incomplete graphs."""
        dependencies = []
        for group in package.depends:
            match = next((found for item in group
                          if (found := self._resolve(item)) is not None), None)
            if match is None:
                alternatives = " | ".join(item.name for item in group)
                message = (f"Не найдена зависимость {package.name}: "
                           f"{alternatives}")
                self.warnings.append(message)
                raise RepositoryError(message)
            if match not in dependencies:
                dependencies.append(match)
        return dependencies
