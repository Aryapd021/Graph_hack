"""Conversational agent endpoint.

Per ARCHITECTURE.md Section 12, 13, 14 & Task B8:
POST /api/chat -> ChatResponse
- Rate limited via sliding window in memory (CHAT_RATE_LIMIT_PER_MIN).
- Requires FalkorDB (503 GRAPH_UNAVAILABLE if down).
- Executes multi-turn Gemini agent loop over MCP tools.
"""

from fastapi import APIRouter, Depends, Request

from brain_api.agent.loop import execute_agent_loop
from brain_api.dependencies import require_falkordb
from brain_api.rate_limit import rate_limiter
from brain_core.models import (
    ChatRequest,
    ChatResponse,
)

router = APIRouter(tags=["chat"], dependencies=[Depends(require_falkordb)])


@router.post("/chat", response_model=ChatResponse)
async def post_chat(
    payload: ChatRequest,
    request: Request,
) -> ChatResponse:
    """Execute conversational reasoning turn over the graph via MCP tools."""
    # 1. Check rate limits
    rate_limiter.check_rate_limit(request)

    # 2. Execute Gemini agent loop
    return await execute_agent_loop(request=payload)
