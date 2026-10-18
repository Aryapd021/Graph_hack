"""MCP server providing the 11 company brain graph tools via stdio transport.

Per ARCHITECTURE.md sections 11, 13, 17 (Gate G6), 19 (Task B6):
- Uses official FastMCP / MCPServer SDK with stdio transport.
- Logs strictly to stderr; stdout carries only the protocol.
- Exactly the 11 tools with exact names, parameters, and docstrings from Section 11.
- Parameter types: str, int, bool, Literal[...], list[Literal[...]]: no Optional, Union, nested models, or $ref.
- Each tool wraps a service in brain_core.services and returns ToolResult serialized as a JSON string.
- Never raises exceptions to the client: wraps any errors into ToolResult(ok=False, ...).
"""

import json
import logging
import sys
from typing import List, Literal

try:
    from mcp.server.fastmcp import FastMCP
except (ImportError, ModuleNotFoundError):
    from mcp.server.mcpserver import MCPServer as FastMCP  # type: ignore[no-redef]

from brain_core.models import GraphPayload, ToolResult
from brain_core.services import (
    check_decision_freshness as service_check_decision_freshness,
    connection_path as service_connection_path,
    flag_for_review as service_flag_for_review,
    get_decision as service_get_decision,
    key_connectors as service_key_connectors,
    list_stale_decisions as service_list_stale_decisions,
    recent_changes as service_recent_changes,
    search_knowledge as service_search_knowledge,
    trace_decision as service_trace_decision,
    who_knows as service_who_knows,
    who_owns as service_who_owns,
)

# Direct all standard logging strictly to stderr so stdout is protocol-only
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)
logger = logging.getLogger("mcp_server")

# Instantiate MCP server
mcp = FastMCP("company_brain")


def _format_result(res: ToolResult) -> str:
    """Serialize ToolResult into a JSON string."""
    return res.model_dump_json()


def _format_error(msg: str) -> str:
    """Format an unhandled exception into a serialized ToolResult(ok=False)."""
    res = ToolResult(
        ok=False,
        summary=msg[:300],
        data={},
        evidence=[],
        graph=GraphPayload(nodes=[], edges=[]),
        cypher_ids=[],
    )
    return res.model_dump_json()


@mcp.tool()
def search_knowledge(
    query: str,
    kinds: list[Literal["Decision", "Doc", "Thread"]] = ["Decision", "Doc", "Thread"],
    k: int = 5,
) -> str:
    """Semantic search over decisions, docs and chat threads. Use first when the user asks about a topic, a decision or a document and you do not yet have a node id. Returns node ids to use with other tools."""
    try:
        # Clamp k to 1..10 per section 11
        clamped_k = max(1, min(k, 10))
        res = service_search_knowledge(query=query, kinds=kinds, k=clamped_k)
        return _format_result(res)
    except Exception as exc:
        logger.error(f"Error in search_knowledge: {exc}", exc_info=True)
        return _format_error(f"Search failed: {exc}")


@mcp.tool()
def get_decision(
    decision_id: str,
) -> str:
    """Full details of one decision by id: decider, affected modules, linked docs, threads, tickets and implementing PRs."""
    try:
        res = service_get_decision(decision_id=decision_id)
        return _format_result(res)
    except Exception as exc:
        logger.error(f"Error in get_decision: {exc}", exc_info=True)
        return _format_error(f"Get decision failed: {exc}")


@mcp.tool()
def trace_decision(
    decision_id: str,
) -> str:
    """Explains why a decision was made: the ordered provenance chain from the decision to its decider, implementing PRs, ticket, chat thread, documentation and any superseding decisions. Use for 'why did we decide X'."""
    try:
        res = service_trace_decision(decision_id=decision_id)
        return _format_result(res)
    except Exception as exc:
        logger.error(f"Error in trace_decision: {exc}", exc_info=True)
        return _format_error(f"Trace decision failed: {exc}")


