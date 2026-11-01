"""Counterexamples for repository rule checks."""

import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import check_rules


class RuleTests(unittest.TestCase):
    """Check that independent rule violations are detected."""

    def test_accepts_small_documented_function(self):
        """A small documented definition passes Python checks."""
        source = (
            '\"\"\"Example module.\"\"\"\n'
            'def add(left, right):\n'
            '    \"\"\"Add two values.\"\"\"\n'
            '    return left + right\n'
        )
        self.assertEqual(check_rules.python_issues("sample.py", source), [])

    def test_numeric_comparisons_are_strict(self):
        """Even zero must be named when used in a comparison."""
        source = '\"\"\"Example.\"\"\"\nresult = value > 0\n'
        problems = check_rules.python_issues("sample.py", source)
        self.assertTrue(any("M1" in item for item in problems))
        named = source.replace("0", "MINIMUM")
        self.assertEqual(check_rules.python_issues("sample.py", named), [])

    def test_signed_numeric_comparison(self):
        """A negative literal cannot evade the comparison check."""
        problems = check_rules.python_issues("sample.py", "result = x < -2")
        self.assertTrue(any("M1" in item for item in problems))

    def test_function_size_and_arguments(self):
        """Oversized functions and argument lists are detected together."""
        source = "def example(a, b, c, d, e, f, g, h):\n"
        source += '    \"\"\"Example.\"\"\"\n' + "    pass\n" * 41
        node = ast.parse(source).body[0]
        problems = check_rules.function_issues("sample.py", node)
        self.assertTrue(any("F1" in item for item in problems))
        self.assertTrue(any("A1" in item for item in problems))

    def test_complexity_includes_boolean_branches(self):
        """Boolean choices contribute to the decision count."""
        source = "def example():\n    return " + " or ".join(["x"] * 12)
        node = ast.parse(source).body[0]
        problems = check_rules.function_issues("sample.py", node)
        self.assertTrue(any("C1" in item for item in problems))

    def test_nested_function_has_separate_complexity(self):
        """A parent does not inherit decisions inside a nested function."""
        source = "def outer():\n    def inner():\n        return x or y\n"
        node = ast.parse(source).body[0]
        self.assertEqual(check_rules.complexity(node), 1)
        self.assertEqual(check_rules.complexity(node.body[0]), 2)

    def test_docstrings_names_and_semicolons(self):
        """Missing docs and nonstandard spelling have separate diagnostics."""
        source = "def BadName(BadArgument):\n    x = 1; return x\n"
        problems = check_rules.python_issues("sample.py", source)
        self.assertTrue(any("D1" in item for item in problems))
        self.assertTrue(any("N1" in item for item in problems))

    def test_syntax_error_is_reported(self):
        """Invalid Python produces a diagnostic without a traceback."""
        problems = check_rules.python_issues("sample.py", "def broken(:")
        self.assertTrue(any("P1" in item for item in problems))

    def test_file_and_line_limits(self):
        """The Python line limit and the general file limit both apply."""
        source = "x" * 81 + "\n" * 1001
        problems = check_rules.text_issues(Path("sample.py"), source)
        self.assertTrue(any("R1" in item for item in problems))
        self.assertTrue(any("R2" in item for item in problems))

    def test_generated_paths(self):
        """Build outputs, archives and editor settings are rejected."""
        for path in ("build/out.txt", "x.pyc", "x.tar.gz", ".idea/misc.xml"):
            with self.subTest(path=path):
                self.assertTrue(check_rules.forbidden(Path(path)))
        self.assertFalse(check_rules.forbidden(Path("tests/Packages")))

    def test_binary_detection(self):
        """Binary data is rejected even without a binary suffix."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").write_bytes(b"abc\x00def")
            problems = check_rules.file_issues(root, Path("data"))
        self.assertTrue(any("G1" in item for item in problems))

    def test_layout_and_commit_detection(self):
        """A missing layout and a nonconventional commit are reported."""
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(check_rules, "git_output") as output:
                output.side_effect = ["", "first version\n"]
                problems = check_rules.repository_issues(Path(directory))
        self.assertTrue(any("README.md" in item for item in problems))
        self.assertTrue(any("S6" in item for item in problems))

    def test_commit_subject_format(self):
        """Scoped conventional subjects pass while bare prose fails."""
        self.assertIsNotNone(
            check_rules.COMMIT_NAME.fullmatch("feat(graph): add DFS")
        )
        self.assertIsNone(check_rules.COMMIT_NAME.fullmatch("add DFS"))
