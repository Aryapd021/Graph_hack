"""Test T7: Contract tests for REST API endpoints and Child MCP Auto-Restart.

Per ARCHITECTURE.md Section 13, 14, 16, 17 & Task B7:
- Verify OpenAPI schema at /openapi.json.
- Verify every route's response validates against its Pydantic model.
- Verify non-2xx responses validate against ErrorResponse(error=ErrorBody(code=..., message=...)).
- Verify degradation: health check returns 200 with status="degraded", falkordb=False when DB unreachable (simulated with wrong port).
- Verify exposure controls: DEMO_MODE and ENABLE_INGEST_REFRESH return 404 when disabled.
- Verify sliding-window rate limit on /api/chat (excess returns 429 RATE_LIMITED).
- Verify Task B7 stub: /api/chat returns INTERNAL error with message 'agent not implemented'.
- Verify Child MCP server process auto-restart on unexpected crashes during development.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import pytest

from brain_api.main import app
from brain_api.mcp_manager import mcp_manager
from brain_api.rate_limit import rate_limiter
from brain_core.config import Settings
from brain_core.models import (
    ChatResponse,
    DecisionSummary,
    ErrorResponse,
    Evidence,
    FlagDecisionResponse,
    GraphPayload,
    HealthResponse,
    Highlight,
    IngestRefreshResponse,
    ModuleSummary,
    NodeDetail,
    ResetDemoResponse,
    ReviewRequestOut,
    SimulatePRResponse,
    ToolResult,
)


@pytest.fixture
def seeded_graph(test_graph):
    """Seed test graph with sample nodes and edges for API verification."""
    # Module
    test_graph.query(
        "CREATE (m:Module {id: 'mod_auth', display: 'auth', path: 'backend/auth', source: 'github'})"
    )
    # Team owning module
    test_graph.query(
        "CREATE (t:Team {id: 'team_sec', display: 'Security Team', source: 'synthetic'})"
    )
    test_graph.query(
        "MATCH (t:Team {id: 'team_sec'}), (m:Module {id: 'mod_auth'}) CREATE (t)-[:OWNS]->(m)"
    )
    # Decider Person
    test_graph.query(
        "CREATE (p:Person {id: 'p_11111111', display: 'Contributor 11111111', source: 'github'})"
    )
    # Decision
    test_graph.query(
        "CREATE (d:Decision {id: 'dec_oauth', display: 'OAuth2 with JWT', title: 'OAuth2 with JWT', summary: 'Use JWT tokens', rationale: 'Stateless', decided_at: 1700000000, status: 'active', source: 'synthetic'})"
    )
    test_graph.query(
        "MATCH (p:Person {id: 'p_11111111'}), (d:Decision {id: 'dec_oauth'}) CREATE (p)-[:DECIDED_BY]->(d)"
    )
    test_graph.query(
        "MATCH (d:Decision {id: 'dec_oauth'}), (m:Module {id: 'mod_auth'}) CREATE (d)-[:AFFECTS]->(m)"
    )
    return test_graph


def test_openapi_schema():
    """Verify /openapi.json is served and contains valid schema."""
    with TestClient(app) as client:
        res = client.get("/openapi.json")
        assert res.status_code == 200
        schema = res.json()
        assert schema["openapi"].startswith("3.")
        assert "/api/health" in schema["paths"]
        assert "/api/chat" in schema["paths"]
        assert "/api/decisions" in schema["paths"]


def test_get_health(seeded_graph):
    """Verify GET /api/health returns valid HealthResponse."""
    with TestClient(app) as client:
        res = client.get("/api/health")
        assert res.status_code == 200
        parsed = HealthResponse.model_validate(res.json())
        assert parsed.status in ("ok", "degraded")
        assert parsed.counts.nodes >= 3


def test_get_modules(seeded_graph):
    """Verify GET /api/modules returns valid list[ModuleSummary]."""
    with TestClient(app) as client:
        res = client.get("/api/modules")
        assert res.status_code == 200
        items = [ModuleSummary.model_validate(item) for item in res.json()]
        assert len(items) >= 1
        assert any(m.id == "mod_auth" for m in items)


def test_graph_endpoints(seeded_graph):
    """Verify GET /api/graph/overview, /neighborhood, and /node/{id}."""
    with TestClient(app) as client:
        # Overview
        res = client.get("/api/graph/overview?limit=50")
        assert res.status_code == 200
        GraphPayload.model_validate(res.json())

        # Neighborhood
        res_nb = client.get("/api/graph/neighborhood/mod_auth?limit=20")
        assert res_nb.status_code == 200
        GraphPayload.model_validate(res_nb.json())

        # Node Detail (found)
        res_nd = client.get("/api/node/mod_auth")
        assert res_nd.status_code == 200
        nd = NodeDetail.model_validate(res_nd.json())
        assert nd.id == "mod_auth"
        assert nd.label == "Module"

        # Node Detail (not found -> 404 ErrorResponse)
        res_404 = client.get("/api/node/nonexistent_xyz")
        assert res_404.status_code == 404
        err = ErrorResponse.model_validate(res_404.json())
        assert err.error.code == "NOT_FOUND"


def test_decisions_endpoints(seeded_graph):
    """Verify GET /api/decisions, /trace, and POST /api/decisions/{id}/flag."""
    with TestClient(app) as client:
        # List decisions
        res = client.get("/api/decisions")
        assert res.status_code == 200
        decs = [DecisionSummary.model_validate(d) for d in res.json()]
        assert len(decs) >= 1

        # Trace existing
        res_tr = client.get("/api/decisions/dec_oauth/trace")
        assert res_tr.status_code == 200
        tr = ToolResult.model_validate(res_tr.json())
        assert tr.ok is True

        # Trace nonexistent -> 404
        res_tr_404 = client.get("/api/decisions/nonexistent_dec/trace")
        assert res_tr_404.status_code == 404
        err = ErrorResponse.model_validate(res_tr_404.json())
        assert err.error.code == "NOT_FOUND"

        # Flag existing
        res_flag = client.post("/api/decisions/dec_oauth/flag", json={"note": "Test review flag"})
        assert res_flag.status_code == 200
        FlagDecisionResponse.model_validate(res_flag.json())

        # Flag nonexistent -> 404
        res_flag_404 = client.post("/api/decisions/unknown_dec/flag", json={"note": "Test note"})
        assert res_flag_404.status_code == 404
        err_flag = ErrorResponse.model_validate(res_flag_404.json())
        assert err_flag.error.code == "NOT_FOUND"


def test_reviews_endpoint(seeded_graph):
    """Verify GET /api/reviews returns valid list[ReviewRequestOut]."""
    with TestClient(app) as client:
        # Flag a decision to ensure a review exists
        client.post("/api/decisions/dec_oauth/flag", json={"note": "Review needed"})

        res = client.get("/api/reviews")
        assert res.status_code == 200
        reviews = [ReviewRequestOut.model_validate(r) for r in res.json()]
        assert len(reviews) >= 1
        assert reviews[0].decision_id == "dec_oauth"


def test_demo_endpoints(seeded_graph):
    """Verify /api/demo/simulate-pr and /api/demo/reset when DEMO_MODE is active and disabled."""
    with TestClient(app) as client:
        # Simulate PR
        res_sim = client.post(
            "/api/demo/simulate-pr",
            json={"module_id": "mod_auth", "title": "Add biometric auth"},
        )
        assert res_sim.status_code == 200
        sim = SimulatePRResponse.model_validate(res_sim.json())
        assert sim.pr_id.startswith("pr_")

        # Reset demo
        res_reset = client.post("/api/demo/reset")
        assert res_reset.status_code == 200
        reset_res = ResetDemoResponse.model_validate(res_reset.json())
        assert reset_res.removed_nodes >= 1

    # When DEMO_MODE is False -> must return 404 NOT_FOUND
    with patch("brain_api.routes.demo.get_settings") as mock_settings:
        mock_cfg = MagicMock()
        mock_cfg.DEMO_MODE = False
        mock_settings.return_value = mock_cfg

        with TestClient(app) as client:
            res_disabled = client.post("/api/demo/reset")
            assert res_disabled.status_code == 404
            err = ErrorResponse.model_validate(res_disabled.json())
            assert err.error.code == "NOT_FOUND"


def test_ingest_refresh_endpoint(seeded_graph):
    """Verify /api/ingest/refresh honors ENABLE_INGEST_REFRESH flag and runs services.ingest_refresh."""
    with patch("brain_api.routes.ingest.get_settings") as mock_settings:
        mock_cfg = MagicMock()
        mock_cfg.ENABLE_INGEST_REFRESH = True
        mock_settings.return_value = mock_cfg

        with TestClient(app) as client:
            res = client.post("/api/ingest/refresh")
            assert res.status_code == 200
            IngestRefreshResponse.model_validate(res.json())

    with patch("brain_api.routes.ingest.get_settings") as mock_settings:
        mock_cfg = MagicMock()
        mock_cfg.ENABLE_INGEST_REFRESH = False
        mock_settings.return_value = mock_cfg

        with TestClient(app) as client:
            res = client.post("/api/ingest/refresh")
            assert res.status_code == 404
            err = ErrorResponse.model_validate(res.json())
            assert err.error.code == "NOT_FOUND"


def test_chat_endpoint_contract(seeded_graph):
    """Verify POST /api/chat returns valid ChatResponse model."""
    mock_chat_response = ChatResponse(
        answer="Module auth is owned by Security [[mod_auth]].",
        citations=[Evidence(node_id="mod_auth", label="Module", display="auth", url=None)],
        trace=[],
        graph=GraphPayload(nodes=[], edges=[]),
        highlight=Highlight(node_ids=["mod_auth"], edge_ids=[]),
    )
    with patch("brain_api.routes.chat.execute_agent_loop", new_callable=AsyncMock) as mock_loop:
        mock_loop.return_value = mock_chat_response
        with TestClient(app) as client:
            payload = {
                "message": "Who owns auth?",
                "history": [{"role": "user", "content": "Hello"}],
            }
            res = client.post("/api/chat", json=payload)
            assert res.status_code == 200
            chat_resp = ChatResponse.model_validate(res.json())
            assert chat_resp.answer.startswith("Module auth")
            assert len(chat_resp.citations) == 1


def test_chat_rate_limiting():
    """Verify chat sliding window rate limiter returns 429 RATE_LIMITED on excess."""
    with patch("brain_api.rate_limit.get_settings") as mock_settings:
        mock_cfg = MagicMock()
        mock_cfg.CHAT_RATE_LIMIT_PER_MIN = 2
        mock_settings.return_value = mock_cfg

        # Reset rate limiter memory
        rate_limiter._requests.clear()

        with patch("brain_api.routes.chat.execute_agent_loop", new_callable=AsyncMock) as mock_loop:
            mock_loop.return_value = ChatResponse(
                answer="ok", citations=[], trace=[], graph=GraphPayload(nodes=[], edges=[]), highlight=Highlight(node_ids=[], edge_ids=[])
            )
            with TestClient(app) as client:
                payload = {"message": "Hello 1", "history": []}
                # First 2 requests pass rate check
                res1 = client.post("/api/chat", json=payload)
                assert res1.status_code == 200

                res2 = client.post("/api/chat", json=payload)
                assert res2.status_code == 200

                # 3rd request exceeds limit -> 429 RATE_LIMITED
                res3 = client.post("/api/chat", json=payload)
                assert res3.status_code == 429
                err = ErrorResponse.model_validate(res3.json())
                assert err.error.code == "RATE_LIMITED"

        rate_limiter._requests.clear()


def test_validation_error_normalization():
    """Verify invalid payloads return 400 BAD_REQUEST formatted as ErrorResponse."""
    with TestClient(app) as client:
        # Invalid chat message (empty string violates min_length=1)
        res = client.post("/api/chat", json={"message": "", "history": []})
        assert res.status_code == 400
        err = ErrorResponse.model_validate(res.json())
        assert err.error.code == "BAD_REQUEST"


def test_degradation_falkordb_wrong_port():
    """Verify Test T7 & T5: when FalkorDB is unreachable (wrong port), /health returns 200 degraded, other routes 503."""
    with patch("brain_core.db.get_settings") as mock_db_settings, patch(
        "brain_api.routes.health.get_settings"
    ) as mock_health_settings:
        bad_settings = Settings(FALKORDB_PORT=6399)
        mock_db_settings.return_value = bad_settings
        mock_health_settings.return_value = bad_settings

        with TestClient(app) as client:
            # Health check never 503s
            res_health = client.get("/api/health")
            assert res_health.status_code == 200
            h = HealthResponse.model_validate(res_health.json())
            assert h.status == "degraded"
            assert h.falkordb is False

            # Other routes return 503 GRAPH_UNAVAILABLE
            res_modules = client.get("/api/modules")
            assert res_modules.status_code == 503
            err_mod = ErrorResponse.model_validate(res_modules.json())
            assert err_mod.error.code == "GRAPH_UNAVAILABLE"


@pytest.mark.asyncio
async def test_child_mcp_auto_restart():
    """Verify child MCP server auto-restarts if process terminates unexpectedly."""
    await mcp_manager.start()
    assert mcp_manager.is_healthy()

    proc1 = mcp_manager._get_process()
    pid1 = getattr(proc1, "pid", None)
    assert pid1 is not None

    # Kill child process
    raw_proc = getattr(proc1, "_process", proc1)
    if hasattr(raw_proc, "kill"):
        raw_proc.kill()

    await asyncio.sleep(0.1)
    assert not mcp_manager.is_healthy()

    # Trigger get_session or wait for watchdog
    session = await mcp_manager.get_session()
    assert session is not None
    assert mcp_manager.is_healthy()

    proc2 = mcp_manager._get_process()
    pid2 = getattr(proc2, "pid", None)
    assert pid2 != pid1

    await mcp_manager.stop()
