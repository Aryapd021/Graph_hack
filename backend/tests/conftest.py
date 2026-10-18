"""Test configuration and safety checks for Company Brain test suite.

Per ARCHITECTURE.md section 17:
- Aborts the entire test session if FALKORDB_GRAPH does not end in '_test'.
- Aborts if FALKORDB_HOST is not 'localhost', '127.0.0.1', or 'falkordb'.
- Aborts if FalkorDB Cloud credentials (username/password) are present.
"""

import pytest
from brain_core.config import get_settings


def pytest_sessionstart(session: pytest.Session) -> None:
    """Validate test safety rules before any test executes.

    Why: ARCHITECTURE.md section 17 strictly enforces test safety to prevent tests from
    mutating non-test graphs or connecting to FalkorDB Cloud instances.
    """
    try:
        settings = get_settings()
    except Exception as exc:
        pytest.exit(f"Failed to load test settings: {exc}", returncode=1)

    # Why: Section 17 mandates that tests run only against a graph whose name ends in '_test'
    if not settings.FALKORDB_GRAPH.endswith("_test"):
        pytest.exit(
            f"TEST SAFETY ABORT: FALKORDB_GRAPH '{settings.FALKORDB_GRAPH}' does not end with '_test'",
            returncode=1,
        )

    # Why: Section 17 mandates host must be local Docker or compose network
    allowed_hosts = {"localhost", "127.0.0.1", "falkordb"}
    if settings.FALKORDB_HOST not in allowed_hosts:
        pytest.exit(
            f"TEST SAFETY ABORT: FALKORDB_HOST '{settings.FALKORDB_HOST}' is not in {allowed_hosts}",
            returncode=1,
        )

    # Why: Section 17 strictly forbids running tests with FalkorDB Cloud credentials
    if settings.FALKORDB_USERNAME or settings.FALKORDB_PASSWORD:
        pytest.exit(
            "TEST SAFETY ABORT: FalkorDB credentials detected in test environment. Never run tests with Cloud credentials.",
            returncode=1,
        )


@pytest.fixture
def test_graph():
    """Provide clean isolated test graph instance for tests."""
    from brain_core.db import get_graph

    g = get_graph()
    try:
        g.delete()
    except Exception:
        pass
    yield g
    try:
        g.delete()
    except Exception:
        pass

