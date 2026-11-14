# Code graph

This folder holds the code knowledge graph that the main README's **Code map** section draws on. It was built with [graphify](https://github.com/Graphify-Labs/graphify) `graphifyy==0.9.108`.

| File | What it is |
|---|---|
| `graph.json` | The full graph: 964 nodes and 2,619 edges. Each edge is tagged `EXTRACTED` or `INFERRED`. |
| `graph.html` | An interactive, self-contained viewer. Open it in a browser. |
| `GRAPH_REPORT.md` | A summary: most-connected nodes, communities and surprising links. |

**Scope.** The graph covers application code, scripts and SQL. Prose, eval data, tests and generated output are excluded, so the graph shows the system's structure; `.graphifyignore` in the repo root sets this. The code was parsed with tree-sitter, so no model was used and no code left the machine. The community names were written by hand when the graph was built.

**To rebuild.** Install the pinned version and run graphify's skill in Claude Code:

```bash
uv tool install 'graphifyy[sql]==0.9.108' --with matplotlib --with scipy
graphify install                # registers the /graphify skill
# then, in Claude Code, from the repo root:  /graphify .
cp graphify-out/{graph.json,graph.html,GRAPH_REPORT.md} docs/code-graph/
uv run python scripts/code_graph_overview.py docs/code-graph/graph.json --min-edges 10
```

The last command prints the Mermaid diagram. Paste it over the one in the README. Then copy `graph.html` to the portfolio site as `assets/code-graph/multimodal-doc-rag.html`; the project card's "Explore the code graph" button opens that copy.

For a code-only change, `graphify update .` re-extracts the code without a full run.
