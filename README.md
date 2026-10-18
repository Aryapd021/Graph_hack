# Track 03: Company Brain

> **Graph-Backed Organizational Intelligence Agent**  
> An autonomous AI assistant powered by **FalkorDB** and the **Model Context Protocol (MCP)** that maps codebase architecture, tracks institutional decisions, detects code drift, and surfaces team expertise with verified graph citations.

---

## 🏆 Track & Problem Statement

Modern software organizations suffer from fragmented institutional memory:
- **Architectural decisions** rot silently in stale docs, Slack threads, or tickets as codebases evolve.
- **Decision drift** occurs when PRs modify modules in ways that contradict previous architecture decisions, with zero alerts.
- **Knowledge silos and ownership gaps** emerge when the contributors writing the code differ from the formal owning team.

**Company Brain** solves this by unifying GitHub code activity, architecture decision records (ADRs), team structures, and communication threads into a high-performance **FalkorDB Knowledge Graph**. An AI agent powered by **Google Gemini** connects to FalkorDB via **MCP stdio tools**, answering organizational questions backed strictly by graph evidence with cryptographically verified citations `[[node_id]]`.

---

## 🌟 Key Highlights & Innovations

1. **FalkorDB as Primary Graph Database & Vector Engine**:
   - Stores 10 node labels and 18 relationship types in a single cohesive property graph.
   - Leverages FalkorDB's native vector index (`db.idx.vector.queryNodes`) with 3072-dimensional cosine similarity embeddings for hybrid semantic search.
   - Executes graph algorithms (PageRank via `algo.pageRank` for collaboration centrality and `shortestPath` for provenance tracing).
   - **FalkorDB is strictly required**: Test `test_t5_degradation.py` proves the application gracefully degrades with `503 GRAPH_UNAVAILABLE` if FalkorDB is offline.

2. **Autonomous Tool Reasoning via Model Context Protocol (MCP)**:
   - Built on the official Python `mcp` SDK using FastMCP over stdio transport.
   - Exposes 11 specialized graph analysis tools (`who_owns`, `who_knows`, `check_decision_freshness`, `trace_decision`, `list_stale_decisions`, `recent_changes`, `connection_path`, `key_connectors`, `search_knowledge`, `get_decision`, `flag_for_review`).
   - Self-healing child process with auto-restart on crashes.

3. **Cryptographically Grounded Citation Verification**:
   - The agent is constrained by a strict verification harness: every factual statement must cite `[[node_id]]`.
   - The server validates markers against actual tool evidence gathered during that turn, discarding hallucinated IDs before sending answers to the UI.

4. **Dynamic Decision Freshness & PR Drift Simulation**:
   - Freshness is never a stale boolean; it is derived at query time based on subsequent merged PRs touching affected modules.
   - Live demo controls allow simulating a merged PR to watch a decision instantly flip from `fresh` to `stale` in real-time.

---

## 🏗️ Architecture Overview

