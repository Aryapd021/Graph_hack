"""Shared data models and schemas for Company Brain.

Per ARCHITECTURE.md sections 13 and 14:
- NodeLabel, EdgeType, Freshness, and ErrorCode literals
- Graph primitives (GraphNode, GraphEdge, GraphPayload, Evidence, Highlight)
- ToolResult and TraceStep for MCP/Agent communication
- ChatRequest, ChatTurn, and ChatResponse
- DTO models (DecisionSummary, ModuleSummary, NodeDetail, ReviewRequestOut)
- Error response structures
- REST endpoint response models (health, flag, simulate-pr, reset, ingest refresh)
"""

from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field

# Enumeration of valid graph node labels
NodeLabel = Literal[
    "Person",
    "Team",
    "Module",
    "File",
    "PR",
    "Doc",
    "Decision",
    "Ticket",
    "Thread",
    "ReviewRequest",
]

# Enumeration of valid graph relationship types
EdgeType = Literal[
    "MEMBER_OF",
    "OWNS",
    "AUTHORED",
    "TOUCHES",
    "PART_OF",
    "PARTICIPATED_IN",
    "ASSIGNED_TO",
    "RESOLVES",
    "DECIDED_BY",
    "AFFECTS",
    "IMPLEMENTS",
    "DOCUMENTED_IN",
    "DISCUSSED_IN",
    "TRACKED_BY",
    "SUPERSEDED_BY",
    "MENTIONS",
    "COLLABORATES_WITH",
    "REVIEWS",
]

# Decision freshness states
Freshness = Literal["fresh", "stale", "superseded"]

# API error codes mapping to HTTP status codes
ErrorCode = Literal[
    "BAD_REQUEST",
    "NOT_FOUND",
    "RATE_LIMITED",
    "GRAPH_UNAVAILABLE",
    "LLM_ERROR",
    "INTERNAL",
]


class GraphNode(BaseModel):
    """Represents a graph node exposed to API and frontend."""

    id: str
    label: NodeLabel
    display: str
    # Why: props contains only public, non-secret fields filtered by allow-list
    props: Dict[str, Union[str, int, float, bool, None]]


class GraphEdge(BaseModel):
    """Represents a graph relationship between two nodes."""

    # Why: Edge identity is source|TYPE|target; DB internal IDs are never exposed
    id: str
    source: str
    target: str
    type: EdgeType


class GraphPayload(BaseModel):
    """Container for graph visualization payloads."""

    nodes: List[GraphNode]
    edges: List[GraphEdge]


class Evidence(BaseModel):
    """Ground-truth citation reference linking answers to graph elements."""

    node_id: str
    label: NodeLabel
    display: str
    url: Optional[str] = None


class Highlight(BaseModel):
    """Defines which nodes and edges should be highlighted in the graph visualizer."""

    node_ids: List[str]
    edge_ids: List[str]


class ToolResult(BaseModel):
    """Standardized result returned by all MCP tools."""

    ok: bool
    summary: str  # Must be concise (<= 300 chars)
    data: Dict[str, Any]
    evidence: List[Evidence]
    graph: GraphPayload
    cypher_ids: List[str]


class TraceStep(BaseModel):
    """Record of an individual tool call executed during agent reasoning."""

    step: int
    tool: str
    args: Dict[str, Any]
    ok: bool
    summary: str
    cypher_ids: List[str]
    duration_ms: int


class ChatTurn(BaseModel):
    """Single turn in a conversational session."""

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """Incoming user chat query."""

    # Why: Section 13 mandates message length 1..2000 chars and history max 10 turns
    message: str = Field(min_length=1, max_length=2000)
    history: List[ChatTurn] = Field(default_factory=list, max_length=10)


class ChatResponse(BaseModel):
    """Response returned by the /api/chat agent endpoint."""

    answer: str  # Markdown containing [[node_id]] chip markers
    citations: List[Evidence]
    trace: List[TraceStep]
    graph: GraphPayload
    highlight: Highlight


class DecisionSummary(BaseModel):
    """Summary of an architectural decision and its calculated drift status."""

    id: str
    title: str
    decided_at: int
    status: Literal["active", "superseded"]
    freshness: Freshness
    drift_count: int
    latest_drift_at: Optional[int] = None
    module_ids: List[str]
    decider: Optional[str] = None


class ModuleSummary(BaseModel):
    """Summary of a codebase module and its formal owning team."""

    id: str
    display: str
    path: str
    owner_team: Optional[str] = None


class NodeDetail(BaseModel):
    """Full detail view of an individual graph node."""

    id: str
    label: NodeLabel
    display: str
    props: Dict[str, Any]
    degree: int
    url: Optional[str] = None


class ReviewRequestOut(BaseModel):
    """Representation of an open or closed decision review request."""

    id: str
    decision_id: str
    decision: str
    note: str
    status: Literal["open", "closed"]
    created_at: int
    assignee_ids: List[str]


class ErrorBody(BaseModel):
    """Standardized error payload."""

    code: ErrorCode
    message: str


class ErrorResponse(BaseModel):
    """Root error container returned for all non-2xx REST responses."""

    error: ErrorBody


# --- REST API Inline Response Models from Section 14 ---


class HealthCounts(BaseModel):
    """Node and edge counts for the system health check."""

    nodes: int
    edges: int


class HealthResponse(BaseModel):
    """Response structure for /api/health."""

    status: Literal["ok", "degraded"]
    falkordb: bool
    mcp: bool
    counts: HealthCounts
    demo_mode: bool
    ingest_refresh: bool


class AssignedPerson(BaseModel):
    """Decider assigned to review a decision."""

    id: str
    display: str


class FlagDecisionRequest(BaseModel):
    """Request payload for POST /api/decisions/{id}/flag."""

    note: str


class FlagDecisionResponse(BaseModel):
    """Response for POST /api/decisions/{id}/flag."""

    review_request_id: str
    assigned_to: List[AssignedPerson]
    already_open: bool


class SimulatePRRequest(BaseModel):
    """Request payload for POST /api/demo/simulate-pr."""

    module_id: str
    title: str


class DecisionFreshnessChange(BaseModel):
    """Record of a decision whose freshness state changed during PR simulation."""

    decision_id: str
    before: Freshness
    after: Freshness


class SimulatePRResponse(BaseModel):
    """Response for POST /api/demo/simulate-pr."""

    pr_id: str
    changed: List[DecisionFreshnessChange]


class ResetDemoResponse(BaseModel):
    """Response for POST /api/demo/reset."""

    removed_nodes: int


class IngestRefreshResponse(BaseModel):
    """Response for POST /api/ingest/refresh."""

    new_prs: int
    new_files: int
