"""Graph payload construction and property allow-list filtering.

Per ARCHITECTURE.md sections 6.1, 6.3, 16.3, 16.4:
- Per-label allow-lists of public properties.
- Strictly forbidden from public output: embedding, text_hash, body, text.
- Rejection of unknown node labels or edge types.
- Edge identity format: source|TYPE|target mapped from nodes' domain id properties.
- Translation of FalkorDB query results into GraphPayload (GraphNode and GraphEdge).
"""

from typing import Any, Dict, List, Optional, Set, Tuple, Union

from brain_core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    GraphPayload,
    NodeLabel,
)

# Allowed public node labels (strictly enforced)
VALID_LABELS: Set[str] = {
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
}

# Allowed public edge types (strictly enforced)
VALID_EDGE_TYPES: Set[str] = {
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
}

# Strictly forbidden properties that must NEVER be returned to clients
FORBIDDEN_PROPERTIES: Set[str] = {"embedding", "text_hash", "body", "text"}

# Allow-list of properties per node label from Section 6.1
PUBLIC_NODE_PROPS: Dict[str, Set[str]] = {
    "Person": {"id", "display", "source", "url", "role"},
    "Team": {"id", "display", "source", "url"},
    "Module": {"id", "display", "source", "url", "path"},
    "File": {"id", "display", "source", "url", "path", "synthetic_demo"},
    "PR": {
        "id",
        "display",
        "source",
        "url",
        "number",
        "state",
        "merged_at",
        "created_at",
        "body_excerpt",
        "synthetic_demo",
    },
    "Doc": {"id", "display", "source", "url", "path", "kind", "updated_at"},
    "Decision": {
        "id",
        "display",
        "source",
        "url",
        "summary",
        "rationale",
        "decided_at",
        "status",
    },
    "Ticket": {
        "id",
        "display",
        "source",
        "url",
        "key",
        "status",
        "created_at",
        "resolved_at",
        "description",
    },
    "Thread": {"id", "display", "source", "url", "channel", "started_at"},
    "ReviewRequest": {
        "id",
        "display",
        "source",
        "url",
        "note",
        "status",
        "created_at",
    },
    "Meta": {
        "id",
        "display",
        "source",
        "url",
        "embed_dim",
        "embed_model",
        "schema_version",
        "repo",
    },
}


def filter_node_properties(
    label: str, raw_props: Dict[str, Any]
) -> Dict[str, Union[str, int, float, bool, None]]:
    """Filter node properties according to the label allow-list.

    Why: Section 6.1 explicitly dictates that embedding, text_hash, body, and text
    must never be returned to clients to keep payloads small and protect internal hashes.
    """
    allowed_keys = PUBLIC_NODE_PROPS.get(label, set())
    filtered: Dict[str, Union[str, int, float, bool, None]] = {}

    for k, v in raw_props.items():
        if k in allowed_keys and k not in FORBIDDEN_PROPERTIES:
            if isinstance(v, (str, int, float, bool)) or v is None:
                filtered[k] = v
            else:
                filtered[k] = str(v)

    return filtered


def to_graph_node(node: Any) -> GraphNode:
    """Convert a FalkorDB Node object or dictionary into a validated GraphNode.

    Rejects unknown node labels.
    """
    # Extract labels
    if hasattr(node, "labels") and node.labels:
        label = node.labels[0]
    elif isinstance(node, dict) and "label" in node:
        label = node["label"]
    else:
        raise ValueError(f"Unable to extract label from node: {node}")

    if label not in VALID_LABELS:
        raise ValueError(f"Unknown node label '{label}'. Allowed: {VALID_LABELS}")

    # Extract raw properties
    if hasattr(node, "properties"):
        raw_props = node.properties
    elif isinstance(node, dict) and "props" in node:
        raw_props = node["props"]
    elif isinstance(node, dict):
        raw_props = node
    else:
        raw_props = {}

    if "id" not in raw_props:
        raise ValueError(f"Node of label '{label}' is missing required 'id' property")

    node_id = str(raw_props["id"])
    display = str(raw_props.get("display", node_id))
    filtered_props = filter_node_properties(label, raw_props)

    # Type assertion safe due to label validation check above
    typed_label: NodeLabel = label  # type: ignore[assignment]

    return GraphNode(
        id=node_id,
        label=typed_label,
        display=display,
        props=filtered_props,
    )