@mcp.tool()
def check_decision_freshness(
    decision_id: str,
) -> str:
    """Checks whether a decision is still valid: fresh, stale (later merged PRs changed what it affects) or superseded. Lists the later PRs. Always call this before saying a decision is still valid."""
    try:
        res = service_check_decision_freshness(decision_id=decision_id)
        return _format_result(res)
    except Exception as exc:
        logger.error(f"Error in check_decision_freshness: {exc}", exc_info=True)
        return _format_error(f"Check decision freshness failed: {exc}")


@mcp.tool()
def list_stale_decisions(
    limit: int = 10,
) -> str:
    """Lists stale decisions, most drifted first. Use for 'which decisions need review'."""
    try:
        clamped_limit = max(1, min(limit, 50))
        res = service_list_stale_decisions(limit=clamped_limit)
        return _format_result(res)
    except Exception as exc:
        logger.error(f"Error in list_stale_decisions: {exc}", exc_info=True)
        return _format_error(f"List stale decisions failed: {exc}")


@mcp.tool()
def who_owns(
    module: str,
) -> str:
    """Who owns a module: the owning team (formal) and the top actual contributors, with a flag when they differ. Takes a module name or path."""
    try:
        res = service_who_owns(module=module)
        return _format_result(res)
    except Exception as exc:
        logger.error(f"Error in who_owns: {exc}", exc_info=True)
        return _format_error(f"Who owns failed: {exc}")


@mcp.tool()
def who_knows(
    topic: str,
    limit: int = 5,
) -> str:
    """Finds the people who know most about a topic or module, scored from PRs, chat threads and decisions."""
    try:
        clamped_limit = max(1, min(limit, 20))
        res = service_who_knows(topic=topic, limit=clamped_limit)
        return _format_result(res)
    except Exception as exc:
        logger.error(f"Error in who_knows: {exc}", exc_info=True)
        return _format_error(f"Who knows failed: {exc}")


@mcp.tool()
def recent_changes(
    module: str,
    since_days: int = 30,
    limit: int = 10,
) -> str:
    """Recently merged PRs touching a module within the last N days."""
    try:
        clamped_days = max(1, min(since_days, 365))
        clamped_limit = max(1, min(limit, 50))
        res = service_recent_changes(module=module, since_days=clamped_days, limit=clamped_limit)
        return _format_result(res)
    except Exception as exc:
        logger.error(f"Error in recent_changes: {exc}", exc_info=True)
        return _format_error(f"Recent changes failed: {exc}")


@mcp.tool()
def connection_path(
    from_id: str,
    to_id: str,
) -> str:
    """Shortest chain of relationships between two nodes (people, modules, decisions, docs). Both arguments are node ids from earlier tool results."""
    try:
        res = service_connection_path(from_id=from_id, to_id=to_id)
        return _format_result(res)
    except Exception as exc:
        logger.error(f"Error in connection_path: {exc}", exc_info=True)
        return _format_error(f"Connection path failed: {exc}")


@mcp.tool()
def key_connectors(
    limit: int = 5,
) -> str:
    """People most central in the collaboration graph (PageRank). Use for 'who are the key connectors' or bus-factor questions."""
    try:
        clamped_limit = max(1, min(limit, 20))
        res = service_key_connectors(limit=clamped_limit)
        return _format_result(res)
    except Exception as exc:
        logger.error(f"Error in key_connectors: {exc}", exc_info=True)
        return _format_error(f"Key connectors failed: {exc}")


@mcp.tool()
def flag_for_review(
    decision_id: str,
    note: str,
) -> str:
    """Creates a review request for a decision and assigns it to the decider. Only call when the user explicitly asks to flag, escalate or request review."""
    try:
        res = service_flag_for_review(decision_id=decision_id, note=note[:300])
        return _format_result(res)
    except Exception as exc:
        logger.error(f"Error in flag_for_review: {exc}", exc_info=True)
        return _format_error(f"Flag for review failed: {exc}")


def main() -> None:
    """Start MCP server on stdio transport."""
    logger.info("Starting Company Brain MCP Server on stdio transport...")
    mcp.run("stdio")


if __name__ == "__main__":
    main()
