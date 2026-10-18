"""Unit and integration tests for Task B2 (ingestion, scrubbing, pseudonymization, loading)."""

import hashlib
import pytest
from brain_core.config import ModuleRule
from ingest.github_loader import resolve_module_path
from ingest.loaders import (
    derive_doc_id,
    derive_file_id,
    derive_module_id,
    derive_pr_id,
    load_github_data,
    prepare_load_data,
)
from ingest.pseudonymize import pseudonymize_login
from ingest.scrub import scan_for_logins, scan_for_pii, scrub_text


def test_pseudonymize_deterministic():
    salt = "test-salt-123"
    person_id1, display1 = pseudonymize_login("alice", salt)
    person_id2, display2 = pseudonymize_login("alice", salt)

    assert person_id1 == person_id2
    assert display1 == display2
    assert person_id1.startswith("p_")
    assert len(person_id1) == 10  # "p_" + 8 hex chars
    assert display1 == f"Contributor {person_id1[2:]}"

    # Different salt produces different pseudonym
    person_id3, _ = pseudonymize_login("alice", "another-salt")
    assert person_id1 != person_id3


def test_scrub_pii_rules():
    text = (
        "Merged PR by @alice touching feature.\n"
        "Contact me at alice@corp.internal or visit https://github.com/alice.\n"
        "Check PR at https://github.com/fastapi/fastapi/pull/100.\n"
        "Co-authored-by: Bob Builder <bob@corp.internal>\n"
        "Signed-off-by: Carol Signer <carol@corp.internal>\n"
        "Alice implemented this algorithm."
    )
    author_logins = {"alice", "bob"}
    scrubbed = scrub_text(text, author_logins=author_logins)

    # Emails scrubbed
    assert "alice@corp.internal" not in scrubbed
    assert "bob@corp.internal" not in scrubbed
    assert "[email]" in scrubbed

    # Mentions scrubbed
    assert "@alice" not in scrubbed
    assert "@contributor" in scrubbed

    # Profile URLs scrubbed, but PR URL preserved
    assert "https://github.com/alice" not in scrubbed
    assert "[profile]" in scrubbed
    assert "https://github.com/fastapi/fastapi/pull/100" in scrubbed

    # Git trailers deleted
    assert "Co-authored-by:" not in scrubbed
    assert "Signed-off-by:" not in scrubbed
    assert "Bob Builder" not in scrubbed
    assert "Carol Signer" not in scrubbed

    # Author logins replaced case-insensitively
    assert "Alice" not in scrubbed
    assert "contributor" in scrubbed


def test_pii_and_login_scanners():
    clean_text = "Contributor implemented this in [profile]. Contact [email]. Check @contributor notes."
    assert scan_for_pii(clean_text) == []
    assert scan_for_logins(clean_text, {"alice", "bob"}) == []

    dirty_text = "Email dev@company.com or ping @octocat."
    violations = scan_for_pii(dirty_text)
    assert len(violations) >= 2

    residual_login_text = "Code reviewed by octocat in production."
    login_violations = scan_for_logins(residual_login_text, {"octocat"})
    assert len(login_violations) == 1


def test_resolve_module_path_rules():
    rules = [
        ModuleRule(prefix="fastapi/", depth=1),
        ModuleRule(prefix="docs/en/docs/", depth=1),
        ModuleRule(prefix="tests/", depth=1),
    ]

    # Section 7 exact examples
    assert resolve_module_path("fastapi/dependencies/utils.py", rules) == "fastapi/dependencies"
    assert resolve_module_path("fastapi/routing.py", rules) == "fastapi"
    assert resolve_module_path("docs/en/docs/tutorial/body.md", rules) == "docs/en/docs/tutorial"
    assert resolve_module_path("tests/test_x.py", rules) == "tests"

    # Unmatched prefixes return None
    assert resolve_module_path("docs/es/docs/index.md", rules) is None
    assert resolve_module_path(".github/workflows/ci.yml", rules) is None


