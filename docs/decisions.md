# Technical Decisions Log

## Pinned versions

| Component | Pinned Version | Rationale |
|---|---|---|
| FalkorDB Docker Image | `falkordb/falkordb:6.0.2` | Latest stable release featuring the Rust core engine and bundled browser UI on port 3000 |
| `falkordb` (Python) | `1.8.0` | Exact version installed from PyPI during initial B0 bootstrap |
| `mcp` (Python) | `2.3.0` | Pinned exact FastMCP / MCP SDK version |
| `google-genai` (Python) | `2.31.0` | Official Google GenAI SDK release |
| `fastapi` (Python) | `0.143.3` | Pinned exact FastAPI framework version |

## Fixed Architectural Decisions (D1 to D11)

| ID | Decision | Rationale |
|---|---|---|
| D1 | One graph, named by `FALKORDB_GRAPH` (default `company_brain`) | Single source of truth across code activity, documentation, and synthetic organizational artifacts. |
| D2 | FalkorDB via Docker; Python sync client (`falkordb` package) | Thread-safe connection pool; simple synchronous query execution without async connection overhead. |
| D3 | Every node has `id` (globally unique string), `display` (string), `source` (`github`\|`synthetic`\|`agent`) | Universal node interface for API, UI cytoscape elements, MCP tools, and citations. |
| D4 | All timestamps are integer epoch seconds (UTC) in graph, API, and MCP | Eliminates timezone parsing inconsistencies; frontend handles localized formatting. |
| D5 | Pseudonymization: `person_id = "p_" + sha256(PSEUDONYM_SALT + login)[:8]`, `display = "Contributor " + that 8-hex` | Zero personal data stored or exposed (satisfies hackathon data policy); deterministic identity resolution. |
| D6 | Cypher lives only in `brain_core/queries.py` as named constants `Q01..Qnn` | Prevents drifting queries; allows auto-generating `docs/queries.md`. |
| D7 | Backend Pydantic models are the only API schema | OpenAPI schema drives generated TypeScript types (`schema.d.ts`), preventing frontend/backend drift. |
| D8 | Agent reaches graph only through MCP server (stdio child); REST read endpoints use `brain_core` directly | Satisfies tool selection requirement through MCP while keeping REST endpoints fast and direct. |
| D9 | Freshness is derived at query time, never stored as a flag | Prevents out-of-sync cache bugs when code or decisions evolve. |
| D10 | Frontend calls relative `/api/...` only | Dev proxy in Vite and production reverse proxy in Nginx/FastAPI prevent CORS issues and hardcoded hosts. |
| D11 | Frontend language is TypeScript | Required for generated OpenAPI type safety and strict schema enforcement. |

## Implementation decisions

### B0: Virtual Environment and Dependencies Installation
- **Decision:** Installed backend packages in an editable venv (`.venv`) with setuptools build-backend and pinned dependencies in `backend/pyproject.toml`. Also installed to user Python environment to support direct execution.
- **Reason:** Ensures isolated and reproducible Python environment compliant with repository layout (Section 4) and gitignore rules, while also supporting direct invocation via `python scripts/smoke_falkordb.py`.

### B0: FalkorDB Docker Image Pinning
- **Decision:** Selected `falkordb/falkordb:6.0.2` instead of `latest` or edge tags.
- **Reason:** Section 18 requirement states to pick the latest stable release and never use `latest`. 6.0.2 is the latest official release on Docker Hub supporting the Rust engine, multi-arch amd64/arm64, port 6379 for the database, and port 3000 for the browser UI.

### B0: Vector Index Score Direction (Gate G2)
- **Decision:** In `db.idx.vector.queryNodes`, cosine similarity returns distance scores where exact match yields `0.0` and orthogonal vectors yield `1.0`. Therefore, a **LOWER score means CLOSER**.
- **Reason:** Verified experimentally via Gate G2 on FalkorDB 6.0.2. In `search_knowledge` and ranking queries, results will be sorted in ascending order (`ASC`) by score.

### B0: ShortestPath Syntax (Gate G4)
- **Decision:** Evaluated `shortestPath` within a `WITH` clause using directed traversal `(a)-[*..6]->(b)` with fallback to `algo.SPpaths`.
- **Reason:** FalkorDB does not support undirected shortestPath pattern traversals and requires shortestPath expressions inside `WITH` or `RETURN` clauses rather than directly in `MATCH`.

### B1: Scoring Weights Rationale (`scoring.py`)
- **Decision:** Set `W_PR = 1`, `W_THREAD = 2`, `W_DECISION = 3`.
- **Reason:** Decision authoring (`W_DECISION=3`) carries the highest institutional knowledge weight, followed by discussion in decision threads (`W_THREAD=2`), and individual PR code touchpoints (`W_PR=1`).

