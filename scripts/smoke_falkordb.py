"""Verification gates for FalkorDB and Gemini services.

Per ARCHITECTURE.md sections 17 and 19:
- Uses scratch graph 'smoke_scratch' and deletes it on exit. Never touches FALKORDB_GRAPH.
- G1: create range index and vector index (dimension = EMBED_DIM, cosine).
- G2: insert 3 nodes with deterministic EMBED_DIM vectors, run queryNodes, determine score direction.
- G3: NOT (pr)-[:IMPLEMENTS]->(d) pattern predicate inside WHERE.
- G4: shortestPath((a)-[*..6]->(b)) with both ends bound in WITH clause (fallback algo.SPpaths).
- G5: algo.pageRank('Person', 'COLLABORATES_WITH') on a tiny graph.
- G8: generate_content with function declaration + GEMINI_THINKING_LEVEL; embedding call with EMBED_DIM.
- Prints 'PASS Gx' or 'FAIL Gx: <exact error>' per gate. Exits non-zero if any gate fails.
"""

import os
import sys
import time
from pathlib import Path
from typing import Any

# Why: Support optional command line arg for env file (e.g. .env.cloud) in addition to ENV_FILE env var
if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
    os.environ["ENV_FILE"] = sys.argv[1]

# Why: Allow running directly via `python scripts/smoke_falkordb.py` without requiring PYTHONPATH setup
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from google import genai
from google.genai import types

from brain_core.config import get_settings
from brain_core.db import get_db

SCRATCH_GRAPH_NAME = "smoke_scratch"


def cleanup_scratch_graph(client: Any) -> None:
    """Delete the scratch graph to leave no traces after verification.

    Why: Section 17 mandates using a scratch graph and deleting it on exit.
    """
    try:
        g = client.select_graph(SCRATCH_GRAPH_NAME)
        g.delete()
    except Exception:
        # If the graph doesn't exist or is already deleted, ignore safely
        pass


def run_g1(graph: Any, embed_dim: int) -> None:
    """Gate G1: DDL range index and vector index."""
    # Why: Range index for deterministic node ID lookups
    graph.query("CREATE INDEX FOR (n:SmokeNode) ON (n.id)")
    # Why: Vector index for semantic retrieval using cosine similarity and EMBED_DIM
    graph.query(
        f"CREATE VECTOR INDEX FOR (n:SmokeNode) ON (n.vec) OPTIONS {{dimension: {embed_dim}, similarityFunction: 'cosine'}}"
    )


def run_g2(graph: Any, embed_dim: int) -> str:
    """Gate G2: Vector search on 3 deterministic vectors; determine score ordering.

    Returns string explaining whether LOWER or HIGHER score means CLOSER.
    """
    # Why: Create three orthogonal unit vectors of length embed_dim
    v1 = [0.0] * embed_dim
    v1[0] = 1.0
    v2 = [0.0] * embed_dim
    v2[1] = 1.0
    v3 = [0.0] * embed_dim
    v3[2] = 1.0

    # Insert 3 nodes with deterministic vectors
    graph.query("CREATE (:SmokeNode {id: 'n1', vec: vecf32($v)})", {"v": v1})
    graph.query("CREATE (:SmokeNode {id: 'n2', vec: vecf32($v)})", {"v": v2})
    graph.query("CREATE (:SmokeNode {id: 'n3', vec: vecf32($v)})", {"v": v3})

    # Query with v1 as query vector (exact match to n1)
    res = graph.query(
        "CALL db.idx.vector.queryNodes('SmokeNode', 'vec', 3, vecf32($q)) YIELD node, score RETURN node.id AS id, score",
        {"q": v1},
    )

    scores = {row[0]: float(row[1]) for row in res.result_set}
    if "n1" not in scores or "n2" not in scores:
        raise ValueError(f"Expected n1 and n2 in vector search results, got {scores}")

    n1_score = scores["n1"]
    n2_score = scores["n2"]

    # Why: If exact match n1 has smaller score than orthogonal n2, lower means closer (cosine distance)
    if n1_score < n2_score:
        direction = "LOWER score means CLOSER (distance metric)"
    else:
        direction = "HIGHER score means CLOSER (similarity metric)"

    return f"Scores: {scores}; {direction}"


