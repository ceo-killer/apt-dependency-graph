"""Comparison of Debian versions, including epochs and pre-releases."""

import re

VERSION = re.compile(r"[0-9][A-Za-z0-9.+:~\-]*")
REVISION = re.compile(r"[A-Za-z0-9+.~]+")
DIGITS = re.compile(r"[0-9]*")
EQUAL = 0


def split_version(version: str) -> tuple[int, str, str]:
    """Validate a version and separate epoch, upstream and revision."""
    if not isinstance(version, str) or not version:
        raise ValueError("Версия должна быть непустой строкой")
    epoch, remaining = 0, version
    if ":" in version:
        prefix, remaining = version.split(":", 1)
        if not prefix.isascii() or not prefix.isdigit():
            raise ValueError(f"Некорректная эпоха версии: {version}")
        epoch = int(prefix)
    upstream, separator, revision = remaining.rpartition("-")
    if not separator:
        upstream, revision = remaining, "0"
    if not VERSION.fullmatch(upstream) or not REVISION.fullmatch(revision):
        raise ValueError(f"Некорректная версия Debian: {version}")
    return epoch, upstream, revision


def _order(character: str) -> int:
    """Return dpkg's ordering for a non-numeric character."""
    if character == "~":
        return -1
    if not character or character.isdigit():
        return 0
    if character.isalpha():
        return ord(character)
    return ord(character) + 256


def _character(text: str, position: int) -> str:
    """Return a character or the end-of-string marker."""
    return text[position:position + 1]


def _compare_letters(left: str, right: str) -> tuple[int, int, int]:
    """Compare the next non-numeric segment and report consumed lengths."""
    first, second = 0, 0
    while True:
        a, b = _character(left, first), _character(right, second)
        if (not a or a.isdigit()) and (not b or b.isdigit()):
            return 0, first, second
        difference = _order(a) - _order(b)
        if difference:
            return difference, first, second
        first += bool(a)
        second += bool(b)


def _compare_component(left: str, right: str) -> int:
    """Compare upstream versions or revisions using Debian rules."""
    while left or right:
        difference, first, second = _compare_letters(left, right)
        if difference:
            return difference
        left, right = left[first:], right[second:]
        a, b = DIGITS.match(left).group(), DIGITS.match(right).group()
        first_digits, second_digits = a.lstrip("0"), b.lstrip("0")
        if len(first_digits) != len(second_digits):
            return len(first_digits) - len(second_digits)
        if first_digits != second_digits:
            return (first_digits > second_digits) * 2 - 1
        left, right = left[len(a):], right[len(b):]
    return 0


def compare_versions(left: str, right: str) -> int:
    """Return a negative, zero or positive Debian version comparison."""
    first, second = split_version(left), split_version(right)
    if first[0] != second[0]:
        return first[0] - second[0]
    return (_compare_component(first[1], second[1])
            or _compare_component(first[2], second[2]))


def satisfies(version: str, operator: str = "", target: str = "") -> bool:
    """Check one of Debian's five version relationship operators."""
    if not operator:
        return True
    difference = compare_versions(version, target)
    comparisons = {
        "<<": difference < EQUAL,
        "<=": difference <= EQUAL,
        "=": difference == EQUAL,
        ">=": difference >= EQUAL,
        ">>": difference > EQUAL,
    }
    if operator not in comparisons:
        raise ValueError(f"Неизвестный оператор версии: {operator}")
    return comparisons[operator]