### B1: Idempotent Schema Application (`schema.py`)
- **Decision:** Caught FalkorDB `ResponseError: Attribute '...' is already indexed` in addition to `already exists` and `equivalent index`.
- **Reason:** FalkorDB emits `Attribute 'id' is already indexed` when re-creating range indexes. Catching this specific error message guarantees `schema.apply()` can be executed multiple times safely without failing.

### B1: Dotenv Resolution Across Working Directories (`config.py`)
- **Decision:** Implemented `_resolve_env_file()` to look in `.` and `..` for `.env` or custom `ENV_FILE`.
- **Reason:** Enables developers and CI runners to execute commands seamlessly from either the repository root (`python scripts/...`) or inside the `backend/` directory (`cd backend && python -c ...`).

### B2: Ingestion Cache File Layout (`data/cache/github/`)
- **Decision:** The GitHub fetcher stores strictly reduced, pseudonymized, scrubbed JSON artifacts in `data/cache/github/`:
  - `repo.json`: `{ "repo": str, "default_branch": str, "fetched_at": int }`
  - `prs.json`: Array of `{ "number": int, "title": str, "body_excerpt": str, "created_at": int, "merged_at": int, "author_id": str, "url": str, "files": [str] }`
  - `docs.json`: Array of `{ "path": str, "title": str, "kind": str, "updated_at": int, "body": str, "url": str }`
- **Reason:** Per ARCHITECTURE.md Section 7 and Decision D5, no personal identifying data (real names, emails, avatars, profile links, or raw logins) is ever written to disk or the graph database. The fetcher enforces an in-memory PII and author login leak scan before writing to cache, ensuring all cached records are completely clean and reproducible across offline runs.

### B3: Synthetic Generation and Freshness Distribution (`synthetic_gen.py`)
- **Decision:** Implemented deterministic synthetic entity generation (`teams.json`, `people_roles.json`, `decisions.json`, `tickets.json`, `threads.json`, and `ground_truth.json`) using `random.Random(SYNTH_SEED)` with strict iteration over sorted collections.
- **Decision:** The PR selection for decisions samples evenly across the chronological timeline of merged PRs, ensuring that tail indices land on PRs touching modules with zero subsequent changes in the snapshot.
- **Reason:** Guarantees that the freshness distribution gate (minimum 3 fresh, 3 stale, and 1 superseded decision) is satisfied deterministically on `SYNTH_SEED=42` and `SYNTH_DECISIONS=12` without artificial drift count overrides.

### B3: Numeric Verification Minimums (`verify.py`)
- **Decision:** Consolidated all numeric gate minimums into a dedicated constants block in `backend/ingest/verify.py`:
  - `MIN_TEAMS = 4`
  - `MIN_TICKETS = 22`
  - `MIN_THREADS = 24`
  - `MIN_PRS = 100`
  - `MIN_PERSONS = 15`
  - `MIN_MODULES = 8`
  - `MIN_DOCS = 20`
  - `MIN_FRESH_DECISIONS = 3`
  - `MIN_STALE_DECISIONS = 3`
  - `MIN_SUPERSEDED_DECISIONS = 1`
- **Reason:** Provides a single, self-documenting location for ingest threshold adjustments per ARCHITECTURE.md Section 19.

### B3: Pure Python Ground Truth Oracle (`ground_truth.json`)
- **Decision:** The expected drift counts and freshness states are computed directly in pure Python from PR timestamps and touched modules without running Cypher queries.
- **Reason:** Acts as an independent correctness oracle against which Q09 and `classify()` can be rigorously verified during `python -m ingest verify` and integration tests.
### B4: Gemini Embeddings Configuration and Idempotence (`embed.py`, `embeddings.py`)
- **Decision:** Used `google-genai` SDK with `GEMINI_EMBED_MODEL` (`gemini-embedding-001`) and `output_dimensionality = EMBED_DIM` (3072).
- **Task Types:** SDK accepted task types without error via `types.EmbedContentConfig(output_dimensionality=3072, task_type=...)`:
  - `task_type="RETRIEVAL_DOCUMENT"` for stored graph texts (`Doc`, `Decision`, `Thread`).
  - `task_type="RETRIEVAL_QUERY"` for runtime search queries in `embed_query(text)`.
- **Text Representation per Label:**
  - `Doc` = `display + "\n" + body`
  - `Decision` = `display + "\n" + summary + "\n" + rationale`
  - `Thread` = `text`
  - All other node types (`Person`, `Team`, `Module`, `File`, `PR`, `Ticket`, `ReviewRequest`) are strictly skipped without embeddings.
