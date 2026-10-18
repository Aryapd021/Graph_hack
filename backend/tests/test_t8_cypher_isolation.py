"""Test T8: Cypher isolation anti-clash rule verification.

Per ARCHITECTURE.md Section 16 Rule 2 & Section 17 Test T8:
- Cypher: only queries.py (and ingest loaders).
- A grep test fails if MATCH, MERGE, or CALL string literals appear in:
  - backend/mcp_server/
  - backend/brain_api/
"""

from pathlib import Path
import re
import pytest


def test_t8_cypher_isolation():
    """Verify that no Cypher query statements (MATCH, MERGE, CALL) appear as string literals

    inside backend/mcp_server/ or backend/brain_api/. All Cypher queries must be isolated
    in brain_core/queries.py.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    backend_dir = repo_root / "backend"

    forbidden_patterns = [
        re.compile(r'["\'].*?\bMATCH\s+.*__["\']', re.IGNORECASE),
        re.compile(r'["\'].*?\bMERGE\s+.*__["\']', re.IGNORECASE),
        re.compile(r'["\'].*?\bCALL\s+.*__["\']', re.IGNORECASE),
    ]

    target_dirs = [
        backend_dir / "mcp_server",
        backend_dir / "brain_api",
    ]

    violations = []

    for directory in target_dirs:
        assert directory.exists(), f"Target directory does not exist: {directory}"
        for py_file in directory.rglob("*.py"):
            lines = py_file.read_text(encoding="utf-8").splitlines()
            for line_no, line in enumerate(lines, start=1):
                # Ignore comments
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue

                for pattern in forbidden_patterns:
                    if pattern.search(line):
                        violations.append(
                            f"{py_file.relative_to(repo_root)}:{line_no} -> {stripped}"
                        )

    assert not violations, (
        f"Cypher isolation violation (Section 16 Rule 2 / Test T8). "
        f"Found Cypher keywords in forbidden directories:\n" + "\n".join(violations)
    )
