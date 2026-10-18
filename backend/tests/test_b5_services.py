"""Tests for B5: services layer, T2, T3, and search_sanity.

Per ARCHITECTURE.md sections 9, 10, 11, 13, 14, 17, 19:
- T2: Q09 + classify equals ground_truth.json for every decision.
- T3: simulate_pr flips exactly the decisions whose affected modules match; reset_demo restores T2.
- search_sanity: for 3 loaded Docs, search by the Doc's own title; the Doc appears in top 3 hits.
  (skips with clear marker if GEMINI_API_KEY is unset/dummy).
"""

import json
import os
from pathlib import Path
import pytest

from brain_core.config import Settings, get_settings
from brain_core.db import get_graph
from brain_core.embeddings import embed_documents
from brain_core.freshness import classify
from brain_core.services import (
    check_freshness,
    connection_path,
    counts,
    flag_for_review,
    get_decision,
    graph_overview,
    key_connectors,
    list_decisions,
    list_modules,
    list_reviews,
    list_stale_decisions,
    neighborhood,
    node_detail,
    recent_changes,
    reset_demo,
    search_knowledge,
    simulate_pr,
    trace_decision,
    who_knows,
    who_owns,
)
from ingest.derive import run_derive
from ingest.loaders import load_from_cache, load_synthetic_from_files


@pytest.fixture(scope="module")
def populated_test_graph():
    """Populate test graph with cached GitHub and synthetic dataset for B5 integration testing."""
    g = get_graph()
    try:
        g.delete()
    except Exception:
        pass

    repo_root = Path(__file__).resolve().parent.parent.parent
    cache_dir = repo_root / "data" / "cache" / "github"
    synth_dir = repo_root / "data" / "synthetic"

    load_from_cache(cache_dir=cache_dir, graph=g)
    load_synthetic_from_files(synthetic_dir=synth_dir, graph=g)
    run_derive(synthetic_dir=synth_dir, graph=g)

    yield g

    try:
        g.delete()
    except Exception:
        pass


def test_t2_ground_truth_decision_freshness(populated_test_graph):
    """Test T2: Q09 + classify equals ground_truth.json for every decision."""
    g = populated_test_graph
    repo_root = Path(__file__).resolve().parent.parent.parent
    gt_file = repo_root / "data" / "synthetic" / "ground_truth.json"
    gt_data = json.loads(gt_file.read_text(encoding="utf-8"))

    gt_threshold = gt_data["threshold"]
    gt_decisions = {d["id"]: d for d in gt_data["decisions"]}

    # Evaluate decisions using list_decisions service with the ground truth threshold
    test_settings = Settings(STALE_PR_THRESHOLD=gt_threshold)
    decisions = list_decisions(graph=g, settings=test_settings)

    assert len(decisions) == len(gt_decisions), f"Expected {len(gt_decisions)} decisions, got {len(decisions)}"

    for dec in decisions:
        assert dec.id in gt_decisions, f"Unexpected decision {dec.id} in graph"
        gt = gt_decisions[dec.id]

        assert dec.freshness == gt["freshness"], (
            f"Decision {dec.id} freshness mismatch: expected {gt['freshness']}, got {dec.freshness}"
        )
        assert dec.drift_count == gt["drift_count"], (
            f"Decision {dec.id} drift_count mismatch: expected {gt['drift_count']}, got {dec.drift_count}"
        )


