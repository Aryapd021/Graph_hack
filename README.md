# Track 03: Company Brain

> **Graph-Backed Organizational Intelligence Agent**  
> An autonomous AI assistant powered by **FalkorDB** and the **Model Context Protocol (MCP)** that maps codebase architecture, tracks institutional decisions, detects code drift, and surfaces team expertise with verified graph citations.

---

## 🌐 Live Demo URL

**Live Demo URL:** `TBD (added in B12)`

---

## 💡 What It Does

Company Brain unifies GitHub code activity, architecture decision records (ADRs), team structures, and communication threads into a high-performance **FalkorDB Knowledge Graph**. Powered by **Google Gemini** via **MCP stdio tools**, it delivers 5 core capabilities:

1. **Who Owns (`who_owns`)**: Identifies the formal owning team of any codebase module alongside de facto contributors, highlighting ownership gaps where active coders differ from the formal team.
2. **Who Knows (`who_knows`)**: Locates subject-matter experts for any topic or module using weighted graph scoring across merged PRs, Slack/Discord discussions, and authored architecture decisions.
3. **Why Did We Decide (`get_decision`, `trace_decision`)**: Traces the full provenance chain, historical rationale, and linked PRs, tickets, and docs behind key architecture decisions.
4. **Is That Decision Still Valid (`check_decision_freshness`, `list_stale_decisions`)**: Derives decision drift dynamically at query time by counting subsequent merged PRs touching affected modules.
5. **Flag for Review (`flag_for_review`)**: Writes back to the graph by creating a `ReviewRequest` node linked to the decision and automatically assigned to the original decider.

Every factual response terminates in cryptographically verified citations `[[node_id]]` validated against tool evidence gathered during that turn.

---

## ⚡ Why the Graph Matters (FalkorDB Dependency)

**The product stops working without FalkorDB.** Company Brain is not a naive RAG wrapper with an optional cache; its reasoning capabilities depend fundamentally on graph topology:

- **Graph Algorithms at the Core**: Contributor centrality relies on native matrix PageRank (`algo.pageRank`), while provenance and organizational bridges require graph traversal (`shortestPath`).
- **Dynamic Decision Freshness**: Drift is computed directly in Cypher (`Q08`) across multi-hop paths `(:Decision)-[:AFFECTS]->(:Module)<-[:PART_OF]-(:File)<-[:TOUCHES]-(:PR)`.
- **Hybrid Vector Indexing**: 3072-dimensional cosine similarity embeddings are indexed directly in FalkorDB (`db.idx.vector.queryNodes`) for semantic retrieval.
- **Proof of Dependency (Test T5)**: Automated test [`backend/tests/test_t5_degradation.py`](backend/tests/test_t5_degradation.py) proves that when FalkorDB is stopped or unreachable, `/api/health` reports `status: "degraded"` (`falkordb: false`), and all agent and data endpoints fail safely with `503 GRAPH_UNAVAILABLE`.

---

## 🏗️ Architecture Overview

The system architecture follows Section 3 of `ARCHITECTURE.md`:

```
                           +----------------------+
 Browser (React/Vite) ---> | nginx :8080          |  /api/* -> api:8000, else static SPA
                           +----------+-----------+
                                      |
                           +----------v-----------+      stdio (spawned child)      +------------------+
                           | FastAPI "brain_api"  | <-----------------------------> | MCP server       |
                           |  - REST routes       |   MCP tools/list, tools/call    | "mcp_server"     |
                           |  - Agent loop        |                                 |  11 tools        |
                           |    (Gemini function  |                                 +---------+--------+
                           |     calling)         |                                           |
                           +----------+-----------+                                           |
                                      | brain_core (queries, services, freshness)             |
                                      +----------------------+--------------------------------+
                                                             v
                                                  +----------------------+
                                                  | FalkorDB :6379       |  browser UI :3000 (debug only)
                                                  +----------^-----------+
                                                             |
                                  +--------------------------+------------------+
                                  | ingest CLI (python -m ingest ...)           |
                                  | GitHub REST -> cache -> graph; synthetic gen |
                                  +---------------------------------------------+
```

---

## 📊 Graph Data Model

### Node Labels (10 Types)

