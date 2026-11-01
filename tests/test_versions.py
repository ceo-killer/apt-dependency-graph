"""Checks for Debian's epoch, revision and tilde ordering rules."""

import unittest

from apt_graph.versions import compare_versions, satisfies, split_version


class VersionTests(unittest.TestCase):
    """Exercise version semantics that differ from lexical and SemVer order."""

    def test_ordering(self):
        """Compare numeric segments, revisions, epochs and pre-releases."""
        pairs = [
            ("1.9", "1.10"),
            ("1.0~rc1", "1.0"),
            ("1.0~~", "1.0~"),
            ("1.0", "1.0+git"),
            ("1.0-1", "1.0-1ubuntu1"),
            ("1.0-2", "1.0-10"),
            ("9.9", "1:0.1"),
            ("1:99", "2:1"),
            ("1.0a", "1.0+"),
            ("1.0-1~bpo1", "1.0-1"),
        ]
        for first, second in pairs:
            with self.subTest(first=first, second=second):
                self.assertLess(compare_versions(first, second), 0)
                self.assertGreater(compare_versions(second, first), 0)

    def test_equivalence(self):
        """Leading zeroes and an absent zero revision are equivalent."""
        for first, second in [("1.01", "1.1"), ("1.0", "0:1.0-0")]:
            with self.subTest(first=first):
                self.assertEqual(compare_versions(first, second), 0)

    def test_relationships(self):
        """All five operators apply the Debian comparator."""
        self.assertTrue(satisfies("1.10", ">>", "1.9"))
        self.assertTrue(satisfies("1.0~rc1", "<<", "1.0"))
        self.assertTrue(satisfies("1.0", "=", "1.0-0"))
        self.assertTrue(satisfies("1.0", ">=", "1.0"))
        self.assertTrue(satisfies("1.0", "<=", "1.0"))
        self.assertTrue(satisfies("1.0"))
        self.assertFalse(satisfies("1.0", ">>", "1.0"))
        with self.assertRaises(ValueError):
            satisfies("1.0", "!=", "2.0")

    def test_invalid_versions(self):
        """Reject malformed versions before they influence package choice."""
        for version in ["", "v1", "bad:1", "1-", "1_0", "1.0 2"]:
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    split_version(version)
