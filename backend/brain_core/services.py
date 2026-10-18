"""Core services and queries execution layer for Company Brain.

Per ARCHITECTURE.md sections 9, 10, 11 (tool contracts), 13, 14, 19:
- Tool-facing functions return ToolResult (summary <= 300 chars, data, evidence, graph, cypher_ids).
- Follows the 'Tool graph rule': ToolResult.graph contains the nodes in evidence plus edges
  implied by the relationships traversed.
- REST-only functions return section 13 DTOs.
- All queries use ONLY constants from brain_core.queries.
- Unknown IDs always give ok=False with a clear summary, never an unhandled exception.
"""

import hashlib
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from brain_core.config import Settings, get_settings
from brain_core.db import get_graph
from brain_core.embeddings import embed_query
from brain_core.freshness import classify
from brain_core.graph_payload import (
    filter_node_properties,
    rows_to_graph_payload,
    to_graph_node,
)
from brain_core.models import (
    DecisionFreshnessChange,
    DecisionSummary,
    Evidence,
    GraphEdge,
    GraphNode,
    GraphPayload,
    HealthCounts,
    IngestRefreshResponse,
    ModuleSummary,
    NodeDetail,
    ResetDemoResponse,
    ReviewRequestOut,
    SimulatePRResponse,
    ToolResult,
)
from brain_core.queries import (
    Q01,
    Q02,
    Q03,
    Q04,
    Q05,
    Q06,
    Q07,
    Q08,
    Q09,
    Q11A,
    Q11B,
    Q11C,
    Q11D,
    Q12,
    Q13,
    Q14,
    Q15A,
    Q15B,
    Q15C,
    Q17,
    Q18,
    Q19,
    Q20,
    Q21,
    Q22A,
    Q22B,
    Q23,
    Q24,
    Q25,
    Q26,
    Q27,
)
from brain_core.scoring import compute_score


def _make_evidence(node_id: str, label: str, display: str, url: Optional[str] = None) -> Evidence:
    """Create a validated Evidence citation model."""
    return Evidence(node_id=node_id, label=label, display=display, url=url)  # type: ignore[arg-type]


def _build_tool_result(
    ok: bool,
    summary: str,
    data: Dict[str, Any],
    evidence: List[Evidence],
    cypher_ids: List[str],
    graph_nodes: Optional[List[GraphNode]] = None,
    graph_edges: Optional[List[GraphEdge]] = None,
) -> ToolResult:
    """Construct a ToolResult ensuring summary length <= 300 and complete graph payload."""
    dedup_evidence: List[Evidence] = []
    seen_ev: Set[str] = set()
    for ev in evidence:
        if ev.node_id not in seen_ev:
            seen_ev.add(ev.node_id)
            dedup_evidence.append(ev)

    nodes_dict: Dict[str, GraphNode] = {}
    if graph_nodes:
        for gn in graph_nodes:
            nodes_dict[gn.id] = gn
    for ev in dedup_evidence:
        if ev.node_id not in nodes_dict:
            nodes_dict[ev.node_id] = GraphNode(
                id=ev.node_id,
                label=ev.label,
                display=ev.display,
                props=filter_node_properties(ev.label, {"id": ev.node_id, "display": ev.display, "url": ev.url}),
            )

    edges_dict: Dict[str, GraphEdge] = {}
    if graph_edges:
        for ge in graph_edges:
            edges_dict[ge.id] = ge

    return ToolResult(
        ok=ok,
        summary=summary[:300],
        data=data,
        evidence=dedup_evidence,
        graph=GraphPayload(nodes=list(nodes_dict.values()), edges=list(edges_dict.values())),
        cypher_ids=cypher_ids,
    )


# ==============================================================================
# TOOL-FACING SERVICES
# ==============================================================================


