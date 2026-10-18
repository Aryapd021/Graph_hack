"""Graph database loaders and derive helpers for GitHub data.

Per ARCHITECTURE.md sections 6.1, 6.2, 7, 19:
- Calls schema.apply() to initialize indexes and Meta node idempotently.
- Derives Node IDs and properties:
    - Person: p_<8hex>, display='Contributor <8hex>', source='github', role=''
    - Module: m_<path-slug>, path, display, source='github'
    - File: f_<sha1(path)[:10]>, path, display, source='github'
    - PR: pr_<number>, number, display, state='merged', merged_at, created_at, body_excerpt, url, source='github'
    - Doc: d_<sha1(path)[:10]>, path, display, kind, updated_at, body, text_hash, url, source='github'
- Derives Edges:
    - AUTHORED: Person -> PR
    - TOUCHES: PR -> File
    - PART_OF: File -> Module
- Executes batched MERGE using UNWIND (200 items per batch).
- Prints counts table using Q26 (node counts) and Q27 (relationship counts).
- Accepts plain dicts for test fixtures.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from brain_core import queries, schema
from brain_core.config import ModuleRule, get_ingest_settings
from brain_core.db import get_graph
from ingest.github_loader import resolve_module_path

BATCH_SIZE = 200


def derive_file_id(path: str) -> str:
    """Derive deterministic File node ID: f_<sha1(path)[:10]>."""
    digest = hashlib.sha1(path.encode("utf-8")).hexdigest()[:10]
    return f"f_{digest}"


def derive_doc_id(path: str) -> str:
    """Derive deterministic Doc node ID: d_<sha1(path)[:10]>."""
    digest = hashlib.sha1(path.encode("utf-8")).hexdigest()[:10]
    return f"d_{digest}"


def derive_module_id(module_path: str) -> str:
    """Derive deterministic Module node ID: m_<path-slug> (slashes replaced with underscores)."""
    clean_path = module_path.strip("/").replace("/", "_")
    return f"m_{clean_path}"


def derive_pr_id(number: int | str) -> str:
    """Derive deterministic PR node ID: pr_<number>."""
    return f"pr_{number}"


def prepare_load_data(
    prs: List[Dict[str, Any]],
    docs: List[Dict[str, Any]],
    module_rules: List[ModuleRule],
) -> Dict[str, Any]:
    """Derive all nodes and edges from raw PR and Doc dictionaries.

    Why: Separates derivation logic from database IO so it can be verified
    with unit tests and mock fixtures without requiring an active database.
    """
    persons: Dict[str, Dict[str, Any]] = {}
    modules: Dict[str, Dict[str, Any]] = {}
    files: Dict[str, Dict[str, Any]] = {}
    prs_data: List[Dict[str, Any]] = []
    docs_data: List[Dict[str, Any]] = []

    authored_edges: Set[Tuple[str, str]] = set()
    touches_edges: Set[Tuple[str, str]] = set()
    part_of_edges: Set[Tuple[str, str]] = set()

    # Process PRs, files, authors, and modules
    for pr in prs:
        pr_number = pr["number"]
        pr_id = derive_pr_id(pr_number)

        # 1. Person
        author_id = pr.get("author_id", "")
        if author_id:
            hex_part = author_id[2:] if author_id.startswith("p_") else author_id
            persons[author_id] = {
                "id": author_id,
                "display": f"Contributor {hex_part}",
                "source": "github",
                "role": "",
            }
            authored_edges.add((author_id, pr_id))

        # 2. PR
        prs_data.append(
            {
                "id": pr_id,
                "number": int(pr_number),
                "display": pr.get("title", f"PR #{pr_number}"),
                "state": "merged",
                "merged_at": pr.get("merged_at"),
                "created_at": int(pr.get("created_at", 0)),
                "body_excerpt": pr.get("body_excerpt", ""),
                "url": pr.get("url", ""),
                "source": "github",
            }
        )

        # 3. Files and Modules touched by PR
        for file_path in pr.get("files", []):
            f_id = derive_file_id(file_path)
            files[f_id] = {
                "id": f_id,
                "path": file_path,
                "display": file_path,
                "source": "github",
            }
            touches_edges.add((pr_id, f_id))

            mod_path = resolve_module_path(file_path, module_rules)
            if mod_path:
                m_id = derive_module_id(mod_path)
                modules[m_id] = {
                    "id": m_id,
                    "path": mod_path,
                    "display": mod_path,
                    "source": "github",
                }
                part_of_edges.add((f_id, m_id))

    # Process Docs
    for doc in docs:
        d_path = doc["path"]
        d_id = derive_doc_id(d_path)
        body = doc.get("body", "")
        text_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

        docs_data.append(
            {
                "id": d_id,
                "path": d_path,
                "display": doc.get("title", Path(d_path).stem),
                "kind": doc.get("kind", "guide"),
                "updated_at": int(doc.get("updated_at", 0)),
                "body": body,
                "text_hash": text_hash,
                "url": doc.get("url", ""),
                "source": "github",
            }
        )

    return {
        "persons": list(persons.values()),
        "modules": list(modules.values()),
        "files": list(files.values()),
        "prs": prs_data,
        "docs": docs_data,
        "authored": [{"from_id": a, "to_id": b} for a, b in sorted(authored_edges)],
        "touches": [{"from_id": a, "to_id": b} for a, b in sorted(touches_edges)],
        "part_of": [{"from_id": a, "to_id": b} for a, b in sorted(part_of_edges)],
    }


def _execute_batch(graph: Any, query_str: str, items: List[Dict[str, Any]], batch_size: int = BATCH_SIZE) -> None:
    """Execute UNWIND query in chunks of batch_size."""
    for i in range(0, len(items), batch_size):
        chunk = items[i : i + batch_size]
        graph.query(query_str, {"batch": chunk})


def load_github_data(
    prs: List[Dict[str, Any]],
    docs: List[Dict[str, Any]],
    repo_info: Optional[Dict[str, Any]] = None,
    graph: Optional[Any] = None,
    module_rules: Optional[List[ModuleRule]] = None,
    batch_size: int = BATCH_SIZE,
) -> Dict[str, Any]:
    """Apply schema and idempotently load Person, Module, File, PR, Doc nodes and edges.

    Accepts plain dicts so test suites can provide mock fixtures.
    """
    settings = get_ingest_settings()
    target_graph = graph if graph is not None else get_graph()
    target_rules = module_rules if module_rules is not None else settings.MODULE_RULES

    # 1. Apply schema and Meta guard node idempotently
    print("Applying schema and indexes...", flush=True)
    schema.apply(target_graph)

    # 2. Derive all entities and relationships
    print(f"Deriving graph entities from {len(prs)} PRs and {len(docs)} Docs...", flush=True)
    payload = prepare_load_data(prs, docs, target_rules)

    # 3. Load Nodes in batches with UNWIND
    # Person
    print(f"Loading {len(payload['persons'])} Person nodes...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MERGE (p:Person {id: item.id})
        SET p.display = item.display,
            p.source = item.source,
            p.role = item.role
        """,
        payload["persons"],
        batch_size,
    )

    # Module
    print(f"Loading {len(payload['modules'])} Module nodes...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MERGE (m:Module {id: item.id})
        SET m.path = item.path,
            m.display = item.display,
            m.source = item.source
        """,
        payload["modules"],
        batch_size,
    )

    # File
    print(f"Loading {len(payload['files'])} File nodes...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MERGE (f:File {id: item.id})
        SET f.path = item.path,
            f.display = item.display,
            f.source = item.source
        """,
        payload["files"],
        batch_size,
    )

    # PR
    print(f"Loading {len(payload['prs'])} PR nodes...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MERGE (pr:PR {id: item.id})
        SET pr.number = item.number,
            pr.display = item.display,
            pr.state = item.state,
            pr.merged_at = item.merged_at,
            pr.created_at = item.created_at,
            pr.body_excerpt = item.body_excerpt,
            pr.url = item.url,
            pr.source = item.source
        """,
        payload["prs"],
        batch_size,
    )

    # Doc
    print(f"Loading {len(payload['docs'])} Doc nodes...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MERGE (d:Doc {id: item.id})
        SET d.display = item.display,
            d.path = item.path,
            d.kind = item.kind,
            d.updated_at = item.updated_at,
            d.body = item.body,
            d.text_hash = item.text_hash,
            d.url = item.url,
            d.source = item.source
        """,
        payload["docs"],
        batch_size,
    )

    # 4. Load Edges in batches with UNWIND
    # AUTHORED: Person -> PR
    print(f"Loading {len(payload['authored'])} AUTHORED edges...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MATCH (p:Person {id: item.from_id})
        MATCH (pr:PR {id: item.to_id})
        MERGE (p)-[:AUTHORED]->(pr)
        """,
        payload["authored"],
        batch_size,
    )

    # TOUCHES: PR -> File
    print(f"Loading {len(payload['touches'])} TOUCHES edges...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MATCH (pr:PR {id: item.from_id})
        MATCH (f:File {id: item.to_id})
        MERGE (pr)-[:TOUCHES]->(f)
        """,
        payload["touches"],
        batch_size,
    )

    # PART_OF: File -> Module
    print(f"Loading {len(payload['part_of'])} PART_OF edges...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MATCH (f:File {id: item.from_id})
        MATCH (m:Module {id: item.to_id})
        MERGE (f)-[:PART_OF]->(m)
        """,
        payload["part_of"],
        batch_size,
    )

    # 5. Query and print counts table using Q26 and Q27
    print_counts_table(target_graph)

    return payload


def print_counts_table(graph: Any) -> Dict[str, Dict[str, int]]:
    """Query and print formatted counts table using Q26 and Q27."""
    node_res = graph.query(queries.Q26)
    edge_res = graph.query(queries.Q27)

    node_counts = {row[0]: int(row[1]) for row in node_res.result_set}
    edge_counts = {row[0]: int(row[1]) for row in edge_res.result_set}

    print("\n" + "=" * 45)
    print("Graph Load Verification Counts")
    print("=" * 45)
    print("Nodes per Label (Q26):")
    for label in sorted(node_counts.keys()):
        print(f"  {label:<18} : {node_counts[label]:>6}")
    print("-" * 45)
    print("Relationships per Type (Q27):")
    for rel_type in sorted(edge_counts.keys()):
        print(f"  {rel_type:<18} : {edge_counts[rel_type]:>6}")
    print("=" * 45 + "\n", flush=True)

    return {"nodes": node_counts, "edges": edge_counts}


def load_from_cache(
    cache_dir: Optional[Path] = None,
    graph: Optional[Any] = None,
    batch_size: int = BATCH_SIZE,
) -> Dict[str, Any]:
    """Read cache files from data/cache/github and load into the graph database."""
    base_dir = cache_dir or (Path(__file__).resolve().parent.parent.parent / "data" / "cache" / "github")

    prs_file = base_dir / "prs.json"
    docs_file = base_dir / "docs.json"
    repo_file = base_dir / "repo.json"

    if not prs_file.exists() or not docs_file.exists():
        raise FileNotFoundError(
            f"GitHub cache files not found in {base_dir}. Please run 'python -m ingest fetch' first."
        )

    prs = json.loads(prs_file.read_text(encoding="utf-8"))
    docs = json.loads(docs_file.read_text(encoding="utf-8"))
    repo_info = json.loads(repo_file.read_text(encoding="utf-8")) if repo_file.exists() else None

    return load_github_data(
        prs=prs,
        docs=docs,
        repo_info=repo_info,
        graph=graph,
        batch_size=batch_size,
    )


def load_synthetic_data(
    teams_data: Dict[str, Any],
    people_roles: List[Dict[str, Any]],
    decisions: List[Dict[str, Any]],
    tickets: List[Dict[str, Any]],
    threads: List[Dict[str, Any]],
    graph: Optional[Any] = None,
    batch_size: int = BATCH_SIZE,
) -> Dict[str, Any]:
    """Load synthetic teams, decisions, tickets, threads, and their relationships.

    Why: ARCHITECTURE.md sections 6.1, 6.2, 7, and 8 define synthetic nodes (source='synthetic')
    and relationships (MEMBER_OF, OWNS, PARTICIPATED_IN, ASSIGNED_TO, RESOLVES, DECIDED_BY,
    AFFECTS, IMPLEMENTS, DISCUSSED_IN, TRACKED_BY, SUPERSEDED_BY). Accepts plain dicts for test fixtures.
    """
    target_graph = graph if graph is not None else get_graph()

    # 1. Update Person roles
    print(f"Updating roles for {len(people_roles)} Person nodes...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MATCH (p:Person {id: item.person_id})
        SET p.role = item.role
        """,
        people_roles,
        batch_size,
    )

    # 2. Load Team nodes
    teams_list = teams_data.get("teams", [])
    print(f"Loading {len(teams_list)} Team nodes...", flush=True)
    teams_payload = [
        {"id": t["id"], "display": t["display"], "source": "synthetic"}
        for t in teams_list
    ]
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MERGE (t:Team {id: item.id})
        SET t.display = item.display,
            t.source = item.source
        """,
        teams_payload,
        batch_size,
    )

    # 3. Load Decision nodes
    print(f"Loading {len(decisions)} Decision nodes...", flush=True)
    decisions_payload = []
    for d in decisions:
        content_to_hash = f"{d.get('summary', '')}\n{d.get('rationale', '')}"
        text_hash = hashlib.sha256(content_to_hash.encode("utf-8")).hexdigest()
        decisions_payload.append({
            "id": d["id"],
            "display": d["display"],
            "summary": d.get("summary", ""),
            "rationale": d.get("rationale", ""),
            "decided_at": int(d.get("decided_at", 0)),
            "status": d.get("status", "active"),
            "text_hash": text_hash,
            "source": "synthetic",
        })
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MERGE (d:Decision {id: item.id})
        SET d.display = item.display,
            d.summary = item.summary,
            d.rationale = item.rationale,
            d.decided_at = item.decided_at,
            d.status = item.status,
            d.text_hash = item.text_hash,
            d.source = item.source
        """,
        decisions_payload,
        batch_size,
    )

    # 4. Load Ticket nodes
    print(f"Loading {len(tickets)} Ticket nodes...", flush=True)
    tickets_payload = [
        {
            "id": tk["id"],
            "key": tk["key"],
            "display": tk["display"],
            "status": tk.get("status", "resolved"),
            "created_at": int(tk.get("created_at", 0)),
            "resolved_at": tk.get("resolved_at"),
            "description": tk.get("description", ""),
            "source": "synthetic",
        }
        for tk in tickets
    ]
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MERGE (tk:Ticket {id: item.id})
        SET tk.key = item.key,
            tk.display = item.display,
            tk.status = item.status,
            tk.created_at = item.created_at,
            tk.resolved_at = item.resolved_at,
            tk.description = item.description,
            tk.source = item.source
        """,
        tickets_payload,
        batch_size,
    )

    # 5. Load Thread nodes
    print(f"Loading {len(threads)} Thread nodes...", flush=True)
    threads_payload = []
    for th in threads:
        text = th.get("text", "")
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        threads_payload.append({
            "id": th["id"],
            "display": th["display"],
            "channel": th.get("channel", "#eng-decisions"),
            "started_at": int(th.get("started_at", 0)),
            "text": text,
            "text_hash": text_hash,
            "source": "synthetic",
        })
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MERGE (th:Thread {id: item.id})
        SET th.display = item.display,
            th.channel = item.channel,
            th.started_at = item.started_at,
            th.text = item.text,
            th.text_hash = item.text_hash,
            th.source = item.source
        """,
        threads_payload,
        batch_size,
    )

    # 6. Load Edges
    # MEMBER_OF: Person -> Team
    members = teams_data.get("members", [])
    print(f"Loading {len(members)} MEMBER_OF edges...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MATCH (p:Person {id: item.person_id})
        MATCH (t:Team {id: item.team_id})
        MERGE (p)-[:MEMBER_OF]->(t)
        """,
        members,
        batch_size,
    )

    # OWNS: Team -> Module
    owns = teams_data.get("owns", [])
    print(f"Loading {len(owns)} OWNS edges...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MATCH (t:Team {id: item.team_id})
        MATCH (m:Module {id: item.module_id})
        MERGE (t)-[:OWNS]->(m)
        """,
        owns,
        batch_size,
    )

    # PARTICIPATED_IN: Person -> Thread
    participated_edges = []
    for th in threads:
        for p_id in th.get("participants", []):
            participated_edges.append({"thread_id": th["id"], "person_id": p_id})
    print(f"Loading {len(participated_edges)} PARTICIPATED_IN edges...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MATCH (p:Person {id: item.person_id})
        MATCH (th:Thread {id: item.thread_id})
        MERGE (p)-[:PARTICIPATED_IN]->(th)
        """,
        participated_edges,
        batch_size,
    )

    # ASSIGNED_TO: Ticket -> Person
    assigned_edges = [
        {"ticket_id": tk["id"], "person_id": tk["assigned_to"]}
        for tk in tickets
        if tk.get("assigned_to")
    ]
    print(f"Loading {len(assigned_edges)} ASSIGNED_TO edges...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MATCH (tk:Ticket {id: item.ticket_id})
        MATCH (p:Person {id: item.person_id})
        MERGE (tk)-[:ASSIGNED_TO]->(p)
        """,
        assigned_edges,
        batch_size,
    )

    # RESOLVES: PR -> Ticket
    resolves_edges = [
        {"ticket_id": tk["id"], "pr_id": tk["resolved_by_pr"]}
        for tk in tickets
        if tk.get("resolved_by_pr")
    ]
    print(f"Loading {len(resolves_edges)} RESOLVES edges...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MATCH (pr:PR {id: item.pr_id})
        MATCH (tk:Ticket {id: item.ticket_id})
        MERGE (pr)-[:RESOLVES]->(tk)
        """,
        resolves_edges,
        batch_size,
    )

    # DECIDED_BY: Decision -> Person
    decided_by_edges = [
        {"decision_id": d["id"], "person_id": d["decided_by"]}
        for d in decisions
        if d.get("decided_by")
    ]
    print(f"Loading {len(decided_by_edges)} DECIDED_BY edges...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MATCH (d:Decision {id: item.decision_id})
        MATCH (p:Person {id: item.person_id})
        MERGE (d)-[:DECIDED_BY]->(p)
        """,
        decided_by_edges,
        batch_size,
    )

    # AFFECTS: Decision -> Module
    affects_edges = []
    for d in decisions:
        for m_id in d.get("affects", []):
            affects_edges.append({"decision_id": d["id"], "module_id": m_id})
    print(f"Loading {len(affects_edges)} AFFECTS edges...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MATCH (d:Decision {id: item.decision_id})
        MATCH (m:Module {id: item.module_id})
        MERGE (d)-[:AFFECTS]->(m)
        """,
        affects_edges,
        batch_size,
    )

    # IMPLEMENTS: PR -> Decision
    implements_edges = []
    for d in decisions:
        for pr_id in d.get("implemented_by", []):
            implements_edges.append({"decision_id": d["id"], "pr_id": pr_id})
    print(f"Loading {len(implements_edges)} IMPLEMENTS edges...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MATCH (pr:PR {id: item.pr_id})
        MATCH (d:Decision {id: item.decision_id})
        MERGE (pr)-[:IMPLEMENTS]->(d)
        """,
        implements_edges,
        batch_size,
    )

    # DISCUSSED_IN: Decision -> Thread
    discussed_edges = [
        {"decision_id": d["id"], "thread_id": d["discussed_in"]}
        for d in decisions
        if d.get("discussed_in")
    ]
    print(f"Loading {len(discussed_edges)} DISCUSSED_IN edges...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MATCH (d:Decision {id: item.decision_id})
        MATCH (th:Thread {id: item.thread_id})
        MERGE (d)-[:DISCUSSED_IN]->(th)
        """,
        discussed_edges,
        batch_size,
    )

    # TRACKED_BY: Decision -> Ticket
    tracked_edges = [
        {"decision_id": d["id"], "ticket_id": d["tracked_by"]}
        for d in decisions
        if d.get("tracked_by")
    ]
    print(f"Loading {len(tracked_edges)} TRACKED_BY edges...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MATCH (d:Decision {id: item.decision_id})
        MATCH (tk:Ticket {id: item.ticket_id})
        MERGE (d)-[:TRACKED_BY]->(tk)
        """,
        tracked_edges,
        batch_size,
    )

    # SUPERSEDED_BY: Decision -> Decision
    superseded_edges = [
        {"from_id": d["id"], "to_id": d["superseded_by"]}
        for d in decisions
        if d.get("superseded_by")
    ]
    print(f"Loading {len(superseded_edges)} SUPERSEDED_BY edges...", flush=True)
    _execute_batch(
        target_graph,
        """
        UNWIND $batch AS item
        MATCH (d1:Decision {id: item.from_id})
        MATCH (d2:Decision {id: item.to_id})
        MERGE (d1)-[:SUPERSEDED_BY]->(d2)
        """,
        superseded_edges,
        batch_size,
    )

    # Print verification counts
    print_counts_table(target_graph)

    return {
        "teams": teams_data,
        "people_roles": people_roles,
        "decisions": decisions,
        "tickets": tickets,
        "threads": threads,
    }


