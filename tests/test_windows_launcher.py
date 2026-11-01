"""Check real cmd launch behavior, including nonfunctional Python aliases."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = "nt"


@unittest.skipUnless(os.name == WINDOWS, "Windows cmd is required")
class WindowsLauncherTests(unittest.TestCase):
    """Exercise the launcher with controlled commands and broken aliases."""

    def setUp(self):
        """Create a spaced project path and private command search path."""
        directory = tempfile.TemporaryDirectory(prefix="launcher space ")
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        shutil.copyfile(ROOT / "run.bat", self.base / "run.bat")
        self.commands = self.base / "commands"
        self.commands.mkdir()
        self.write_command("py", "@echo off\necho Python\n")
        self.write_command("python", "@echo off\necho Python\n")

    def write_command(self, name, content):
        """Create an ASCII command stub in the isolated search path."""
        (self.commands / f"{name}.cmd").write_text(content, encoding="utf-8")

    def invoke(self):
        """Run the actual batch file without seeing other Python commands."""
        environment = dict(os.environ, PATH=str(self.commands))
        return subprocess.run(
            [os.environ["COMSPEC"], "/d", "/c", "run.bat", "--config",
             "a file with spaces.json"], cwd=self.base, env=environment,
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=30,
        )

    def test_alias_is_not_accepted_as_python(self):
        """An alias printing Python must fail instead of pretending success."""
        result = self.invoke()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Python 3.10+ was not found", result.stderr)

    def test_real_python_fallback_preserves_arguments(self):
        """Use real Python when py is an alias and preserve spaced arguments."""
        self.write_command("python", f'@echo off\n"{sys.executable}" %*\n')
        package = self.base / "src" / "apt_graph"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "__main__.py").write_text(
            "import json, sys\nprint(json.dumps(sys.argv[1:]))\n",
            encoding="utf-8",
        )
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('["--config", "a file with spaces.json"]', result.stdout)
