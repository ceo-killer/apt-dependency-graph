"""Check repository rules; complexity uses conservative AST branch counting.

Counts if/loops/except/conditional expressions, boolean operators, asserts,
comprehension loops and filters, and non-default match cases. Name checks
cover definitions, arguments and assigned names, not every PEP8 convention.
"""

import ast
import re
import subprocess
import sys
import tokenize
from io import StringIO
from pathlib import Path

MAX_FILE_LINES = 1000
MAX_PYTHON_LINE = 80
MAX_CODE_LINE = 120
MAX_FUNCTION_LINES = 40
MAX_ARGUMENTS = 7
MAX_COMPLEXITY = 10
BASE_COMPLEXITY = 1
FIRST_LINE = 1
EMPTY_COUNT = 0
REQUIRED = ("README.md", ".gitignore", "src", "tests")
LAUNCHERS = ("Makefile", "run.sh", "run.bat")
SNAKE_NAME = re.compile(r"(?:_*[a-z][a-z0-9_]*|_+)$")
CONSTANT_NAME = re.compile(r"_*[A-Z][A-Z0-9_]*$")
CLASS_NAME = re.compile(r"_*[A-Z][a-zA-Z0-9]*$")
INHERITED_NAMES = {"setUp", "tearDown", "setUpClass", "tearDownClass"}
COMMIT_NAME = re.compile(
    r"(?:feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(?:\([a-z0-9_.-]+\))?!?: .+"
)
FORBIDDEN_PARTS = {
    "__pycache__", ".venv", "venv", ".idea", ".vscode", "build", "dist",
    "node_modules", ".pytest_cache", ".mypy_cache", ".ruff_cache",
}
FORBIDDEN_SUFFIXES = {
    ".zip", ".gz", ".bz2", ".xz", ".tar", ".7z", ".rar", ".pyc", ".pyo",
    ".exe", ".dll", ".so", ".o", ".a", ".class", ".jar", ".whl", ".pdf",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".db", ".sqlite",
}
CODE_SUFFIXES = {
    ".py", ".sh", ".bat", ".json", ".yml", ".yaml", ".toml", ".js",
    ".ts", ".rs", ".go", ".java", ".c", ".h", ".cpp", ".cs", ".kt",
}
BRANCH_NODES = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
    ast.IfExp, ast.Assert,
)
FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def issue(path, line, code, message):
    """Format one location and diagnostic."""
    return f"{path}:{line}: {code} {message}"


def complexity(node):
    """Count decisions without including nested function/class bodies."""
    score = BASE_COMPLEXITY
    pending = list(ast.iter_child_nodes(node))
    while pending:
        child = pending.pop()
        if isinstance(child, FUNCTION_NODES + (ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(child, BRANCH_NODES):
            score += BASE_COMPLEXITY
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - BASE_COMPLEXITY
        elif isinstance(child, ast.comprehension):
            score += BASE_COMPLEXITY + len(child.ifs)
        elif isinstance(child, ast.Match):
            score += sum(not is_default(case) for case in child.cases)
        pending.extend(ast.iter_child_nodes(child))
    return score


def is_default(case):
    """Recognize an unguarded match wildcard as a default branch."""
    pattern = case.pattern
    return (
        isinstance(pattern, ast.MatchAs)
        and pattern.pattern is None
        and case.guard is None
    )


def argument_count(node):
    """Count positional, keyword-only and variable arguments."""
    args = node.args
    return (
        len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)
        + bool(args.vararg) + bool(args.kwarg)
    )


def function_issues(path, node):
    """Check function size, argument count and decision count."""
    first = min([node.lineno] + [d.lineno for d in node.decorator_list])
    measurements = (
        (node.end_lineno - first + FIRST_LINE, MAX_FUNCTION_LINES, "F1",
         "function lines"),
        (argument_count(node), MAX_ARGUMENTS, "A1", "arguments"),
        (complexity(node), MAX_COMPLEXITY, "C1", "complexity"),
    )
    return [
        issue(path, node.lineno, code, f"{label}: {actual} > {limit}")
        for actual, limit, code, label in measurements if actual > limit
    ]


def valid_name(node):
    """Check basic PEP8 forms, allowing inherited unittest methods."""
    if isinstance(node, ast.ClassDef):
        return bool(CLASS_NAME.fullmatch(node.name))
    if isinstance(node, FUNCTION_NODES):
        return bool(
            SNAKE_NAME.fullmatch(node.name) or node.name in INHERITED_NAMES
        )
    name = node.arg if isinstance(node, ast.arg) else node.id
    return bool(SNAKE_NAME.fullmatch(name) or CONSTANT_NAME.fullmatch(name))


def has_numeric_literal(node):
    """Detect a direct numeric operand, including a signed literal."""
    if isinstance(node, ast.UnaryOp):
        node = node.operand
    return (
        isinstance(node, ast.Constant)
        and type(node.value) in (int, float, complex)
    )


def node_issues(path, node):
    """Check one definition, name or comparison."""
    problems = []
    if isinstance(node, FUNCTION_NODES):
        problems.extend(function_issues(path, node))
    if isinstance(node, FUNCTION_NODES + (ast.ClassDef,)):
        if not ast.get_docstring(node):
            problems.append(issue(path, node.lineno, "D1", "no docstring"))
    if needs_name_check(node) and not valid_name(node):
        problems.append(issue(path, node.lineno, "N1", "name is not PEP8"))
    if isinstance(node, ast.Compare):
        operands = [node.left] + node.comparators
        if any(has_numeric_literal(item) for item in operands):
            problems.append(issue(path, node.lineno, "M1", "numeric literal"))
    return problems


def needs_name_check(node):
    """Select names whose spelling can be checked without type inference."""
    if isinstance(node, FUNCTION_NODES + (ast.ClassDef, ast.arg)):
        return True
    return isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)