```
                                  +------------------------------------+
                                  |            Frontend UI             |
                                  |    React 18 + Vite + Tailwind     |
                                  |   Cytoscape Graph + Chat Panel    |
                                  +-----------------+------------------+
                                                    |  /api/* (Relative)
                                                    v
                                  +------------------------------------+
                                  |          FastAPI Gateway           |
                                  |   Error Normalization + Rate Limit |
                                  |   Lifespan Watchdog & REST Routes  |
                                  +--------+------------------+--------+
                                           |                  |
                       Direct Cypher /     |                  | StdIO JSON-RPC
                       Read Services       |                  |
                                           v                  v
+-----------------------+         +----------------+   +---------------+
|   Google GenAI SDK    | <=====> |  Agent Loop    |   |  MCP Server   |
| Gemini 3.5 Flash-Lite |         | (Multi-turn)   |   | (11 FastMCP   |
|   Function Calling    |         | Citation Filter|   |    Tools)     |
+-----------------------+         +----------------+   +-------+-------+
                                                               |
                                                               v
                                    +----------------------------------+
                                    |        FalkorDB Graph Core       |
                                    |     Knowledge Graph + Vector     |
                                    |   PageRank + Shortest Paths      |
                                    +----------------------------------+
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

- `(:Person)-[:MEMBER_OF]->(:Team)`
- `(:Team)-[:OWNS]->(:Module)`
- `(:Person)-[:AUTHORED]->(:PR)`
- `(:PR)-[:TOUCHES]->(:File)`
- `(:File)-[:PART_OF]->(:Module)`
- `(:Person)-[:PARTICIPATED_IN]->(:Thread)`
- `(:Ticket)-[:ASSIGNED_TO]->(:Person)`
- `(:PR)-[:RESOLVES]->(:Ticket)`
- `(:Decision)-[:DECIDED_BY]->(:Person)`
- `(:Decision)-[:AFFECTS]->(:Module)`
- `(:PR)-[:IMPLEMENTS]->(:Decision)`
- `(:Decision)-[:DOCUMENTED_IN]->(:Doc)`
- `(:Decision)-[:DISCUSSED_IN]->(:Thread)`
- `(:Decision)-[:TRACKED_BY]->(:Ticket)`
- `(:Decision)-[:SUPERSEDED_BY]->(:Decision)`
- `(:Thread\|Doc)-[:MENTIONS]->(:Module)`
- `(:Person)-[:COLLABORATES_WITH {weight}]->(:Person)` *(derived from shared module PRs)*
- `(:ReviewRequest)-[:REVIEWS]->(:Decision)`, `(:ReviewRequest)-[:ASSIGNED_TO]->(:Person)`

### Graph Indexes & Constraints
- **Range Indexes**: `Module(id)`, `File(id)`, `Person(id)`, `PR(id)`, `PR(merged_at)`, `Doc(id)`, `Decision(id)`, `Decision(decided_at)`, `Ticket(id)`, `Thread(id)`, `ReviewRequest(id)`.
- **Vector Index**: 3072-dimensional vector index with cosine distance on `Doc(embedding)`, `Decision(embedding)`, and `Thread(embedding)`.

---

## 🛠️ The 11 MCP Tools

| Tool | Purpose | FalkorDB Queries |
|---|---|---|
| `search_knowledge` | Hybrid semantic vector search over Decisions, Docs, Threads | `Q04` (Vector index) |
| `get_decision` | Inspect an ADR with all its linked graph entities | `Q05` |
| `trace_decision` | Traverse provenance and supersession chains | `Q05`, `Q06`, `Q07`, `Q08` |
| `check_decision_freshness` | Compute live decision drift and subsequent PRs | `Q05`, `Q08` |
| `list_stale_decisions` | Find all drifted decisions ordered by drift count | `Q09` |
| `who_owns` | Formal team ownership vs de facto contributors (ownership gap) | `Q03`, `Q01`, `Q02` |
| `who_knows` | Identify subject-matter experts using PR, Thread, and ADR scoring | `Q03`, `Q04`, `Q23`, `Q11a-d` |
| `recent_changes` | List merged PRs touching a module within N days | `Q03`, `Q12` |
| `connection_path` | Shortest path between any two nodes in the organization | `Q13` (`shortestPath`) |
| `key_connectors` | Graph centrality using PageRank on collaboration network | `Q14` (`algo.pageRank`) |
| `flag_for_review` | Create a ReviewRequest linked to a decision and assigned decider | `Q15a-c` |

*All 27 Cypher queries are strictly documented in [`docs/queries.md`](docs/queries.md).*

---

## 🚀 Local Quickstart Setup

### Prerequisites
- Docker & Docker Compose
- Python 3.11+
- Node.js 18+ & npm

### 1. Clone & Configure
```bash
git clone <repo-url>
cd GRAPH_HACK