| Label | Description | Key Properties |
|---|---|---|
| `Person` | Contributor or engineer (pseudonymized) | `id`, `display`, `role` |
| `Team` | Organizational team | `id`, `display` |
| `Module` | Codebase component/directory | `id`, `display`, `path` |
| `File` | Source code file | `id`, `display`, `path`, `source` |
| `PR` | Pull Request (code change) | `id`, `number`, `display`, `merged_at`, `state` |
| `Doc` | Documentation page / Markdown file | `id`, `display`, `body`, `url`, `embedding` |
| `Decision` | Architecture Decision Record (ADR) | `id`, `display`, `summary`, `rationale`, `decided_at`, `status`, `embedding` |
| `Ticket` | Issue or tracking ticket | `id`, `key`, `display`, `status`, `created_at` |
| `Thread` | Slack/Discord discussion thread | `id`, `display`, `channel`, `text`, `started_at`, `embedding` |
| `ReviewRequest`| Flagged architectural review | `id`, `display`, `note`, `status`, `created_at`, `source` |

### Relationships (18 Types)

| Relationship Type | Source Label | Target Label | Description |
|---|---|---|---|
| `MEMBER_OF` | `Person` | `Team` | Formal team membership |
| `OWNS` | `Team` | `Module` | Formal codebase ownership |
| `AUTHORED` | `Person` | `PR` | Pull request authorship |
| `TOUCHES` | `PR` | `File` | File modifications in a PR |
| `PART_OF` | `File` | `Module` | File hierarchy within a module |
| `PARTICIPATED_IN` | `Person` | `Thread` | Discussion engagement |
| `ASSIGNED_TO` | `Ticket` / `ReviewRequest` | `Person` | Task or review responsibility |
| `RESOLVES` | `PR` | `Ticket` | Issue resolution by PR |
| `DECIDED_BY` | `Decision` | `Person` | Architecture decision authority |
| `AFFECTS` | `Decision` | `Module` | Target module governed by decision |
| `IMPLEMENTS` | `PR` | `Decision` | Code change realizing a decision |
| `DOCUMENTED_IN` | `Decision` | `Doc` | Reference documentation link |
| `DISCUSSED_IN` | `Decision` | `Thread` | Communication channel discussion |
| `TRACKED_BY` | `Decision` | `Ticket` | Project management tracking |
| `SUPERSEDED_BY` | `Decision` | `Decision` | Successor architectural policy |
| `MENTIONS` | `Thread` / `Doc` | `Module` | Contextual reference to a component |
| `COLLABORATES_WITH` | `Person` | `Person` | Co-authorship network (`weight` derived from shared module PRs) |
| `REVIEWS` | `ReviewRequest` | `Decision` | Pending review link |

---

## 🔍 Cypher Queries & Algorithms

All 27 Cypher queries are strictly isolated in [`backend/brain_core/queries.py`](backend/brain_core/queries.py) as named constants `Q01` through `Q27`. Hand-editing of query documentation is prohibited; the registry is generated via `python scripts/gen_queries_doc.py`.

- Complete Query Reference: [`docs/queries.md`](docs/queries.md)
- **PageRank Centrality (`Q14`)**: Evaluates influence across the collaboration network (`COLLABORATES_WITH`) using FalkorDB's native matrix algorithm:
  ```cypher
  CALL algo.pageRank('Person', 'COLLABORATES_WITH') YIELD node, score
  RETURN node.id AS id, node.display AS display, score
  ORDER BY score DESC LIMIT $limit
  ```
- **Freshness Rule (`Q08` / `classify`)**: Evaluates subsequent merged PRs touching affected modules. A decision is classified as:
  - `superseded`: If `(:Decision)-[:SUPERSEDED_BY]->(:Decision)` exists.
  - `stale`: If count of subsequent PRs where `pr.merged_at > decision.decided_at` AND NOT `(pr)-[:IMPLEMENTS]->(decision)` is $\ge \text{STALE\_PR\_THRESHOLD}$ (default 1).
  - `fresh`: If drift count is 0.

---

## 🚀 Local Setup

Follow Section 18 of `ARCHITECTURE.md`:

```bash
# 1. Clone repository and configure environment
git clone https://github.com/Aryapd021/Graph_hack.git
cd Graph_hack

# Copy template; config.py automatically resolves .env or custom ENV_FILE
cp .env.example .env
# Edit .env and supply GEMINI_API_KEY

# 2. Start FalkorDB container
docker compose up -d falkordb
python scripts/smoke_falkordb.py

# 3. Ingest snapshot data & build graph
cd backend
pip install -e .
python -m ingest all
cd ..

# 4. Start backend API & Vite frontend
# Terminal 1: Backend API
cd backend
python -m uvicorn brain_api.main:app --port 8000 --host 127.0.0.1

# Terminal 2: Web UI
cd web
npm install
npm run gen:types
npm run dev
# Open http://localhost:5173 (or http://localhost:8080 via Docker Compose)
```

