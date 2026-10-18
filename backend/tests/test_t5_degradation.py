"""Test T5: Graceful degradation when FalkorDB is unreachable.

Per ARCHITECTURE.md Section 14, 16, 17:
- When FalkorDB is stopped or unreachable:
  - /api/health returns HTTP 200 with status="degraded", falkordb=False.
  - /api/chat returns HTTP 503 GRAPH_UNAVAILABLE formatted as ErrorResponse.
  - REST read/write endpoints return HTTP 503 GRAPH_UNAVAILABLE.
  - Never leaks stack traces to the client.
- When run against a local container: stops container, verifies degraded and 503,
  then restarts container and waits for health check recovery.
"""

import os
import shutil
import subprocess
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
import pytest

from brain_api.main import app
from brain_core.config import Settings, get_settings
from brain_core.models import ErrorResponse, HealthResponse


def test_t5_falkordb_mock_degradation():
    """Verify that when FalkorDB is unreachable via network failure:

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


def test_t5_local_container_stop_and_restart():
    """Verify stopping local FalkorDB container produces degraded health and 503s,

    then container restart restores healthy state.
    Honors test-safety rule: aborts/skips if not running against local container.
    """
    cfg = get_settings()
    if cfg.FALKORDB_HOST not in ("localhost", "127.0.0.1", "falkordb") or cfg.FALKORDB_SSL:
        pytest.skip("Test safety rule: do not stop containers for remote/Cloud FalkorDB instances.")

    if not shutil.which("docker"):
        pytest.skip("Docker CLI not available in environment.")

    # Locate local container by image or name
    container_id = None
    try:
        out = subprocess.check_output(
            ["docker", "ps", "--filter", "ancestor=falkordb/falkordb:6.0.2", "--format", "{{.ID}}"],
            text=True,
            timeout=5,
        ).strip()
        if not out:
            out = subprocess.check_output(
                ["docker", "ps", "--filter", "name=falkordb", "--format", "{{.ID}}"],
                text=True,
                timeout=5,
            ).strip()
        if out:
            container_id = out.splitlines()[0].strip()
    except Exception:
        pytest.skip("Docker command failed; skipping live container stop test.")

    if not container_id:
        pytest.skip("No running local FalkorDB container found.")

    try:
        # Stop container
        subprocess.run(["docker", "stop", container_id], check=True, timeout=15, stdout=subprocess.DEVNULL)
        time.sleep(1)

        with TestClient(app) as client:
            res_health = client.get("/api/health")
            assert res_health.status_code == 200
            assert res_health.json()["falkordb"] is False
            assert res_health.json()["status"] == "degraded"

            res_chat = client.post("/api/chat", json={"message": "Why did we decide X?", "history": []})
            assert res_chat.status_code == 503
            assert res_chat.json()["error"]["code"] == "GRAPH_UNAVAILABLE"
    finally:
        # Always restart container
        subprocess.run(["docker", "start", container_id], check=True, timeout=15, stdout=subprocess.DEVNULL)

        # Wait for health recovery
        recovered = False
        with TestClient(app) as client:
            for _ in range(20):
                time.sleep(1)
                try:
                    res = client.get("/api/health")
                    if res.status_code == 200 and res.json().get("falkordb") is True:
                        recovered = True
                        break
                except Exception:
                    pass
        assert recovered, "FalkorDB container did not recover in time after restart."
