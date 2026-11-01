"""Parser for binary package dependency relationships."""

import re
from dataclasses import dataclass

from .versions import split_version

RELATION = re.compile(
    r"\s*([A-Za-z0-9][A-Za-z0-9+.\-]*)"
    r"(?::([a-z0-9][a-z0-9\-]*))?"
    r"\s*(?:\(\s*(<<|<=|=|>=|>>)\s*([^\s()]+)\s*\))?\s*"
)
SINGLE_RELATION = 1


@dataclass(frozen=True)
class Relation:
    """One package requirement, optionally qualified by version and arch."""

    name: str
    operator: str = ""
    version: str = ""
    architecture: str = ""


def parse_relation(text: str) -> Relation:
    """Parse a single requirement without alternatives."""
    match = RELATION.fullmatch(text)
    if not match:
        raise ValueError(f"Некорректная зависимость: {text!r}")
    name, architecture, operator, version = match.groups()
    if version:
        split_version(version)
    return Relation(name, operator or "", version or "", architecture or "")


def parse_relations(text: str) -> tuple[tuple[Relation, ...], ...]:
    """Return mandatory groups; each group contains ordered alternatives."""
    if not text.strip():
        return ()
    return tuple(
        tuple(parse_relation(item) for item in group.split("|"))
        for group in text.split(",")
    )


def parse_provides(text: str) -> tuple[Relation, ...]:
    """Parse virtual package declarations, allowing only exact versions."""
    groups = parse_relations(text)
    provides = []
    for group in groups:
        if len(group) != SINGLE_RELATION or group[0].operator not in ("", "="):
            raise ValueError(f"Некорректное поле Provides: {text!r}")
        provides.append(group[0])
    return tuple(provides)