def run_g3(graph: Any) -> None:
    """Gate G3: NOT (pr)-[:IMPLEMENTS]->(d) pattern predicate inside WHERE."""
    graph.query("CREATE (pr1:PR {id: 'pr1'}), (pr2:PR {id: 'pr2'}), (d:Decision {id: 'd1'})")
    graph.query(
        "MATCH (pr:PR {id: 'pr1'}), (d:Decision {id: 'd1'}) CREATE (pr)-[:IMPLEMENTS]->(d)"
    )

    # Why: Verify Cypher engine supports inline pattern predicates inside WHERE clauses
    res = graph.query(
        """
        MATCH (pr:PR)
        WHERE NOT (pr)-[:IMPLEMENTS]->(:Decision)
        RETURN pr.id AS pr_id
        """
    )
    returned_ids = [row[0] for row in res.result_set]
    if returned_ids != ["pr2"]:
        raise ValueError(f"Expected only ['pr2'] matching NOT IMPLEMENTS, got {returned_ids}")


def run_g4(graph: Any) -> None:
    """Gate G4: shortestPath((a)-[*..6]-(b)) with both ends bound.

    Why: Per FalkorDB documentation, shortestPath is supported in WITH/RETURN clauses.
    If undirected syntax is unsupported, fallback to directed traversal or algo.SPpaths per section 17.
    """
    graph.query("CREATE (a:Entity {id: 'a'}), (b:Entity {id: 'b'}), (c:Entity {id: 'c'})")
    graph.query(
        """
        MATCH (a:Entity {id: 'a'}), (b:Entity {id: 'b'}), (c:Entity {id: 'c'})
        CREATE (a)-[:CONNECTED]->(c)
        CREATE (c)-[:CONNECTED]->(b)
        """
    )

    try:
        # FalkorDB shortestPath in WITH clause
        res = graph.query(
            """
            MATCH (a:Entity {id: 'a'}), (b:Entity {id: 'b'})
            WITH shortestPath((a)-[*..6]->(b)) AS p
            RETURN length(p) AS path_len
            """
        )
        if not res.result_set or res.result_set[0][0] != 2:
            raise ValueError(f"Expected shortest path length 2, got {res.result_set}")
    except Exception as exc:
        # Fallback to algo.SPpaths per Section 17 G4 guidance
        res = graph.query(
            """
            MATCH (a:Entity {id: 'a'}), (b:Entity {id: 'b'})
            CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['CONNECTED']})
            YIELD path
            RETURN length(path) AS path_len
            """
        )
        if not res.result_set or res.result_set[0][0] != 2:
            raise ValueError(f"Fallback algo.SPpaths failed: {exc}")


def run_g5(graph: Any) -> None:
    """Gate G5: algo.pageRank('Person', 'COLLABORATES_WITH') on a tiny graph."""
    graph.query("CREATE (p1:Person {id: 'p1'}), (p2:Person {id: 'p2'}), (p3:Person {id: 'p3'})")
    graph.query(
        """
        MATCH (p1:Person {id: 'p1'}), (p2:Person {id: 'p2'}), (p3:Person {id: 'p3'})
        CREATE (p1)-[:COLLABORATES_WITH]->(p2)
        CREATE (p3)-[:COLLABORATES_WITH]->(p2)
        """
    )

    # Why: Verify algo.pageRank built-in procedure with specific label and edge type
    res = graph.query(
        "CALL algo.pageRank('Person', 'COLLABORATES_WITH') YIELD node, score RETURN node.id AS id, score"
    )
    if not res.result_set:
        raise ValueError("algo.pageRank returned no rows")


def run_g6() -> None:
    """Gate G6: All 11 MCP tool JSON Schemas convert to accepted Gemini FunctionDeclarations.

    Why: Section 17 Gate G6 mandates converting all 11 MCP tool schemas into accepted
    Gemini FunctionDeclarations with the pinned google-genai version.
    """
    from brain_api.agent.mcp_client import convert_tool_to_function_declaration
    from mcp_server.server import mcp

    tools = mcp._tool_manager.list_tools()
    if len(tools) != 11:
        raise ValueError(f"Expected 11 MCP tools, found {len(tools)}")

    expected_tool_names = {
        "search_knowledge",
        "get_decision",
        "trace_decision",
        "check_decision_freshness",
        "list_stale_decisions",
        "who_owns",
        "who_knows",
        "recent_changes",
        "connection_path",
        "key_connectors",
        "flag_for_review",
    }
    actual_names = {t.name for t in tools}
    if actual_names != expected_tool_names:
        raise ValueError(
            f"MCP tool names mismatch: missing {expected_tool_names - actual_names}, extra {actual_names - expected_tool_names}"
        )

    for tool in tools:
        decl = convert_tool_to_function_declaration(tool)
        if not decl.name or not decl.description or not decl.parameters:
            raise ValueError(f"Invalid FunctionDeclaration produced for tool '{tool.name}'")


