"""Module endpoints.

Per ARCHITECTURE.md Section 14:
GET /api/modules -> list[ModuleSummary]
"""

from typing import List
from fastapi import APIRouter, Depends

from brain_api.dependencies import require_falkordb
from brain_core.models import ModuleSummary
from brain_core.services import list_modules

router = APIRouter(tags=["modules"], dependencies=[Depends(require_falkordb)])


@router.get("/modules", response_model=List[ModuleSummary])
def get_modules() -> List[ModuleSummary]:
    """List all codebase modules sorted by path with formal owning team."""
    return list_modules()