def test_t3_simulate_pr_and_reset_demo(populated_test_graph):
    """Test T3: simulate_pr flips exactly the decisions whose affected modules match; reset_demo restores T2."""
    g = populated_test_graph
    repo_root = Path(__file__).resolve().parent.parent.parent
    gt_file = repo_root / "data" / "synthetic" / "ground_truth.json"
    gt_data = json.loads(gt_file.read_text(encoding="utf-8"))
    gt_threshold = gt_data["threshold"]
    test_settings = Settings(STALE_PR_THRESHOLD=gt_threshold)

    # 1. Baseline T2 check
    decisions_before = {d.id: d.freshness for d in list_decisions(graph=g, settings=test_settings)}
    assert decisions_before["dec_006"] == "fresh"

    # 2. Simulate PR touching 'm_tests_benchmarks' (affected by dec_006)
    sim_res = simulate_pr(
        module_id="m_tests_benchmarks",
        title="Simulate benchmark update",
        graph=g,
        settings=test_settings,
    )

    assert sim_res.pr_id.startswith("pr_")
    assert len(sim_res.changed) > 0

    # Ensure dec_006 was flipped from fresh to stale
    flipped_ids = [c.decision_id for c in sim_res.changed]
    assert "dec_006" in flipped_ids

    for change in sim_res.changed:
        assert change.before == "fresh"
        assert change.after == "stale"
        # Confirm that the flipped decision actually affects m_tests_benchmarks
        affects_res = g.query("MATCH (d:Decision {id:$id})-[:AFFECTS]->(m:Module) RETURN m.id", {"id": change.decision_id})
        aff_mods = [r[0] for r in affects_res.result_set]
        assert "m_tests_benchmarks" in aff_mods

    # 3. Reset demo state
    reset_res = reset_demo(graph=g, settings=test_settings)
    assert reset_res.removed_nodes > 0

    # 4. Verify T2 state is completely restored
    decisions_after = {d.id: d.freshness for d in list_decisions(graph=g, settings=test_settings)}
    assert decisions_after == decisions_before
    assert decisions_after["dec_006"] == "fresh"


def test_search_sanity(populated_test_graph):
    """Test search_sanity: for 3 loaded Docs, search by Doc's title; appears in top 3 hits."""
    g = populated_test_graph
    cfg = get_settings()

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key or api_key == "test-gemini-key":
        # Check if real key is in .env file
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val and val != "test-gemini-key":
                        api_key = val
                        break

    if not api_key or api_key == "test-gemini-key":
        pytest.skip("GEMINI_API_KEY is unset or dummy; skipping search_sanity live embedding test")

    test_settings = Settings(GEMINI_API_KEY=api_key)

    # Fetch 3 Docs from graph
    res = g.query("MATCH (d:Doc) RETURN d.id, d.display, d.body LIMIT 3")
    assert len(res.result_set) >= 3, "Expected at least 3 Doc nodes in graph"

    # Ensure these 3 Docs have embeddings in the test graph
    docs_to_embed = []
    for row in res.result_set:
        d_id = row[0]
        d_display = row[1] or ""
        d_body = row[2] or ""
        embed_text = f"{d_display}\n{d_body}"
        docs_to_embed.append({"id": d_id, "display": d_display, "text": embed_text})

    try:
        vectors = embed_documents([d["text"] for d in docs_to_embed], settings=test_settings)
    except Exception as exc:
        pytest.skip(f"Live embedding network unavailable: {exc}")
    assert len(vectors) == len(docs_to_embed)

    for i, item in enumerate(docs_to_embed):
        g.query(
            "MATCH (d:Doc {id:$id}) SET d.embedding = vecf32($vec)",
            {"id": item["id"], "vec": vectors[i]},
        )

    # For each Doc, search by title and verify it appears in top 3 hits
    for item in docs_to_embed:
        query_title = item["display"]
        search_res = search_knowledge(
            query=query_title,
            kinds=["Doc"],
            k=3,
            graph=g,
            settings=test_settings,
        )
        assert search_res.ok is True
        hits = search_res.data.get("hits", [])
        assert len(hits) > 0
        hit_ids = [h["id"] for h in hits[:3]]
        assert item["id"] in hit_ids, f"Doc {item['id']} ('{query_title}') not found in top 3 hits: {hit_ids}"


def test_tool_who_owns(populated_test_graph):
    """Test who_owns with single match, zero match, and candidate resolution."""
    g = populated_test_graph

    # 1. Zero match -> ok=False
    res_none = who_owns("nonexistent_module_xyz", graph=g)
    assert res_none.ok is False
    assert "No module found" in res_none.summary
    assert res_none.cypher_ids == ["Q03"]

    # 2. Ambiguous match -> ok=False with candidates
    res_multi = who_owns("docs", graph=g)
    if not res_multi.ok and "candidates" in res_multi.data:
        assert len(res_multi.data["candidates"]) > 1
        assert res_multi.cypher_ids == ["Q03"]

    # 3. Exact unique match -> ok=True
    res_ok = who_owns("fastapi/dependencies", graph=g)
    assert res_ok.ok is True
    assert "module" in res_ok.data
    assert "owner_teams" in res_ok.data
    assert "top_contributors" in res_ok.data
    assert "ownership_gap" in res_ok.data
    assert isinstance(res_ok.data["ownership_gap"], bool)
    assert "Q03" in res_ok.cypher_ids
    assert "Q01" in res_ok.cypher_ids
    assert "Q02" in res_ok.cypher_ids
    assert len(res_ok.summary) <= 300


