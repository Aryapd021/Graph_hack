"""FastAPI dependencies for route protection and health verification.

Per ARCHITECTURE.md Section 14 & Test T5:
- If FalkorDB is unreachable, non-health routes return 503 GRAPH_UNAVAILABLE.
"""

from brain_api.exceptions import GraphUnavailableException
from brain_core.db import get_db


def require_falkordb() -> None:
    """Ensure FalkorDB is reachable before executing database-dependent routes."""
    try:
        db = get_db()
        db.connection.ping()
    except Exception as exc:
        raise GraphUnavailableException(f"FalkorDB is unreachable: {exc}")
