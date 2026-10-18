"""Database schema DDL, index management, and Meta node validation.

Per ARCHITECTURE.md sections 6.1, 6.4, 6.5, 17:
- Idempotent creation of range indexes on id for all 11 labels.
- Additional range indexes on PR(merged_at), Decision(decided_at), Module(path).
- Vector indexes on Doc(embedding), Decision(embedding), Thread(embedding) using EMBED_DIM and cosine.
- Upsert Meta node with schema_version=1, embed_dim, embed_model, repo.
- check_meta() guard preventing execution against misconfigured or outdated graphs.
"""

from typing import Any, Optional

from brain_core.config import get_settings
from brain_core.db import get_graph


def _execute_idempotent_ddl(graph: Any, query_str: str) -> None:
    """Execute a DDL query, ignoring errors if the index already exists.

    Why: FalkorDB raises ResponseError: Attribute '...' is already indexed when an index
    already exists. Catching 'already indexed' or 'already exists' ensures apply() is completely idempotent.
    """
    try:
        graph.query(query_str)
    except Exception as exc:
        msg = str(exc).lower()
        if "already indexed" in msg or "already exists" in msg or "equivalent index" in msg:
            pass
        else:
            raise


def apply(graph: Optional[Any] = None) -> None:
    """Apply all schema DDL and indexes to the database idempotently.

    Creates range indexes, vector indexes, and upserts the Meta configuration node.
    """
    settings = get_settings()
    target_graph = graph if graph is not None else get_graph()

    # Section 6.1 labels: 10 domain entities + Meta
    labels = [
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
        "Meta",
    ]

    # 1. Range indexes on id property for all labels
    for label in labels:
        # Why: Section 6.4 requires range indexes on id for all node labels
        _execute_idempotent_ddl(target_graph, f"CREATE INDEX FOR (n:{label}) ON (n.id)")

    # 2. Specific range indexes from Section 6.4
    _execute_idempotent_ddl(target_graph, "CREATE INDEX FOR (n:PR) ON (n.merged_at)")
    _execute_idempotent_ddl(target_graph, "CREATE INDEX FOR (n:Decision) ON (n.decided_at)")
    _execute_idempotent_ddl(target_graph, "CREATE INDEX FOR (n:Module) ON (n.path)")

    # 3. Vector indexes on embedding for Doc, Decision, Thread
    embed_dim = settings.EMBED_DIM
    vector_labels = ["Doc", "Decision", "Thread"]
    for vlabel in vector_labels:
        # Why: Uses exact syntax verified in Gate G1
        _execute_idempotent_ddl(
            target_graph,
            f"CREATE VECTOR INDEX FOR (n:{vlabel}) ON (n.embedding) OPTIONS {{dimension: {embed_dim}, similarityFunction: 'cosine'}}",
        )

    # 4. Upsert Meta node per Section 6.5
    # Why: Guards against model or dimension mismatches when embedding or querying
    target_graph.query(
        """
        MERGE (m:Meta {id: 'meta'})
        SET m.embed_dim = $embed_dim,
            m.embed_model = $embed_model,
            m.schema_version = 1,
            m.repo = $repo,
            m.display = 'Meta',
            m.source = 'schema'
        """,
        {
            "embed_dim": settings.EMBED_DIM,
            "embed_model": settings.GEMINI_EMBED_MODEL,
            "repo": settings.GITHUB_REPO,
        },
    )


def check_meta(graph: Optional[Any] = None, settings: Optional[Any] = None) -> None:
    """Validate that the database Meta node matches current environment configuration.

    Why: Section 6.5 mandates that API and MCP startup refuse to start if EMBED_DIM,
    GEMINI_EMBED_MODEL, or GITHUB_REPO differ from the graph's Meta node.
    """
    cfg = settings or get_settings()
    target_graph = graph if graph is not None else get_graph()

    res = target_graph.query(
        """
        MATCH (m:Meta {id: 'meta'})
        RETURN m.embed_dim AS embed_dim,
               m.embed_model AS embed_model,
               m.schema_version AS schema_version,
               m.repo AS repo
        """
    )

    if not res.result_set:
        raise ValueError(
            "Meta node not found in graph. The database schema has not been initialized. "
            "Fix: python -m ingest all --reset"
        )

    row = res.result_set[0]
    actual_dim, actual_model, _, actual_repo = row

    mismatches = []
    if actual_dim != cfg.EMBED_DIM:
        mismatches.append(f"EMBED_DIM (graph={actual_dim}, env={cfg.EMBED_DIM})")
    if actual_model != cfg.GEMINI_EMBED_MODEL:
        mismatches.append(f"GEMINI_EMBED_MODEL (graph='{actual_model}', env='{cfg.GEMINI_EMBED_MODEL}')")
    if actual_repo != cfg.GITHUB_REPO:
        mismatches.append(f"GITHUB_REPO (graph='{actual_repo}', env={cfg.GITHUB_REPO})")

    if mismatches:
        # Why: Section 6.5 requires exact error message naming the mismatch and fix command
        raise ValueError(
            f"Meta configuration mismatch in graph: {', '.join(mismatches)}. "
            "Fix: python -m ingest all --reset"
        )
