"""Offline checks of index reading, version selection and test graphs."""

import gzip
import json
import lzma
import tempfile
import unittest
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from apt_graph.repository import Repository, RepositoryError

INDEX = """Package: root
Version: 1.0
Architecture: amd64
Depends: missing | leaf (>= 1.9),
 virtual (>= 2)
Pre-Depends: early

Package: root
Version: 2.0
Architecture: amd64
Depends: leaf (<< 1.10)

Package: leaf
Version: 1.9
Architecture: amd64

Package: leaf
Version: 1.10
Architecture: amd64

Package: provider
Version: 9.0
Architecture: all
Provides: virtual (= 2)

Package: early
Version: 1.0
Architecture: amd64
"""


def repository(data: bytes = INDEX.encode()) -> Repository:
    """Build a repository through the same HTTP reader as a real index."""
    response = MagicMock()
    response.__enter__.return_value.read.return_value = data
    with patch("apt_graph.repository.urlopen", return_value=response):
        return Repository("https://example.org/Packages")


class RepositoryTests(unittest.TestCase):
    """Check direct dependencies without a live network or apt process."""

    def test_exact_root_and_newest_dependency(self):
        """The requested root version changes its resolved direct edges."""
        repo = repository()
        first = repo.dependencies(repo.get("root", "1.0"))
        self.assertEqual([item.name for item in first],
                         ["early", "leaf", "provider"])
        self.assertEqual(first[1].version, "1.10")
        second = repo.dependencies(repo.get("root", "2.0"))
        self.assertEqual(second[0].version, "1.9")
        self.assertEqual(repo.get("root").version, "2.0")
        with self.assertRaises(RepositoryError):
            repo.get("root", "3.0")
        with self.assertRaises(RepositoryError):
            repo.get("unknown")

    def test_compressed_indices(self):
        """Plain, gzip and xz input produce the same package identity."""
        for data in [INDEX.encode(), gzip.compress(INDEX.encode()),
                     lzma.compress(INDEX.encode())]:
            with self.subTest(size=len(data)):
                self.assertEqual(repository(data).get("root").version, "2.0")

    def test_virtual_versions(self):
        """An unversioned Provides cannot satisfy a versioned requirement."""
        unversioned = INDEX.replace("virtual (= 2)", "virtual")
        repo = repository(unversioned.encode())
        with self.assertRaises(RepositoryError):
            repo.dependencies(repo.get("root", "1.0"))
        self.assertEqual(len(repo.warnings), 1)
        plain = unversioned.replace("virtual (>= 2)", "virtual")
        repo = repository(plain.encode())
        self.assertEqual(repo.dependencies(repo.get("root", "1.0"))[-1].name,
                         "provider")

    def test_first_satisfiable_alternative(self):
        """Select one satisfiable alternative in metadata order."""
        data = INDEX.replace("missing | leaf (>= 1.9)", "early | leaf")
        repo = repository(data.encode())
        self.assertEqual([item.name for item in
                          repo.dependencies(repo.get("root", "1.0"))],
                         ["early", "provider"])

    def test_architecture_qualifiers(self):
        """Resolve native/any in this index and reject absent explicit arch."""
        for qualifier in ["any", "native", "amd64"]:
            data = INDEX.replace("leaf (<< 1.10)", f"leaf:{qualifier}")
            repo = repository(data.encode())
            self.assertEqual(repo.dependencies(repo.get("root", "2.0"))[0].name,
                             "leaf")
        data = INDEX.replace("leaf (<< 1.10)", "leaf:arm64")
        repo = repository(data.encode())
        with self.assertRaises(RepositoryError):
            repo.dependencies(repo.get("root", "2.0"))

    def test_bad_metadata(self):
        """Malformed, empty and truncated indices report readable errors."""
        inputs = [b"", b"not metadata", b" Depends: stray", b"\xff",
                  b"Package: root\n", b"Package: a\nPackage: b\n",
                  gzip.compress(INDEX.encode())[:-5],
                  lzma.compress(INDEX.encode())[:-5]]
        for data in inputs:
            with self.subTest(data=data[:25]):
                with self.assertRaises(RepositoryError):
                    repository(data)

    def test_network_failure(self):
        """An HTTP failure does not leak an urllib traceback to callers."""
        with patch("apt_graph.repository.urlopen", side_effect=URLError("404")):
            with self.assertRaisesRegex(RepositoryError, "загрузить"):
                Repository("https://example.org/Packages")
        with self.assertRaises(RepositoryError):
            Repository("file:///tmp/Packages")

    def test_interrupted_download(self):
        """A truncated HTTP response is converted to a repository error."""
        response = MagicMock()
        response.__enter__.return_value.read.side_effect = IncompleteRead(b"x")
        with patch("apt_graph.repository.urlopen", return_value=response):
            with self.assertRaisesRegex(RepositoryError, "загрузить"):
                Repository("https://example.org/Packages")


class TestRepositoryTests(unittest.TestCase):
    """Validate the file format used for offline graph demonstrations."""

    def setUp(self):
        """Give every case an isolated temporary repository file."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "graph.json"

    def load(self, packages):
        """Write a small graph and use the public test-mode constructor."""
        self.path.write_text(json.dumps({"packages": packages}),
                             encoding="utf-8")
        return Repository(str(self.path), test_mode=True)

    def test_test_graph(self):
        """Cycles are valid repository data and remain visible to traversal."""
        repo = self.load({
            "A": {"version": "1", "dependencies": ["B"]},
            "B": {"version": "1", "dependencies": ["A"]},
        })
        self.assertEqual(repo.dependencies(repo.get("A", "1"))[0].name, "B")
        self.assertEqual(repo.dependencies(repo.get("B", "1"))[0].name, "A")

    def test_invalid_test_nodes(self):
        """Reject missing references, bad names, fields and value types."""
        inputs = [
            {},
            {"a": {"version": "1", "dependencies": []}},
            {"A": {"version": "1", "dependencies": ["B"]}},
            {"A": {"version": 1, "dependencies": []}},
            {"A": {"version": "1", "dependencies": "B"}},
            {"A": {"version": "1", "dependencies": [1]}},
            {"A": {"version": "1", "dependencies": [], "extra": True}},
        ]
        for packages in inputs:
            with self.subTest(packages=packages):
                with self.assertRaises(RepositoryError):
                    self.load(packages)

    def test_bad_test_file(self):
        """Reject invalid JSON, its wrong root shape and a missing path."""
        for content in ["{", "[]", '{"packages": []}']:
            self.path.write_text(content, encoding="utf-8")
            with self.subTest(content=content):
                with self.assertRaises(RepositoryError):
                    Repository(str(self.path), test_mode=True)
        with self.assertRaises(RepositoryError):
            Repository(str(self.path.with_suffix(".missing")), test_mode=True)
