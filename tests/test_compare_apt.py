"""Checks for the isolated apt comparison and its output interpretation."""

import io
import tempfile
import unittest
from contextlib import redirect_stderr
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import MagicMock, patch

from apt_graph.repository import Repository
from tools import compare_apt

DOTTY = """digraph packages {
"root" -> "leaf";
"root" -> "early"[color=blue];
"root" -> "conflict"[color=springgreen];
"leaf" -> "beyond";
}
"""
INDEX = """Package: root
Version: 1
Depends: leaf

Package: leaf
Version: 1
"""


class ComparisonTests(unittest.TestCase):
    """Native apt output is evidence, never an application data source."""

    def setUp(self):
        """Use isolated temporary directories for all reference state."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)

    def test_dotty_relationships_and_depth(self):
        """Compare only expanded nodes and separate other relationships."""
        mandatory, other = compare_apt.dotty_edges(DOTTY, {"root"})
        self.assertEqual(mandatory, {("root", "leaf"), ("root", "early")})
        self.assertEqual(other, {("root", "conflict")})

    def test_dependency_alternatives(self):
        """The native listing declares all alternatives, not a chosen plan."""
        text = ("root\n  PreDepends: libc6\n |Depends: dpkg\n"
                "  Depends: install-info\n  Recommends: optional\n")
        self.assertEqual(compare_apt.dependency_names(text),
                         {"libc6", "dpkg", "install-info"})

    def test_download_and_unpack_orders_are_distinct(self):
        """URI plans and dpkg simulation have separate parsers."""
        uris = ("Reading package lists...\n"
                "'https://example.org/leaf.deb' leaf_1_amd64.deb 1 MD5:x\n"
                "'https://example.org/root.deb' root_1_amd64.deb 1 MD5:x\n")
        simulated = "Inst root (1)\nConf root (1)\nInst leaf (1)\n"
        self.assertEqual(compare_apt.download_order(uris), ["leaf", "root"])
        self.assertEqual(compare_apt.unpack_order(simulated), ["root", "leaf"])

    def test_state_is_private_and_empty(self):
        """Use the supplied index and an empty installed-package database."""
        compare_apt.prepare_state(self.folder, INDEX)
        self.assertEqual((self.folder / "status").read_text(), "")
        self.assertEqual(
            (self.folder / "lists" / compare_apt.LIST_NAME).read_text(), INDEX
        )
        options = compare_apt.apt_options(self.folder)
        settings = dict(option.split("=", 1) for option in options
                        if option != "-o")
        self.assertEqual(settings["Dir::State::status"],
                         str(self.folder / "status"))
        self.assertEqual(settings["Dir::Etc::sourceparts"], "-")
        self.assertEqual(settings["Dir::Etc::preferencesparts"], "-")
        self.assertEqual(settings["APT::Install-Recommends"], "false")

    def test_snapshot_is_downloaded_once(self):
        """Subsequent experiments reuse byte-identical cached metadata."""
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"snapshot"
        with patch.object(compare_apt, "urlopen",
                          return_value=response) as fetch:
            first = compare_apt.read_snapshot(self.folder)
            second = compare_apt.read_snapshot(self.folder)
        self.assertEqual(first, b"snapshot")
        self.assertEqual(first, second)
        fetch.assert_called_once()

    def test_reference_command_is_read_only(self):
        """The wrapper runs an explicit reference command with private paths."""
        completed = MagicMock(stdout="reference output")
        with patch.object(compare_apt.subprocess, "run",
                          return_value=completed):
            result = compare_apt.run_apt(
                self.folder, "apt-cache", "dotty", "root"
            )
        self.assertEqual(result, "reference output")

    def test_comparison_detects_additional_native_edges(self):
        """Report differences instead of asserting that graphs are equal."""
        repo = Repository.from_index(INDEX)
        outputs = [DOTTY, "root\n  Depends: leaf\n", "Inst leaf (1)\n", ""]
        with patch.object(compare_apt, "run_apt", side_effect=outputs):
            report = compare_apt.compare_package(
                repo, self.folder, self.folder, "root", 1
            )
        self.assertEqual(report["analyser_only"], [])
        self.assertEqual(report["apt_only"], [("root", "early")])
        self.assertEqual(report["order"], ["leaf", "root"])
        self.assertEqual(report["graph_nodes_outside_apt_downloads"],
                         ["leaf", "root"])
        self.assertTrue((self.folder / "root.dot").is_file())

    def test_main_reports_interrupted_http(self):
        """A partial HTTP response produces a controlled failure code."""
        response = MagicMock()
        response.__enter__.return_value.read.side_effect = IncompleteRead(b"x")
        errors = io.StringIO()
        with patch.object(compare_apt, "urlopen", return_value=response):
            with redirect_stderr(errors):
                result = compare_apt.main(["--workdir", str(self.folder)])
        self.assertEqual(result, 1)
        self.assertIn("Comparison failed:", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())
        self.assertFalse((self.folder / "Packages.xz").exists())

    def test_main_reports_corrupted_cached_snapshot(self):
        """A corrupt cached xz snapshot fails before running apt commands."""
        (self.folder / "Packages.xz").write_bytes(b"invalid xz data")
        errors = io.StringIO()
        with patch.object(compare_apt, "run_apt") as apt:
            with redirect_stderr(errors):
                result = compare_apt.main(["--workdir", str(self.folder)])
        self.assertEqual(result, 1)
        self.assertIn("Comparison failed:", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())
        apt.assert_not_called()
