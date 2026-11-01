"""Run the real D2 CLI when available, including non-ASCII file paths."""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

from apt_graph.cli import main


@unittest.skipUnless(shutil.which("d2"), "D2 is not installed")
class NativeTests(unittest.TestCase):
    """Exercise native renderer invocation on each supported OS."""

    def test_unicode_paths_with_spaces(self):
        """Render real SVG with Cyrillic configuration and output paths."""
        with tempfile.TemporaryDirectory(prefix="граф с пробелами ") as folder:
            base = Path(folder)
            repo = {"packages": {"A": {"version": "1", "dependencies": []}}}
            (base / "репозиторий.json").write_text(
                json.dumps(repo), encoding="utf-8"
            )
            settings = {
                "package": "A", "version": "1", "test_mode": True,
                "source": "репозиторий.json", "output": "рисунок графа.svg",
                "max_depth": 3,
            }
            config = base / "настройки.json"
            config.write_text(json.dumps(settings), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                status = main(["--config", str(config)])
            self.assertEqual(status, 0)
            output = base / "рисунок графа.svg"
            root = ElementTree.parse(output).getroot()
            self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
            self.assertTrue(output.with_suffix(".d2").is_file())
