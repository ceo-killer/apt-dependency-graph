"""Generate D2 diagrams and render checked SVG output."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
from xml.etree import ElementTree

if TYPE_CHECKING:
    from apt_graph.graph import DependencyGraph

RENDER_TIMEOUT = 60
ERROR_DETAIL_LIMIT = 400
SVG_ROOT = "{http://www.w3.org/2000/svg}svg"


class RenderError(ValueError):
    """Diagram rendering failed without replacing an existing SVG file."""


def _label(package, truncated):
    """Keep package text in labels, separate from D2 identifiers."""
    text = f"{package.name}\n{package.version} [{package.architecture}]"
    if truncated:
        text += "\n[depth limit]"
    return json.dumps(text, ensure_ascii=False)


def to_d2(graph: DependencyGraph) -> str:
    """Describe every package and edge, including leaves and cycles."""
    identifiers = {
        node: f"n{index}" for index, node in enumerate(graph.nodes)
    }
    lines = ["direction: down", ""]
    for node, package in graph.nodes.items():
        label = _label(package, node in graph.truncated)
        lines.append(f"{identifiers[node]}: {label}")
    lines.append("")
    for parent, children in graph.edges.items():
        for child in children:
            lines.append(f"{identifiers[parent]} -> {identifiers[child]}")
    return "\n".join(lines) + "\n"


def _run_d2(source: Path, target: Path):
    """Invoke the renderer directly, with a bounded execution time."""
    try:
        subprocess.run(
            ["d2", "--layout=elk", str(source), str(target)],
            check=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=RENDER_TIMEOUT,
        )
    except FileNotFoundError as error:
        message = "D2 is not installed or is absent from PATH"
        raise RenderError(message) from error
    except subprocess.TimeoutExpired as error:
        raise RenderError("D2 rendering timed out") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error)).strip()
        message = f"D2 failed: {detail[:ERROR_DETAIL_LIMIT]}"
        raise RenderError(message) from error


def _check_svg(path: Path):
    """Reject missing, malformed and non-SVG renderer output."""
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError) as error:
        raise RenderError("D2 did not produce a valid SVG file") from error
    if root.tag != SVG_ROOT:
        raise RenderError("D2 output is not an SVG document")


def render_svg(graph: DependencyGraph, output: Path) -> Path:
    """Write D2 source and atomically replace SVG only after validation."""
    output = Path(output)
    if output.suffix.lower() != ".svg":
        raise RenderError("Output filename must have the .svg extension")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        source = output.with_suffix(".d2")
        source.write_text(to_d2(graph), encoding="utf-8")
        with TemporaryDirectory(prefix=".d2-", dir=output.parent) as folder:
            temporary = Path(folder) / "graph.svg"
            _run_d2(source, temporary)
            _check_svg(temporary)
            temporary.replace(output)
    except OSError as error:
        raise RenderError(f"Cannot write diagram: {error}") from error
    return output
