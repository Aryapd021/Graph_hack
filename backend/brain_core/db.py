"""FalkorDB database client and graph connection provider.

Per ARCHITECTURE.md sections 2, 5, 17:
- Pass host, port, username, password, ssl as separate arguments (never URL strings).
- Empty username or password means None.
- Expose get_db(), get_graph(), and ping() helper.
"""

from typing import Optional

from falkordb import FalkorDB
from falkordb.graph import Graph
from redis.exceptions import ConnectionError, RedisError

from brain_core.config import get_settings


def get_db(
    host: Optional[str] = None,
    port: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    ssl: Optional[bool] = None,
) -> FalkorDB:
    """Initialize and return a FalkorDB client instance.

    Passes host, port, username, password, and ssl as separate arguments.
    Falls back to settings if arguments are not provided.
    Empty string username or password is treated as None.
    """
    settings = get_settings()

    target_host = host if host is not None else settings.FALKORDB_HOST
    target_port = port if port is not None else settings.FALKORDB_PORT
    raw_user = username if username is not None else settings.FALKORDB_USERNAME
    raw_pass = password if password is not None else settings.FALKORDB_PASSWORD
    target_ssl = ssl if ssl is not None else settings.FALKORDB_SSL

    # Why: Section 5 explicitly specifies empty username or password means None
    target_username = raw_user.strip() if (raw_user and raw_user.strip()) else None
    target_password = raw_pass.strip() if (raw_pass and raw_pass.strip()) else None

    # Why: Section 5 prohibits constructing redis:// URLs to avoid credential escaping issues
    return FalkorDB(
        host=target_host,
        port=target_port,
        username=target_username,
        password=target_password,
        ssl=target_ssl,
        socket_connect_timeout=10,
        socket_timeout=15,
    )


def get_graph(
    graph_name: Optional[str] = None,
    db: Optional[FalkorDB] = None,
) -> Graph:
    """Retrieve a Graph instance by name.

    If graph_name is omitted, defaults to FALKORDB_GRAPH from settings.
    If db is omitted, initializes a default client via get_db().
    """
    settings = get_settings()
    target_name = graph_name if graph_name is not None else settings.FALKORDB_GRAPH
    client = db if db is not None else get_db()
    # Why: select_graph returns the handle used for all Cypher query executions
    return client.select_graph(target_name)


def ping(db: Optional[FalkorDB] = None) -> bool:
    """Check connectivity to FalkorDB.

    Returns True if reachable and responding to PING, False otherwise.
    Never throws ConnectionError so callers (e.g. /api/health) can degrade gracefully.
    """
    client = db if db is not None else get_db()
    try:
        # Why: FalkorDB delegates command execution to the underlying Redis connection
        return bool(client.connection.ping())
    except (ConnectionError, RedisError, OSError):
        # Why: Per section 14 degradation rules, unreachable DB returns false without crashing
        return False