- **Idempotence and Storage:**
  - `text_hash = sha256(embed_text.encode("utf-8")).hexdigest()`.
  - Nodes with matching `text_hash` and non-null `embedding` are skipped on subsequent runs.
  - Vectors are persisted in FalkorDB using Cypher `SET n.embedding = vecf32(item.vec), n.text_hash = item.text_hash`.
  - Batching and exponential backoff retry logic handle Gemini 429 rate limits and 5xx transient errors.

### B5: Services Layer Architecture and Tool Contracts (`services.py`)
- **Tool Graph Rule Enforcement:** Every tool-facing function returns `ToolResult` containing `summary` (<=300 chars), `data`, `evidence`, `graph` (nodes in evidence + implied traversed edges), and `cypher_ids` tracking exactly which queries were executed.
- **Fail-Safe Contract Compliance:** Unknown IDs, ambiguous module names, or disconnected paths return `ok=False` with descriptive summaries or `data.candidates`, never throwing uncaught exceptions to clients or agent loops.
- **ShortestPath Syntax (Q13):** Formulated Q13 with `WITH shortestPath((a)-[*..6]-(b)) AS p RETURN p` matching FalkorDB 6.0.2 syntax requirements established in Gate G4.
- **PR Simulation and Demo Reset (Q21, Q22A, Q22B, Q24):** `simulate_pr` captures decision freshness before and after, dynamically generating demo PR number from Q24, creating a synthetic demo PR and file touching the targeted module, and returning only decisions whose freshness flipped. `reset_demo` atomically purges all synthetic demo nodes and review requests, restoring baseline state verified by Test T3.

### B6: MCP Server & Gemini Schema Compatibility (`server.py`, `mcp_client.py`)
- **MCP Framework Selection:** Implemented MCP server using FastMCP / MCPServer over standard input/output (`stdio`) transport. All logging explicitly routes to `sys.stderr` so `sys.stdout` remains dedicated exclusively to JSON-RPC wire frames.
- **Parameter Types & Gemini Schema Gate (Gate G6):** All 11 MCP tool parameters are strictly constrained to primitives (`str`, `int`, `bool`, `Literal[...]`, `list[Literal[...]]`) with defaults for optional fields, avoiding `Optional`, `Union`, nested objects, or `$ref`.
- **Gemini FunctionDeclaration Conversion:** `mcp_client.py` implements `convert_tool_to_function_declaration()` which recursively strips unsupported keywords (`$schema`, `title`, `$defs`) and converts input schemas to `google.genai.types.Schema` via `from_json_schema()`, verified across all 11 tools in Gate G6 and Test T4.
### B7: REST API Architecture, Error Normalization & Child MCP Auto-Restart (`brain_api/`)
- **Child MCP Lifecycle & Watchdog Auto-Restart:**
  - `MCPProcessManager` manages `python -m mcp_server` over stdio.
  - A background watchdog loop detects unexpected child termination/crashes in development within 1 second and immediately auto-restarts the server.
  - `call_tool()` transparently catches broken pipe / connection drops, restarts the child process, and retries the call once.
  - Lifespan context in FastAPI cleanly initializes the child process on startup and terminates it with bounded teardown timeouts on shutdown.
- **Strict Error Normalization:**
  - Every non-2xx REST response strictly adheres to `ErrorResponse(error=ErrorBody(code=..., message=...))` with status codes: `BAD_REQUEST` 400, `NOT_FOUND` 404, `RATE_LIMITED` 429, `GRAPH_UNAVAILABLE` 503, `LLM_ERROR` 502, `INTERNAL` 500.
  - FastAPI's 422 `RequestValidationError` is intercepted and normalized to 400 `BAD_REQUEST` with detailed validation messages, avoiding raw validation schema leakage.
- **Degradation and Exposure Controls:**
  - `GET /api/health` never 503s; when FalkorDB is unreachable it returns HTTP 200 with `status: "degraded", falkordb: false`.
  - All other routes depend on `require_falkordb` and return 503 `GRAPH_UNAVAILABLE` when the graph is unreachable (Test T5).
  - `/api/demo/*` endpoints return 404 `NOT_FOUND` when `DEMO_MODE=False`.
  - `/api/ingest/refresh` returns 404 `NOT_FOUND` when `ENABLE_INGEST_REFRESH=False`.
  - `/api/chat` enforces in-memory sliding-window rate limiting per client IP (`X-Forwarded-For` first hop or socket address).