def load_synthetic_from_files(
    synthetic_dir: Optional[Path] = None,
    graph: Optional[Any] = None,
    batch_size: int = BATCH_SIZE,
) -> Dict[str, Any]:
    """Read generated synthetic JSON files and load them into the graph database."""
    base_dir = synthetic_dir or (Path(__file__).resolve().parent.parent.parent / "data" / "synthetic")

    teams_file = base_dir / "teams.json"
    roles_file = base_dir / "people_roles.json"
    decisions_file = base_dir / "decisions.json"
    tickets_file = base_dir / "tickets.json"
    threads_file = base_dir / "threads.json"

    required_files = [teams_file, roles_file, decisions_file, tickets_file, threads_file]
    for rf in required_files:
        if not rf.exists():
            raise FileNotFoundError(f"Synthetic file {rf} not found. Run 'python -m ingest synth' first.")

    teams_data = json.loads(teams_file.read_text(encoding="utf-8"))
    people_roles = json.loads(roles_file.read_text(encoding="utf-8"))
    decisions = json.loads(decisions_file.read_text(encoding="utf-8"))
    tickets = json.loads(tickets_file.read_text(encoding="utf-8"))
    threads = json.loads(threads_file.read_text(encoding="utf-8"))

    return load_synthetic_data(
        teams_data=teams_data,
        people_roles=people_roles,
        decisions=decisions,
        tickets=tickets,
        threads=threads,
        graph=graph,
        batch_size=batch_size,
    )