def test_derive_identifiers():
    assert derive_pr_id(42) == "pr_42"
    assert derive_module_id("fastapi/dependencies") == "m_fastapi_dependencies"
    assert derive_file_id("fastapi/routing.py").startswith("f_")
    assert derive_doc_id("README.md").startswith("d_")
    assert len(derive_file_id("fastapi/routing.py")) == 12  # "f_" + 10 chars
    assert len(derive_doc_id("README.md")) == 12  # "d_" + 10 chars


def test_prepare_load_data_fixtures():
    rules = [
        ModuleRule(prefix="fastapi/", depth=1),
        ModuleRule(prefix="tests/", depth=1),
    ]
    prs = [
        {
            "number": 101,
            "title": "Fix routing bug",
            "body_excerpt": "Fixed dependency resolution issue.",
            "created_at": 1700000000,
            "merged_at": 1700003600,
            "author_id": "p_a1b2c3d4",
            "url": "https://github.com/owner/repo/pull/101",
            "files": ["fastapi/routing.py", "tests/test_routing.py"],
        }
    ]
    docs = [
        {
            "path": "README.md",
            "title": "FastAPI Framework",
            "kind": "readme",
            "updated_at": 1700004000,
            "body": "# FastAPI\nHigh performance framework.",
            "url": "https://github.com/owner/repo/blob/master/README.md",
        }
    ]

    payload = prepare_load_data(prs, docs, rules)

    assert len(payload["persons"]) == 1
    assert payload["persons"][0]["id"] == "p_a1b2c3d4"
    assert payload["persons"][0]["display"] == "Contributor a1b2c3d4"

    assert len(payload["prs"]) == 1
    assert payload["prs"][0]["id"] == "pr_101"
    assert payload["prs"][0]["number"] == 101

    assert len(payload["modules"]) == 2
    mod_ids = {m["id"] for m in payload["modules"]}
    assert "m_fastapi" in mod_ids
    assert "m_tests" in mod_ids

    assert len(payload["files"]) == 2
    assert len(payload["docs"]) == 1
    assert payload["docs"][0]["id"] == derive_doc_id("README.md")

    # Verify edge connectivity
    assert len(payload["authored"]) == 1
    assert payload["authored"][0] == {"from_id": "p_a1b2c3d4", "to_id": "pr_101"}
    assert len(payload["touches"]) == 2
    assert len(payload["part_of"]) == 2


def test_load_github_data_live_scratch(test_graph):
    """Verify loading plain dict fixtures into FalkorDB and querying Q26/Q27."""
    rules = [ModuleRule(prefix="fastapi/", depth=1)]
    prs = [
        {
            "number": 200,
            "title": "Add telemetry",
            "body_excerpt": "Added telemetry metrics.",
            "created_at": 1700000000,
            "merged_at": 1700005000,
            "author_id": "p_99887766",
            "url": "https://github.com/owner/repo/pull/200",
            "files": ["fastapi/telemetry.py"],
        }
    ]
    docs = [
        {
            "path": "docs/architecture.md",
            "title": "System Architecture",
            "kind": "design",
            "updated_at": 1700006000,
            "body": "# Architecture\nOverview of the telemetry subsystem.",
            "url": "https://github.com/owner/repo/blob/master/docs/architecture.md",
        }
    ]

    payload = load_github_data(
        prs=prs,
        docs=docs,
        graph=test_graph,
        module_rules=rules,
        batch_size=10,
    )

    # Verify node counts via Cypher query directly on test_graph
    person_res = test_graph.query("MATCH (p:Person {id: 'p_99887766'}) RETURN p.display, p.source")
    assert person_res.result_set[0] == ["Contributor 99887766", "github"]

    pr_res = test_graph.query("MATCH (pr:PR {id: 'pr_200'}) RETURN pr.number, pr.state")
    assert pr_res.result_set[0] == [200, "merged"]

    edge_res = test_graph.query(
        "MATCH (p:Person {id: 'p_99887766'})-[:AUTHORED]->(pr:PR)-[:TOUCHES]->(f:File)-[:PART_OF]->(m:Module) "
        "RETURN m.id"
    )
    assert len(edge_res.result_set) == 1
    assert edge_res.result_set[0][0] == "m_fastapi"
