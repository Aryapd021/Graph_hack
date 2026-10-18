"""Graph and node detail endpoints.

Per ARCHITECTURE.md Section 14:
GET /api/graph/overview?limit=150 -> GraphPayload (limit 1..500)
GET /api/graph/neighborhood/{node_id}?limit=60 -> GraphPayload (one hop, Q18)
GET /api/node/{node_id} -> NodeDetail
"""

from fastapi import APIRouter, Depends, Query

from brain_api.dependencies import require_falkordb
from brain_api.exceptions import NotFoundException
from brain_core.models import GraphPayload, NodeDetail
from brain_core.services import graph_overview, neighborhood, node_detail

router = APIRouter(tags=["graph"], dependencies=[Depends(require_falkordb)])


@router.get("/graph/overview", response_model=GraphPayload)
def get_graph_overview(
    limit: int = Query(default=150, ge=1, le=500, description="Max relationships to return"),
) -> GraphPayload:
    """Retrieve overview subgraph containing decisions and their immediate neighbors."""
    return graph_overview(limit=limit)


@router.get("/graph/neighborhood/{node_id}", response_model=GraphPayload)
def get_graph_neighborhood(
    node_id: str,
    limit: int = Query(default=60, ge=1, le=200, description="Max neighbor connections"),
) -> GraphPayload:
    """Retrieve one-hop neighborhood subgraph centered around a specific node."""
    return neighborhood(node_id=node_id, limit=limit)


@router.get("/node/{node_id}", response_model=NodeDetail)
def get_node_detail(node_id: str) -> NodeDetail:
    """Retrieve detailed properties, label, degree, and URL for a single node."""
    detail = node_detail(node_id=node_id)
    if detail is None:
        raise NotFoundException(f"Node '{node_id}' not found.")
    return detail