def to_graph_edge(
    edge: Any,
    source_id: Optional[str] = None,
    target_id: Optional[str] = None,
    internal_id_to_domain_id: Optional[Dict[int, str]] = None,
) -> GraphEdge:
    """Convert a FalkorDB Edge object or dictionary into a validated GraphEdge.

    Resolves endpoint domain IDs using internal_id_to_domain_id mapping if not directly provided.
    Why: Section 6.3 requires edge ID format 'source|TYPE|target' using domain IDs, not internal IDs.
    """
    # Extract relationship type
    if hasattr(edge, "relation"):
        rel_type = edge.relation
    elif isinstance(edge, dict) and "type" in edge:
        rel_type = edge["type"]
    else:
        raise ValueError(f"Unable to extract relation type from edge: {edge}")

    if rel_type not in VALID_EDGE_TYPES:
        raise ValueError(f"Unknown edge type '{rel_type}'. Allowed: {VALID_EDGE_TYPES}")

    # Resolve source domain ID
    src = source_id
    if src is None and hasattr(edge, "src_node") and internal_id_to_domain_id:
        src = internal_id_to_domain_id.get(edge.src_node)
    elif src is None and isinstance(edge, dict):
        src = edge.get("source")

    # Resolve target domain ID
    tgt = target_id
    if tgt is None and hasattr(edge, "dest_node") and internal_id_to_domain_id:
        tgt = internal_id_to_domain_id.get(edge.dest_node)
    elif tgt is None and isinstance(edge, dict):
        tgt = edge.get("target")

    if not src or not tgt:
        raise ValueError(
            f"Cannot resolve domain IDs for edge {rel_type} (source={src}, target={tgt})"
        )

    edge_id = f"{src}|{rel_type}|{tgt}"
    typed_type: EdgeType = rel_type  # type: ignore[assignment]

    return GraphEdge(
        id=edge_id,
        source=src,
        target=tgt,
        type=typed_type,
    )


def rows_to_graph_payload(rows: List[Any]) -> GraphPayload:
    """Parse Cypher query result rows into a unified GraphPayload.

    Performs a two-pass extraction:
    1. Extracts and deduplicates all nodes, building internal ID -> domain ID map.
    2. Extracts and deduplicates all edges, using the ID map to build standard edge IDs.
    """
    nodes_by_id: Dict[str, GraphNode] = {}
    edges_by_id: Dict[str, GraphEdge] = {}
    internal_to_domain: Dict[int, str] = {}

    unprocessed_edges: List[Any] = []

    # Flatten nested elements in rows
    elements: List[Any] = []
    for row in rows:
        if isinstance(row, (list, tuple)):
            for item in row:
                elements.append(item)
        else:
            elements.append(row)

    # First pass: Process nodes and build internal ID map
    for item in elements:
        if hasattr(item, "labels") and hasattr(item, "properties"):
            # It's a FalkorDB Node
            try:
                g_node = to_graph_node(item)
                nodes_by_id[g_node.id] = g_node
                if hasattr(item, "id"):
                    internal_to_domain[item.id] = g_node.id
            except ValueError:
                # Skip nodes with unexposed labels (e.g. Meta)
                continue
        elif hasattr(item, "relation") and hasattr(item, "src_node"):
            # It's a FalkorDB Edge
            unprocessed_edges.append(item)

    # Second pass: Process edges with resolved endpoints
    for edge in unprocessed_edges:
        try:
            g_edge = to_graph_edge(
                edge, internal_id_to_domain_id=internal_to_domain
            )
            edges_by_id[g_edge.id] = g_edge
        except ValueError:
            # Skip edges whose endpoints could not be resolved or are unknown types
            continue

    return GraphPayload(
        nodes=list(nodes_by_id.values()),
        edges=list(edges_by_id.values()),
    )
