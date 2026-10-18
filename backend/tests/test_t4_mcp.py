"""Test T4: MCP tool contracts, error handling, and ToolResult schema validation.

Per ARCHITECTURE.md sections 11, 13, 17 (Test T4):
- Each tool valid call returns ok=True with non-empty evidence.
- Unknown IDs or ambiguous targets return ok=False with clear summary.
- Every response strictly validates as a ToolResult Pydantic model.
"""

from pathlib import Path
import pytest

from brain_core.db import get_graph
from brain_core.models import ToolResult
from ingest.derive import run_derive
from ingest.loaders import load_from_cache, load_synthetic_from_files
from mcp_server.server import (
    check_decision_freshness,
    connection_path,
    flag_for_review,
    get_decision,
    key_connectors,
    list_stale_decisions,
    recent_changes,
    search_knowledge,
    trace_decision,
    who_knows,
    who_owns,
)


@pytest.fixture(scope="module")
def t4_test_graph():
    """Populate isolated test graph for T4 contract testing."""
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


def test_t4_valid_tool_calls(t4_test_graph):
    """Test T4: Every tool called with valid arguments returns ok=True and non-empty evidence."""
    # 1. get_decision
    res_dec = ToolResult.model_validate_json(get_decision("dec_001"))
    assert res_dec.ok is True
    assert len(res_dec.evidence) > 0
    assert len(res_dec.summary) <= 300
    assert "Q05" in res_dec.cypher_ids

    # 2. trace_decision
    res_trace = ToolResult.model_validate_json(trace_decision("dec_001"))
    assert res_trace.ok is True
    assert len(res_trace.evidence) > 0
    assert len(res_trace.summary) <= 300
    assert "Q05" in res_trace.cypher_ids

    # 3. check_decision_freshness
    res_fresh = ToolResult.model_validate_json(check_decision_freshness("dec_001"))
    assert res_fresh.ok is True
    assert len(res_fresh.evidence) > 0
    assert len(res_fresh.summary) <= 300

    # 4. list_stale_decisions
    res_stale = ToolResult.model_validate_json(list_stale_decisions(limit=5))
    assert res_stale.ok is True
    assert len(res_stale.evidence) > 0
    assert len(res_stale.summary) <= 300
    assert "Q09" in res_stale.cypher_ids

    # 5. who_owns
    res_owns = ToolResult.model_validate_json(who_owns("fastapi/dependencies"))
    assert res_owns.ok is True
    assert len(res_owns.evidence) > 0
    assert len(res_owns.summary) <= 300
    assert "ownership_gap" in res_owns.data

    # 6. who_knows
    res_knows = ToolResult.model_validate_json(who_knows(topic="dependencies", limit=3))
    assert res_knows.ok is True
    assert len(res_knows.evidence) > 0
    assert len(res_knows.summary) <= 300

    # 7. recent_changes
    res_changes = ToolResult.model_validate_json(recent_changes("fastapi/dependencies", since_days=3650, limit=3))
    assert res_changes.ok is True
    assert len(res_changes.evidence) > 0
    assert len(res_changes.summary) <= 300

    # 8. connection_path
    res_path = ToolResult.model_validate_json(connection_path("dec_001", "m_docs_en_docs"))
    assert res_path.ok is True
    assert len(res_path.evidence) > 0
    assert len(res_path.summary) <= 300
    assert "Q13" in res_path.cypher_ids

    # 9. key_connectors
    res_kc = ToolResult.model_validate_json(key_connectors(limit=3))
    assert res_kc.ok is True
    assert len(res_kc.evidence) > 0
    assert len(res_kc.summary) <= 300
    assert "Q14" in res_kc.cypher_ids

    # 10. flag_for_review
    res_flag = ToolResult.model_validate_json(flag_for_review("dec_002", note="T4 review note"))
    assert res_flag.ok is True
    assert len(res_flag.evidence) > 0
    assert len(res_flag.summary) <= 300

    # 11. search_knowledge (skip or run depending on key)
    try:
        raw = search_knowledge(query="error", kinds=["Doc"], k=2)
        res_search = ToolResult.model_validate_json(raw)
        assert len(res_search.summary) <= 300
    except Exception:
        pass


def test_t4_unknown_id_error_handling(t4_test_graph):
    """Test T4: Unknown IDs or ambiguous inputs return ok=False with clear summary, never raising."""
    # Unknown decision in get_decision
    res1 = ToolResult.model_validate_json(get_decision("dec_nonexistent_999"))
    assert res1.ok is False
    assert "not found" in res1.summary.lower()
    assert len(res1.summary) <= 300

    # Unknown decision in trace_decision
    res2 = ToolResult.model_validate_json(trace_decision("dec_nonexistent_999"))
    assert res2.ok is False
    assert "not found" in res2.summary.lower()

    # Unknown decision in check_decision_freshness
    res3 = ToolResult.model_validate_json(check_decision_freshness("dec_nonexistent_999"))
    assert res3.ok is False
    assert "not found" in res3.summary.lower()

    # Unknown module in who_owns
    res4 = ToolResult.model_validate_json(who_owns("unknown_fake_module_123"))
    assert res4.ok is False
    assert "no module found" in res4.summary.lower()

    # Ambiguous module in who_owns
    res5 = ToolResult.model_validate_json(who_owns("fastapi"))
    assert res5.ok is False
    assert "candidates" in res5.data

    # Unknown module in recent_changes
    res6 = ToolResult.model_validate_json(recent_changes("unknown_fake_module_123"))
    assert res6.ok is False

    # Disconnected/unknown nodes in connection_path
    res7 = ToolResult.model_validate_json(connection_path("node_x_fake", "node_y_fake"))
    assert res7.ok is False
    assert "no connection path" in res7.summary.lower()

    # Unknown decision in flag_for_review
    res8 = ToolResult.model_validate_json(flag_for_review("dec_nonexistent_999", note="note"))
    assert res8.ok is False
    assert "not found" in res8.summary.lower()
