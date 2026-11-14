"""Collapse graphify's code graph into the subsystem diagram shown in README.md.

graphify (github.com/Graphify-Labs/graphify) maps every function, class and import into a
graph of about 1,000 nodes. That graph is too dense to read as a picture, so this script
groups the nodes by subsystem and counts the cross-subsystem references. The result is a
Mermaid diagram, which GitHub renders inline. Only structural edges are counted: calls,
imports, uses, inherits and references. "contains" and docstring edges are left out.

    uv run python scripts/code_graph_overview.py docs/code-graph/graph.json --min-edges 10
"""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

# (id, title, path fragments). A fragment ending in "/" matches a folder; otherwise it
# must be the file name. Order matters: the first match wins.
GROUPS: list[tuple[str, str, tuple[str, ...]]] = [
    ("cli", "CLI scripts", ("scripts/",)),
    ("evals", "Eval harness & release gates", ("evals/",)),
    ("models", "Model calls via OpenRouter", ("models/",)),
    ("db", "Postgres + pgvector", ("db/", "migrations/")),
    (
        "ingest",
        "Ingest: fetch, parse, chunk",
        ("parsing/", "fetch.py", "ingest.py", "corpus_ingest.py", "chunking.py"),
    ),
    ("answer", "Retrieval & answering", ("pipeline.py", "answer.py", "search.py")),
    ("api", "API & replay", ("api.py", "contracts.py", "replay.py")),
    ("core", "Core types, seams & fakes", ("types.py", "protocols.py", "fakes.py", "config.py")),
]
STRUCTURAL = {
    "calls",
    "imports",
    "imports_from",
    "uses",
    "inherits",
    "references",
    "indirect_call",
    "indexes",
}


def group_of(source_file: str) -> str | None:
    for gid, _, fragments in GROUPS:
        for frag in fragments:
            if frag.endswith("/") and frag in source_file:
                return gid
            if source_file.endswith("/" + frag):
                return gid
    return None


def overview(graph: dict[str, Any], min_edges: int) -> str:
    files_of: dict[str, set[str]] = {gid: set() for gid, _, _ in GROUPS}
    nodes_of: Counter[str] = Counter()
    group_by_node: dict[str, str] = {}
    for node in graph["nodes"]:
        gid = group_of(node.get("source_file") or "")
        if gid:
            group_by_node[node["id"]] = gid
            files_of[gid].add(node["source_file"])
            nodes_of[gid] += 1
    weights: Counter[tuple[str, str]] = Counter()
    for edge in graph["links"]:
        a, b = group_by_node.get(edge["source"]), group_by_node.get(edge["target"])
        if a and b and a != b and edge["relation"] in STRUCTURAL:
            weights[(a, b)] += 1
    lines = ["flowchart LR"]
    for gid, title, _ in GROUPS:
        lines.append(f'    {gid}["{title}<br/>{len(files_of[gid])} files · {nodes_of[gid]} nodes"]')
    for (a, b), count in sorted(weights.items(), key=lambda kv: (-kv[1], kv)):
        if count >= min_edges:
            lines.append(f"    {a} -->|{count}| {b}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("graph", type=Path, help="graphify graph.json")
    parser.add_argument(
        "--min-edges",
        type=int,
        default=10,
        help="hide subsystem links with fewer references than this",
    )
    args = parser.parse_args()
    print(overview(json.loads(args.graph.read_text(encoding="utf-8")), args.min_edges))


if __name__ == "__main__":
    main()
