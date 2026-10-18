"""Test T1: Ingestion of tiny fixture snapshot into test graph.

Per ARCHITECTURE.md sections 17 and 19 (Test T1):
- Uses fixtures in backend/tests/fixtures/.
- Loads GitHub data via load_github_data.
- Loads synthetic data via load_synthetic_data.
- Derives edges via run_derive.
- Asserts exact node and edge counts in isolated test graph.
"""

import json
from pathlib import Path
import pytest

from brain_core import queries
from brain_core.config import ModuleRule
from ingest.derive import run_derive
from ingest.loaders import load_github_data, load_synthetic_data


@pytest.mark.usefixtures("test_graph")
def test_t1_tiny_fixture_ingest(test_graph):
    """Verify that a tiny fixture snapshot loads deterministically with expected node/edge counts."""
    fixtures_dir = Path(__file__).resolve().parent / "fixtures"

    prs_file = fixtures_dir / "prs.json"
    docs_file = fixtures_dir / "docs.json"
    repo_file = fixtures_dir / "repo.json"

    prs = json.loads(prs_file.read_text(encoding="utf-8"))
    docs = json.loads(docs_file.read_text(encoding="utf-8"))
    repo_info = json.loads(repo_file.read_text(encoding="utf-8"))

    rules = [
        ModuleRule(prefix="fastapi/", depth=1),
        ModuleRule(prefix="docs/en/docs/", depth=1),
        ModuleRule(prefix="tests/", depth=1),
    ]

    # 1. Load GitHub snapshot into test graph
    load_github_data(
        prs=prs,
        docs=docs,
        repo_info=repo_info,
        graph=test_graph,
        module_rules=rules,
        batch_size=10,
    )

    # Assert GitHub node counts
    node_res = test_graph.query(queries.Q26)
    node_counts = {row[0]: int(row[1]) for row in node_res.result_set}

    assert node_counts["Person"] == 2
    assert node_counts["PR"] == 2
    assert node_counts["File"] == 2
    assert node_counts["Module"] == 2  # m_fastapi, m_tests
    assert node_counts["Doc"] == 1
    assert node_counts["Meta"] == 1

    # Assert GitHub edge counts
    edge_res = test_graph.query(queries.Q27)
    edge_counts = {row[0]: int(row[1]) for row in edge_res.result_set}

    assert edge_counts["AUTHORED"] == 2
    assert edge_counts["TOUCHES"] == 3
    assert edge_counts["PART_OF"] == 2

    # 2. Load Synthetic fixtures into test graph
    teams_data = {
        "teams": [
            {"id": "t_platform", "display": "Platform"},
            {"id": "t_core", "display": "Core"},
        ],
        "members": [
            {"team_id": "t_platform", "person_id": "p_00000001"},
            {"team_id": "t_core", "person_id": "p_00000002"},
        ],
        "owns": [
            {"team_id": "t_platform", "module_id": "m_fastapi"},
            {"team_id": "t_core", "module_id": "m_tests"},
        ],
    }
    people_roles = [
        {"person_id": "p_00000001", "role": "Staff Engineer"},
        {"person_id": "p_00000002", "role": "Senior Backend Engineer"},
    ]
    decisions = [
        {
            "id": "dec_001",
            "display": "Standardize routing in fastapi",
            "summary": "Standardize routing handlers.",
            "rationale": "Improve maintainability.",
            "decided_at": 1699990000,
            "status": "active",
            "decided_by": "p_00000001",
            "affects": ["m_fastapi"],
            "implemented_by": ["pr_1"],
            "tracked_by": "tk_BRAIN-1",
            "discussed_in": "th_001",
            "superseded_by": None,
        }
    ]
    tickets = [
        {
            "id": "tk_BRAIN-1",
            "key": "BRAIN-1",
            "display": "[BRAIN-1] Standardize routing in fastapi",
            "status": "resolved",
            "created_at": 1699990000,
            "resolved_at": 1700000000,
            "description": "Implement routing standardization.",
            "assigned_to": "p_00000001",
            "resolved_by_pr": "pr_1",
        }
    ]
    threads = [
        {
            "id": "th_001",
            "display": "#eng-decisions: Routing architecture",
            "channel": "#eng-decisions",
            "started_at": 1699800000,
            "text": "Contributor 00000001: Let's standardize routing in fastapi.",
            "participants": ["p_00000001", "p_00000002"],
            "mentions": ["m_fastapi"],
        }
    ]

    load_synthetic_data(
        teams_data=teams_data,
        people_roles=people_roles,
        decisions=decisions,
        tickets=tickets,
        threads=threads,
        graph=test_graph,
        batch_size=10,
    )

    # Assert synthetic nodes added
    node_res2 = test_graph.query(queries.Q26)
    node_counts2 = {row[0]: int(row[1]) for row in node_res2.result_set}

    assert node_counts2["Team"] == 2
    assert node_counts2["Decision"] == 1
    assert node_counts2["Ticket"] == 1
    assert node_counts2["Thread"] == 1

    # Verify Person roles updated
    role_res = test_graph.query("MATCH (p:Person {id: 'p_00000001'}) RETURN p.role")
    assert role_res.result_set[0][0] == "Staff Engineer"

    # 3. Run Edge Derivations
    derive_res = run_derive(graph=test_graph, synthetic_threads=threads, batch_size=10)

    # Assert derived counts
    assert derive_res["doc_mentions"] >= 1
    assert derive_res["thread_mentions"] >= 1
    assert derive_res["documented_in"] == 1
    assert derive_res["collaborates_with"] == 2  # p1 -> p2 and p2 -> p1

    # Assert final edge counts in graph
    final_edge_res = test_graph.query(queries.Q27)
    final_edge_counts = {row[0]: int(row[1]) for row in final_edge_res.result_set}

    assert final_edge_counts["AUTHORED"] == 2
    assert final_edge_counts["TOUCHES"] == 3
    assert final_edge_counts["PART_OF"] == 2
    assert final_edge_counts["MEMBER_OF"] == 2
    assert final_edge_counts["OWNS"] == 2
    assert final_edge_counts["DECIDED_BY"] == 1
    assert final_edge_counts["AFFECTS"] == 1
    assert final_edge_counts["IMPLEMENTS"] == 1
    assert final_edge_counts["DISCUSSED_IN"] == 1
    assert final_edge_counts["TRACKED_BY"] == 1
    assert final_edge_counts["ASSIGNED_TO"] == 1
    assert final_edge_counts["RESOLVES"] == 1
    assert final_edge_counts["PARTICIPATED_IN"] == 2
    assert final_edge_counts["MENTIONS"] >= 2
    assert final_edge_counts["DOCUMENTED_IN"] == 1
    assert final_edge_counts["COLLABORATES_WITH"] == 2
