"""Unit tests for Task B1 core modules (freshness, scoring, models, graph payload)."""

import pytest

from brain_core.freshness import classify
from brain_core.graph_payload import (
    filter_node_properties,
    rows_to_graph_payload,
    to_graph_edge,
    to_graph_node,
)
from brain_core.models import (
    ChatRequest,
    ChatTurn,
    DecisionSummary,
    Evidence,
    FlagDecisionResponse,
    GraphPayload,
    HealthCounts,
    HealthResponse,
    Highlight,
    SimulatePRResponse,
    ToolResult,
)
from brain_core.scoring import W_DECISION, W_PR, W_THREAD, compute_score


# --- Freshness Tests ---


def test_freshness_classify_superseded() -> None:
    """Verify that superseded decisions always return 'superseded' regardless of drift."""
    assert classify("superseded", drift_count=0, threshold=1) == "superseded"
    assert classify("superseded", drift_count=5, threshold=1) == "superseded"


def test_freshness_classify_threshold_boundary() -> None:
    """Verify classification around the threshold boundary."""
    # Strict boundary checks: drift_count < threshold -> fresh; drift_count >= threshold -> stale
    assert classify("active", drift_count=0, threshold=1) == "fresh"
    assert classify("active", drift_count=1, threshold=1) == "stale"
    assert classify("active", drift_count=2, threshold=1) == "stale"

    # Higher threshold boundary
    threshold = 3
    assert classify("active", drift_count=2, threshold=threshold) == "fresh"
    assert classify("active", drift_count=3, threshold=threshold) == "stale"
    assert classify("active", drift_count=4, threshold=threshold) == "stale"


# --- Scoring Tests ---


def test_scoring_weights_and_computation() -> None:
    """Verify scoring constants and compute_score formula."""
    assert W_PR == 1
    assert W_THREAD == 2
    assert W_DECISION == 3

    # 1*10 + 2*5 + 3*2 = 10 + 10 + 6 = 26
    score = compute_score(prs=10, threads=5, decisions=2)
    assert score == 26


# --- Graph Payload Tests ---


def test_graph_payload_property_allow_list() -> None:
    """Verify that forbidden properties (embedding, text_hash, body, text) are stripped."""
    # Test Doc node
    raw_doc = {
        "id": "d_12345",
        "display": "Architecture Guide",
        "source": "github",
        "path": "docs/architecture.md",
        "kind": "design",
        "updated_at": 1700000000,
        "body": "Sensitive body content...",
        "text_hash": "abc123hash",
        "embedding": [0.1, 0.2, 0.3],
        "unknown_extra": "drop me",
    }
    filtered_doc = filter_node_properties("Doc", raw_doc)
    assert "id" in filtered_doc
    assert "path" in filtered_doc
    assert "kind" in filtered_doc
    assert "body" not in filtered_doc
    assert "text_hash" not in filtered_doc
    assert "embedding" not in filtered_doc
    assert "unknown_extra" not in filtered_doc

    # Test Thread node
    raw_thread = {
        "id": "th_001",
        "display": "Discussion on auth",
        "source": "synthetic",
        "channel": "#eng-decisions",
        "started_at": 1700001000,
        "text": "Secret chat text",
        "text_hash": "th_hash",
        "embedding": [0.5, 0.5],
    }
    filtered_thread = filter_node_properties("Thread", raw_thread)
    assert "id" in filtered_thread
    assert "channel" in filtered_thread
    assert "text" not in filtered_thread
    assert "text_hash" not in filtered_thread
    assert "embedding" not in filtered_thread


def test_graph_payload_edge_id_format() -> None:
    """Verify edge ID formatting rule: source|TYPE|target."""
    edge_dict = {
        "type": "AFFECTS",
        "source": "dec_001",
        "target": "m_routing",
    }
    edge = to_graph_edge(edge_dict)
    assert edge.id == "dec_001|AFFECTS|m_routing"
    assert edge.source == "dec_001"
    assert edge.target == "m_routing"
    assert edge.type == "AFFECTS"


def test_graph_payload_reject_unknown_labels_and_edges() -> None:
    """Verify that unknown node labels and relationship types are rejected."""
    with pytest.raises(ValueError, match="Unknown node label"):
        to_graph_node({"label": "InvalidLabel", "id": "x1"})

    with pytest.raises(ValueError, match="Unknown edge type"):
        to_graph_edge({"type": "INVALID_REL", "source": "a", "target": "b"})


def test_graph_payload_mock_node_edge_conversion() -> None:
    """Test full conversion with internal ID to domain ID mapping."""
    class MockNode:
        def __init__(self, internal_id: int, label: str, domain_id: str, display: str):
            self.id = internal_id
            self.labels = [label]
            self.properties = {"id": domain_id, "display": display, "source": "synthetic"}

    class MockEdge:
        def __init__(self, relation: str, src_node: int, dest_node: int):
            self.relation = relation
            self.src_node = src_node
            self.dest_node = dest_node

    node_a = MockNode(101, "Person", "p_11111111", "Contributor 1")
    node_b = MockNode(102, "Team", "t_platform", "Platform Team")
    edge_r = MockEdge("MEMBER_OF", 101, 102)

    payload = rows_to_graph_payload([[node_a, edge_r, node_b]])
    assert len(payload.nodes) == 2
    assert len(payload.edges) == 1

    assert payload.edges[0].id == "p_11111111|MEMBER_OF|t_platform"
    assert payload.edges[0].source == "p_11111111"
    assert payload.edges[0].target == "t_platform"


# --- Models Validation Tests ---


def test_chat_request_validation() -> None:
    """Verify ChatRequest validation rules: 1..2000 chars, max 10 turns."""
    # Valid request
    req = ChatRequest(message="Hello", history=[ChatTurn(role="user", content="Hi")])
    assert req.message == "Hello"
    assert len(req.history) == 1

    # Empty message invalid
    with pytest.raises(ValueError):
        ChatRequest(message="", history=[])

    # Message exceeding 2000 chars invalid
    with pytest.raises(ValueError):
        ChatRequest(message="x" * 2001, history=[])

    # More than 10 turns invalid
    turns = [ChatTurn(role="user", content=f"msg {i}") for i in range(11)]
    with pytest.raises(ValueError):
        ChatRequest(message="Hi", history=turns)


def test_rest_models_schemas() -> None:
    """Verify REST API response model shapes from Section 14."""
    # Health response
    health = HealthResponse(
        status="ok",
        falkordb=True,
        mcp=True,
        counts=HealthCounts(nodes=100, edges=250),
        demo_mode=True,
        ingest_refresh=True,
    )
    assert health.status == "ok"
    assert health.counts.nodes == 100

    # Flag response
    flag_res = FlagDecisionResponse(
        review_request_id="rr_12345678",
        assigned_to=[{"id": "p_001", "display": "Contributor 1"}],
        already_open=False,
    )
    assert flag_res.review_request_id == "rr_12345678"
    assert len(flag_res.assigned_to) == 1

    # Simulate PR response
    sim_res = SimulatePRResponse(
        pr_id="pr_900001",
        changed=[{"decision_id": "dec_001", "before": "fresh", "after": "stale"}],
    )
    assert sim_res.pr_id == "pr_900001"
    assert sim_res.changed[0].after == "stale"
