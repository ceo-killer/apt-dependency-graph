"""Check diagram content, renderer failures and preservation of output."""

import json
import subprocess
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from apt_graph.graph import DependencyGraph, key
from apt_graph.visualize import RenderError, render_svg, to_d2

SVG = '<svg xmlns="http://www.w3.org/2000/svg"><text>A</text></svg>'
SHARED_GRAPH_SIZE = 3


@dataclass(frozen=True)
class Package:
    """Package label data independent of repository loading."""

    name: str
    version: str = "1"
    architecture: str = "all"


def make_graph(names=("A", "B", "C")):
    """Create shared dependencies and a back edge for rendering tests."""
    packages = [Package(name) for name in names]
    nodes = {key(package): package for package in packages}
    keys = list(nodes)
    edges = {node: [] for node in keys}
    if len(keys) == SHARED_GRAPH_SIZE:
        edges = {keys[0]: keys[1:], keys[1]: [keys[2]], keys[2]: [keys[0]]}
    return DependencyGraph(keys[0], nodes, edges)


def write_svg(command, **options):
    """Stand in for the external process while writing its actual target."""
    Path(command[-1]).write_text(SVG, encoding="utf-8")
    return subprocess.CompletedProcess(command, 0, "", "")


class D2Tests(unittest.TestCase):
    """Verify generated data without relying on visual layout choices."""

    def test_every_edge_is_present(self):
        """Shared and cyclic edges are retained in the D2 description."""
        source = to_d2(make_graph())
        edges = {line for line in source.splitlines() if " -> " in line}
        self.assertEqual(edges, {
            "n0 -> n1", "n0 -> n2", "n1 -> n2", "n2 -> n0",
        })
        self.assertTrue(source.startswith("direction: down\n"))

    def test_single_package_is_visible(self):
        """A graph without edges still declares its only package."""
        source = to_d2(make_graph(("A",)))
        self.assertIn('n0: "A\\n1 [all]"', source)
        self.assertNotIn(" -> ", source)

    def test_special_text_cannot_create_nodes_or_edges(self):
        """Names containing diagram syntax remain quoted label data."""
        name = 'A"\\\nnew: {label: "injected"}\nn0 -> stolen'
        source = to_d2(make_graph((name,)))
        declaration = source.splitlines()[2]
        label = json.loads(declaration.split(": ", 1)[1])
        self.assertEqual(label, f"{name}\n1 [all]")
        self.assertEqual(len(source.splitlines()), 4)

    def test_truncation_is_labelled(self):
        """The diagram makes a depth-limited frontier visible."""
        graph = make_graph(("A",))
        graph.truncated.add(graph.root)
        self.assertIn("[depth limit]", to_d2(graph))


class RenderTests(unittest.TestCase):
    """Check subprocess contracts and atomic replacement of SVG output."""

    def test_success_writes_source_and_valid_svg(self):
        """The renderer receives argument lists and creates nested output."""
        with TemporaryDirectory() as folder:
            output = Path(folder) / "nested" / "graph.svg"
            with patch("apt_graph.visualize.subprocess.run", write_svg):
                result = render_svg(make_graph(), output)
            self.assertEqual(result, output)
            self.assertEqual(output.read_text(encoding="utf-8"), SVG)
            self.assertEqual(output.with_suffix(".d2").read_text(),
                             to_d2(make_graph()))
            self.assertFalse(list(output.parent.glob(".d2-*")))

    def test_subprocess_has_timeout_and_no_shell(self):
        """Process arguments are separate values, even for spaced paths."""
        with TemporaryDirectory(prefix="graph space ") as folder:
            output = Path(folder) / "graph.svg"
            with patch("apt_graph.visualize.subprocess.run") as run:
                run.side_effect = write_svg
                render_svg(make_graph(), output)
            arguments, options = run.call_args
            self.assertEqual(arguments[0][:2], ["d2", "--layout=elk"])
            self.assertIsInstance(arguments[0], list)
            self.assertTrue(options["check"])
            self.assertIn("timeout", options)
            self.assertFalse(options.get("shell", False))

    def test_process_failures_preserve_old_svg(self):
        """Missing D2, timeout and nonzero exits leave the old file intact."""
        errors = [
            FileNotFoundError("d2"),
            subprocess.TimeoutExpired(["d2"], 60),
            subprocess.CalledProcessError(1, ["d2"], stderr="bad D2"),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                self.assert_old_output_survives(error)

    def assert_old_output_survives(self, error):
        """Exercise one renderer error with an existing destination file."""
        with TemporaryDirectory() as folder:
            output = Path(folder) / "graph.svg"
            output.write_text("old graph", encoding="utf-8")
            with patch("apt_graph.visualize.subprocess.run") as run:
                run.side_effect = error
                with self.assertRaises(RenderError):
                    render_svg(make_graph(), output)
            self.assertEqual(output.read_text(), "old graph")
            self.assertTrue(output.with_suffix(".d2").exists())
            self.assertFalse(list(output.parent.glob(".d2-*")))

    def test_invalid_output_preserves_old_svg(self):
        """A successful process exit is insufficient proof of valid SVG."""
        for content in ["<svg", "<html/>", "<svg/>"]:
            with self.subTest(content=content), TemporaryDirectory() as folder:
                output = Path(folder) / "graph.svg"
                output.write_text("old graph", encoding="utf-8")

                def invalid_svg(command, **options):
                    """Write malformed or wrong-format renderer output."""
                    Path(command[-1]).write_text(content, encoding="utf-8")

                with patch("apt_graph.visualize.subprocess.run", invalid_svg):
                    with self.assertRaises(RenderError):
                        render_svg(make_graph(), output)
                self.assertEqual(output.read_text(), "old graph")

    def test_missing_output_is_a_render_error(self):
        """The renderer must create the requested SVG file."""
        with TemporaryDirectory() as folder:
            with patch("apt_graph.visualize.subprocess.run"):
                with self.assertRaises(RenderError):
                    render_svg(make_graph(), Path(folder) / "graph.svg")

    def test_wrong_extension_is_rejected(self):
        """Avoid collisions between source and output paths."""
        with self.assertRaises(RenderError):
            render_svg(make_graph(), Path("graph.d2"))

    def test_unwritable_parent_is_a_render_error(self):
        """Filesystem errors are translated into readable application errors."""
        with TemporaryDirectory() as folder:
            parent = Path(folder) / "file"
            parent.write_text("not a directory", encoding="utf-8")
            with self.assertRaises(RenderError):
                render_svg(make_graph(), parent / "graph.svg")