def token_issues(path, source):
    """Check tab indentation and multiple statements separated by semicolons."""
    problems = []
    try:
        tokens = tokenize.generate_tokens(StringIO(source).readline)
        for token in tokens:
            tab = token.type == tokenize.INDENT and "\t" in token.string
            semicolon = token.type == tokenize.OP and token.string == ";"
            if tab or semicolon:
                problems.append(issue(path, token.start[0], "N1", "style"))
    except (tokenize.TokenError, IndentationError) as error:
        problems.append(issue(path, FIRST_LINE, "P1", str(error)))
    return problems


def python_issues(path, source):
    """Check syntax, docstrings, definitions, names and comparisons."""
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        return [issue(path, error.lineno, "P1", error.msg)]
    problems = token_issues(path, source)
    if not ast.get_docstring(tree):
        problems.append(issue(path, FIRST_LINE, "D1", "no module docstring"))
    for node in ast.walk(tree):
        problems.extend(node_issues(path, node))
    return problems


def text_issues(path, source):
    """Apply file and source line limits."""
    lines = source.splitlines()
    problems = []
    if len(lines) > MAX_FILE_LINES:
        message = "file exceeds 1000 lines"
        problems.append(issue(path, FIRST_LINE, "R1", message))
    limit = MAX_PYTHON_LINE if path.suffix == ".py" else MAX_CODE_LINE
    if path.suffix in CODE_SUFFIXES or path.name == "Makefile":
        for number, line in enumerate(lines, FIRST_LINE):
            if len(line) > limit:
                message = f"line length {len(line)} > {limit}"
                problems.append(issue(path, number, "R2", message))
    return problems


def forbidden(path):
    """Recognize generated, binary, archive and editor paths."""
    return (
        bool(set(path.parts) & FORBIDDEN_PARTS)
        or path.suffix.lower() in FORBIDDEN_SUFFIXES
        or any(part.endswith(".egg-info") for part in path.parts)
        or path.name in {".DS_Store", "Thumbs.db"}
    )


def file_issues(root, path):
    """Inspect a nonignored repository file without following symlinks."""
    if forbidden(path):
        return [issue(path, FIRST_LINE, "G1", "generated or binary file")]
    full_path = root / path
    if full_path.is_symlink():
        return [issue(path, FIRST_LINE, "G1", "symlink requires review")]
    try:
        source = full_path.read_text(encoding="utf-8")
    except (UnicodeError, OSError) as error:
        return [issue(path, FIRST_LINE, "G1", str(error))]
    if "\x00" in source:
        return [issue(path, FIRST_LINE, "G1", "binary data")]
    problems = text_issues(path, source)
    if path.suffix == ".py":
        problems.extend(python_issues(path, source))
    return problems


def git_output(root, arguments):
    """Run a read-only Git command and return its output."""
    result = subprocess.run(
        ["git", "-C", str(root), *arguments], check=False,
        capture_output=True, text=True,
    )
    return result.stdout if result.returncode == EMPTY_COUNT else ""


def repository_issues(root):
    """Check layout, nonignored files and existing commit subjects."""
    problems = [
        f"{name}: S1 required path is missing"
        for name in REQUIRED if not (root / name).exists()
    ]
    if not any((root / name).is_file() for name in LAUNCHERS):
        problems.append("S5 missing Makefile, run.sh or run.bat")
    paths = git_output(root, ["ls-files", "-cz", "--others",
                              "--exclude-standard"])
    if not paths:
        problems.append("S1 no repository files found")
    for name in sorted(set(paths.split("\0")) - {""}):
        problems.extend(file_issues(root, Path(name)))
    for subject in git_output(root, ["log", "--format=%s"]).splitlines():
        if not COMMIT_NAME.fullmatch(subject):
            problems.append(f"S6 invalid commit subject: {subject}")
    return problems


def main():
    """Print diagnostics and return a nonzero status on violations."""
    root = Path(__file__).resolve().parents[1]
    problems = repository_issues(root)
    if problems:
        print("\n".join(problems))
        return 1
    print("Repository rules: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
