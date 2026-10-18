"""Ingest control endpoints.

Per ARCHITECTURE.md Section 14:
POST /api/ingest/refresh -> IngestRefreshResponse
Exposure control: active only when ENABLE_INGEST_REFRESH=true; otherwise returns 404 NOT_FOUND.
"""

from fastapi import APIRouter, Depends

from brain_api.dependencies import require_falkordb
from brain_api.exceptions import NotFoundException
from brain_core.config import get_settings
from brain_core.models import IngestRefreshResponse
from brain_core.services import ingest_refresh

router = APIRouter(prefix="/ingest", tags=["ingest"], dependencies=[Depends(require_falkordb)])


def require_ingest_refresh() -> None:
    """Ensure ENABLE_INGEST_REFRESH is enabled before accessing ingest endpoints."""
    cfg = get_settings()
    if not cfg.ENABLE_INGEST_REFRESH:
        raise NotFoundException("Ingest refresh is disabled on this server.")


@router.post("/refresh", response_model=IngestRefreshResponse, dependencies=[Depends(require_ingest_refresh)])
def post_ingest_refresh() -> IngestRefreshResponse:
    """Trigger incremental ingest refresh from GitHub data."""
    return ingest_refresh()

