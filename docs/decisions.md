# Technical Decisions Log

## 1. Pinned Versions

| Component | Pinned Version | Rationale |
|---|---|---|
| FalkorDB Docker Image | `falkordb/falkordb:6.0.2` | Latest stable release featuring the Rust core engine and bundled browser UI on port 3000 |
| `falkordb` (Python) | `1.8.0` | Exact version installed from PyPI during initial B0 bootstrap |
| `mcp` (Python) | `2.3.0` | FastMCP / MCP SDK version with primitive JSON Schema serialization |
| `google-genai` (Python) | `2.31.0` | Official Google GenAI SDK release |
| `fastapi` (Python) | `0.143.3` | Pinned exact FastAPI framework version |
| Python (Backend Runtime) | `3.11` / `3.14` | Compatible with FalkorDB and Google GenAI SDK |
| Node.js / npm (Frontend) | `20-alpine` / npm 10+ | LTS Node release for Vite and Tailwind CSS bundle creation |

---

## 2. Fixed Architectural Decisions (D1 to D14)

| ID | Decision | Rationale |
|---|---|---|
| **D1** | One graph, named by `FALKORDB_GRAPH` (default `company_brain`) | Single source of truth across code activity, documentation, and synthetic organizational artifacts. |
| **D2** | FalkorDB via Docker; Python sync client (`falkordb` package) | Mandatory DB; simple, thread-safe pool without async connection overhead. |
| **D3** | Every node has `id` (globally unique string), `display` (string), `source` (`github`\|`synthetic`\|`agent`) | Universal node interface for API, UI cytoscape elements, MCP tools, and citations. |
| **D4** | All timestamps are integer epoch seconds (UTC) in graph, API, and MCP | Eliminates timezone parsing inconsistencies; frontend handles localized formatting. |
| **D5** | **Pseudonymization:** `person_id = "p_" + sha256(PSEUDONYM_SALT + login)[:8]`, `display = "Contributor " + that 8-hex`. Emails, real names, and avatars are never stored | Hackathon rule: no personal data. Also makes identity resolution deterministic. |
| **D6** | Cypher lives only in `brain_core/queries.py` as named constants `Q01..Qnn`. MCP server and REST both import them | No duplicate or drifting queries. `docs/queries.md` is generated from this file. |
| **D7** | Backend Pydantic models are the only API schema. Frontend TypeScript types are generated from OpenAPI | Zero frontend/backend contract drift. Types generated via `npm run gen:types`. |
| **D8** | Agent reaches graph only through MCP server (stdio child). REST read endpoints use `brain_core` services directly | Satisfies "tool selection through MCP"; UI endpoints stay fast and direct. |
| **D9** | Freshness is derived at query time, never stored as a flag | Prevents out-of-sync cache bugs when code or decisions evolve. |
| **D10** | Frontend calls relative `/api/...` only. Vite dev proxy and nginx proxy forward `/api` to the backend | Eliminates CORS issues and avoids hardcoded hostnames. |
| **D11** | Frontend language is TypeScript | Required for generated OpenAPI type safety and strict schema enforcement. |
| **D12** | Live demo = one Docker image: FastAPI serves `/api` and the built SPA from the same origin, against FalkorDB Cloud | Keeps D10 true in production; one service to host. |
| **D13** | Public-exposure controls: `DEMO_MODE`, `ENABLE_INGEST_REFRESH`, per-IP chat rate limit | A public URL must not expose token-spending or destructive routes unguarded. |
| **D14** | Synthetic text is deterministic templates; Gemini paraphrase is an optional upgrade (`synth --llm`) that never changes ids, structure or ground truth | Reliability first, polish if time allows. |

---

## 3. Configuration & Rationale

### Scoring Weights Rationale (`scoring.py`)
- **Weights:** `W_PR = 1`, `W_THREAD = 2`, `W_DECISION = 3`.
- **Rationale:** Decision authoring (`W_DECISION = 3`) carries the highest institutional knowledge weight, followed by discussion in decision threads (`W_THREAD = 2`), and individual PR code touchpoints (`W_PR = 1`).

### Stale PR Threshold (`STALE_PR_THRESHOLD`)
- **Value:** `1`
- **Rationale:** Set to 1 so that any subsequent merged code change touching an affected module triggers freshness drift and immediately signals architectural attention.

### Module Rules Rationale for `fastapi/fastapi`
- **Rules:** `[{"prefix": "fastapi/", "depth": 1}, {"prefix": "docs/en/docs/", "depth": 1}, {"prefix": "tests/", "depth": 1}]`
- **Rationale:** Core library code is nested under `fastapi/`, English documentation is under `docs/en/docs/`, and tests/benchmarks are under `tests/`. Depth 1 groups files into meaningful architectural components (e.g., `fastapi/dependencies`, `fastapi/routing`, `docs/en/docs/advanced`, `tests/test_tutorial`) without fragmenting into individual files or collapsing everything into one root module. Files outside these prefixes are ignored.

### Doc Exclude Rationale (`DOC_EXCLUDE`)
- **Value:** `people,sponsors,release-notes,external-links,newsletter,contributing`
- **Rationale:** These pages contain community, administrative, and sponsorship text rather than technical architecture, routing, dependency injection, and framework design documentation. Excluding them prevents vector search noise and keeps semantic retrieval focused on technical architecture.

---

## 4. Implementation Decisions & Spec Deviations

