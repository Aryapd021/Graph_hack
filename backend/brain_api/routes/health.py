"""Health check endpoint.

Per ARCHITECTURE.md Section 14:
GET /api/health -> {status:"ok"|"degraded", falkordb:bool, mcp:bool, counts:{nodes:int, edges:int}, demo_mode:bool, ingest_refresh:bool}
"""

from fastapi import APIRouter

from brain_api.mcp_manager import mcp_manager
from brain_core.config import get_settings
from brain_core.db import get_db
from brain_core.models import HealthCounts, HealthResponse
from brain_core.services import counts

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Return system health status, DB connectivity, MCP child status, and graph counts."""
    cfg = get_settings()

    falkordb_ok = False
    graph_counts = HealthCounts(nodes=0, edges=0)

    try:
        db = get_db()
        db.connection.ping()
        falkordb_ok = True
        graph_counts = counts()
    except Exception:
        falkordb_ok = False

    mcp_ok = mcp_manager.is_healthy()

    status = "ok" if (falkordb_ok and mcp_ok) else "degraded"

    return HealthResponse(
        status=status,
        falkordb=falkordb_ok,
        mcp=mcp_ok,
        counts=graph_counts,
        demo_mode=cfg.DEMO_MODE,
        ingest_refresh=cfg.ENABLE_INGEST_REFRESH,
    )
