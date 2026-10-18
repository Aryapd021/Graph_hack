"""Test T6: Unit and integration tests for the Gemini Agent reasoning loop.

Per ARCHITECTURE.md Section 12, 17 (Test T6) & Task B8:
- Citation validation: removes [[unknown_id]], keeps valid markers, builds citations in order.
- Date enrichment helper: adds *_utc_date siblings in YYYY-MM-DD form for *_at and last_active.
- Step cap: terminates loop when AGENT_MAX_STEPS is reached and requests final answer with tools disabled.
- Highlight generation: includes cited node IDs plus connection path nodes and edges.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brain_api.agent.loop import enrich_dates, execute_agent_loop, validate_citations
from brain_api.exceptions import LLMErrorException
from brain_core.config import Settings
from brain_core.models import (
    ChatRequest,
    ChatTurn,
    Evidence,
    GraphEdge,
    GraphNode,
    GraphPayload,
    ToolResult,
)


def test_enrich_dates_helper():
    """Verify enrich_dates adds <key>_utc_date siblings without mutating epoch numbers."""
    raw_data = {
        "title": "Standardize error handling",
        "created_at": 1700000000,
        "last_active": 1700003600,
        "drift_count": 5,
        "nested": {
            "decided_at": 1700090000,
            "status": "active",
        },
        "prs": [
            {"id": "pr_1", "merged_at": 1700176400},
            {"id": "pr_2", "merged_at": None},
        ],
    }

    enriched = enrich_dates(raw_data)

    # Original epoch numbers preserved
    assert enriched["created_at"] == 1700000000
    assert enriched["last_active"] == 1700003600
    assert enriched["nested"]["decided_at"] == 1700090000
    assert enriched["prs"][0]["merged_at"] == 1700176400

    # Sibling UTC date strings added
    assert enriched["created_at_utc_date"] == "2023-11-14"
    assert enriched["last_active_utc_date"] == "2023-11-14"
    assert enriched["nested"]["decided_at_utc_date"] == "2023-11-15"
    assert enriched["prs"][0]["merged_at_utc_date"] == "2023-11-16"

    # Non-date keys untouched
    assert "title_utc_date" not in enriched
    assert "drift_count_utc_date" not in enriched
    assert enriched["prs"][1]["merged_at"] is None


def test_citation_filter():
    """Verify citation validation keeps known evidence IDs, removes unknown markers, and dedupes."""
    evidence_pool = [
        Evidence(node_id="mod_auth", label="Module", display="backend/auth", url=None),
        Evidence(node_id="dec_001", label="Decision", display="Use JWT", url=None),
        Evidence(node_id="p_alice", label="Person", display="Contributor Alice", url=None),
    ]

    answer_text = (
        "The module [[mod_auth]] was designed by [[p_alice]]. "
        "A controversial decision [[dec_001]] was made, despite protests from [[p_unknown_hacker]]. "
        "Further details on [[mod_auth]] are documented."
    )

    cleaned_text, citations = validate_citations(answer_text, evidence_pool)

    # Valid markers preserved, unknown marker stripped
    assert "[[mod_auth]]" in cleaned_text
    assert "[[p_alice]]" in cleaned_text
    assert "[[dec_001]]" in cleaned_text
    assert "[[p_unknown_hacker]]" not in cleaned_text
    assert "p_unknown_hacker" not in cleaned_text

    # Citations list preserves first-appearance order and dedupes mod_auth
    assert len(citations) == 3
    assert [c.node_id for c in citations] == ["mod_auth", "p_alice", "dec_001"]


@pytest.mark.asyncio
async def test_agent_loop_direct_text_answer():
    """Verify loop handles direct textual response from model without tools."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_candidate = MagicMock()
    mock_candidate.content = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_response.function_calls = []
    mock_response.text = "Hello! I can answer questions about the repository."

    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    req = ChatRequest(message="Hi", history=[])
    settings = Settings(GEMINI_API_KEY="test-key", GEMINI_MODEL="gemini-test", AGENT_MAX_STEPS=3)

    with patch("brain_api.agent.loop.get_tool_declarations", new_callable=AsyncMock) as mock_tools:
        mock_tools.return_value = []
        resp = await execute_agent_loop(request=req, settings=settings, client=mock_client)

    assert resp.answer == "Hello! I can answer questions about the repository."
    assert resp.citations == []
    assert resp.trace == []


