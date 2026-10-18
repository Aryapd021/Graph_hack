"""Documentation generator for Cypher queries and graph algorithms.

Per ARCHITECTURE.md sections 4, 9, 20:
- Reads queries and descriptions from backend/brain_core/queries.py.
- Writes docs/queries.md with formatted tables, descriptions, and Cypher code blocks.
- Documents the PageRank collaboration algorithm per section 20 submission checklist.
"""

import sys
from pathlib import Path

# Add backend directory to sys.path so queries can be imported
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import brain_core.queries as q_mod


def generate_queries_doc() -> str:
    """Generate Markdown documentation for all registered queries and PageRank."""
    lines = [
        "# Cypher Queries and Graph Algorithms Registry",
        "",
        "> *Note: This file is GENERATED automatically by `scripts/gen_queries_doc.py`. Do not hand-edit.*",
        "",
        "## Summary Table",
        "",
        "| ID | Description |",
        "|---|---|",
    ]

    # Sort queries logically by ID
    query_items = sorted(q_mod.QUERY_DOCS.items())

    for qid, desc in query_items:
        lines.append(f"| [`{qid}`](#{qid.lower()}) | {desc} |")

    lines.append("")
    lines.append("## Query Definitions")
    lines.append("")

    for qid, desc in query_items:
        cypher_text = getattr(q_mod, qid, "").strip()
        lines.append(f"### {qid}")
        lines.append("")
        lines.append(f"**Description:** {desc}")
        lines.append("")
        lines.append("```cypher")
        lines.append(cypher_text)
        lines.append("```")
        lines.append("")

    # PageRank documentation section required by Section 20 checklist
    lines.extend(
        [
            "## Graph Algorithms: PageRank Centrality",
            "",
            "Company Brain utilizes FalkorDB's native high-performance matrix algorithms to calculate contributor influence across the codebase collaboration graph.",
            "",
            "### Procedure Signature",
            "",
            "```cypher",
            "CALL algo.pageRank('Person', 'COLLABORATES_WITH') YIELD node, score",
            "RETURN node.id AS id, node.display AS display, score",
            "ORDER BY score DESC LIMIT $limit",
            "```",
            "",
            "### Algorithm Mechanics",
            "- **Target Graph:** Subgraph composed of `Person` nodes linked by bidirectional `COLLABORATES_WITH` relationships (derived in `Q16` based on shared module authorship).",
            "- **Convergence:** Evaluates relative prestige/centrality across the network. Contributor scores reflect not merely PR volume, but the degree to which a contributor bridges different engineering groups and architectural domains.",
            "- **Usage:** Powers the `key_connectors` tool and REST service to identify central domain experts and prevent institutional knowledge silos.",
            "",
        ]
    )

    return "\n".join(lines)


def main() -> None:
    """Generate and write docs/queries.md."""
    doc_content = generate_queries_doc()
    output_path = Path(__file__).resolve().parent.parent / "docs" / "queries.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(doc_content, encoding="utf-8")
    print(f"Successfully generated {output_path}")


if __name__ == "__main__":
    main()
