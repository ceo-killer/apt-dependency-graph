"""Compare the analyser with apt using an isolated, empty package state."""

import argparse
import hashlib
import json
import lzma
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

from apt_graph.graph import build_graph
from apt_graph.order import CycleError, dependency_order
from apt_graph.repository import Repository

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ("https://archive.ubuntu.com/ubuntu/dists/noble/main/"
          "binary-amd64/Packages.xz")
LIST_NAME = "archive.ubuntu.com_ubuntu_dists_noble_main_binary-amd64_Packages"
SOURCE_LINE = (
    "deb [trusted=yes arch=amd64] "
    "https://archive.ubuntu.com/ubuntu noble main\n"
)
EDGE = re.compile(r'^"([^"\n]+)" -> "([^"\n]+)"(?:\[([^\]]*)\])?;$')
DEPENDENCY = re.compile(r"^\s*\|?(?:PreDepends|Depends):\s*<?([^>\s]+)>?")
ROOT_DEPTH = 0


def read_snapshot(folder: Path) -> bytes:
    """Keep one downloaded index so both implementations use the same bytes."""
    folder.mkdir(parents=True, exist_ok=True)
    cached = folder / "Packages.xz"
    if not cached.exists():
        with urlopen(SOURCE, timeout=30) as response:
            cached.write_bytes(response.read())
    return cached.read_bytes()


def prepare_state(folder: Path, text: str) -> None:
    """Create apt's private lists, cache and empty installed-package file."""
    for directory in ["lists/partial", "archives/partial", "log"]:
        (folder / directory).mkdir(parents=True, exist_ok=True)
    (folder / "status").write_text("", encoding="utf-8")
    (folder / "sources.list").write_text(SOURCE_LINE, encoding="utf-8")
    (folder / "lists" / LIST_NAME).write_text(text, encoding="utf-8")


def apt_options(folder: Path) -> list[str]:
    """Redirect all relevant apt state and source paths away from the host."""
    settings = {
        "Dir::State": folder,
        "Dir::State::lists": folder / "lists",
        "Dir::State::status": folder / "status",
        "Dir::State::extended_states": folder / "extended_states",
        "Dir::Etc::sourcelist": folder / "sources.list",
        "Dir::Etc::sourceparts": "-",
        "Dir::Etc::main": "-",
        "Dir::Etc::parts": "-",
        "Dir::Etc::preferences": "-",
        "Dir::Etc::preferencesparts": "-",
        "Dir::Cache": folder,
        "Dir::Cache::pkgcache": folder / "pkgcache.bin",
        "Dir::Cache::srcpkgcache": folder / "srcpkgcache.bin",
        "Dir::Cache::archives": folder / "archives",
        "Dir::Log": folder / "log",
        "APT::Architecture": "amd64",
        "APT::Install-Recommends": "false",
        "APT::Install-Suggests": "false",
        "Debug::NoLocking": "true",
    }
    return [item for name, value in settings.items()
            for item in ("-o", f"{name}={value}")]


def run_apt(folder: Path, program: str, *arguments: str) -> str:
    """Run a read-only reference command with consistent English output."""
    environment = dict(os.environ, LC_ALL="C")
    result = subprocess.run(
        [program, *apt_options(folder), *arguments], check=True,
        capture_output=True, text=True, timeout=60, env=environment,
    )
    return result.stdout


def dotty_edges(text: str, sources: set[str]) -> tuple[set, set]:
    """Separate mandatory edges from dotty's additional relationships."""
    mandatory, other = set(), set()
    for line in text.splitlines():
        match = EDGE.fullmatch(line.strip())
        if not match or match[1] not in sources:
            continue
        edge = (match[1], match[2])
        if not match[3] or "color=blue" in match[3]:
            mandatory.add(edge)
        else:
            other.add(edge)
    return mandatory, other


def dependency_names(text: str) -> set[str]:
    """Extract mandatory declared names from apt-cache depends output."""
    return {match[1] for line in text.splitlines()
            if (match := DEPENDENCY.match(line))}