def test_tool_recent_changes(populated_test_graph):
    """Test recent_changes module resolution and PR retrieval."""
    g = populated_test_graph

    res_ok = recent_changes("fastapi/dependencies", since_days=3650, limit=5, graph=g)
    assert res_ok.ok is True
    assert "prs" in res_ok.data
    assert "Q03" in res_ok.cypher_ids
    assert "Q12" in res_ok.cypher_ids

    res_fail = recent_changes("completely_fake_module", graph=g)
    assert res_fail.ok is False


def test_tool_decision_lifecycle(populated_test_graph):
    """Test get_decision, trace_decision, and check_freshness."""
    g = populated_test_graph

    # Unknown ID -> ok=False, no exception
    res_bad = get_decision("dec_999999", graph=g)
    assert res_bad.ok is False
    assert "not found" in res_bad.summary.lower()

    # Valid ID -> ok=True
    res_dec = get_decision("dec_001", graph=g)
    assert res_dec.ok is True
    assert "decision" in res_dec.data
    assert "decider" in res_dec.data
    assert "modules" in res_dec.data
    assert res_dec.cypher_ids == ["Q05"]

    # Trace decision
    res_trace = trace_decision("dec_001", graph=g)
    assert res_trace.ok is True
    assert "chain" in res_trace.data
    assert "freshness" in res_trace.data
    assert set(res_trace.cypher_ids) == {"Q05", "Q06", "Q07", "Q08"}

    # Check freshness
    res_fresh = check_freshness("dec_001", graph=g)
    assert res_fresh.ok is True
    assert res_fresh.data["freshness"] == "superseded"


def test_tool_flag_for_review(populated_test_graph):
    """Test flag_for_review creation and idempotency (already_open)."""
    g = populated_test_graph

    # Unknown decision -> ok=False
    res_bad = flag_for_review("dec_missing", note="Review please", graph=g)
    assert res_bad.ok is False

    # First flag -> created
    res1 = flag_for_review("dec_003", note="Needs migration review", graph=g)
    assert res1.ok is True
    assert res1.data["already_open"] is False
    rr_id = res1.data["review_request_id"]
    assert rr_id.startswith("rr_")

    # Second flag -> already_open=True with same id
    res2 = flag_for_review("dec_003", note="Another note", graph=g)
    assert res2.ok is True
    assert res2.data["already_open"] is True
    assert res2.data["review_request_id"] == rr_id


def test_tool_connection_path_and_key_connectors(populated_test_graph):
    """Test connection_path and key_connectors tool services."""
    g = populated_test_graph

    # Path between known connected nodes
    res_path = connection_path("dec_001", "m_docs_en_docs", graph=g)
    assert res_path.ok is True
    assert len(res_path.data["path"]) >= 2
    assert res_path.data["path"][0]["edge_type"] is None
    assert res_path.data["path"][1]["edge_type"] == "AFFECTS"
    assert res_path.cypher_ids == ["Q13"]

    # Key connectors (PageRank)
    res_kc = key_connectors(limit=3, graph=g)
    assert res_kc.ok is True
    assert len(res_kc.data["people"]) <= 3
    assert res_kc.cypher_ids == ["Q14"]


def test_rest_services(populated_test_graph):
    """Test REST-only DTO return types and operations."""
    g = populated_test_graph

    # Modules
    mods = list_modules(graph=g)
    assert len(mods) > 0
    assert hasattr(mods[0], "owner_team")

    # Overview and neighborhood
    overview = graph_overview(limit=50, graph=g)
    assert len(overview.nodes) > 0

    nb = neighborhood(mods[0].id, limit=20, graph=g)
    assert len(nb.nodes) > 0

    # Node detail
    detail = node_detail(mods[0].id, graph=g)
    assert detail is not None
    assert detail.id == mods[0].id

    # Reviews
    reviews = list_reviews(graph=g)
    assert len(reviews) >= 1  # From flag_for_review test above

    # Counts
    cnt = counts(graph=g)
    assert cnt.nodes > 0
    assert cnt.edges > 0