> **Note on `ENV_FILE`**: `config.py` searches both current and parent directories for `.env`. To run against FalkorDB Cloud locally without touching `.env`, set `ENV_FILE=.env.cloud`.

---

## ☁️ Deployment

Summarized from Section 18b of `ARCHITECTURE.md`:

- **Topology**: Single-container deployment where FastAPI serves `/api/*` and the static React SPA (`web/dist` mounted at `/`) over a unified origin, connecting to FalkorDB Cloud via TLS.
- **Production Container**: Built via multi-stage [`Dockerfile`](Dockerfile) (Stage 1: Node 20 builds `web/dist`; Stage 2: Python 3.11-slim installs backend and runs Uvicorn on single worker).
- **Public Exposure Controls**: `DEMO_MODE=true` enables `/api/demo/*`; `ENABLE_INGEST_REFRESH=false` protects public servers; per-client IP rate limiter (`CHAT_RATE_LIMIT_PER_MIN=10`) guards the Gemini agent loop.
- **1-Click Blueprints**: Configured for Railway ([`railway.json`](railway.json)) and Render ([`render.yaml`](render.yaml)).

---

## 🔒 Data and Privacy Statement

> GitHub data comes from the public repository `fastapi/fastapi` and contains only public information. Contributor identities are pseudonymized (hashed with a private salt) and emails, names and profile links are removed before anything is stored. All Slack-style and Jira-style records (teams, tickets, chat threads, decisions) are synthetic and generated deterministically from the public data. No private, login-protected, paywalled or personal data is used.

---

## 🤖 AI Disclosure

> This project was built with AI assistance. Claude (Anthropic) helped design the architecture and plan. Antigravity (AI coding assistant) generated much of the code. I reviewed, tested and can explain every part of it, and the design decisions are documented in `docs/decisions.md`. At runtime the agent uses Google's Gemini models (`gemini-3.5-flash-lite`, `gemini-embedding-001`).

---

## 🧪 Testing

Automated test execution is orchestrated via `scripts/test.sh`. All tests run against safe isolated test graphs (`company_brain_test`) per the mandatory test-safety rule.

```bash
# Run full test suite (T1 through T8)
bash scripts/test.sh
```

### Test Suite Index (T1 – T8)

| Test ID | File | Verification Objective |
|---|---|---|
| **T1** | [`backend/tests/test_t1_fixture.py`](backend/tests/test_t1_fixture.py) | Ingest tiny fixture snapshot; verify deterministic node & edge count parity. |
| **T2** | [`backend/tests/test_b5_services.py`](backend/tests/test_b5_services.py) | `Q09` freshness state for every decision equals `ground_truth.json` oracle. |
| **T3** | [`backend/tests/test_b5_services.py`](backend/tests/test_b5_services.py) | `simulate_pr` flips affected decision freshness; `reset_demo` fully restores baseline. |
| **T4** | [`backend/tests/test_t4_mcp.py`](backend/tests/test_t4_mcp.py) | All 11 MCP tools return `ToolResult` with valid evidence and fail-safe error handling. |
| **T5** | [`backend/tests/test_t5_degradation.py`](backend/tests/test_t5_degradation.py) | FalkorDB stopped: `/api/health` reports degraded, `/api/chat` returns 503 `GRAPH_UNAVAILABLE`; container restarts and recovers. |
| **T6** | [`backend/tests/test_t6_agent.py`](backend/tests/test_t6_agent.py) | Citation filter strips ungrounded markers `[[unknown_id]]` and keeps verified ones. |
| **T7** | [`backend/tests/test_t7_contract.py`](backend/tests/test_t7_contract.py) | Every REST route validates strictly against Pydantic models; child MCP auto-restarts on crash. |
| **T8** | [`backend/tests/test_t8_cypher_isolation.py`](backend/tests/test_t8_cypher_isolation.py) | Grep test ensures no `MATCH`, `MERGE`, `CALL`, `CREATE`, or `UNWIND` string literals exist in `mcp_server/` or `brain_api/`. |

---

## 📜 License

[MIT License](LICENSE) — Copyright (c) 2026 Arya P D. All rights reserved.