def graph_edges(graph) -> set[tuple[str, str]]:
    """Convert versioned graph identities to names for apt-dotty comparison."""
    return {(graph.nodes[parent].name, graph.nodes[child].name)
            for parent, children in graph.edges.items() for child in children}


def download_order(text: str) -> list[str]:
    """Read the planned URI listing; this does not measure network timing."""
    return [shlex.split(line)[1].split("_", 1)[0]
            for line in text.splitlines() if line.startswith("'")]


def unpack_order(text: str) -> list[str]:
    """Extract dpkg unpack operations, keeping them separate from downloads."""
    return [line.split()[1] for line in text.splitlines()
            if line.startswith("Inst ")]


def order_result(graph) -> dict:
    """Record a valid visible-graph order or an actual dependency cycle."""
    try:
        return {"order": [graph.nodes[key].name
                          for key in dependency_order(graph)]}
    except CycleError as error:
        return {"cycle": [graph.nodes[key].name for key in error.cycle]}


def compare_package(repo, folder, output, name, depth):
    """Save native output and report differences for one exact root version."""
    root = repo.get(name)
    graph = build_graph(repo, root, depth)
    dotty = run_apt(folder, "apt-cache", "dotty", name)
    direct = run_apt(folder, "apt-cache", "depends", "--important",
                     f"{name}={root.version}")
    simulation = run_apt(folder, "apt-get", "-s", "--no-install-recommends",
                         "install", f"{name}={root.version}")
    uris = run_apt(folder, "apt-get", "--print-uris", "--download-only",
                   "--yes", "--no-install-recommends", "install",
                   f"{name}={root.version}")
    for suffix, text in [("dot", dotty), ("depends.txt", direct),
                         ("simulation.txt", simulation), ("uris.txt", uris)]:
        (output / f"{name}.{suffix}").write_text(text, encoding="utf-8")
    expanded = {graph.nodes[key].name for key in graph.nodes
                if key not in graph.truncated}
    mandatory, other = dotty_edges(dotty, expanded)
    actual = graph_edges(graph)
    return {
        "package": name, "version": root.version, "depth": depth,
        "nodes": len(graph.nodes), "edges": len(actual),
        "direct_analyser": sorted(item.name
                                  for item in repo.dependencies(root)),
        "direct_apt_declared": sorted(dependency_names(direct)),
        "analyser_only": sorted(actual - mandatory),
        "apt_only": sorted(mandatory - actual),
        "apt_additional_relations": len(other),
        "apt_planned_download_order": download_order(uris),
        "apt_simulated_unpack_order": unpack_order(simulation),
        "apt_downloads_outside_graph": sorted(
            set(download_order(uris))
            - {item.name for item in graph.nodes.values()}
        ),
        **order_result(graph),
    }


def arguments(argv=None):
    """Read paths, graph depth and the packages selected for comparison."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", nargs="*",
                        default=["hello", "make", "gzip"])
    parser.add_argument("--workdir", type=Path,
                        default=ROOT / ".cache/apt-reference")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "output/comparison")
    parser.add_argument("--depth", type=int, default=3)
    settings = parser.parse_args(argv)
    if settings.depth < ROOT_DEPTH:
        parser.error("depth must be non-negative")
    return settings


def main(argv=None) -> int:
    """Run an isolated experiment; apt is only an external comparison tool."""
    settings = arguments(argv)
    folder, output = settings.workdir.resolve(), settings.output.resolve()
    try:
        data = read_snapshot(folder)
        text = lzma.decompress(data).decode("utf-8")
        prepare_state(folder, text)
        repo = Repository.from_index(text)
        output.mkdir(parents=True, exist_ok=True)
        reports = [compare_package(repo, folder, output, name, settings.depth)
                   for name in settings.packages]
        version = run_apt(folder, "apt-cache", "--version").strip()
        report = {"source": SOURCE, "sha256": hashlib.sha256(data).hexdigest(),
                  "apt_version": version,
                  "packages": reports}
        formatted = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        (output / "report.json").write_text(formatted, encoding="utf-8")
        print(formatted, end="")
    except (OSError, ValueError, lzma.LZMAError,
            subprocess.SubprocessError) as error:
        print(f"Comparison failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
