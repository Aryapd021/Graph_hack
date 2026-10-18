"""Test T5: Graceful degradation when FalkorDB is unreachable.

Per ARCHITECTURE.md Section 14, 16, 17:
- When FalkorDB is stopped or unreachable:
  - /api/health returns HTTP 200 with status="degraded", falkordb=False.
  - /api/chat returns HTTP 503 GRAPH_UNAVAILABLE formatted as ErrorResponse.
  - REST read/write endpoints return HTTP 503 GRAPH_UNAVAILABLE.
  - Never leaks stack traces to the client.
"""

from unittest.mock import patch
from fastapi.testclient import TestClient
import pytest

from brain_api.main import app
from brain_core.config import Settings
from brain_core.models import ErrorResponse, HealthResponse


def test_t5_falkordb_stopped_degradation():
    """Verify that when FalkorDB is unreachable:

    - /api/health returns HTTP 200 with status: degraded and falkordb: false.
    - /api/chat and all data routes return HTTP 503 GRAPH_UNAVAILABLE.
    - Error response body conforms strictly to ErrorResponse schema.
    """
    with patch("brain_core.db.get_settings") as mock_db_settings, patch(
        "brain_api.routes.health.get_settings"
    ) as mock_health_settings:
        # Point FalkorDB to an unreachable port
        unreachable_settings = Settings(FALKORDB_PORT=6398, FALKORDB_HOST="127.0.0.1")
        mock_db_settings.return_value = unreachable_settings
        mock_health_settings.return_value = unreachable_settings

        with TestClient(app) as client:
            # 1. Health endpoint returns degraded (never 503s)
            res_health = client.get("/api/health")
            assert res_health.status_code == 200
            health_body = HealthResponse.model_validate(res_health.json())
            assert health_body.status == "degraded"
            assert health_body.falkordb is False

            # 2. Chat endpoint returns 503 GRAPH_UNAVAILABLE
            res_chat = client.post(
                "/api/chat",
                json={"message": "Why did we decide X?", "history": []},
            )
            assert res_chat.status_code == 503
            err_chat = ErrorResponse.model_validate(res_chat.json())
            assert err_chat.error.code == "GRAPH_UNAVAILABLE"
            assert "traceback" not in res_chat.text.lower()

            # 3. Graph overview returns 503 GRAPH_UNAVAILABLE
            res_graph = client.get("/api/graph/overview")
            assert res_graph.status_code == 503
            err_graph = ErrorResponse.model_validate(res_graph.json())
            assert err_graph.error.code == "GRAPH_UNAVAILABLE"

            # 4. Decisions route returns 503 GRAPH_UNAVAILABLE
            res_dec = client.get("/api/decisions")
            assert res_dec.status_code == 503
            err_dec = ErrorResponse.model_validate(res_dec.json())
            assert err_dec.error.code == "GRAPH_UNAVAILABLE"

            # 5. Modules route returns 503 GRAPH_UNAVAILABLE
            res_mod = client.get("/api/modules")
            assert res_mod.status_code == 503
            err_mod = ErrorResponse.model_validate(res_mod.json())
            assert err_mod.error.code == "GRAPH_UNAVAILABLE"
