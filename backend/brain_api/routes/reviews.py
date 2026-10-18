"""Reviews endpoints.

Per ARCHITECTURE.md Section 14:
GET /api/reviews -> list[ReviewRequestOut]
"""

from typing import List
from fastapi import APIRouter, Depends

from brain_api.dependencies import require_falkordb
from brain_core.models import ReviewRequestOut
from brain_core.services import list_reviews

router = APIRouter(tags=["reviews"], dependencies=[Depends(require_falkordb)])


@router.get("/reviews", response_model=List[ReviewRequestOut])
def get_reviews() -> List[ReviewRequestOut]:
    """Retrieve all open and closed decision review requests."""
    return list_reviews()
