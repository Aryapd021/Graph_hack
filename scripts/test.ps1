# Test safety (mandatory) rule from ARCHITECTURE.md section 17
# Enforces safe local test graph parameters before invoking pytest on Windows PowerShell.
$ErrorActionPreference = "Stop"

$env:FALKORDB_HOST = "localhost"
$env:FALKORDB_PORT = "6379"
$env:FALKORDB_USERNAME = ""
$env:FALKORDB_PASSWORD = ""
$env:FALKORDB_SSL = "false"
$env:FALKORDB_GRAPH = "company_brain_test"

if (-not $env:GEMINI_API_KEY) { $env:GEMINI_API_KEY = "test-gemini-key" }
if (-not $env:GEMINI_MODEL) { $env:GEMINI_MODEL = "gemini-3.5-flash-lite" }
if (-not $env:GEMINI_EMBED_MODEL) { $env:GEMINI_EMBED_MODEL = "gemini-embedding-001" }
if (-not $env:EMBED_DIM) { $env:EMBED_DIM = "3072" }
if (-not $env:GITHUB_REPO) { $env:GITHUB_REPO = "fastapi/fastapi" }

python -m pytest backend/tests $args