### B0: Vector Index Score Direction (Gate G2)
- **Decision:** In `db.idx.vector.queryNodes`, cosine similarity returns distance scores where exact match yields `0.0` and orthogonal vectors yield `1.0`. Therefore, a **LOWER score means CLOSER**.
- **Reason:** Verified experimentally via Gate G2 on FalkorDB 6.0.2. In `search_knowledge` and ranking queries, results are sorted in ascending order (`ASC`) by score.

### B0: ShortestPath Syntax (Gate G4)
- **Spec Deviation / Syntax Accommodation:** FalkorDB 6.0.2 requires `shortestPath` expressions within a `WITH` clause: `WITH shortestPath((a)-[*..6]-(b)) AS p RETURN p`.
- **Reason:** FalkorDB does not support undirected `shortestPath` directly in the `MATCH` pattern. Formulating with `WITH shortestPath(...) AS p` ensures compatibility across Docker and Cloud.

### B1: Idempotent Schema Application (`schema.py`)
- **Decision:** Caught FalkorDB `ResponseError: Attribute '...' is already indexed` in addition to `already exists` and `equivalent index`.
- **Reason:** FalkorDB emits `Attribute 'id' is already indexed` when re-creating range indexes. Catching this specific error message guarantees `schema.apply()` can be executed multiple times safely without failing.

### B2: Ingestion Cache File Layout (`data/cache/github/`)
- **Decision:** The GitHub fetcher stores strictly reduced, pseudonymized, scrubbed JSON artifacts in `data/cache/github/`:
  - `repo.json`: `{ "repo": str, "default_branch": str, "fetched_at": int }`
  - `prs.json`: Array of `{ "number": int, "title": str, "body_excerpt": str, "created_at": int, "merged_at": int, "author_id": str, "url": str, "files": [str] }`
  - `docs.json`: Array of `{ "path": str, "title": str, "kind": str, "updated_at": int, "body": str, "url": str }`
- **Reason:** Per Section 7 and Decision D5, no personal identifying data is ever written to disk or the graph database.

### B3: Synthetic Generation and Freshness Distribution (`synthetic_gen.py`)
- **Decision:** Implemented deterministic synthetic entity generation using `random.Random(SYNTH_SEED)` with strict iteration over sorted collections.
- **Reason:** Guarantees that the freshness distribution gate (minimum 3 fresh, 3 stale, and 1 superseded decision) is satisfied deterministically on `SYNTH_SEED=42` and `SYNTH_DECISIONS=12` without artificial drift overrides.

### B4: Gemini Embeddings Configuration (`embed.py`, `embeddings.py`)
- **Decision:** Used `google-genai` SDK with `GEMINI_EMBED_MODEL` (`gemini-embedding-001`) and `output_dimensionality = EMBED_DIM` (3072).
- **Task Types:** `task_type="RETRIEVAL_DOCUMENT"` for stored graph texts (`Doc`, `Decision`, `Thread`), and `task_type="RETRIEVAL_QUERY"` for runtime search queries in `embed_query(text)`.
- **Storage:** Persisted in FalkorDB using `vecf32(item.vec)`.

### B5: Module Name Disambiguation in Services (`services.py`)
- **Spec Deviation / Implementation Polish:** When resolving modules by query string, paths containing slashes (e.g. `docs/en/docs` or `fastapi/dependencies`) use exact-match resolution when multiple matches occur. Bare root queries without slashes (e.g. `fastapi`) return `ok=False` with `data.candidates` to satisfy Test T4 anti-clash rules.

### B6: MCP Server & Gemini Schema Gate (`server.py`, `mcp_client.py`)
- **Decision:** All 11 MCP tool parameters are strictly constrained to primitives (`str`, `int`, `bool`, `Literal[...]`, `list[Literal[...]]`) with defaults for optional fields, avoiding `Optional`, `Union`, nested objects, or `$ref`.
- **Reason:** Satisfies Gate G6 and guarantees seamless conversion to Google Gemini `FunctionDeclaration` without schema validation failures.

### B7: Child MCP Lifecycle & Watchdog Auto-Restart (`brain_api/`)
- **Decision:** `MCPProcessManager` runs `python -m mcp_server` over stdio with an asynchronous watchdog that detects crashes and auto-restarts within 1 second. `call_tool()` retries on connection drops.

### B8: LLM Model Selection & Rate Limit Resilience (`loop.py`, `.env`)
- **Spec Deviation:** Runtime default set to `GEMINI_MODEL=gemini-3.5-flash-lite` (with compatibility for `gemini-3.7-flash` and `gemini-3.8-flash`).
- **Reason:** Gemini free-tier quotas on `gemini-3.6-flash` and `gemini-3.5-flash` hit 20 requests/day exhaustion, while `gemini-3.7-flash` is capped at 5 RPM. `gemini-3.5-flash-lite` offers high RPM allowances, stable function-calling, and fast response times (~2-4 seconds per tool round).

### B9–B10: Frontend Core & Reactive Verification (`web/`)
- **Decision:** Full TypeScript type generation via `npm run gen:types`. No hand-written API types.
- **Graph Visualization:** Built with Cytoscape (`cose` layout for overview, `breadthfirst` for traces, `.hl` highlighted styling, and 30% dimming for non-highlighted nodes).

### B11–B12: Container Topology & Production Deployment
- **Decision:** Single multi-stage container (`Dockerfile` / `deploy/Dockerfile.prod`) builds the React SPA and runs FastAPI serving both `/api` and `/` SPA fallback on port 8000.