def run_g8(settings: Any) -> None:
    """Gate G8: Gemini function calling with thinking level and embedding dimensionality."""
    # Why: Section 17 gate G8 checks function calling and embedding dimensionality with pinned SDK
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    # 1. Function calling check using FunctionDeclaration
    func_decl = types.FunctionDeclaration(
        name="lookup_verification_code",
        description="Verify a confirmation code",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "code": types.Schema(type=types.Type.STRING, description="The verification code"),
            },
            required=["code"],
        ),
    )

    thinking_level = settings.GEMINI_THINKING_LEVEL.upper()

    # Retry up to 5 times with exponential backoff for temporary 503 high-demand spikes
    last_err = None
    response = None
    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents="Call lookup_verification_code with code='CHECK123'. Do not respond with text.",
                config=types.GenerateContentConfig(
                    tools=[types.Tool(function_declarations=[func_decl])],
                    thinking_config=types.ThinkingConfig(thinking_level=thinking_level),
                ),
            )
            break
        except Exception as exc:
            last_err = exc
            wait_sec = 2 * (attempt + 1)
            time.sleep(wait_sec)

    if response is None:
        raise ValueError(f"Gemini generate_content failed after retries: {last_err}")

    if not response.function_calls:
        raise ValueError(
            f"Expected function call from Gemini, received text response instead: {response.text}"
        )

    # 2. Embedding dimensionality check
    embed_res = client.models.embed_content(
        model=settings.GEMINI_EMBED_MODEL,
        contents="Company Brain G8 verification",
        config=types.EmbedContentConfig(output_dimensionality=settings.EMBED_DIM),
    )

    if not embed_res.embeddings or not embed_res.embeddings[0].values:
        raise ValueError("Gemini embedding returned empty vector")

    actual_dim = len(embed_res.embeddings[0].values)
    if actual_dim != settings.EMBED_DIM:
        raise ValueError(f"Expected embedding dimension {settings.EMBED_DIM}, got {actual_dim}")


def main() -> None:
    """Execute all B0 verification gates and print results."""
    failed = False

    env_target = os.getenv("ENV_FILE", ".env")
    print(f"Loading configuration from '{env_target}'...", flush=True)

    # 1. Load settings (fail-fast)
    try:
        settings = get_settings()
        print(
            f"Connecting to FalkorDB at {settings.FALKORDB_HOST}:{settings.FALKORDB_PORT} (SSL={settings.FALKORDB_SSL})...",
            flush=True,
        )
    except Exception as exc:
        print(f"FAIL Settings: {exc}", flush=True)
        sys.exit(1)

    # 2. Connect to DB and get scratch graph
    client = None
    try:
        client = get_db()
        cleanup_scratch_graph(client)
        scratch_graph = client.select_graph(SCRATCH_GRAPH_NAME)
        print("Connected to FalkorDB scratch graph.", flush=True)
    except Exception as exc:
        print(f"FAIL Connection: {exc}", flush=True)
        sys.exit(1)

    try:
        # Gate G1
        try:
            run_g1(scratch_graph, settings.EMBED_DIM)
            print("PASS G1")
        except Exception as exc:
            print(f"FAIL G1: {exc}")
            failed = True

        # Gate G2
        if not failed:
            try:
                g2_info = run_g2(scratch_graph, settings.EMBED_DIM)
                print(f"PASS G2 ({g2_info})")
            except Exception as exc:
                print(f"FAIL G2: {exc}")
                failed = True

        # Gate G3
        try:
            run_g3(scratch_graph)
            print("PASS G3")
        except Exception as exc:
            print(f"FAIL G3: {exc}")
            failed = True

        # Gate G4
        try:
            run_g4(scratch_graph)
            print("PASS G4")
        except Exception as exc:
            print(f"FAIL G4: {exc}")
            failed = True

        # Gate G5
        try:
            run_g5(scratch_graph)
            print("PASS G5")
        except Exception as exc:
            print(f"FAIL G5: {exc}")
            failed = True

        # Gate G6
        try:
            run_g6()
            print("PASS G6")
        except Exception as exc:
            print(f"FAIL G6: {exc}")
            failed = True

        # Gate G8
        try:
            run_g8(settings)
            print("PASS G8")
        except Exception as exc:
            print(f"FAIL G8: {exc}")
            failed = True

    finally:
        # Always clean up the scratch graph
        if client is not None:
            cleanup_scratch_graph(client)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
