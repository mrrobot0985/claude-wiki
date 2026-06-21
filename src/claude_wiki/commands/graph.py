"""`claude-wiki graph` — report wiki link topology."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_wiki.config import ConfigManager
from claude_wiki.errors import RepoNotFoundError
from claude_wiki.graph_utils import KB_SUBDIRS, LinkGraph, build_link_graph


EXIT_OK = 0
EXIT_USAGE = 1


class _UnionFind:
    """Disjoint-set union/find for connected components."""

    def __init__(self, nodes: set[str]) -> None:
        self.parent: dict[str, str] = {node: node for node in nodes}

    def find(self, node: str) -> str:
        while self.parent[node] != node:
            self.parent[node] = self.parent[self.parent[node]]
            node = self.parent[node]
        return node

    def union(self, a: str, b: str) -> None:
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a != root_b:
            self.parent[root_b] = root_a


def register(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
    handlers: dict[str, Callable[[argparse.Namespace], int]],
) -> None:
    """Register the ``graph`` subcommand."""
    parser = subparsers.add_parser(
        "graph",
        help="Report the knowledge base link topology",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Repo root containing .claude-wiki.lock (default: auto-detect)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human text",
    )
    parser.add_argument(
        "--top",
        type=_parse_top,
        default=5,
        help="Number of hubs to list (default: 5)",
    )
    handlers["graph"] = _handle_graph


def _parse_top(value: str) -> int:
    """Parse a positive integer for ``--top``."""
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--top must be a positive integer, got '{value}'"
        ) from exc
    if n <= 0:
        raise argparse.ArgumentTypeError(f"--top must be a positive integer, got {n}")
    return n


def _handle_graph(args: argparse.Namespace) -> int:
    """Print link-topology report for the current repo."""
    detector = ConfigManager()
    start = args.path if args.path else Path.cwd()

    try:
        repo_root = detector.find_repo_root(start)
    except RepoNotFoundError:
        if args.json:
            print(json.dumps({"error": "Not in a git repository"}))
        else:
            print("Error: Not in a git repository.", file=sys.stderr)
        return EXIT_USAGE

    config = detector.load(repo_root)
    kb_root = detector.get_kb_root(repo_root, config)

    if not kb_root.exists():
        if args.json:
            print(
                json.dumps({"error": f"Knowledge base directory not found: {kb_root}"})
            )
        else:
            print(
                f"Error: Knowledge base directory not found: {kb_root}", file=sys.stderr
            )
        return EXIT_USAGE

    graph = build_link_graph(kb_root)
    report = _build_report(graph, repo_name=repo_root.name, top_n=args.top)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_human_report(report, top_n=args.top)

    return EXIT_OK


def _build_report(
    graph: LinkGraph, *, repo_name: str, top_n: int = 5
) -> dict[str, Any]:
    """Compute the topology report."""
    articles = len(graph.articles)
    by_subdir: dict[str, int] = {name: 0 for name in KB_SUBDIRS}
    for rel in graph.articles:
        subdir = rel.split("/", 1)[0]
        if subdir in by_subdir:
            by_subdir[subdir] += 1

    links = 0
    for rel, targets in graph.outbound.items():
        for target in targets:
            if target in graph.articles or f"{target}.md" in graph.articles:
                links += 1

    orphans = sorted(
        rel
        for rel in graph.articles
        if graph.inbound.get(rel.replace(".md", ""), 0) == 0
    )

    hub_targets: dict[str, int] = {}
    for rel in graph.articles:
        target_key = rel.replace(".md", "")
        inbound = graph.inbound.get(target_key, 0)
        if inbound > 0:
            hub_targets[target_key] = inbound

    sorted_hubs = sorted(hub_targets.items(), key=lambda item: (-item[1], item[0]))
    top_hubs = sorted_hubs[:top_n]
    hubs = [{"article": key, "inbound": count} for key, count in top_hubs]

    components = _compute_components(graph)

    return {
        "repo": repo_name,
        "articles": articles,
        "by_subdir": by_subdir,
        "links": links,
        "orphans": orphans,
        "hubs": hubs,
        "components": components,
    }


def _compute_components(graph: LinkGraph) -> dict[str, int]:
    """Return connected-component statistics for the undirected link graph."""
    nodes = set(graph.articles.keys())
    uf = _UnionFind(nodes)

    for rel, targets in graph.outbound.items():
        for target in targets:
            target_file = f"{target}.md"
            if target_file in graph.articles:
                uf.union(rel, target_file)

    component_sizes: dict[str, int] = {}
    for node in nodes:
        root = uf.find(node)
        component_sizes[root] = component_sizes.get(root, 0) + 1

    count = len(component_sizes)
    largest = max(component_sizes.values()) if component_sizes else 0
    return {"count": count, "largest": largest}


def _print_human_report(report: dict[str, Any], *, top_n: int = 5) -> None:
    """Emit a readable topology report."""
    repo = report["repo"]
    articles = report["articles"]
    by_subdir = report["by_subdir"]
    links = report["links"]
    orphans = report["orphans"]
    hubs = report["hubs"]
    components = report["components"]

    print(f"claude-wiki graph for {repo}\n")

    subdir_parts = [f"{by_subdir[name]} {name}" for name in KB_SUBDIRS]
    print(f"Articles: {articles} ({', '.join(subdir_parts)})")
    print(f"Links:    {links}")

    print(f"\nOrphans: {len(orphans)}")
    _print_truncated_list(orphans, indent="  ")

    print(f"\nHubs (top {top_n} by inbound links):")
    for hub in hubs:
        print(f"  {hub['article']} ({hub['inbound']} inbound)")

    print(
        f"\nComponents: {components['count']} connected, "
        f"largest size {components['largest']}"
    )


def _print_truncated_list(items: list[str], *, indent: str = "") -> None:
    """Print a list, truncating very long output."""
    if not items:
        print(f"{indent}(none)")
        return
    max_display = 20
    for item in items[:max_display]:
        print(f"{indent}{item}")
    if len(items) > max_display:
        print(f"{indent}...and {len(items) - max_display} more")