# Copy environment variables
cp .env.example .env
# Edit .env and supply GEMINI_API_KEY
```

### 2. Start FalkorDB Container
```bash
docker compose up -d falkordb
python scripts/smoke_falkordb.py
```

### 3. Ingest Data (GitHub + Synthetic Org Data)
```bash
# Ingest snapshot, generate synthetic data, derive collaboration edges, embed vectors
cd backend
python -m ingest all
cd ..
```

### 4. Run Backend & Frontend

**Backend API:**
```bash
cd backend
python -m uvicorn brain_api.main:app --port 8000 --host 127.0.0.1
```

**Frontend Web App:**
```bash
cd web
npm install
npm run gen:types
npm run dev
# Open http://localhost:5173
```

---

## 🧪 Verification & Test Suite

Run the full pytest suite (56 tests across T1 through T8):

```bash
# Run all tests
pytest backend/tests -v
```

### Key Tests:
- `test_t1_fixture.py`: Verifies deterministic ingestion against tiny ground truth.
- `test_b5_services.py` (T2, T3): Verifies ground-truth decision freshness and `simulate_pr` / `reset_demo` state restoration.
- `test_t4_mcp.py`: Verifies all 11 MCP tools return `ToolResult` with valid evidence and fail-safe error handling.
- `test_t5_degradation.py`: **Proves the application strictly requires FalkorDB** — when FalkorDB is unreachable, `/api/health` reports `degraded`, and routes return `503 GRAPH_UNAVAILABLE`.
- `test_t6_agent.py`: Verifies citation filtering, date enrichment, and connection path highlighting.
- `test_t7_contract.py`: Verifies all API endpoints adhere to OpenAPI contracts and child MCP auto-restart.
- `test_t8_cypher_isolation.py`: Enforces Anti-clash Rule 2 — no Cypher strings in `mcp_server/` or `brain_api/`.

---

## 🎬 Demo Walkthrough Script

Use this sequence to explore or record the demo:

1. **"Which decisions need review?"**  
   - Agent invokes `list_stale_decisions`.  
   - Returns all stale decisions ordered by drift count with citations `[[dec_004]]`.  
   - Click a citation chip to open node properties.

2. **"Why did we decide Implement structured request lifecycle telemetry in tests?"**  
   - Agent invokes `search_knowledge` and `trace_decision`.  
   - Returns the exact rationale and decision context.  
   - Provenance path is highlighted in the interactive Cytoscape graph.

3. **"Is that decision still valid?"**  
   - Agent invokes `check_decision_freshness`.  
   - Confirms the decision is stale (81 subsequent drifting changes).

4. **"Simulate PR Change" (Demo Controls)**  
   - In the top bar, click **Simulate PR**.  
   - Target module `m_tests_benchmarks` and click **Simulate Merge**.  
   - A toast notification announces: `dec_006: fresh ➔ stale`.

5. **"Flag it for review"**  
   - Click **Flag** on the decision card or type *"Flag dec_006 for review"*.  
   - Creates a `ReviewRequest` assigned to the decider. Switch to the **Reviews** tab to see it.

6. **"FalkorDB Offline Proof" (Test T5)**  
   - Stop FalkorDB (`docker compose stop falkordb`).  
   - Reload page or hit `/api/chat`: persistent banner displays `FalkorDB Graph Engine is unavailable (503 GRAPH_UNAVAILABLE)`.

---

## 🔒 Data Policy Statement

- **Public Repository Source**: All code, commit history, and PR data is drawn from the public open-source repository `fastapi/fastapi`.
- **Pseudonymization (Rule D5)**: No real names, emails, avatars, or raw GitHub usernames are stored in disk caches or in the graph database. Contributor identities are deterministically salted and hashed into `p_<sha256>[:8]` and displayed as `Contributor <hash>`.
- **Synthetic Organizational Data**: All Slack channels, discussion threads, Jira-style issue tickets, and team structures are deterministically generated synthetic artifacts created specifically for this benchmark.

---

## 🤖 AI Disclosure & Engineering Accountability

This project was built pair-programming with the **Antigravity** advanced agentic coding assistant. All architectural decisions (D1–D11), schema definitions, graph queries, MCP tool contracts, agent loops, and frontend components were reviewed, verified, tested, and can be explained in complete detail by the author.

---

## 📄 Documentation Links

- [`ARCHITECTURE.md`](ARCHITECTURE.md): Complete architecture specification and source of truth.
- [`docs/decisions.md`](docs/decisions.md): Comprehensive architectural decision log (D1–D11, weights, pinned versions).
- [`docs/queries.md`](docs/queries.md): Auto-generated documentation of all 27 Cypher queries and PageRank implementation.
