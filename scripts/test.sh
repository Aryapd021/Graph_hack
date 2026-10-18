#!/usr/bin/env bash
# Test safety (mandatory) rule from ARCHITECTURE.md section 17
# Enforces safe local test graph parameters before invoking pytest.
set -euo pipefail

export FALKORDB_HOST=localhost
export FALKORDB_PORT=6379
export FALKORDB_USERNAME=""
export FALKORDB_PASSWORD=""
export FALKORDB_SSL=false
export FALKORDB_GRAPH=company_brain_test

# Fallback test values for core variables if not provided in environment
export GEMINI_API_KEY="${GEMINI_API_KEY:-test-gemini-key}"
export GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.8-flash}"
export GEMINI_EMBED_MODEL="${GEMINI_EMBED_MODEL:-gemini-embedding-001}"
export EMBED_DIM="${EMBED_DIM:-3072}"
export GITHUB_REPO="${GITHUB_REPO:-fastapi/fastapi}"

# Detect virtual environment pytest binary if available
if [ -f ".venv/Scripts/pytest" ]; then
    PYTEST_BIN=".venv/Scripts/pytest"
elif [ -f ".venv/bin/pytest" ]; then
    PYTEST_BIN=".venv/bin/pytest"
else
    PYTEST_BIN="pytest"
fi

"$PYTEST_BIN" backend/tests "$@"
