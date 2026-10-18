"""Derivation step for graph edges.

Per ARCHITECTURE.md sections 6.2, 7, 19:
- MENTIONS (Doc -> Module):
    Rule: doc path starts with the module path, OR doc body contains the module path
    as a whole token, OR doc body contains dotted form (e.g. fastapi.dependencies).
- MENTIONS (Thread -> Module):
    Rule: connects Thread to each Module it mentions from synthetic generation.
- DOCUMENTED_IN (Decision -> Doc):
    Rule: for each decision, among Docs that MENTIONS any module the decision AFFECTS,
    pick the one with the lowest path (lexicographically, deterministic). If none, no edge.
- COLLABORATES_WITH (Person -> Person):
    Rule: runs query Q16 from brain_core.queries to compute shared module collaborations.
- Prints updated counts table using Q26 and Q27.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from brain_core import queries
from brain_core.db import get_graph
from ingest.loaders import BATCH_SIZE, _execute_batch, print_counts_table


def derive_doc_mentions(graph: Any, batch_size: int = BATCH_SIZE) -> List[Dict[str, str]]:
    """Derive MENTIONS edges from Doc to Module.

    Why: ARCHITECTURE.md Section 7 rule:
    doc path starts with module path, or doc body contains module path as a whole token,
    or contains the dotted form (module path with '/' replaced by '.').
    """
    print("Deriving MENTIONS (Doc -> Module) edges...", flush=True)

    # 1. Fetch all docs with id, path, body
    doc_res = graph.query("MATCH (d:Doc) RETURN d.id, d.path, d.body")
    docs = [{"id": row[0], "path": row[1], "body": row[2] or ""} for row in doc_res.result_set]

    # 2. Fetch all modules with id, path
    mod_res = graph.query("MATCH (m:Module) RETURN m.id, m.path")
    modules = [{"id": row[0], "path": row[1]} for row in mod_res.result_set]

    mentions_edges: Set[Tuple[str, str]] = set()

    # Pre-compile regexes for each module path and dotted form
    mod_matchers = []
    for m in modules:
        m_id = m["id"]
        m_path = m["path"]
        dotted = m_path.replace("/", ".")
        # Whole token regex
        path_pattern = re.compile(r"\b" + re.escape(m_path) + r"\b", re.IGNORECASE)
        dotted_pattern = re.compile(r"\b" + re.escape(dotted) + r"\b", re.IGNORECASE)
        mod_matchers.append((m_id, m_path, path_pattern, dotted_pattern))

    for doc in docs:
        d_id = doc["id"]
        d_path = doc["path"]
        d_body = doc["body"]

        for m_id, m_path, path_pattern, dotted_pattern in mod_matchers:
            # Condition 1: doc path starts with module path
            if d_path.startswith(m_path):
                mentions_edges.add((d_id, m_id))
                continue

            # Condition 2: doc body contains module path as whole token
            if path_pattern.search(d_body):
                mentions_edges.add((d_id, m_id))
                continue

            # Condition 3: doc body contains dotted form
            if dotted_pattern.search(d_body):
                mentions_edges.add((d_id, m_id))
                continue

    items = [{"doc_id": d_id, "module_id": m_id} for d_id, m_id in sorted(mentions_edges)]
    print(f"Creating {len(items)} MENTIONS (Doc -> Module) edges...", flush=True)

    _execute_batch(
        graph,
        """
        UNWIND $batch AS item
        MATCH (d:Doc {id: item.doc_id})
        MATCH (m:Module {id: item.module_id})
        MERGE (d)-[:MENTIONS]->(m)
        """,
        items,
        batch_size,
    )

    return items


def derive_thread_mentions(
    graph: Any,
    synthetic_dir: Optional[Path] = None,
    synthetic_threads: Optional[List[Dict[str, Any]]] = None,
    batch_size: int = BATCH_SIZE,
) -> List[Dict[str, str]]:
    """Derive MENTIONS edges from Thread to Module using threads metadata.

    Why: Threads generated in synthetic step mention affected modules or discussion topics.
    """
    print("Deriving MENTIONS (Thread -> Module) edges...", flush=True)
    if synthetic_threads is not None:
        threads = synthetic_threads
    else:
        base_dir = synthetic_dir or (Path(__file__).resolve().parent.parent.parent / "data" / "synthetic")
        threads_file = base_dir / "threads.json"
        if not threads_file.exists():
            print("Note: threads.json not found, skipping Thread MENTIONS derivation.", flush=True)
            return []
        threads = json.loads(threads_file.read_text(encoding="utf-8"))
    items: Set[Tuple[str, str]] = set()

    for th in threads:
        th_id = th["id"]
        for m_id in th.get("mentions", []):
            items.add((th_id, m_id))

    payload = [{"thread_id": th_id, "module_id": m_id} for th_id, m_id in sorted(items)]
    print(f"Creating {len(payload)} MENTIONS (Thread -> Module) edges...", flush=True)

    _execute_batch(
        graph,
        """
        UNWIND $batch AS item
        MATCH (th:Thread {id: item.thread_id})
        MATCH (m:Module {id: item.module_id})
        MERGE (th)-[:MENTIONS]->(m)
        """,
        payload,
        batch_size,
    )

    return payload


def derive_documented_in(graph: Any, batch_size: int = BATCH_SIZE) -> List[Dict[str, str]]:
    """Derive DOCUMENTED_IN edges from Decision to Doc.

    Why: ARCHITECTURE.md Section 7 rule:
    For each decision, among Docs that MENTIONS any module the decision AFFECTS,
    pick the one with the lowest path (deterministic). If none, no edge.
    """
    print("Deriving DOCUMENTED_IN (Decision -> Doc) edges...", flush=True)

    # Cypher query finding candidate docs for each decision through shared module
    res = graph.query(
        """
        MATCH (d:Decision)-[:AFFECTS]->(m:Module)<-[:MENTIONS]-(doc:Doc)
        RETURN d.id AS decision_id, doc.id AS doc_id, doc.path AS doc_path
        """
    )

    # Group docs per decision
    decision_to_docs: Dict[str, List[Tuple[str, str]]] = {}
    for row in res.result_set:
        d_id = row[0]
        doc_id = row[1]
        doc_path = row[2]
        if d_id not in decision_to_docs:
            decision_to_docs[d_id] = []
        decision_to_docs[d_id].append((doc_path, doc_id))

    documented_edges = []
    for d_id, doc_candidates in sorted(decision_to_docs.items()):
        # Sort by doc_path ascending (lowest path wins)
        sorted_candidates = sorted(doc_candidates, key=lambda x: x[0])
        best_doc_id = sorted_candidates[0][1]
        documented_edges.append({"decision_id": d_id, "doc_id": best_doc_id})

    print(f"Creating {len(documented_edges)} DOCUMENTED_IN edges...", flush=True)
    _execute_batch(
        graph,
        """
        UNWIND $batch AS item
        MATCH (d:Decision {id: item.decision_id})
        MATCH (doc:Doc {id: item.doc_id})
        MERGE (d)-[:DOCUMENTED_IN]->(doc)
        """,
        documented_edges,
        batch_size,
    )

    return documented_edges


def derive_collaborates_with(graph: Any) -> int:
    """Derive COLLABORATES_WITH relationships between Person nodes using Q16.

    Why: ARCHITECTURE.md sections 6.2, 7, and 9 define Q16 for collaboration graph weighting.
    """
    print("Deriving COLLABORATES_WITH edges using query Q16...", flush=True)
    res = graph.query(queries.Q16)
    # Check count of created COLLABORATES_WITH edges
    count_res = graph.query("MATCH ()-[c:COLLABORATES_WITH]->() RETURN count(c)")
    total_edges = int(count_res.result_set[0][0]) if count_res.result_set else 0
    print(f"COLLABORATES_WITH edges in graph: {total_edges}", flush=True)
    return total_edges


def run_derive(
    graph: Optional[Any] = None,
    synthetic_dir: Optional[Path] = None,
    synthetic_threads: Optional[List[Dict[str, Any]]] = None,
    batch_size: int = BATCH_SIZE,
) -> Dict[str, Any]:
    """Execute complete edge derivation pipeline.

    Order:
    1. Doc -> Module MENTIONS
    2. Thread -> Module MENTIONS
    3. Decision -> Doc DOCUMENTED_IN
    4. Person -> Person COLLABORATES_WITH (Q16)
    5. Print updated counts table
    """
    target_graph = graph if graph is not None else get_graph()

    print("\n--- Starting Graph Edge Derivation ---", flush=True)
    doc_mentions = derive_doc_mentions(target_graph, batch_size=batch_size)
    thread_mentions = derive_thread_mentions(
        target_graph,
        synthetic_dir=synthetic_dir,
        synthetic_threads=synthetic_threads,
        batch_size=batch_size,
    )
    documented_in = derive_documented_in(target_graph, batch_size=batch_size)
    collaborations = derive_collaborates_with(target_graph)

    counts = print_counts_table(target_graph)

    return {
        "doc_mentions": len(doc_mentions),
        "thread_mentions": len(thread_mentions),
        "documented_in": len(documented_in),
        "collaborates_with": collaborations,
        "counts": counts,
    }


if __name__ == "__main__":
    run_derive()
