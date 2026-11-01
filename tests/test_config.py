"""Check configuration validation and command line errors."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from apt_graph.cli import main
from apt_graph.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    """Exercise each user setting with valid and invalid input."""

    def setUp(self):
        """Create an isolated configuration and repository path."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        (self.base / "repo.json").write_text("{}", encoding="utf-8")
        self.path = self.base / "config.json"
        self.data = {
            "package": "A", "source": "repo.json", "test_mode": True,
            "version": "1", "output": "out/graph.svg", "max_depth": 3,
        }

    def write(self):
        """Write the current test settings."""
        self.path.write_text(json.dumps(self.data), encoding="utf-8")
        return self.path

    def test_valid_relative_paths(self):
        """Resolve file paths relative to the configuration location."""
        config = load_config(self.write())
        self.assertEqual(config.source, str(self.base / "repo.json"))
        self.assertEqual(config.output, self.base / "out/graph.svg")
        self.assertEqual(config.max_depth, 3)

    def test_invalid_settings(self):
        """Reject an invalid value for every setting."""
        invalid = {
            "package": ["", "a", 12],
            "source": ["missing.json", "", False],
            "test_mode": ["true", 1, None],
            "version": ["", "1 2", 1, "not-a-version!", "1:"],
            "output": ["graph.png", "", False],
            "max_depth": [-1, 1.5, True],
        }
        for field, values in invalid.items():
            original = self.data[field]
            for value in values:
                with self.subTest(field=field, value=value):
                    self.data[field] = value
                    with self.assertRaises(ConfigError):
                        load_config(self.write())
            self.data[field] = original

    def test_url_validation(self):
        """Require HTTP(S) index URLs with a valid host and port."""
        self.data.update(test_mode=False, package="libc6")
        invalid = ["file:///tmp/a", "https://", "https://a:bad/p"]
        for value in invalid:
            self.data["source"] = value
            with self.subTest(value=value), self.assertRaises(ConfigError):
                load_config(self.write())
        self.data["source"] = "https://example.org/Packages.xz"
        self.assertEqual(load_config(self.write()).package, "libc6")

    def test_invalid_json_and_structure(self):
        """Reject missing files, malformed JSON and wrong fields."""
        for text in ["{", "[]", "{}"]:
            self.path.write_text(text, encoding="utf-8")
            with self.subTest(text=text), self.assertRaises(ConfigError):
                load_config(self.path)
        with self.assertRaises(ConfigError):
            load_config(self.base / "absent.json")
        self.data["unknown"] = "x"
        with self.assertRaises(ConfigError):
            load_config(self.write())

    def test_cli_reports_configuration_error(self):
        """Return a failure code and readable stderr without a traceback."""
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            status = main(["--config", str(self.base / "missing.json")])
        self.assertEqual(status, 1)
        self.assertIn("Ошибка:", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())

    def test_malformed_paths_and_urls_have_no_traceback(self):
        """Convert path and URL parsing failures to ordinary CLI errors."""
        cases = [
            {"output": "bad\u0000.svg"},
            {"source": "bad\u0000.json"},
            {"test_mode": False, "package": "libc6",
             "source": "https://[bad/Packages"},
        ]
        for changes in cases:
            original = self.data.copy()
            self.data.update(changes)
            output = io.StringIO()
            with self.subTest(changes=changes):
                with contextlib.redirect_stderr(output):
                    status = main(["--config", str(self.write())])
                self.assertEqual(status, 1)
                self.assertNotIn("Traceback", output.getvalue())
            self.data = original


if __name__ == "__main__":
    unittest.main()