def search_knowledge(
    query: str,
    kinds: Optional[List[str]] = None,
    k: int = 5,
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> ToolResult:
    """Vector search across stored Doc, Decision, or Thread embeddings.

    Per ARCHITECTURE.md Section 11 & Rule 2:
    - Embeds query with embed_query (RETRIEVAL_QUERY).
    - Runs Q04 once per requested kind.
    - Merges hits and sorts ascending by score (lower distance = closer, per Gate G2).
    - Returns distance in each hit.
    """
    g = graph if graph is not None else get_graph()
    cfg = settings or get_settings()

    target_kinds = kinds or ["Decision", "Doc", "Thread"]
    try:
        vec = embed_query(query, settings=cfg)
    except Exception as exc:
        return _build_tool_result(
            ok=False,
            summary=f"Failed to generate embedding for search query: {exc}",
            data={"hits": []},
            evidence=[],
            cypher_ids=["Q04"],
        )

    all_hits: List[Dict[str, Any]] = []
    evidence_list: List[Evidence] = []
    graph_nodes: List[GraphNode] = []

    for kind in target_kinds:
        try:
            res = g.query(Q04, {"label": kind, "k": k, "vec": vec})
            for row in res.result_set:
                node_id = row[0]
                label = row[1]
                display = row[2] or node_id
                url = row[3]
                score = float(row[4])
                hit_data = {
                    "id": node_id,
                    "label": label,
                    "display": display,
                    "url": url,
                    "distance": score,
                }
                all_hits.append(hit_data)
        except Exception:
            continue

    # Gate G2: sort ascending by distance (lower score = closer)
    all_hits.sort(key=lambda h: h["distance"])
    top_hits = all_hits[:k]

    for h in top_hits:
        ev = _make_evidence(node_id=h["id"], label=h["label"], display=h["display"], url=h.get("url"))
        evidence_list.append(ev)
        graph_nodes.append(
            GraphNode(
                id=h["id"],
                label=h["label"],  # type: ignore[arg-type]
                display=h["display"],
                props=filter_node_properties(h["label"], {"id": h["id"], "display": h["display"], "url": h.get("url")}),
            )
        )

    summary = f"Found {len(top_hits)} closest matches across {', '.join(target_kinds)}."
    return _build_tool_result(
        ok=True,
        summary=summary,
        data={"hits": top_hits},
        evidence=evidence_list,
        cypher_ids=["Q04"],
        graph_nodes=graph_nodes,
        graph_edges=[],
    )


def get_decision(
    decision_id: str,
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> ToolResult:
    """Retrieve decision node and all immediate connected neighbors.

    Per ARCHITECTURE.md Section 11 & Q05.
    """
    g = graph if graph is not None else get_graph()
    res = g.query(Q05, {"id": decision_id})

    if not res.result_set or res.result_set[0][0] is None:
        return _build_tool_result(
            ok=False,
            summary=f"Decision '{decision_id}' not found.",
            data={},
            evidence=[],
            cypher_ids=["Q05"],
        )

    row = res.result_set[0]
    d_node = row[0]
    p_node = row[1]
    modules = row[2] or []
    docs = row[3] or []
    threads = row[4] or []
    tickets = row[5] or []
    prs = row[6] or []

    evidence: List[Evidence] = []
    graph_nodes: List[GraphNode] = []
    graph_edges: List[GraphEdge] = []

    # Decision node
    d_id = d_node.properties["id"]
    d_display = d_node.properties.get("display", d_id)
    d_props = filter_node_properties("Decision", d_node.properties)
    evidence.append(_make_evidence(d_id, "Decision", d_display, d_node.properties.get("url")))
    graph_nodes.append(GraphNode(id=d_id, label="Decision", display=d_display, props=d_props))

    # Decider person
    decider_data = None
    if p_node is not None:
        p_id = p_node.properties["id"]
        p_disp = p_node.properties.get("display", p_id)
        decider_data = {"id": p_id, "display": p_disp, "role": p_node.properties.get("role")}
        evidence.append(_make_evidence(p_id, "Person", p_disp, p_node.properties.get("url")))
        graph_nodes.append(GraphNode(id=p_id, label="Person", display=p_disp, props=filter_node_properties("Person", p_node.properties)))
        graph_edges.append(GraphEdge(id=f"{d_id}|DECIDED_BY|{p_id}", source=d_id, target=p_id, type="DECIDED_BY"))

    # Modules
    mod_data = []
    for m in modules:
        m_id = m.properties["id"]
        m_disp = m.properties.get("display", m_id)
        mod_data.append({"id": m_id, "display": m_disp, "path": m.properties.get("path")})
        evidence.append(_make_evidence(m_id, "Module", m_disp, m.properties.get("url")))
        graph_nodes.append(GraphNode(id=m_id, label="Module", display=m_disp, props=filter_node_properties("Module", m.properties)))
        graph_edges.append(GraphEdge(id=f"{d_id}|AFFECTS|{m_id}", source=d_id, target=m_id, type="AFFECTS"))

    # Docs
    doc_data = []
    for doc in docs:
        doc_id = doc.properties["id"]
        doc_disp = doc.properties.get("display", doc_id)
        doc_data.append({"id": doc_id, "display": doc_disp, "path": doc.properties.get("path")})
        evidence.append(_make_evidence(doc_id, "Doc", doc_disp, doc.properties.get("url")))
        graph_nodes.append(GraphNode(id=doc_id, label="Doc", display=doc_disp, props=filter_node_properties("Doc", doc.properties)))
        graph_edges.append(GraphEdge(id=f"{d_id}|DOCUMENTED_IN|{doc_id}", source=d_id, target=doc_id, type="DOCUMENTED_IN"))

    # Threads
    th_data = []
    for th in threads:
        th_id = th.properties["id"]
        th_disp = th.properties.get("display", th_id)
        th_data.append({"id": th_id, "display": th_disp, "channel": th.properties.get("channel")})
        evidence.append(_make_evidence(th_id, "Thread", th_disp, th.properties.get("url")))
        graph_nodes.append(GraphNode(id=th_id, label="Thread", display=th_disp, props=filter_node_properties("Thread", th.properties)))
        graph_edges.append(GraphEdge(id=f"{d_id}|DISCUSSED_IN|{th_id}", source=d_id, target=th_id, type="DISCUSSED_IN"))

    # Tickets
    tk_data = []
    for tk in tickets:
        tk_id = tk.properties["id"]
        tk_disp = tk.properties.get("display", tk_id)
        tk_data.append({"id": tk_id, "display": tk_disp, "key": tk.properties.get("key"), "status": tk.properties.get("status")})
        evidence.append(_make_evidence(tk_id, "Ticket", tk_disp, tk.properties.get("url")))
        graph_nodes.append(GraphNode(id=tk_id, label="Ticket", display=tk_disp, props=filter_node_properties("Ticket", tk.properties)))
        graph_edges.append(GraphEdge(id=f"{d_id}|TRACKED_BY|{tk_id}", source=d_id, target=tk_id, type="TRACKED_BY"))

    # Implementing PRs
    pr_data = []
    for pr in prs:
        pr_id = pr.properties["id"]
        pr_disp = pr.properties.get("display", pr_id)
        pr_data.append({"id": pr_id, "display": pr_disp, "number": pr.properties.get("number")})
        evidence.append(_make_evidence(pr_id, "PR", pr_disp, pr.properties.get("url")))
        graph_nodes.append(GraphNode(id=pr_id, label="PR", display=pr_disp, props=filter_node_properties("PR", pr.properties)))
        graph_edges.append(GraphEdge(id=f"{pr_id}|IMPLEMENTS|{d_id}", source=pr_id, target=d_id, type="IMPLEMENTS"))

    data = {
        "decision": d_props,
        "decider": decider_data,
        "modules": mod_data,
        "docs": doc_data,
        "threads": th_data,
        "tickets": tk_data,
        "prs": pr_data,
    }
    summary = f"Decision '{d_display}' with {len(modules)} modules, {len(prs)} PRs, {len(docs)} docs."
    return _build_tool_result(
        ok=True,
        summary=summary,
        data=data,
        evidence=evidence,
        cypher_ids=["Q05"],
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
    )


def check_freshness(
    decision_id: str,
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> ToolResult:
    """Evaluate decision freshness, drift count, and subsequent PR touchpoints.

    Per ARCHITECTURE.md Section 11 & Rules 5, 6:
    - Runs Q05 and Q08.
    - Classifies freshness via freshness.classify(status, drift_count, STALE_PR_THRESHOLD).
    """
    g = graph if graph is not None else get_graph()
    cfg = settings or get_settings()

    res_q05 = g.query(Q05, {"id": decision_id})
    if not res_q05.result_set or res_q05.result_set[0][0] is None:
        return _build_tool_result(
            ok=False,
            summary=f"Decision '{decision_id}' not found.",
            data={},
            evidence=[],
            cypher_ids=["Q05"],
        )

    d_node = res_q05.result_set[0][0]
    status = d_node.properties.get("status", "active")
    d_display = d_node.properties.get("display", decision_id)

    # Check forward supersession (Q06) to find superseded_by if applicable
    res_q06 = g.query(Q06, {"id": decision_id})
    superseded_by: Optional[str] = None
    if res_q06.result_set and res_q06.result_set[0][0] is not None:
        path = res_q06.result_set[0][0]
        nodes = path.nodes() if hasattr(path, "nodes") and callable(path.nodes) else []
        if len(nodes) > 1:
            superseded_by = nodes[-1].properties.get("id")

    # Q08: Drift detail
    res_q08 = g.query(Q08, {"id": decision_id, "limit": 100})
    later_prs: List[Dict[str, Any]] = []
    seen_pr_ids: Set[str] = set()

    evidence: List[Evidence] = [
        _make_evidence(decision_id, "Decision", d_display, d_node.properties.get("url"))
    ]
    graph_nodes: List[GraphNode] = [
        GraphNode(
            id=decision_id,
            label="Decision",
            display=d_display,
            props=filter_node_properties("Decision", d_node.properties),
        )
    ]
    graph_edges: List[GraphEdge] = []

    for row in res_q08.result_set:
        pr_id = row[0]
        pr_title = row[1] or pr_id
        merged_at = row[2]
        mod_id = row[3]
        later_prs.append({
            "pr_id": pr_id,
            "title": pr_title,
            "merged_at": merged_at,
            "module_id": mod_id,
        })
        seen_pr_ids.add(pr_id)
        evidence.append(_make_evidence(pr_id, "PR", pr_title))
        graph_nodes.append(GraphNode(id=pr_id, label="PR", display=pr_title, props={"id": pr_id, "display": pr_title, "merged_at": merged_at}))

    drift_count = len(seen_pr_ids)
    threshold = cfg.STALE_PR_THRESHOLD
    freshness_state = classify(status=status, drift_count=drift_count, threshold=threshold)

    data = {
        "freshness": freshness_state,
        "drift_count": drift_count,
        "threshold": threshold,
        "later_prs": later_prs,
        "superseded_by": superseded_by,
    }
    summary = f"Decision '{d_display}' is {freshness_state} (drift count: {drift_count}, threshold: {threshold})."
    return _build_tool_result(
        ok=True,
        summary=summary,
        data=data,
        evidence=evidence,
        cypher_ids=["Q05", "Q06", "Q08"],
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
    )


# Alias for MCP server naming consistency
check_decision_freshness = check_freshness


def trace_decision(
    decision_id: str,
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> ToolResult:
    """Trace decision lifecycle chain and freshness status.

    Per ARCHITECTURE.md Section 11 & Rule 5:
    Chain order: decided_by, implemented_by, tracked_by, discussed_in, documented_in,
    supersedes, superseded_by; plus freshness.
    """
    g = graph if graph is not None else get_graph()
    cfg = settings or get_settings()

    res_q05 = g.query(Q05, {"id": decision_id})
    if not res_q05.result_set or res_q05.result_set[0][0] is None:
        return _build_tool_result(
            ok=False,
            summary=f"Decision '{decision_id}' not found.",
            data={},
            evidence=[],
            cypher_ids=["Q05"],
        )

    row = res_q05.result_set[0]
    d_node = row[0]
    p_node = row[1]
    modules = row[2] or []
    docs = row[3] or []
    threads = row[4] or []
    tickets = row[5] or []
    prs = row[6] or []

    d_id = d_node.properties["id"]
    d_display = d_node.properties.get("display", d_id)
    d_status = d_node.properties.get("status", "active")

    chain: List[Dict[str, Any]] = []
    evidence: List[Evidence] = [
        _make_evidence(d_id, "Decision", d_display, d_node.properties.get("url"))
    ]
    graph_nodes: List[GraphNode] = [
        GraphNode(id=d_id, label="Decision", display=d_display, props=filter_node_properties("Decision", d_node.properties))
    ]
    graph_edges: List[GraphEdge] = []

    # 1. decided_by
    if p_node is not None:
        p_id = p_node.properties["id"]
        p_disp = p_node.properties.get("display", p_id)
        ev_p = _make_evidence(p_id, "Person", p_disp, p_node.properties.get("url"))
        chain.append({"relation": "decided_by", "node": ev_p})
        evidence.append(ev_p)
        graph_nodes.append(GraphNode(id=p_id, label="Person", display=p_disp, props=filter_node_properties("Person", p_node.properties)))
        graph_edges.append(GraphEdge(id=f"{d_id}|DECIDED_BY|{p_id}", source=d_id, target=p_id, type="DECIDED_BY"))

    # 2. implemented_by
    for pr in prs:
        pr_id = pr.properties["id"]
        pr_disp = pr.properties.get("display", pr_id)
        ev_pr = _make_evidence(pr_id, "PR", pr_disp, pr.properties.get("url"))
        chain.append({"relation": "implemented_by", "node": ev_pr})
        evidence.append(ev_pr)
        graph_nodes.append(GraphNode(id=pr_id, label="PR", display=pr_disp, props=filter_node_properties("PR", pr.properties)))
        graph_edges.append(GraphEdge(id=f"{pr_id}|IMPLEMENTS|{d_id}", source=pr_id, target=d_id, type="IMPLEMENTS"))

    # 3. tracked_by
    for tk in tickets:
        tk_id = tk.properties["id"]
        tk_disp = tk.properties.get("display", tk_id)
        ev_tk = _make_evidence(tk_id, "Ticket", tk_disp, tk.properties.get("url"))
        chain.append({"relation": "tracked_by", "node": ev_tk})
        evidence.append(ev_tk)
        graph_nodes.append(GraphNode(id=tk_id, label="Ticket", display=tk_disp, props=filter_node_properties("Ticket", tk.properties)))
        graph_edges.append(GraphEdge(id=f"{d_id}|TRACKED_BY|{tk_id}", source=d_id, target=tk_id, type="TRACKED_BY"))

    # 4. discussed_in
    for th in threads:
        th_id = th.properties["id"]
        th_disp = th.properties.get("display", th_id)
        ev_th = _make_evidence(th_id, "Thread", th_disp, th.properties.get("url"))
        chain.append({"relation": "discussed_in", "node": ev_th})
        evidence.append(ev_th)
        graph_nodes.append(GraphNode(id=th_id, label="Thread", display=th_disp, props=filter_node_properties("Thread", th.properties)))
        graph_edges.append(GraphEdge(id=f"{d_id}|DISCUSSED_IN|{th_id}", source=d_id, target=th_id, type="DISCUSSED_IN"))

    # 5. documented_in
    for doc in docs:
        doc_id = doc.properties["id"]
        doc_disp = doc.properties.get("display", doc_id)
        ev_doc = _make_evidence(doc_id, "Doc", doc_disp, doc.properties.get("url"))
        chain.append({"relation": "documented_in", "node": ev_doc})
        evidence.append(ev_doc)
        graph_nodes.append(GraphNode(id=doc_id, label="Doc", display=doc_disp, props=filter_node_properties("Doc", doc.properties)))
        graph_edges.append(GraphEdge(id=f"{d_id}|DOCUMENTED_IN|{doc_id}", source=d_id, target=doc_id, type="DOCUMENTED_IN"))

    # 6. supersedes (Q07: decisions this one supersedes)
    res_q07 = g.query(Q07, {"id": decision_id})
    for r in res_q07.result_set:
        path = r[0]
        if hasattr(path, "nodes") and callable(path.nodes):
            p_nodes = path.nodes()
            if len(p_nodes) > 1:
                older = p_nodes[0]
                old_id = older.properties["id"]
                old_disp = older.properties.get("display", old_id)
                ev_old = _make_evidence(old_id, "Decision", old_disp, older.properties.get("url"))
                chain.append({"relation": "supersedes", "node": ev_old})
                evidence.append(ev_old)
                graph_nodes.append(GraphNode(id=old_id, label="Decision", display=old_disp, props=filter_node_properties("Decision", older.properties)))
                graph_edges.append(GraphEdge(id=f"{old_id}|SUPERSEDED_BY|{d_id}", source=old_id, target=d_id, type="SUPERSEDED_BY"))

    # 7. superseded_by (Q06: decisions that supersede this one)
    res_q06 = g.query(Q06, {"id": decision_id})
    for r in res_q06.result_set:
        path = r[0]
        if hasattr(path, "nodes") and callable(path.nodes):
            p_nodes = path.nodes()
            if len(p_nodes) > 1:
                newer = p_nodes[-1]
                new_id = newer.properties["id"]
                new_disp = newer.properties.get("display", new_id)
                ev_new = _make_evidence(new_id, "Decision", new_disp, newer.properties.get("url"))
                chain.append({"relation": "superseded_by", "node": ev_new})
                evidence.append(ev_new)
                graph_nodes.append(GraphNode(id=new_id, label="Decision", display=new_disp, props=filter_node_properties("Decision", newer.properties)))
                graph_edges.append(GraphEdge(id=f"{d_id}|SUPERSEDED_BY|{new_id}", source=d_id, target=new_id, type="SUPERSEDED_BY"))

    # Freshness via Q08
    res_q08 = g.query(Q08, {"id": decision_id, "limit": 100})
    drift_prs = set(row[0] for row in res_q08.result_set)
    drift_count = len(drift_prs)
    freshness_state = classify(status=d_status, drift_count=drift_count, threshold=cfg.STALE_PR_THRESHOLD)

    data = {
        "chain": chain,
        "freshness": freshness_state,
    }
    summary = f"Trace for '{d_display}': {len(chain)} linked entities, status is {freshness_state}."
    return _build_tool_result(
        ok=True,
        summary=summary,
        data=data,
        evidence=evidence,
        cypher_ids=["Q05", "Q06", "Q07", "Q08"],
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
    )


def list_stale_decisions(
    limit: int = 10,
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> ToolResult:
    """List architectural decisions classified as stale, ordered by drift count descending.

    Per ARCHITECTURE.md Section 11 & Q09.
    """
    g = graph if graph is not None else get_graph()
    cfg = settings or get_settings()

    res_q09 = g.query(Q09)
    stale_summaries: List[DecisionSummary] = []
    evidence: List[Evidence] = []
    graph_nodes: List[GraphNode] = []

    for row in res_q09.result_set:
        d_id = row[0]
        title = row[1] or d_id
        decided_at = row[2]
        status = row[3] or "active"
        drift_count = row[4]
        latest_drift = row[5]
        decider = row[6]
        module_ids = row[7] or []

        freshness_state = classify(status=status, drift_count=drift_count, threshold=cfg.STALE_PR_THRESHOLD)
        if freshness_state == "stale":
            ds = DecisionSummary(
                id=d_id,
                title=title,
                decided_at=decided_at,
                status=status,
                freshness=freshness_state,
                drift_count=drift_count,
                latest_drift_at=latest_drift,
                module_ids=module_ids,
                decider=decider,
            )
            stale_summaries.append(ds)
            ev = _make_evidence(d_id, "Decision", title)
            evidence.append(ev)
            graph_nodes.append(GraphNode(
                id=d_id,
                label="Decision",
                display=title,
                props={"id": d_id, "display": title, "decided_at": decided_at, "status": status},
            ))

    top_stale = stale_summaries[:limit]
    data = {"decisions": [ds.model_dump() for ds in top_stale]}
    summary = f"Found {len(stale_summaries)} stale decisions (showing top {len(top_stale)})."
    return _build_tool_result(
        ok=True,
        summary=summary,
        data=data,
        evidence=evidence[:limit],
        cypher_ids=["Q09"],
        graph_nodes=graph_nodes[:limit],
        graph_edges=[],
    )


def who_owns(
    module: str,
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> ToolResult:
    """Identify formal owning teams and top contributors for a module.

    Per ARCHITECTURE.md Section 11 & Rule 3:
    - Resolves module via Q03.
    - Zero matches: ok=False.
    - >1 matches: ok=False with data.candidates [{id, display, path}].
    - Queries Q01 and Q02.
    - Computes ownership_gap (true if top contributor not member of an owning team).
    """
    g = graph if graph is not None else get_graph()

    res_q03 = g.query(Q03, {"q": module})
    if not res_q03.result_set:
        return _build_tool_result(
            ok=False,
            summary=f"No module found matching '{module}'.",
            data={},
            evidence=[],
            cypher_ids=["Q03"],
        )

    matched_rows = res_q03.result_set
    if len(matched_rows) > 1:
        q_clean = module.strip().rstrip("/").lower()
        exact_matches = [
            r for r in matched_rows
            if (r[2] and r[2].strip().rstrip("/").lower() == q_clean)
            or (r[1] and r[1].strip().rstrip("/").lower() == q_clean)
        ]
        if len(exact_matches) == 1:
            matched_rows = exact_matches
        else:
            candidates = [{"id": r[0], "display": r[1], "path": r[2]} for r in matched_rows]
            return _build_tool_result(
                ok=False,
                summary=f"Multiple modules matched '{module}'. Please specify one.",
                data={"candidates": candidates},
                evidence=[],
                cypher_ids=["Q03"],
            )

    mod_id = matched_rows[0][0]
    mod_display = matched_rows[0][1]
    mod_path = matched_rows[0][2]

    # Q01: Formal owners
    res_q01 = g.query(Q01, {"module_id": mod_id})
    owner_teams: List[Dict[str, Any]] = []
    all_team_member_ids: Set[str] = set()

    evidence: List[Evidence] = [
        _make_evidence(mod_id, "Module", mod_display)
    ]
    graph_nodes: List[GraphNode] = [
        GraphNode(id=mod_id, label="Module", display=mod_display, props={"id": mod_id, "display": mod_display, "path": mod_path})
    ]
    graph_edges: List[GraphEdge] = []

    for r in res_q01.result_set:
        t_id = r[0]
        if t_id is not None:
            t_display = r[1]
            members = r[2] or []
            owner_teams.append({
                "id": t_id,
                "display": t_display,
                "member_ids": members,
            })
            all_team_member_ids.update(members)
            evidence.append(_make_evidence(t_id, "Team", t_display))
            graph_nodes.append(GraphNode(id=t_id, label="Team", display=t_display, props={"id": t_id, "display": t_display}))
            graph_edges.append(GraphEdge(id=f"{t_id}|OWNS|{mod_id}", source=t_id, target=mod_id, type="OWNS"))

    # Q02: De facto contributors
    res_q02 = g.query(Q02, {"module_id": mod_id, "limit": 5})
    top_contributors: List[Dict[str, Any]] = []
    for r in res_q02.result_set:
        p_id = r[0]
        p_name = r[1]
        pr_count = r[2]
        last_active = r[3]
        top_contributors.append({
            "person_id": p_id,
            "display": p_name,
            "pr_count": pr_count,
            "last_active": last_active,
        })
        evidence.append(_make_evidence(p_id, "Person", p_name))
        graph_nodes.append(GraphNode(id=p_id, label="Person", display=p_name, props={"id": p_id, "display": p_name, "last_active": last_active}))

    # Ownership gap: true if top contributor is not a member of an owning team
    ownership_gap = False
    if top_contributors:
        top_person_id = top_contributors[0]["person_id"]
        if not owner_teams or top_person_id not in all_team_member_ids:
            ownership_gap = True

    data = {
        "module": {"id": mod_id, "display": mod_display, "path": mod_path},
        "owner_teams": owner_teams,
        "top_contributors": top_contributors,
        "ownership_gap": ownership_gap,
    }
    summary = f"Module '{mod_display}': owned by {len(owner_teams)} teams, {len(top_contributors)} contributors (gap={ownership_gap})."
    return _build_tool_result(
        ok=True,
        summary=summary,
        data=data,
        evidence=evidence,
        cypher_ids=["Q03", "Q01", "Q02"],
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
    )


def who_knows(
    topic: str,
    limit: int = 5,
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> ToolResult:
    """Identify top institutional experts on a topic across PRs, threads, and decisions.

    Per ARCHITECTURE.md Section 11 & Rule 4:
    - Finds modules via Q03 on topic + vector hits via Q23 (cap 5).
    - Computes expertise scores via scoring.py with Q11A, Q11B, Q11C.
    - Fetches contributor details via Q11D.
    """
    g = graph if graph is not None else get_graph()
    cfg = settings or get_settings()

    # 1. Modules from Q03
    res_q03 = g.query(Q03, {"q": topic})
    module_ids: List[str] = [r[0] for r in res_q03.result_set]

    # 2. Vector search hits on topic -> Q23 modules
    cypher_ids = ["Q03"]
    try:
        vec = embed_query(topic, settings=cfg)
        res_q04 = g.query(Q04, {"label": "Doc", "k": 5, "vec": vec})
        cypher_ids.append("Q04")
        hit_ids = [r[0] for r in res_q04.result_set]
        if hit_ids:
            res_q23 = g.query(Q23, {"ids": hit_ids})
            cypher_ids.append("Q23")
            for r in res_q23.result_set:
                m_id = r[0]
                if m_id not in module_ids:
                    module_ids.append(m_id)
    except Exception:
        pass

    # Cap to 5 modules total
    module_ids = module_ids[:5]
    if not module_ids:
        return _build_tool_result(
            ok=False,
            summary=f"No modules found related to topic '{topic}'.",
            data={"modules": [], "experts": []},
            evidence=[],
            cypher_ids=cypher_ids,
        )

    # 3. Score components via Q11A, Q11B, Q11C
    pr_counts: Dict[str, int] = {}
    res_q11a = g.query(Q11A, {"module_ids": module_ids})
    cypher_ids.append("Q11A")
    for r in res_q11a.result_set:
        pr_counts[r[0]] = r[1]

    thread_counts: Dict[str, int] = {}
    res_q11b = g.query(Q11B, {"module_ids": module_ids})
    cypher_ids.append("Q11B")
    for r in res_q11b.result_set:
        thread_counts[r[0]] = r[1]

    decision_counts: Dict[str, int] = {}
    res_q11c = g.query(Q11C, {"module_ids": module_ids})
    cypher_ids.append("Q11C")
    for r in res_q11c.result_set:
        decision_counts[r[0]] = r[1]

    all_person_ids = set(pr_counts.keys()) | set(thread_counts.keys()) | set(decision_counts.keys())
    if not all_person_ids:
        return _build_tool_result(
            ok=True,
            summary=f"Topic '{topic}' mapped to {len(module_ids)} modules, but found no active contributors.",
            data={"modules": module_ids, "experts": []},
            evidence=[],
            cypher_ids=cypher_ids,
        )

    scored_persons: List[Tuple[str, int, Dict[str, int]]] = []
    for pid in all_person_ids:
        prs = pr_counts.get(pid, 0)
        ths = thread_counts.get(pid, 0)
        decs = decision_counts.get(pid, 0)
        score = compute_score(prs=prs, threads=ths, decisions=decs)
        scored_persons.append((pid, score, {"prs": prs, "threads": ths, "decisions": decs}))

    scored_persons.sort(key=lambda x: x[1], reverse=True)
    top_experts = scored_persons[:limit]
    top_pids = [x[0] for x in top_experts]

    # 4. Details via Q11D
    res_q11d = g.query(Q11D, {"ids": top_pids})
    cypher_ids.append("Q11D")
    details_map = {r[0]: {"display": r[1], "role": r[2]} for r in res_q11d.result_set}

    experts: List[Dict[str, Any]] = []
    evidence: List[Evidence] = []
    graph_nodes: List[GraphNode] = []

    for pid, score, breakdown in top_experts:
        p_info = details_map.get(pid, {"display": pid, "role": None})
        disp = p_info["display"] or pid
        role = p_info["role"]
        experts.append({
            "person_id": pid,
            "display": disp,
            "role": role,
            "score": score,
            "breakdown": breakdown,
        })
        ev = _make_evidence(pid, "Person", disp)
        evidence.append(ev)
        graph_nodes.append(GraphNode(id=pid, label="Person", display=disp, props={"id": pid, "display": disp, "role": role}))

    for mid in module_ids:
        evidence.append(_make_evidence(mid, "Module", mid))
        graph_nodes.append(GraphNode(id=mid, label="Module", display=mid, props={"id": mid, "display": mid}))

    summary = f"Found {len(experts)} experts across {len(module_ids)} modules related to '{topic}'."
    return _build_tool_result(
        ok=True,
        summary=summary,
        data={"modules": module_ids, "experts": experts},
        evidence=evidence,
        cypher_ids=cypher_ids,
        graph_nodes=graph_nodes,
        graph_edges=[],
    )


def recent_changes(
    module: str,
    since_days: int = 30,
    limit: int = 10,
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> ToolResult:
    """Retrieve recently merged PRs that touched files in a module.

    Per ARCHITECTURE.md Section 11 & Rule 3:
    - Resolves module via Q03.
    - Runs Q12.
    """
    g = graph if graph is not None else get_graph()

    res_q03 = g.query(Q03, {"q": module})
    if not res_q03.result_set:
        return _build_tool_result(
            ok=False,
            summary=f"No module found matching '{module}'.",
            data={},
            evidence=[],
            cypher_ids=["Q03"],
        )

    matched_rows_rc = res_q03.result_set
    if len(matched_rows_rc) > 1:
        q_clean = module.strip().rstrip("/").lower()
        exact_matches = [
            r for r in matched_rows_rc
            if (r[2] and r[2].strip().rstrip("/").lower() == q_clean)
            or (r[1] and r[1].strip().rstrip("/").lower() == q_clean)
        ]
        if len(exact_matches) == 1:
            matched_rows_rc = exact_matches
        else:
            candidates = [{"id": r[0], "display": r[1], "path": r[2]} for r in matched_rows_rc]
            return _build_tool_result(
                ok=False,
                summary=f"Multiple modules matched '{module}'. Please specify one.",
                data={"candidates": candidates},
                evidence=[],
                cypher_ids=["Q03"],
            )

    mod_id = matched_rows_rc[0][0]
    mod_display = matched_rows_rc[0][1]
    mod_path = matched_rows_rc[0][2]

    since_timestamp = int(time.time()) - (since_days * 86400)
    res_q12 = g.query(Q12, {"module_id": mod_id, "since": since_timestamp, "limit": limit})

    prs: List[Dict[str, Any]] = []
    evidence: List[Evidence] = [
        _make_evidence(mod_id, "Module", mod_display)
    ]
    graph_nodes: List[GraphNode] = [
        GraphNode(id=mod_id, label="Module", display=mod_display, props={"id": mod_id, "display": mod_display, "path": mod_path})
    ]

    for r in res_q12.result_set:
        pr_id = r[0]
        pr_title = r[1] or pr_id
        merged_at = r[2]
        prs.append({
            "id": pr_id,
            "title": pr_title,
            "merged_at": merged_at,
        })
        ev = _make_evidence(pr_id, "PR", pr_title)
        evidence.append(ev)
        graph_nodes.append(GraphNode(id=pr_id, label="PR", display=pr_title, props={"id": pr_id, "display": pr_title, "merged_at": merged_at}))

    data = {
        "module": {"id": mod_id, "display": mod_display, "path": mod_path},
        "prs": prs,
    }
    summary = f"Module '{mod_display}': {len(prs)} PRs merged in the last {since_days} days."
    return _build_tool_result(
        ok=True,
        summary=summary,
        data=data,
        evidence=evidence,
        cypher_ids=["Q03", "Q12"],
        graph_nodes=graph_nodes,
        graph_edges=[],
    )


def connection_path(
    from_id: str,
    to_id: str,
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> ToolResult:
    """Find the shortest connection path between two graph nodes.

    Per ARCHITECTURE.md Section 11 & Q13:
    path: [{node: Evidence, edge_type: str|null, direction: 'out'|'in'|null}] (first entry has null edge).
    """
    g = graph if graph is not None else get_graph()
    try:
        res_q13 = g.query(Q13, {"a": from_id, "b": to_id})
    except Exception as exc:
        return _build_tool_result(
            ok=False,
            summary=f"Path search failed between '{from_id}' and '{to_id}': {exc}",
            data={"path": []},
            evidence=[],
            cypher_ids=["Q13"],
        )

    if not res_q13.result_set or res_q13.result_set[0][0] is None:
        return _build_tool_result(
            ok=False,
            summary=f"No connection path found between '{from_id}' and '{to_id}'.",
            data={"path": []},
            evidence=[],
            cypher_ids=["Q13"],
        )

    path_obj = res_q13.result_set[0][0]
    p_nodes = path_obj.nodes() if hasattr(path_obj, "nodes") and callable(path_obj.nodes) else []
    p_edges = path_obj.edges() if hasattr(path_obj, "edges") and callable(path_obj.edges) else []

    if not p_nodes:
        return _build_tool_result(
            ok=False,
            summary=f"No path returned between '{from_id}' and '{to_id}'.",
            data={"path": []},
            evidence=[],
            cypher_ids=["Q13"],
        )

    path_data: List[Dict[str, Any]] = []
    evidence: List[Evidence] = []
    graph_nodes: List[GraphNode] = []
    graph_edges: List[GraphEdge] = []

    # First entry has null edge
    first_node = p_nodes[0]
    fn_id = first_node.properties.get("id", str(first_node.id))
    fn_label = first_node.labels[0] if first_node.labels else "Entity"
    fn_disp = first_node.properties.get("display", fn_id)
    ev_first = _make_evidence(fn_id, fn_label, fn_disp, first_node.properties.get("url"))
    path_data.append({"node": ev_first, "edge_type": None, "direction": None})
    evidence.append(ev_first)
    graph_nodes.append(GraphNode(id=fn_id, label=fn_label, display=fn_disp, props=filter_node_properties(fn_label, first_node.properties)))

    for i in range(1, len(p_nodes)):
        curr_node = p_nodes[i]
        cn_id = curr_node.properties.get("id", str(curr_node.id))
        cn_label = curr_node.labels[0] if curr_node.labels else "Entity"
        cn_disp = curr_node.properties.get("display", cn_id)

        edge = p_edges[i - 1] if i - 1 < len(p_edges) else None
        edge_type = edge.relation if edge else None

        # Determine edge direction relative to previous node
        direction: Optional[str] = None
        if edge and hasattr(edge, "src_node"):
            prev_node_internal_id = p_nodes[i - 1].id
            if edge.src_node == prev_node_internal_id:
                direction = "out"
            else:
                direction = "in"

        ev_curr = _make_evidence(cn_id, cn_label, cn_disp, curr_node.properties.get("url"))
        path_data.append({"node": ev_curr, "edge_type": edge_type, "direction": direction})
        evidence.append(ev_curr)
        graph_nodes.append(GraphNode(id=cn_id, label=cn_label, display=cn_disp, props=filter_node_properties(cn_label, curr_node.properties)))

        if edge and edge_type:
            prev_id = p_nodes[i - 1].properties.get("id", str(p_nodes[i - 1].id))
            src = prev_id if direction == "out" else cn_id
            tgt = cn_id if direction == "out" else prev_id
            graph_edges.append(GraphEdge(id=f"{src}|{edge_type}|{tgt}", source=src, target=tgt, type=edge_type))  # type: ignore[arg-type]

    summary = f"Path of length {len(p_nodes) - 1} found between '{from_id}' and '{to_id}'."
    return _build_tool_result(
        ok=True,
        summary=summary,
        data={"path": path_data},
        evidence=evidence,
        cypher_ids=["Q13"],
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
    )


def key_connectors(
    limit: int = 5,
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> ToolResult:
    """Identify key collaborative connectors using PageRank over COLLABORATES_WITH edges.

    Per ARCHITECTURE.md Section 11 & Q14.
    """
    g = graph if graph is not None else get_graph()
    res_q14 = g.query(Q14, {"limit": limit})

    people: List[Dict[str, Any]] = []
    evidence: List[Evidence] = []
    graph_nodes: List[GraphNode] = []

    for r in res_q14.result_set:
        p_id = r[0]
        p_disp = r[1] or p_id
        score = float(r[2])
        people.append({"id": p_id, "display": p_disp, "score": score})
        ev = _make_evidence(p_id, "Person", p_disp)
        evidence.append(ev)
        graph_nodes.append(GraphNode(id=p_id, label="Person", display=p_disp, props={"id": p_id, "display": p_disp, "pagerank": score}))

    summary = f"Found top {len(people)} key connectors by PageRank centrality."
    return _build_tool_result(
        ok=True,
        summary=summary,
        data={"people": people},
        evidence=evidence,
        cypher_ids=["Q14"],
        graph_nodes=graph_nodes,
        graph_edges=[],
    )


def flag_for_review(
    decision_id: str,
    note: str,
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> ToolResult:
    """Flag an architectural decision for review by creating or returning an open ReviewRequest.

    Per ARCHITECTURE.md Section 11 & Rule 7:
    - Runs Q15A first. If open request exists: return already_open=True with its id.
    - Otherwise runs Q05 to confirm existence & get title.
    - Runs Q15B (rr_id = 'rr_' + 8 hex, display = 'Review: <title>', now = epoch seconds).
    - Runs Q15C to assign to the decider.
    """
    g = graph if graph is not None else get_graph()

    # 1. Check existing open review request
    res_q15a = g.query(Q15A, {"decision_id": decision_id})
    if res_q15a.result_set:
        existing_rr_id = res_q15a.result_set[0][0]
        # Get assigned person if any from Q20
        res_q20 = g.query(Q20)
        assigned: List[Dict[str, Any]] = []
        for r in res_q20.result_set:
            rr_obj = r[0]
            if rr_obj.properties.get("id") == existing_rr_id:
                assignee_ids = r[3] or []
                for aid in assignee_ids:
                    assigned.append({"id": aid, "display": aid})
                break
        return _build_tool_result(
            ok=True,
            summary=f"Decision '{decision_id}' already has an open review request ({existing_rr_id}).",
            data={
                "review_request_id": existing_rr_id,
                "assigned_to": assigned,
                "already_open": True,
            },
            evidence=[_make_evidence(decision_id, "Decision", decision_id)],
            cypher_ids=["Q15A"],
        )

    # 2. Check decision existence and title via Q05
    res_q05 = g.query(Q05, {"id": decision_id})
    if not res_q05.result_set or res_q05.result_set[0][0] is None:
        return _build_tool_result(
            ok=False,
            summary=f"Decision '{decision_id}' not found.",
            data={},
            evidence=[],
            cypher_ids=["Q15A", "Q05"],
        )

    d_node = res_q05.result_set[0][0]
    d_display = d_node.properties.get("display", decision_id)

    # 3. Create review request via Q15B
    rr_id = "rr_" + uuid.uuid4().hex[:8]
    rr_display = f"Review: {d_display}"
    now_epoch = int(time.time())
    clean_note = note[:300]

    g.query(Q15B, {
        "decision_id": decision_id,
        "rr_id": rr_id,
        "display": rr_display,
        "note": clean_note,
        "now": now_epoch,
    })

    # 4. Assign review to original decider via Q15C
    res_q15c = g.query(Q15C, {"decision_id": decision_id, "rr_id": rr_id})
    assigned_to: List[Dict[str, Any]] = []
    evidence: List[Evidence] = [
        _make_evidence(decision_id, "Decision", d_display),
        _make_evidence(rr_id, "ReviewRequest", rr_display),
    ]
    graph_nodes: List[GraphNode] = [
        GraphNode(id=decision_id, label="Decision", display=d_display, props=filter_node_properties("Decision", d_node.properties)),
        GraphNode(id=rr_id, label="ReviewRequest", display=rr_display, props={"id": rr_id, "display": rr_display, "note": clean_note, "status": "open", "created_at": now_epoch}),
    ]
    graph_edges: List[GraphEdge] = [
        GraphEdge(id=f"{rr_id}|REVIEWS|{decision_id}", source=rr_id, target=decision_id, type="REVIEWS")
    ]

    for r in res_q15c.result_set:
        p_id = r[0]
        if p_id is not None:
            p_name = r[1] or p_id
            assigned_to.append({"id": p_id, "display": p_name})
            evidence.append(_make_evidence(p_id, "Person", p_name))
            graph_nodes.append(GraphNode(id=p_id, label="Person", display=p_name, props={"id": p_id, "display": p_name}))
            graph_edges.append(GraphEdge(id=f"{rr_id}|ASSIGNED_TO|{p_id}", source=rr_id, target=p_id, type="ASSIGNED_TO"))

    data = {
        "review_request_id": rr_id,
        "assigned_to": assigned_to,
        "already_open": False,
    }
    summary = f"Flagged '{d_display}' for review (request {rr_id})."
    return _build_tool_result(
        ok=True,
        summary=summary,
        data=data,
        evidence=evidence,
        cypher_ids=["Q15A", "Q05", "Q15B", "Q15C"],
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
    )


# ==============================================================================
# REST-ONLY SERVICES
# ==============================================================================


def list_decisions(
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> List[DecisionSummary]:
    """Retrieve all decisions with dynamic freshness classification, sorted by drift count desc.

    Per ARCHITECTURE.md Section 13, 14 & Q09.
    """
    g = graph if graph is not None else get_graph()
    cfg = settings or get_settings()

    res_q09 = g.query(Q09)
    summaries: List[DecisionSummary] = []

    for row in res_q09.result_set:
        d_id = row[0]
        title = row[1] or d_id
        decided_at = row[2]
        status = row[3] or "active"
        drift_count = row[4]
        latest_drift = row[5]
        decider = row[6]
        module_ids = row[7] or []

        freshness_state = classify(status=status, drift_count=drift_count, threshold=cfg.STALE_PR_THRESHOLD)
        summaries.append(
            DecisionSummary(
                id=d_id,
                title=title,
                decided_at=decided_at,
                status=status,
                freshness=freshness_state,
                drift_count=drift_count,
                latest_drift_at=latest_drift,
                module_ids=module_ids,
                decider=decider,
            )
        )

    return summaries


def list_modules(
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> List[ModuleSummary]:
    """List all codebase modules sorted by path with formal owning team.

    Per ARCHITECTURE.md Section 13, 14 & Q25.
    """
    g = graph if graph is not None else get_graph()
    res_q25 = g.query(Q25)
    return [
        ModuleSummary(
            id=r[0],
            display=r[1] or r[0],
            path=r[2] or "",
            owner_team=r[3],
        )
        for r in res_q25.result_set
    ]


def graph_overview(
    limit: int = 150,
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> GraphPayload:
    """Retrieve overview subgraph containing decisions and immediate connected neighbors.

    Per ARCHITECTURE.md Section 13, 14 & Q17.
    """
    g = graph if graph is not None else get_graph()
    clamped_limit = max(1, min(limit, 500))
    res_q17 = g.query(Q17, {"limit": clamped_limit})
    return rows_to_graph_payload(res_q17.result_set)


def neighborhood(
    node_id: str,
    limit: int = 60,
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> GraphPayload:
    """Retrieve one-hop neighborhood subgraph centered around a specific node.

    Per ARCHITECTURE.md Section 13, 14 & Q18.
    """
    g = graph if graph is not None else get_graph()
    clamped_limit = max(1, min(limit, 200))
    res_q18 = g.query(Q18, {"id": node_id, "limit": clamped_limit})
    return rows_to_graph_payload(res_q18.result_set)


def node_detail(
    node_id: str,
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> Optional[NodeDetail]:
    """Retrieve detailed properties, label, and degree for an individual node.

    Per ARCHITECTURE.md Section 13, 14 & Q19.
    """
    g = graph if graph is not None else get_graph()
    res_q19 = g.query(Q19, {"id": node_id})

    if not res_q19.result_set or res_q19.result_set[0][0] is None:
        return None

    row = res_q19.result_set[0]
    n = row[0]
    label = row[1]
    degree = row[2]

    filtered_props = filter_node_properties(label, n.properties)
    return NodeDetail(
        id=n.properties.get("id", node_id),
        label=label,
        display=n.properties.get("display", node_id),
        props=filtered_props,
        degree=degree,
        url=n.properties.get("url"),
    )


def list_reviews(
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> List[ReviewRequestOut]:
    """Retrieve all open and closed decision review requests.

    Per ARCHITECTURE.md Section 13, 14 & Q20.
    """
    g = graph if graph is not None else get_graph()
    res_q20 = g.query(Q20)

    reviews: List[ReviewRequestOut] = []
    for r in res_q20.result_set:
        rr = r[0]
        decision_id = r[1]
        decision_title = r[2]
        assignee_ids = r[3] or []

        reviews.append(
            ReviewRequestOut(
                id=rr.properties.get("id"),
                decision_id=decision_id,
                decision=decision_title,
                note=rr.properties.get("note", ""),
                status=rr.properties.get("status", "open"),
                created_at=rr.properties.get("created_at", 0),
                assignee_ids=assignee_ids,
            )
        )
    return reviews


def simulate_pr(
    module_id: str,
    title: str,
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> SimulatePRResponse:
    """Simulate a merged pull request touching a module and return freshness changes.

    Per ARCHITECTURE.md Section 14 & Rule 8:
    - Computes freshness before for all decisions.
    - Runs Q24 to get next demo PR number.
    - Generates PR ID and synthetic file ID.
    - Runs Q21.
    - Recomputes freshness after.
    - Returns only decisions whose freshness changed.
    """
    g = graph if graph is not None else get_graph()
    cfg = settings or get_settings()

    # 1. Freshness before
    decisions_before = {d.id: d.freshness for d in list_decisions(graph=g, settings=cfg)}

    # 2. Resolve module path
    mods = list_modules(graph=g, settings=cfg)
    target_mod = next((m for m in mods if m.id == module_id or m.path == module_id or m.display == module_id), None)
    if not target_mod:
        actual_module_id = module_id
        module_path = module_id
    else:
        actual_module_id = target_mod.id
        module_path = target_mod.path

    # 3. Next demo PR number via Q24
    res_q24 = g.query(Q24)
    current_max = res_q24.result_set[0][0]
    next_number = int(current_max) + 1 if current_max is not None else 900000
    if next_number < 900000:
        next_number = 900000

    pr_id = f"pr_{next_number}"
    file_path = f"{module_path}/__demo__{next_number}.txt"
    file_id = "f_" + hashlib.sha1(file_path.encode("utf-8")).hexdigest()[:10]
    now_epoch = int(time.time())

    # 4. Insert demo PR and file via Q21
    g.query(
        Q21,
        {
            "module_id": actual_module_id,
            "file_id": file_id,
            "path": file_path,
            "pr_id": pr_id,
            "number": next_number,
            "title": title,
            "now": now_epoch,
        },
    )

    # 5. Freshness after
    decisions_after = {d.id: d.freshness for d in list_decisions(graph=g, settings=cfg)}

    changed: List[DecisionFreshnessChange] = []
    for d_id, before_state in decisions_before.items():
        after_state = decisions_after.get(d_id, before_state)
        if before_state != after_state:
            changed.append(
                DecisionFreshnessChange(
                    decision_id=d_id,
                    before=before_state,
                    after=after_state,
                )
            )

    return SimulatePRResponse(pr_id=pr_id, changed=changed)


def reset_demo(
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> ResetDemoResponse:
    """Reset demo state by deleting synthetic demo nodes and review requests.

    Per ARCHITECTURE.md Section 14 & Rule 8:
    Runs Q22A then Q22B, returning total removed nodes.
    """
    g = graph if graph is not None else get_graph()

    res_q22a = g.query(Q22A)
    deleted_a = getattr(res_q22a, "nodes_deleted", 0)

    res_q22b = g.query(Q22B)
    deleted_b = getattr(res_q22b, "nodes_deleted", 0)

    total_deleted = deleted_a + deleted_b
    return ResetDemoResponse(removed_nodes=total_deleted)


def counts(
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> HealthCounts:
    """Compute total graph node and relationship counts for health checks.

    Per ARCHITECTURE.md Section 10, 14 & Q26, Q27.
    """
    g = graph if graph is not None else get_graph()

    res_q26 = g.query(Q26)
    total_nodes = sum(row[1] for row in res_q26.result_set)

    res_q27 = g.query(Q27)
    total_edges = sum(row[1] for row in res_q27.result_set)

    return HealthCounts(nodes=total_nodes, edges=total_edges)


def ingest_refresh(
    graph: Optional[Any] = None,
    settings: Optional[Settings] = None,
) -> IngestRefreshResponse:
    """Incrementally fetch newly merged PRs, upsert them, and rerun edge derivation.

    Per ARCHITECTURE.md Section 7 & 14:
    - Finds max(PR.merged_at) among source='github' nodes.
    - Fetches newer merged PRs from GitHub.
    - Upserts new PRs and Files.
    - Reruns derive (MENTIONS, DOCUMENTED_IN, COLLABORATES_WITH).
    - Synchronous. Returns counts.
    """
    g = graph if graph is not None else get_graph()
    res = g.query("MATCH (pr:PR {source:'github'}) RETURN coalesce(max(pr.merged_at), 0) AS max_m")
    max_merged_at = int(res.result_set[0][0]) if (res.result_set and res.result_set[0][0] is not None) else 0

    new_prs_count = 0
    new_files_count = 0

    try:
        from ingest.github_loader import GitHubFetcher
        from brain_core.config import get_ingest_settings
        ingest_cfg = get_ingest_settings()
        fetcher = GitHubFetcher(settings=ingest_cfg)
        fetched_prs = fetcher.fetch_merged_prs()
        incremental_prs = [p for p in fetched_prs if p.get("merged_at", 0) > max_merged_at]
        if incremental_prs:
            from ingest.loaders import prepare_load_data, load_graph_data
            from ingest.derive import run_derive

            load_payload = prepare_load_data(prs=incremental_prs, docs=[], module_rules=ingest_cfg.MODULE_RULES)
            load_graph_data(g, load_payload)
            run_derive(graph=g)
            new_prs_count = len(incremental_prs)
            new_files_count = len(load_payload.get("files", []))
    except Exception as exc:
        import logging
        logging.getLogger("brain_core.services").warning(
            f"Incremental refresh encountered exception or offline environment: {exc}"
        )

    return IngestRefreshResponse(new_prs=new_prs_count, new_files=new_files_count)

