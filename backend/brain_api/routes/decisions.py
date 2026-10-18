"""Decisions endpoints.

Per ARCHITECTURE.md Section 14:
GET /api/decisions -> list[DecisionSummary] (all, by drift_count desc)
GET /api/decisions/{id}/trace -> ToolResult (same service as trace_decision)
POST /api/decisions/{id}/flag -> FlagDecisionResponse ({note:str})
"""

from typing import List
from fastapi import APIRouter, Depends

from brain_api.dependencies import require_falkordb
from brain_api.exceptions import NotFoundException
from brain_core.models import (
    DecisionSummary,
    FlagDecisionRequest,
    FlagDecisionResponse,
    ToolResult,
)
from brain_core.services import flag_for_review, list_decisions, trace_decision

router = APIRouter(tags=["decisions"], dependencies=[Depends(require_falkordb)])


@router.get("/decisions", response_model=List[DecisionSummary])
def get_decisions() -> List[DecisionSummary]:
    """Retrieve all decisions with dynamic freshness classification, ordered by drift count desc."""
    return list_decisions()


@router.get("/decisions/{id}/trace", response_model=ToolResult)
def get_decision_trace(id: str) -> ToolResult:
    """Retrieve the full decision provenance trace and freshness graph."""
    res = trace_decision(decision_id=id)
    if not res.ok:
        raise NotFoundException(f"Decision '{id}' not found.")
    return res


@router.post("/decisions/{id}/flag", response_model=FlagDecisionResponse)
def post_decision_flag(id: str, payload: FlagDecisionRequest) -> FlagDecisionResponse:
    """Flag a decision for review by creating or returning an open ReviewRequest."""
    res = flag_for_review(decision_id=id, note=payload.note)
    if not res.ok:
        raise NotFoundException(f"Decision '{id}' not found.")

    return FlagDecisionResponse(
        review_request_id=res.data["review_request_id"],
        assigned_to=res.data["assigned_to"],
        already_open=res.data["already_open"],
    )