@pytest.mark.asyncio
async def test_agent_step_cap_with_stubbed_model():
    """Verify agent loop enforces AGENT_MAX_STEPS cap and requests final answer with tools disabled."""
    mock_client = MagicMock()

    # Step 1 response: requests tool call 'who_owns'
    call1 = MagicMock()
    call1.name = "who_owns"
    call1.args = {"module": "auth"}

    resp1 = MagicMock()
    cand1 = MagicMock()
    cand1.content = MagicMock()
    resp1.candidates = [cand1]
    resp1.function_calls = [call1]
    resp1.text = None

    # Forced final answer response (when tools disabled)
    final_resp = MagicMock()
    final_resp.candidates = [MagicMock()]
    final_resp.function_calls = []
    final_resp.text = "Module auth is owned by Security [[mod_auth]]."

    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=[resp1, final_resp]
    )

    tool_result_mock = ToolResult(
        ok=True,
        summary="Security team owns auth",
        data={"module": {"id": "mod_auth", "display": "auth"}},
        evidence=[Evidence(node_id="mod_auth", label="Module", display="auth", url=None)],
        graph=GraphPayload(
            nodes=[GraphNode(id="mod_auth", label="Module", display="auth", props={})],
            edges=[],
        ),
        cypher_ids=["Q03"],
    )

    settings = Settings(
        GEMINI_API_KEY="test-key",
        GEMINI_MODEL="gemini-test",
        AGENT_MAX_STEPS=1,  # Cap at 1 step
        LLM_TIMEOUT_S=10,
    )
    req = ChatRequest(message="Who owns auth?", history=[])

    with patch("brain_api.agent.loop.get_tool_declarations", new_callable=AsyncMock) as mock_tools, \
         patch("brain_api.agent.loop.call_tool", new_callable=AsyncMock) as mock_call:
        mock_tools.return_value = []
        mock_call.return_value = tool_result_mock

        resp = await execute_agent_loop(request=req, settings=settings, client=mock_client)

    # Verified step cap reached: exactly 1 tool step in trace
    assert len(resp.trace) == 1
    assert resp.trace[0].tool == "who_owns"
    assert resp.answer == "Module auth is owned by Security [[mod_auth]]."
    assert len(resp.citations) == 1
    assert resp.citations[0].node_id == "mod_auth"


@pytest.mark.asyncio
async def test_agent_highlights_connection_path():
    """Verify highlight includes cited IDs plus connection path nodes and edges."""
    mock_client = MagicMock()

    call_path = MagicMock()
    call_path.name = "connection_path"
    call_path.args = {"from_id": "p_alice", "to_id": "mod_auth"}

    resp1 = MagicMock()
    cand1 = MagicMock()
    cand1.content = MagicMock()
    resp1.candidates = [cand1]
    resp1.function_calls = [call_path]
    resp1.text = None

    final_resp = MagicMock()
    final_resp.candidates = [MagicMock()]
    final_resp.function_calls = []
    final_resp.text = "Alice connects to auth via Security team [[p_alice]]."

    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=[resp1, final_resp]
    )

    ev_alice = Evidence(node_id="p_alice", label="Person", display="Alice", url=None)
    ev_team = Evidence(node_id="t_sec", label="Team", display="Security", url=None)
    ev_auth = Evidence(node_id="mod_auth", label="Module", display="auth", url=None)

    path_data = [
        {"node": ev_alice, "edge_type": None, "direction": None},
        {"node": ev_team, "edge_type": "MEMBER_OF", "direction": "out"},
        {"node": ev_auth, "edge_type": "OWNS", "direction": "out"},
    ]

    tool_result_path = ToolResult(
        ok=True,
        summary="Path of length 2",
        data={"path": path_data},
        evidence=[ev_alice, ev_team, ev_auth],
        graph=GraphPayload(
            nodes=[
                GraphNode(id="p_alice", label="Person", display="Alice", props={}),
                GraphNode(id="t_sec", label="Team", display="Security", props={}),
                GraphNode(id="mod_auth", label="Module", display="auth", props={}),
            ],
            edges=[
                GraphEdge(id="p_alice|MEMBER_OF|t_sec", source="p_alice", target="t_sec", type="MEMBER_OF"),
                GraphEdge(id="t_sec|OWNS|mod_auth", source="t_sec", target="mod_auth", type="OWNS"),
            ],
        ),
        cypher_ids=["Q13"],
    )

    settings = Settings(
        GEMINI_API_KEY="test-key",
        GEMINI_MODEL="gemini-test",
        AGENT_MAX_STEPS=3,
    )
    req = ChatRequest(message="Connect Alice to auth", history=[])

    with patch("brain_api.agent.loop.get_tool_declarations", new_callable=AsyncMock) as mock_tools, \
         patch("brain_api.agent.loop.call_tool", new_callable=AsyncMock) as mock_call:
        mock_tools.return_value = []
        mock_call.return_value = tool_result_path

        resp = await execute_agent_loop(request=req, settings=settings, client=mock_client)

    assert "p_alice" in resp.highlight.node_ids
    assert "t_sec" in resp.highlight.node_ids
    assert "mod_auth" in resp.highlight.node_ids
    assert "p_alice|MEMBER_OF|t_sec" in resp.highlight.edge_ids
    assert "t_sec|OWNS|mod_auth" in resp.highlight.edge_ids
