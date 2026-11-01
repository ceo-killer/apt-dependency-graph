"""Exercise the complete command line flow using local repositories."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apt_graph.cli import main
from apt_graph.visualize import RenderError


class CliTests(unittest.TestCase):
    """Use real JSON files to test CLI integration and diagnostics."""

    def setUp(self):
        """Create an isolated repository and six-setting configuration."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.config = self.base / "config.json"
        self.settings = {
            "package": "A", "source": "repo.json", "test_mode": True,
            "version": "1", "output": "graph.svg", "max_depth": 3,
        }
        self.write_repository({"A": ["B"], "B": []})
        renderer = patch("apt_graph.cli.render_svg",
                         side_effect=self.fake_render)
        self.render = renderer.start()
        self.addCleanup(renderer.stop)

    def fake_render(self, graph, output):
        """Capture the real built graph without depending on installed D2."""
        self.graph = graph
        output.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>',
                          encoding="utf-8")
        return output

    def write_repository(self, edges):
        """Save a test graph in the documented JSON format."""
        packages = {
            name: {"version": "1", "dependencies": children}
            for name, children in edges.items()
        }
        (self.base / "repo.json").write_text(
            json.dumps({"packages": packages}), encoding="utf-8"
        )

    def invoke(self, extra=()):
        """Run the CLI and capture both output channels."""
        self.config.write_text(json.dumps(self.settings), encoding="utf-8")
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output):
            with contextlib.redirect_stderr(errors):
                status = main(["--config", str(self.config), *extra])
        return status, output.getvalue(), errors.getvalue()

    def test_successful_local_run(self):
        """Analyse a local repository without network access."""
        status, output, errors = self.invoke()
        self.assertEqual(status, 0)
        self.assertIn("graph.svg", output)
        self.assertTrue((self.base / "graph.svg").is_file())
        self.assertEqual(self.graph.edges["A@1:all"], ["B@1:all"])
        self.assertEqual(errors, "")

    def test_exact_root_version_is_required(self):
        """Reject unavailable versions instead of choosing the latest one."""
        self.settings["version"] = "2"
        status, output, errors = self.invoke()
        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertIn("A=2", errors)
        self.assertNotIn("Traceback", errors)

    def test_missing_root_has_a_readable_error(self):
        """Report a package absent from an otherwise valid repository."""
        self.settings["package"] = "Z"
        status, output, errors = self.invoke()
        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertIn("Z=1", errors)

    def test_depth_zero_only_contains_root(self):
        """Keep the root without revealing its dependencies at depth zero."""
        self.settings["max_depth"] = 0
        status, output, errors = self.invoke()
        self.assertEqual(status, 0)
        self.assertEqual(set(self.graph.nodes), {"A@1:all"})
        self.assertIn("graph.svg", output)
        self.assertIn("границе глубины", errors)

    def test_cycle_can_be_rendered(self):
        """A cycle is valid graph data and does not prevent visualization."""
        self.write_repository({"A": ["B"], "B": ["A"]})
        status, output, errors = self.invoke()
        self.assertEqual(status, 0)
        self.assertIn("graph.svg", output)
        self.assertEqual(self.graph.edges["A@1:all"], ["B@1:all"])
        self.assertEqual(self.graph.edges["B@1:all"], ["A@1:all"])
        self.assertEqual(errors, "")

    def test_renderer_error_has_a_readable_message(self):
        """Return a failure without claiming that an SVG was generated."""
        self.render.side_effect = RenderError("D2 is absent from PATH")
        status, output, errors = self.invoke()
        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertIn("D2", errors)
        self.assertNotIn("Traceback", errors)


if __name__ == "__main__":
    unittest.main()
