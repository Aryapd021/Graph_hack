"""Demo interactive control endpoints.

Per ARCHITECTURE.md Section 14:
POST /api/demo/simulate-pr -> SimulatePRResponse ({module_id:str, title:str})
POST /api/demo/reset -> ResetDemoResponse
Exposure control: active only when DEMO_MODE=true; otherwise returns 404 NOT_FOUND.
"""

from fastapi import APIRouter, Depends

from brain_api.dependencies import require_falkordb
from brain_api.exceptions import NotFoundException
from brain_core.config import get_settings
from brain_core.models import (
    ResetDemoResponse,
    SimulatePRRequest,
    SimulatePRResponse,
)
from brain_core.services import reset_demo, simulate_pr

router = APIRouter(prefix="/demo", tags=["demo"], dependencies=[Depends(require_falkordb)])


def require_demo_mode() -> None:
    """Ensure DEMO_MODE is enabled before accessing demo endpoints."""
    cfg = get_settings()
    if not cfg.DEMO_MODE:
        raise NotFoundException("Demo mode is disabled on this server.")


@router.post("/simulate-pr", response_model=SimulatePRResponse, dependencies=[Depends(require_demo_mode)])
def post_simulate_pr(payload: SimulatePRRequest) -> SimulatePRResponse:
    """Simulate a merged pull request touching a module and return freshness changes."""
    return simulate_pr(module_id=payload.module_id, title=payload.title)


@router.post("/reset", response_model=ResetDemoResponse, dependencies=[Depends(require_demo_mode)])
def post_reset_demo() -> ResetDemoResponse:
    """Reset demo state by removing synthetic demo PRs, demo files, and review requests."""
    return reset_demo()
