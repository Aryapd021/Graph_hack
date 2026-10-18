# Company Brain: Architecture Specification

**Hackathon:** Graph Hacks (WeMakeDevs x FalkorDB) | **Track:** Track 03, Company Brain | **Team:** solo
**Status of this file:** single source of truth. Code must conform to it. If code and this file disagree, fix the code or update this file in the same commit. Never let them drift.

---

## 0. Inputs (all provided; values live in your local `.env` and the host dashboard, never in this file)

| # | Input | Where it goes | Why it is not assumed |
|---|---|---|---|
| I1 | Public GitHub repo `owner/name` to ingest | `.env` -> `GITHUB_REPO` | Architecture is repo-agnostic. Pick one with >=100 merged PRs, source code in top-level directories, and >=10 Markdown docs. Public data only. |
| I2 | Gemini generation model id | `.env` -> `GEMINI_MODEL` | No default on purpose. App refuses to start if unset. |
| I3 | Gemini embedding model id + dimension | `.env` -> `GEMINI_EMBED_MODEL`, `EMBED_DIM` | Dimension must match the FalkorDB vector index. Guarded by the `Meta` node (section 6.5). |
| I4 | Live host provider (any host that runs a Docker image, injects env vars, and allows outbound TLS) | host dashboard, section 18b | Free-tier terms change, so the choice is yours |
| I5 | FalkorDB Cloud instance: host, port, username, password | `.env` -> `FALKORDB_*` (never committed) | Live demo only |

**Provided:** I1 `fastapi/fastapi`; I2 `gemini-3.8-flash` (listed in Google's Gemini API model docs, GA, function calling supported, thinking levels low/medium/high only); I3 `gemini-embedding-001` with `EMBED_DIM=3072`; I4 Railway; I5 FalkorDB Cloud. Never write credentials into this repo.

## 1. Purpose and scope

An agent that understands how a software company works. It answers "who owns / who knows / why did we decide / is that decision still valid" from one FalkorDB graph that unifies code activity (real GitHub data) with docs, tickets, chats and decisions (synthetic, linked to the real data).

**Differentiator:** decision provenance with automatic staleness detection, computed in Cypher, plus an action (`flag_for_review`) that writes back to the graph.

**In scope:** ingestion, graph, MCP tool server, agent loop, REST API, web UI, deployment, docs.
**Out of scope (do not build):** GitHub Issues, PR reviews, real Slack/Jira, auth, multi-tenancy, streaming responses, LLM-based decision extraction, write-back to external systems.

## 2. Fixed decisions

| ID | Decision | Rationale |
|---|---|---|
| D1 | One graph, named by `FALKORDB_GRAPH` (default `company_brain`) | Single source of truth |
| D2 | FalkorDB via Docker; Python sync client (`falkordb` package) | Mandatory DB; simple, thread-safe pool |
| D3 | Every node has `id` (globally unique string), `display` (string), `source` (`github`\|`synthetic`\|`agent`) | One key for API, UI, MCP, citations |
| D4 | All timestamps are integer epoch seconds (UTC) in graph, API, and MCP | No timezone/format clashes. Frontend formats |
| D5 | **Pseudonymization:** GitHub logins become `person_id = "p_" + sha256(PSEUDONYM_SALT + login)[:8]`, `display = "Contributor " + that 8-hex`. Emails, real names, and avatars are never stored | Hackathon rule: no personal data. Also makes identity resolution deterministic |
| D6 | Cypher lives only in `brain_core/queries.py` as named constants `Q01..Qnn`. MCP server and REST both import them | No duplicate/drifting queries. `docs/queries.md` is generated from this file |
| D7 | Backend Pydantic models are the only API schema. Frontend TypeScript types are generated from OpenAPI | Zero frontend/backend contract drift |
| D8 | Agent reaches the graph only through the MCP server (stdio). REST read endpoints use `brain_core` services directly | Satisfies "tool selection through MCP"; UI endpoints stay fast |
| D9 | Freshness is derived at query time, never stored as a flag | No sync bugs |
| D10 | Frontend calls relative `/api/...` only. Vite dev proxy and nginx proxy both forward `/api` to the backend | No CORS, no hardcoded hosts |
| D11 | Frontend language is TypeScript | Needed for generated types |
| D12 | Live demo = one Docker image: FastAPI serves `/api` and the built SPA from the same origin, against FalkorDB Cloud | Keeps D10 true in production; one service to host |
| D13 | Public-exposure controls: `DEMO_MODE`, `ENABLE_INGEST_REFRESH`, per-IP chat rate limit | A public URL must not expose token-spending or destructive routes unguarded |
| D14 | Synthetic text is deterministic templates; Gemini paraphrase is an optional upgrade (`synth --llm`) that never changes ids, structure or ground truth | Reliability first, polish if time allows |

## 3. System diagram

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

## 4. Repository layout

```
company-brain/
  README.md                     # track declaration, setup, data model, AI disclosure
  ARCHITECTURE.md               # this file
  docker-compose.yml
  .env.example
  deploy/
    Dockerfile.prod             # single image for the live host (section 18b)
  docs/
    queries.md                  # GENERATED by scripts/gen_queries_doc.py. Do not hand-edit
    decisions.md                # technical decision log (hackathon rule: explain decisions)
  data/
    cache/github/               # raw GitHub JSON snapshot (committed, public data only)
    synthetic/                  # generated JSON (committed) + ground_truth.json
  scripts/
    smoke_falkordb.py           # verification gates (section 17)
    gen_queries_doc.py
    mcp_probe.py                # standalone MCP client: lists tools, calls each once (B6)
    test.sh                     # runs pytest against LOCAL Docker FalkorDB, graph company_brain_test (section 17)
  backend/
    pyproject.toml              # one project, four packages below, installed editable
    Dockerfile
    brain_core/                 # shared by ingest, mcp_server, brain_api
      config.py                 # env parsing (pydantic-settings), fail-fast
      db.py                     # FalkorDB client + graph handle
      schema.py                 # DDL (indexes), Meta node check; exposes apply()
      queries.py                # Q01..Qnn constants (the ONLY Cypher outside ingest loaders)
      models.py                 # Pydantic models (section 13) + enums NodeLabel, EdgeType
      services.py               # functions wrapping queries -> typed results
      freshness.py              # the single freshness function (section 10)
      scoring.py                # who_knows weights
      graph_payload.py          # rows -> GraphPayload (nodes/edges), prop allow-lists
    ingest/
      cli.py                    # python -m ingest {fetch|load|synth|derive|embed|verify|all}
      github_loader.py
      pseudonymize.py
      scrub.py                  # email / @mention removal
      synthetic_gen.py
      loaders.py                # MERGE writers
      derive.py                 # MENTIONS, COLLABORATES_WITH
      embed.py
    mcp_server/
      server.py                 # FastMCP server, 11 tools
    brain_api/
      main.py                   # FastAPI app + lifespan
      routes/                   # chat.py graph.py decisions.py demo.py health.py
      agent/
        loop.py                 # Gemini function-calling loop
        mcp_client.py           # stdio client + schema conversion
        prompts.py
    tests/
  web/
    package.json
    vite.config.ts              # dev proxy /api -> http://localhost:8000
    nginx.conf
    Dockerfile
    src/
      api/schema.d.ts           # GENERATED from /openapi.json (npm run gen:types)
      api/client.ts             # typed fetch wrappers
      store/brainStore.ts       # zustand
      graph/style.ts            # label -> color/shape map
      components/               # ChatPanel TracePanel GraphView DecisionsBoard ReviewsPanel NodeDrawer DemoControls HealthBadge
      App.tsx
```

## 5. Configuration (`.env`, one file for all services)

```
# FalkorDB
FALKORDB_HOST=falkordb          # use localhost when running outside compose
FALKORDB_PORT=6379
FALKORDB_USERNAME=               # empty for local Docker; set for FalkorDB Cloud (I5)
FALKORDB_PASSWORD=               # same
FALKORDB_SSL=false               # true if FalkorDB Cloud requires TLS (checked in gate G7)
FALKORDB_GRAPH=company_brain

# Gemini (I2, I3: no defaults, app fails fast if missing)
GEMINI_API_KEY=
GEMINI_MODEL=
GEMINI_EMBED_MODEL=
EMBED_DIM=
GEMINI_THINKING_LEVEL=low        # low | medium | high ("minimal" is rejected by gemini-3.8-flash)
LLM_TIMEOUT_S=45

# GitHub (I1)
GITHUB_REPO=owner/name
GITHUB_TOKEN=                   # optional but needed to avoid 60 req/hr limit; public scopes only
MAX_PRS=150
MAX_DOCS=40
MAX_DOC_CHARS=6000
MODULE_RULES='[{"prefix":"fastapi/","depth":1},{"prefix":"docs/en/docs/","depth":1},{"prefix":"tests/","depth":1}]'
                                # first matching prefix wins; files matching no prefix are dropped (section 7)
DOC_PATH_PREFIXES=docs/en/docs/ # comma-separated; repo-root README.md is always a candidate
DOC_EXCLUDE=people,sponsors,release-notes,external-links,newsletter,contributing
SKIP_BOT_PRS=true

# Synthetic data
PSEUDONYM_SALT=change-me
SYNTH_SEED=42
SYNTH_TEAMS=4
SYNTH_DECISIONS=12
SYNTH_EXTRA_TICKETS=10
SYNTH_EXTRA_THREADS=12

# Behavior
STALE_PR_THRESHOLD=1
AGENT_MAX_STEPS=8
API_PORT=8000                   # the host's PORT variable overrides this when set
SERVE_STATIC=false              # true in the live image: FastAPI serves web/dist
DEMO_MODE=true                  # enables /api/demo/* routes
ENABLE_INGEST_REFRESH=true      # false on the live host
CHAT_RATE_LIMIT_PER_MIN=10      # per client IP, in-memory (needs the single worker)
```

The dotenv path comes from the `ENV_FILE` environment variable (default `.env`). Keep a second gitignored file `.env.cloud` for FalkorDB Cloud values and select it with `ENV_FILE=.env.cloud`.

Quote any value containing `#`, `@` or spaces, e.g. `FALKORDB_PASSWORD='...'`. Never build `redis://user:pass@host` URLs: `db.py` passes host, port, username, password and ssl as separate arguments.

`config.py` validates: `EMBED_DIM` is a positive int; `GITHUB_REPO` matches `^[\w.-]+/[\w.-]+$`; required vars non-empty; the boolean vars (`FALKORDB_SSL`, `SERVE_STATIC`, `DEMO_MODE`, `ENABLE_INGEST_REFRESH`) accept only `true`/`false`; `CHAT_RATE_LIMIT_PER_MIN` is a positive int; `GEMINI_THINKING_LEVEL` is one of low, medium, high; `MODULE_RULES` parses as a JSON list of `{prefix: str ending in "/", depth: int >= 0}`; ingest-only variables (`GITHUB_TOKEN`, `PSEUDONYM_SALT`, `MAX_*`, `MODULE_RULES`, `DOC_*`, `SKIP_BOT_PRS`, `SYNTH_*`) are required only when the ingest CLI runs, or when `ENABLE_INGEST_REFRESH=true`, so the live host does not need them. `GITHUB_REPO` is always required (the `Meta` guard compares it).

## 6. Graph model

### 6.1 Node labels and properties

Common to **every** node: `id: str`, `display: str`, `source: str`, optional `url: str`.

| Label | `id` format | Extra properties | Created by |
|---|---|---|---|
| `Person` | `p_<8hex>` | `role` | github (identity) + synthetic (role) |
| `Team` | `t_<slug>` | none | synthetic |
| `Module` | `m_<path-slug>` | `path` | derived from file paths |
| `File` | `f_<sha1(path)[:10]>` | `path` | github (files touched by ingested PRs only) |
| `PR` | `pr_<number>` | `number:int`, `state`, `merged_at:int\|null`, `created_at:int`, `body_excerpt` (<=500 chars, scrubbed) | github |
| `Doc` | `d_<sha1(path)[:10]>` | `path`, `kind` (`readme`\|`design`\|`adr`\|`guide`), `updated_at:int`, `body` (<=MAX_DOC_CHARS, scrubbed), `text_hash`, `embedding` | github |
| `Decision` | `dec_<3 digits>` | `summary`, `rationale`, `decided_at:int`, `status` (`active`\|`superseded`), `text_hash`, `embedding` | synthetic |
| `Ticket` | `tk_<key>` | `key` (e.g. `BRAIN-12`), `status`, `created_at:int`, `resolved_at:int\|null`, `description` | synthetic |
| `Thread` | `th_<3 digits>` | `channel`, `started_at:int`, `text`, `text_hash`, `embedding` | synthetic |
| `ReviewRequest` | `rr_<uuid8>` | `note`, `status` (`open`\|`closed`), `created_at:int` | agent / API |
| `Meta` | `meta` | `embed_dim:int`, `embed_model`, `schema_version:int`, `repo` | schema step |

Demo-only nodes (simulated PRs and their File) additionally carry `synthetic_demo: true`.

**Never returned to clients:** `embedding`, `text_hash`, `body`, `text`. `graph_payload.py` holds a per-label allow-list of public props.

### 6.2 Relationship types

| Type | From -> To | Props | Created by |
|---|---|---|---|
| `MEMBER_OF` | Person -> Team | | synthetic |
| `OWNS` | Team -> Module | | synthetic (formal ownership) |
| `AUTHORED` | Person -> PR | | github |
| `TOUCHES` | PR -> File | | github |
| `PART_OF` | File -> Module | | derived from path |
| `PARTICIPATED_IN` | Person -> Thread | | synthetic |
| `ASSIGNED_TO` | Ticket \| ReviewRequest -> Person | | synthetic / agent |
| `RESOLVES` | PR -> Ticket | | synthetic |
| `DECIDED_BY` | Decision -> Person | | synthetic |
| `AFFECTS` | Decision -> Module | | synthetic |
| `IMPLEMENTS` | PR -> Decision | | synthetic (links real PR) |
| `DOCUMENTED_IN` | Decision -> Doc | | derived |
| `DISCUSSED_IN` | Decision -> Thread | | synthetic |
| `TRACKED_BY` | Decision -> Ticket | | synthetic |
| `SUPERSEDED_BY` | Decision -> Decision | | synthetic |
| `MENTIONS` | Doc \| Thread -> Module | | derived |
| `COLLABORATES_WITH` | Person -> Person | `weight:int` (shared modules), both directions | derived |
| `REVIEWS` | ReviewRequest -> Decision | | agent / API |

### 6.3 Identity of edges in the API
`GraphEdge.id = f"{source}|{TYPE}|{target}"`. Never expose FalkorDB internal ids.

### 6.4 Indexes (created by `schema.py`, idempotent)
Range indexes on `id` for every label above, plus `PR(merged_at)`, `Decision(decided_at)`, `Module(path)`.
Vector indexes on `embedding` for `Doc`, `Decision`, `Thread`: dimension = `EMBED_DIM`, similarity = cosine.
Exact DDL syntax depends on the pinned FalkorDB image: see verification gate G1.

### 6.5 `Meta` guard
At the end of `schema.py`, upsert `Meta {embed_dim, embed_model, schema_version=1, repo}`. On API and MCP startup, if env `EMBED_DIM`, `GEMINI_EMBED_MODEL` or `GITHUB_REPO` differ from `Meta`, refuse to start with a message naming the mismatch and the fix (`python -m ingest all --reset`).

## 7. Ingestion pipeline (`python -m ingest <step>`)

All steps are idempotent (`MERGE` on `id`). `all` runs them in order. `--reset` drops only the graph named `FALKORDB_GRAPH`, and when the host is not `localhost` it also requires `--yes`.

| Step | Does | Output |
|---|---|---|
| `fetch` | Calls GitHub REST, keeps only the fields the loader needs (no avatar URLs, profile URLs, emails or names), pseudonymizes authors, scrubs text, writes the result to `data/cache/github/` | cache files. Re-runs read cache; `--refresh` refetches |
| `load` | Schema, then Person, Module, File, PR, Doc nodes and AUTHORED, TOUCHES, PART_OF edges | graph |
| `synth` | Generates `data/synthetic/*.json` from the loaded snapshot (section 8) | JSON files |
| `load --synthetic` | Loads Teams, Tickets, Threads, Decisions and their edges | graph |
| `derive` | `MENTIONS`, `DOCUMENTED_IN`, `COLLABORATES_WITH` (Q16) | graph |
| `embed` | Embeds `Doc`, `Decision`, `Thread` text with Gemini; skips nodes whose `text_hash` is unchanged | `embedding` props |
| `verify` | Prints node/edge counts, asserts minimums, compares freshness with `ground_truth.json`, runs the PII scan | exit code |

### GitHub endpoints (exact)
- PRs: `GET /repos/{o}/{r}/pulls?state=closed&sort=updated&direction=desc&per_page=100` (paginate; keep items where `merged_at` is non-null; stop at `MAX_PRS`)
- PR files: `GET /repos/{o}/{r}/pulls/{number}/files?per_page=100` (one call per PR; this is why a token is recommended)
- Doc tree: `GET /repos/{o}/{r}/git/trees/{default_branch}?recursive=1`
- Doc content: `GET /repos/{o}/{r}/contents/{path}`
- Doc last change: `GET /repos/{o}/{r}/commits?path={path}&per_page=1` -> `commit.committer.date` -> epoch
- Default branch: `GET /repos/{o}/{r}` -> `default_branch`

### Rules
- **PR filtering:** when `SKIP_BOT_PRS=true`, skip PRs whose author `user.type` is `Bot` or whose login ends with `[bot]`. After fetching a PR's files, drop files that match no `MODULE_RULES` prefix; skip the PR entirely if no files remain. `MAX_PRS` counts kept PRs only; stop paging when it is reached or results run out. (For `fastapi/fastapi` this removes translation PRs under `docs/<lang>/`, bot PRs, and non-code churn.)
- **Doc selection:** candidates are `*.md` files whose path starts with a `DOC_PATH_PREFIXES` entry, plus the repo-root `README.md`, minus any path containing a `DOC_EXCLUDE` entry (case-insensitive substring; for `fastapi/fastapi` this removes contributor, sponsor and release-note pages that list people). Sort candidates by path; if there are more than `MAX_DOCS`, take evenly spaced items (`candidates[::step]`, `step = ceil(n / MAX_DOCS)`) so every section is represented, and always keep `README.md`. `kind`: path contains `adr` -> `adr`; contains `design` or `architecture` -> `design`; basename `README.md` -> `readme`; else `guide`.
- **Module of a file:** find the first `MODULE_RULES` entry whose `prefix` the path starts with. Module path = that prefix plus the next `depth` directory segments of the path if the file lies that deep in directories, else the prefix itself (trailing `/` removed). Examples: `fastapi/dependencies/utils.py` -> `fastapi/dependencies`; `fastapi/routing.py` -> `fastapi`; `docs/en/docs/tutorial/body.md` -> `docs/en/docs/tutorial`; `tests/test_x.py` -> `tests`. `Module.id = "m_"` + path with `/` replaced by `_`. There is no `(root)` module.
- **Scrubbing (`scrub.py`),** applied to PR titles, PR bodies and doc bodies before storage: emails -> `[email]`; `@handle` -> `@contributor`; lines starting `Co-authored-by:` or `Signed-off-by:` are deleted; GitHub profile URLs (`github.com/<single segment>`) -> `[profile]`; any author login seen in this fetch run (whole word, case-insensitive) -> `contributor`.
- **PII scans:** `fetch` ends by scanning its scrubbed output against the in-memory author-login set and fails if any login remains (the set is never written to disk). `verify` rescans every stored text property (`PR.display`, `PR.body_excerpt`, `Doc.body`, `Thread.text`, `Ticket.description`, `Decision.summary`, `Decision.rationale`) for the pattern classes only (email, `@handle`, profile URL, `Co-authored-by:`/`Signed-off-by:` lines) and fails on any hit.
- **Person:** only PR `user.login` and `user.type` are read; the login is hashed per D5; raw logins are never written to disk or the graph. Cache files contain only pseudonymized ids and scrubbed text.
- **MENTIONS (Doc -> Module):** doc path starts with the module path, or the doc body contains the module path as a whole token, or contains the dotted form (module path with `/` replaced by `.`, e.g. `fastapi.dependencies`).
- **DOCUMENTED_IN (Decision -> Doc):** for each decision, among Docs that `MENTIONS` any module the decision `AFFECTS`, pick the one with the lowest `path` (deterministic). If none, no edge.
- **Incremental refresh** (`POST /api/ingest/refresh`): fetch PRs merged after `max(PR.merged_at)` among `source='github'` nodes, upsert, rerun `derive`. Synchronous. Returns counts.

## 8. Synthetic data specification (`synthetic_gen.py`)

Deterministic: `random.Random(SYNTH_SEED)`; all iteration over sorted ids. Reads the loaded snapshot (persons, modules, merged PRs with their modules). Output files in `data/synthetic/`: `teams.json`, `people_roles.json`, `decisions.json`, `tickets.json`, `threads.json`, `ground_truth.json`.

1. **Teams:** `SYNTH_TEAMS` teams from the fixed name list `["Platform","Core","Developer Experience","Reliability","Data"]` (first N). Persons sorted by id are assigned round-robin (`MEMBER_OF`). Modules sorted by path are assigned round-robin (`OWNS`). Roles come from a fixed list indexed by `int(person_hex,16) % len(list)`.
2. **Decisions (`SYNTH_DECISIONS`):** choose merged PRs at evenly spaced indexes of the time-sorted list, preferring PRs that touch a module under the first `MODULE_RULES` prefix (the code prefix), falling back to any kept PR. Template bank of >=15 titles/summaries/rationales parameterized by module name (examples: "Standardize error handling in {m}", "Move {m} configuration to environment variables", "Deprecate the legacy {m} interface"). Per decision:
   - `AFFECTS`: up to 2 modules touched by the chosen PR (most files first)
   - `IMPLEMENTS`: the chosen real PR
   - `decided_at` = that PR's `created_at` (decision precedes implementation)
   - `DECIDED_BY`: the PR author (a Person)
   - `status`: `active`, except as set in step 3
3. **Supersession:** find up to 2 pairs (earlier decision i, later decision j) sharing an affected module. Create `(i)-[:SUPERSEDED_BY]->(j)` and set `i.status = 'superseded'`. If fewer than 2 pairs exist, create fewer; `ground_truth.json` records what was actually made.
4. **Tickets:** one per decision (`BRAIN-<n>`, `TRACKED_BY`, `RESOLVES` from the implementing PR, `ASSIGNED_TO` the decider) plus `SYNTH_EXTRA_TICKETS` resolved by other real PRs.
5. **Threads:** one per decision (channel `#eng-decisions`, 3 to 5 template messages, participants = decider + 1 to 3 members of the owning team, `DISCUSSED_IN`, `MENTIONS` the affected modules) plus `SYNTH_EXTRA_THREADS` module chatter without decisions (retrieval noise).
6. **ground_truth.json:** per decision, the expected `freshness` and `drift_count` computed in pure Python from the snapshot (no Cypher). `verify` and tests compare it with the Cypher result (Q09). This is the correctness oracle.

7. **Optional text upgrade (`python -m ingest synth --llm`):** after the template pass, ask Gemini to paraphrase only free-text fields (decision `summary`/`rationale`, thread message text, ticket `description`), one record at a time, with the template text as input and an instruction to keep pseudonyms, module paths and facts unchanged. Results are cached in `data/synthetic/llm_cache.json` keyed by `record_id + sha256(template_text)`. Any failure, or any output that drops a module path or pseudonym, falls back to the template text. Ids, edges, timestamps and `ground_truth.json` are never touched. Do this only after the core build is complete.

All synthetic text uses only pseudonymous display names. No real names, emails, or handles.

## 9. Cypher registry (`brain_core/queries.py`)

Parameters use `$name`. Names below are the constants' ids. Syntax-sensitive items are marked (G#) and covered by section 17. In code, suffixed ids are uppercase (`Q11A`, `Q15B`, `Q22A`) and `cypher_ids` in `ToolResult` and `TraceStep` use the same form.

```cypher
// Q01 formal owners of a module
MATCH (t:Team)-[:OWNS]->(m:Module {id:$module_id})
OPTIONAL MATCH (p:Person)-[:MEMBER_OF]->(t)
RETURN t.id AS team_id, t.display AS team, collect(p.id) AS member_ids

// Q02 de facto contributors of a module
MATCH (p:Person)-[:AUTHORED]->(pr:PR)-[:TOUCHES]->(:File)-[:PART_OF]->(m:Module {id:$module_id})
RETURN p.id AS person_id, p.display AS person, count(DISTINCT pr) AS pr_count, max(pr.merged_at) AS last_active
ORDER BY pr_count DESC LIMIT $limit

// Q03 resolve module by name or path
MATCH (m:Module)
WHERE toLower(m.display) CONTAINS toLower($q) OR toLower(m.path) CONTAINS toLower($q)
RETURN m.id AS id, m.display AS display, m.path AS path LIMIT 5

// Q04 vector search, executed once per label in $label (Decision | Doc | Thread)   (G1, G2)
CALL db.idx.vector.queryNodes($label, 'embedding', $k, vecf32($vec)) YIELD node, score
RETURN node.id AS id, labels(node)[0] AS label, node.display AS display, node.url AS url, score

// Q05 decision with all neighbors
MATCH (d:Decision {id:$id})
OPTIONAL MATCH (d)-[:DECIDED_BY]->(p:Person)
OPTIONAL MATCH (d)-[:AFFECTS]->(m:Module)
OPTIONAL MATCH (d)-[:DOCUMENTED_IN]->(doc:Doc)
OPTIONAL MATCH (d)-[:DISCUSSED_IN]->(th:Thread)
OPTIONAL MATCH (d)-[:TRACKED_BY]->(tk:Ticket)
OPTIONAL MATCH (pr:PR)-[:IMPLEMENTS]->(d)
RETURN d, p, collect(DISTINCT m) AS modules, collect(DISTINCT doc) AS docs,
       collect(DISTINCT th) AS threads, collect(DISTINCT tk) AS tickets, collect(DISTINCT pr) AS prs

// Q06 decisions that supersede this one (forward chain)
MATCH path = (d:Decision {id:$id})-[:SUPERSEDED_BY*1..5]->(n:Decision) RETURN path

// Q07 decisions this one supersedes (backward chain)
MATCH path = (o:Decision)-[:SUPERSEDED_BY*1..5]->(d:Decision {id:$id}) RETURN path

// Q08 later PRs that touched what the decision affects (drift detail for one decision)
MATCH (d:Decision {id:$id})-[:AFFECTS]->(m:Module)
MATCH (pr:PR)-[:TOUCHES]->(:File)-[:PART_OF]->(m)
WHERE pr.merged_at IS NOT NULL AND pr.merged_at > d.decided_at AND NOT (pr)-[:IMPLEMENTS]->(d)   // (G3)
RETURN DISTINCT pr.id AS pr_id, pr.display AS title, pr.merged_at AS merged_at, m.id AS module_id
ORDER BY merged_at DESC LIMIT $limit

// Q09 drift counts for ALL decisions (freshness classification happens in freshness.py)
MATCH (d:Decision)
OPTIONAL MATCH (d)-[:AFFECTS]->(m:Module)<-[:PART_OF]-(:File)<-[:TOUCHES]-(pr:PR)
WHERE pr.merged_at > d.decided_at AND NOT (pr)-[:IMPLEMENTS]->(d)
WITH d, count(DISTINCT pr) AS drift_count, max(pr.merged_at) AS latest
OPTIONAL MATCH (d)-[:DECIDED_BY]->(p:Person)
OPTIONAL MATCH (d)-[:AFFECTS]->(m2:Module)
RETURN d.id AS id, d.display AS title, d.decided_at AS decided_at, d.status AS status,
       drift_count, latest, p.display AS decider, collect(DISTINCT m2.id) AS module_ids
ORDER BY drift_count DESC

// Q11a / Q11b / Q11c who_knows score components, over $module_ids
MATCH (p:Person)-[:AUTHORED]->(pr:PR)-[:TOUCHES]->(:File)-[:PART_OF]->(m:Module)
WHERE m.id IN $module_ids
RETURN p.id AS person_id, count(DISTINCT pr) AS prs;

MATCH (p:Person)-[:PARTICIPATED_IN]->(th:Thread)-[:MENTIONS]->(m:Module)
WHERE m.id IN $module_ids
RETURN p.id AS person_id, count(DISTINCT th) AS threads;

MATCH (d:Decision)-[:AFFECTS]->(m:Module), (d)-[:DECIDED_BY]->(p:Person)
WHERE m.id IN $module_ids
RETURN p.id AS person_id, count(DISTINCT d) AS decisions

// Q11d person details
MATCH (p:Person) WHERE p.id IN $ids RETURN p.id AS id, p.display AS display, p.role AS role

// Q12 recent changes in a module
MATCH (pr:PR)-[:TOUCHES]->(:File)-[:PART_OF]->(m:Module {id:$module_id})
WHERE pr.merged_at >= $since
RETURN DISTINCT pr.id AS id, pr.display AS title, pr.merged_at AS merged_at
ORDER BY merged_at DESC LIMIT $limit

// Q13 shortest connection between two nodes, any labels   (G4)
MATCH (a {id:$a}), (b {id:$b})
MATCH p = shortestPath((a)-[*..6]-(b))
RETURN p

// Q14 PageRank over the collaboration graph   (G5)
CALL algo.pageRank('Person', 'COLLABORATES_WITH') YIELD node, score
RETURN node.id AS id, node.display AS display, score
ORDER BY score DESC LIMIT $limit

// Q15a existing open review for a decision
MATCH (r:ReviewRequest {status:'open'})-[:REVIEWS]->(:Decision {id:$decision_id}) RETURN r.id AS id LIMIT 1

// Q15b create review request
MATCH (d:Decision {id:$decision_id})
CREATE (r:ReviewRequest {id:$rr_id, display:$display, note:$note, status:'open', created_at:$now, source:'agent'})
CREATE (r)-[:REVIEWS]->(d)
RETURN r.id AS id

// Q15c assign review to the decider
MATCH (r:ReviewRequest {id:$rr_id}), (:Decision {id:$decision_id})-[:DECIDED_BY]->(p:Person)
CREATE (r)-[:ASSIGNED_TO]->(p)
RETURN p.id AS person_id, p.display AS person

// Q16 derive collaboration edges (ingest-time)
MATCH (a:Person)-[:AUTHORED]->(:PR)-[:TOUCHES]->(:File)-[:PART_OF]->(m:Module)<-[:PART_OF]-(:File)<-[:TOUCHES]-(:PR)<-[:AUTHORED]-(b:Person)
WHERE a.id <> b.id
WITH a, b, count(DISTINCT m) AS shared
MERGE (a)-[c:COLLABORATES_WITH]->(b)
SET c.weight = shared

// Q17 overview graph (decisions and their neighbors)
MATCH (d:Decision)-[r]-(n) RETURN d, r, n LIMIT $limit

// Q18 one-hop neighborhood
MATCH (a {id:$id})-[r]-(n) RETURN a, r, n LIMIT $limit

// Q19 node detail
MATCH (n {id:$id})
OPTIONAL MATCH (n)-[r]-()
RETURN n, labels(n)[0] AS label, count(r) AS degree

// Q20 review requests
MATCH (r:ReviewRequest)-[:REVIEWS]->(d:Decision)
OPTIONAL MATCH (r)-[:ASSIGNED_TO]->(p:Person)
RETURN r, d.id AS decision_id, d.display AS decision, collect(p.id) AS assignee_ids
ORDER BY r.created_at DESC

// Q21 demo: simulate a merged PR touching a module
MATCH (m:Module {id:$module_id})
MERGE (f:File {id:$file_id})
  SET f.path = $path, f.display = $path, f.source = 'synthetic', f.synthetic_demo = true
MERGE (f)-[:PART_OF]->(m)
CREATE (pr:PR {id:$pr_id, number:$number, display:$title, state:'merged', merged_at:$now,
               created_at:$now, source:'synthetic', synthetic_demo:true})
CREATE (pr)-[:TOUCHES]->(f)
RETURN pr.id AS id

// Q22 demo reset
MATCH (n) WHERE n.synthetic_demo = true DETACH DELETE n;
MATCH (r:ReviewRequest) DETACH DELETE r

// Q23 modules referenced by search hits
MATCH (n)-[:MENTIONS|AFFECTS]->(m:Module) WHERE n.id IN $ids
RETURN DISTINCT m.id AS id, m.display AS display

// Q24 next demo PR number
MATCH (pr:PR {synthetic_demo:true}) RETURN coalesce(max(pr.number), 899999) AS n

// Q25 modules with owning team
MATCH (m:Module)
OPTIONAL MATCH (t:Team)-[:OWNS]->(m)
RETURN m.id AS id, m.display AS display, m.path AS path, t.display AS owner_team
ORDER BY m.path

// Q26 node counts per label
MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n

// Q27 relationship counts per type
MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n
```

Q10 intentionally unused (number reserved). Semicolons above only separate statements in documentation; the code runs each statement separately.

## 10. Shared services and the freshness rule

`freshness.py` exposes exactly one function:

```python
def classify(status: str, drift_count: int, threshold: int) -> Literal["fresh", "stale", "superseded"]:
    if status == "superseded": return "superseded"
    return "stale" if drift_count >= threshold else "fresh"
```

`threshold = STALE_PR_THRESHOLD`. Drift counts come from Q09 (list) or Q08 (detail). Every consumer (MCP tools, REST, tests, `verify`) calls this function. A decision is **stale** when at least `threshold` merged PRs, other than its own implementing PRs, touched files in modules it `AFFECTS` after `decided_at`.

`services.py` functions (all return Pydantic models): `resolve_module`, `get_decision`, `trace_decision`, `check_freshness`, `list_decisions`, `who_owns`, `who_knows`, `recent_changes`, `connection_path`, `key_connectors`, `flag_for_review`, `search_knowledge`, `graph_overview`, `neighborhood`, `node_detail`, `list_reviews`, `simulate_pr`, `reset_demo`. The MCP server and REST routes are thin wrappers over these.

**Tool graph rule:** for every tool-facing service, `ToolResult.graph` contains the nodes listed in `evidence` plus the edges implied by the relationships its queries traversed between those nodes. Tool-facing services return `ToolResult`; REST-only services return the DTOs in section 13. `/api/health` `counts` are the sums of Q26 and Q27.

`scoring.py`: `who_knows` score = `1 * prs + 2 * threads + 3 * decisions`; constants are module-level and documented in `docs/decisions.md`.

## 11. MCP server (`mcp_server/server.py`)

- Library: official `mcp` Python SDK, `FastMCP`. Transport: **stdio**. Server logs go to **stderr only**; stdout is protocol-only.
- Spawned by `brain_api` at startup: `python -m mcp_server`. One child process; run uvicorn with a single worker.
- Tool functions are plain `def` with simple type hints.
- **Schema constraint:** parameters are only `str`, `int`, `bool`, `Literal[...]`, or `list[Literal[...]]`, with defaults for optional parameters. **No `Optional`, `Union`, nested models, or `$ref`**, so JSON Schemas stay convertible to Gemini function declarations (gate G6).
- Return value: a JSON string of `ToolResult` (section 13) as a single text content block.
- Errors never raise to the client: return `ToolResult(ok=False, summary=<reason>, data={"candidates": [...]} when ambiguous)`.

### Tool contracts

| Tool | Parameters | `data` keys | Queries |
|---|---|---|---|
| `search_knowledge` | `query: str`, `kinds: list[Literal["Decision","Doc","Thread"]] = ["Decision","Doc","Thread"]`, `k: int = 5` (1 to 10) | `hits: [{id,label,display,url,distance}]` sorted by ascending distance (G2) | Q04 |
| `get_decision` | `decision_id: str` | `decision, decider, modules, docs, threads, tickets, prs` | Q05 |
| `trace_decision` | `decision_id: str` | `chain: [{relation, node: Evidence}]` ordered: `decided_by`, `implemented_by`, `tracked_by`, `discussed_in`, `documented_in`, `supersedes`, `superseded_by`; plus `freshness` | Q05, Q06, Q07, Q08 |
| `check_decision_freshness` | `decision_id: str` | `freshness, drift_count, threshold, later_prs: [{pr_id,title,merged_at,module_id}], superseded_by: str\|null` | Q05, Q08 |
| `list_stale_decisions` | `limit: int = 10` | `decisions: [DecisionSummary]` (stale only, by `drift_count` desc) | Q09 |
| `who_owns` | `module: str` (name or path) | `module, owner_teams: [{id,display,member_ids}], top_contributors: [{person_id,display,pr_count,last_active}], ownership_gap: bool` (true if the top contributor is not a member of an owning team) | Q03, Q01, Q02 |
| `who_knows` | `topic: str`, `limit: int = 5` | `modules, experts: [{person_id,display,role,score,breakdown:{prs,threads,decisions}}]` | Q03, Q04, Q23, Q11a-d |
| `recent_changes` | `module: str`, `since_days: int = 30` (1 to 365), `limit: int = 10` | `module, prs: [{id,title,merged_at}]` | Q03, Q12 |
| `connection_path` | `from_id: str`, `to_id: str` | `path: [{node: Evidence, edge_type: str\|null, direction: "out"\|"in"\|null}]` (first entry has null edge) | Q13 |
| `key_connectors` | `limit: int = 5` | `people: [{id,display,score}]` | Q14 |
| `flag_for_review` (**only write tool**) | `decision_id: str`, `note: str` (<=300 chars) | `review_request_id, assigned_to: [{id,display}], already_open: bool` | Q15a-c |

Name resolution: tools taking a module name call Q03. Zero matches -> `ok=False`. More than one match -> `ok=False` with `data.candidates`; the agent must retry with a specific candidate path.

## 12. Agent (`brain_api/agent/`)

**Model:** `GEMINI_MODEL` via the `google-genai` SDK. Automatic function calling is **disabled**; the loop is manual so every call is traced.

**Startup:** open stdio MCP session, `list_tools()`, convert each tool's `inputSchema` into a Gemini `FunctionDeclaration` (`mcp_client.py`, gate G6).

**Loop (per `/api/chat` request):**
1. Build contents: system prompt + `history` + user `message`.
2. Call Gemini with tool declarations. If the response has function calls, execute each via `session.call_tool(name, args)`, parse `ToolResult`, record a `TraceStep`, accumulate `graph` and `evidence`, then send results back to Gemini as function responses containing **only `{summary, data, evidence}`** (the `graph` stays server-side). Before sending, add a `<key>_utc_date` sibling (`YYYY-MM-DD`) for every integer field in `data` whose key ends in `_at` or equals `last_active`, because models convert epoch seconds unreliably; the stored trace and API responses keep epoch seconds only.
3. Repeat until Gemini returns text or `AGENT_MAX_STEPS` is reached. On the step cap, force a final answer from what was gathered with tools disabled.
4. **Citation validation:** the answer must cite sources as `[[node_id]]`. The server keeps only markers whose `node_id` appears in the evidence collected this turn, removes unknown markers, and builds `citations` from the valid ones. Hallucinated ids cannot reach the UI.
5. `highlight.node_ids` = cited ids plus nodes on any returned path; `highlight.edge_ids` = edges of returned paths.

**System prompt rules (`prompts.py`):**
- Answer only from tool results. If tools return nothing relevant, say so.
- Every factual sentence ends with one or more `[[node_id]]` markers.
- Use `flag_for_review` only when the user explicitly asks to flag, escalate, or request review.
- Prefer `check_decision_freshness` before calling a decision "still valid".
- Never reveal ids that were not returned by a tool.

**Question to tool plan** (for tests and demo script):

| Question | Expected tools |
|---|---|
| Who owns X? | `who_owns` |
| Who knows about X? | `who_knows` |
| Why did we decide X? | `search_knowledge` -> `trace_decision` |
| Is that still valid? | `check_decision_freshness` |
| Which decisions need review? | `list_stale_decisions` |
| Flag it / request review | `flag_for_review` |
| How are A and B connected? | `search_knowledge` -> `connection_path` |
| Who are the key connectors? | `key_connectors` |
| What changed in X lately? | `recent_changes` |

## 13. Shared types (Pydantic, `brain_core/models.py`: the schema source of truth)

```python
NodeLabel = Literal["Person","Team","Module","File","PR","Doc","Decision","Ticket","Thread","ReviewRequest"]
EdgeType  = Literal["MEMBER_OF","OWNS","AUTHORED","TOUCHES","PART_OF","PARTICIPATED_IN","ASSIGNED_TO","RESOLVES",
                    "DECIDED_BY","AFFECTS","IMPLEMENTS","DOCUMENTED_IN","DISCUSSED_IN","TRACKED_BY",
                    "SUPERSEDED_BY","MENTIONS","COLLABORATES_WITH","REVIEWS"]
Freshness = Literal["fresh","stale","superseded"]
ErrorCode = Literal["BAD_REQUEST","NOT_FOUND","RATE_LIMITED","GRAPH_UNAVAILABLE","LLM_ERROR","INTERNAL"]

class GraphNode(BaseModel):  id: str; label: NodeLabel; display: str; props: dict[str, str|int|float|bool|None]
class GraphEdge(BaseModel):  id: str; source: str; target: str; type: EdgeType
class GraphPayload(BaseModel): nodes: list[GraphNode]; edges: list[GraphEdge]
class Evidence(BaseModel):   node_id: str; label: NodeLabel; display: str; url: str | None
class Highlight(BaseModel):  node_ids: list[str]; edge_ids: list[str]

class ToolResult(BaseModel):
    ok: bool; summary: str                    # summary <= 300 chars
    data: dict; evidence: list[Evidence]; graph: GraphPayload; cypher_ids: list[str]

class TraceStep(BaseModel):
    step: int; tool: str; args: dict; ok: bool; summary: str; cypher_ids: list[str]; duration_ms: int

class ChatTurn(BaseModel):   role: Literal["user","assistant"]; content: str
class ChatRequest(BaseModel): message: str   # 1..2000 chars
                              history: list[ChatTurn]   # max 10
class ChatResponse(BaseModel):
    answer: str                               # markdown; contains [[node_id]] markers that all appear in citations
    citations: list[Evidence]; trace: list[TraceStep]; graph: GraphPayload; highlight: Highlight

class DecisionSummary(BaseModel):
    id: str; title: str; decided_at: int; status: Literal["active","superseded"]
    freshness: Freshness; drift_count: int; latest_drift_at: int | None
    module_ids: list[str]; decider: str | None

class ModuleSummary(BaseModel): id: str; display: str; path: str; owner_team: str | None
class NodeDetail(BaseModel):    id: str; label: NodeLabel; display: str; props: dict; degree: int; url: str | None
class ReviewRequestOut(BaseModel):
    id: str; decision_id: str; decision: str; note: str; status: Literal["open","closed"]
    created_at: int; assignee_ids: list[str]
class ErrorBody(BaseModel):  code: ErrorCode; message: str
class ErrorResponse(BaseModel): error: ErrorBody
```

## 14. REST API (FastAPI, prefix `/api`)

Read routes are `def` (sync, threadpool). `/api/chat` is `async def`. Every non-2xx body is `ErrorResponse`. Status mapping: `BAD_REQUEST` 400, `NOT_FOUND` 404, `RATE_LIMITED` 429, `GRAPH_UNAVAILABLE` 503, `LLM_ERROR` 502, `INTERNAL` 500.

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/api/health` | | `{status:"ok"\|"degraded", falkordb:bool, mcp:bool, counts:{nodes:int, edges:int}, demo_mode:bool, ingest_refresh:bool}` |
| POST | `/api/chat` | `ChatRequest` | `ChatResponse` |
| GET | `/api/modules` | | `list[ModuleSummary]` |
| GET | `/api/graph/overview?limit=150` | limit 1..500 | `GraphPayload` |
| GET | `/api/graph/neighborhood/{node_id}?limit=60` | | `GraphPayload` (one hop, Q18) |
| GET | `/api/node/{node_id}` | | `NodeDetail` |
| GET | `/api/decisions` | | `list[DecisionSummary]` (all, by `drift_count` desc) |
| GET | `/api/decisions/{id}/trace` | | `ToolResult` (same service as `trace_decision`) |
| POST | `/api/decisions/{id}/flag` | `{note:str}` | `{review_request_id:str, assigned_to:list[{id,display}], already_open:bool}` |
| GET | `/api/reviews` | | `list[ReviewRequestOut]` |
| POST | `/api/demo/simulate-pr` | `{module_id:str, title:str}` | `{pr_id:str, changed:list[{decision_id:str, before:Freshness, after:Freshness}]}` |
| POST | `/api/demo/reset` | | `{removed_nodes:int}` (removes demo PRs/Files and all ReviewRequests) |
| POST | `/api/ingest/refresh` | | `{new_prs:int, new_files:int}` |

`simulate-pr`: computes freshness for all decisions, runs Q24 to get the next number (current maximum demo PR number + 1, which starts at 900000), then Q21 (`number` from Q24, `pr_id = pr_<number>`, file path `{module_path}/__demo__{number}.txt`), recomputes, and returns only decisions whose freshness changed.

Exposure controls: `/api/demo/*` routes exist only when `DEMO_MODE=true`; `/api/ingest/refresh` only when `ENABLE_INGEST_REFRESH=true`. When disabled they return 404 `NOT_FOUND`, and the frontend hides their controls using the `demo_mode` and `ingest_refresh` flags from `/api/health`. `/api/chat` allows `CHAT_RATE_LIMIT_PER_MIN` requests per client IP (first hop of `X-Forwarded-For` when present, else the socket address), sliding window, in memory; excess requests get 429 `RATE_LIMITED`.

Degradation: if FalkorDB is unreachable, `/api/health` returns `status:"degraded", falkordb:false`, and every other route returns 503 `GRAPH_UNAVAILABLE`. This is the "product breaks without FalkorDB" proof (test T5).

## 15. Frontend (`web/`)

**Stack:** React 18, TypeScript, Vite, Tailwind CSS, TanStack Query, zustand, `cytoscape` + `react-cytoscapejs`, `react-markdown`, `openapi-typescript` (dev).

**Types:** `npm run gen:types` runs `openapi-typescript http://localhost:8000/openapi.json -o src/api/schema.d.ts`. All API calls in `api/client.ts` use those generated types. Never hand-write an API type.

**Layout:** top bar (HealthBadge, DemoControls), then three columns: Chat (left), GraphView (center), tabs Trace | Decisions | Reviews | Node (right).

**State (`brainStore`):** `graph: GraphPayload`, `highlight: Highlight`, `selectedNodeId: string|null`, `rightTab`. Graph merge rule: union nodes by `id`, edges by `id`.

**Flows**
- App load: `GET /api/health`, `GET /api/graph/overview`, `GET /api/decisions`, `GET /api/modules`.
- Send message: `POST /api/chat` -> append message with `citations`; merge `graph`; set `highlight`; switch to Trace tab. `[[node_id]]` markers render as clickable chips using `citations` for labels; clicking selects the node.
- Select node (graph click or chip): `GET /api/node/{id}`, Node tab; "Expand" button calls `GET /api/graph/neighborhood/{id}` and merges.
- Decisions tab: list with freshness badge (fresh = green, stale = amber, superseded = gray), drift count, "Trace" (calls `/api/decisions/{id}/trace`, highlights the chain) and "Flag for review" (`POST /api/decisions/{id}/flag`, then refetch `/api/reviews`).
- DemoControls: "Simulate change" (module select from `/api/modules` + title -> `POST /api/demo/simulate-pr`, then invalidate decisions and show the `changed` list as a toast), "Reset" (`/api/demo/reset`, invalidate all), "Refresh data" (`/api/ingest/refresh`).
- Errors: render `error.message`; 503 `GRAPH_UNAVAILABLE` shows a persistent banner; 429 `RATE_LIMITED` shows a transient "slow down" notice in the chat. DemoControls renders only the controls enabled by the two `/api/health` flags.

**Graph styling (`graph/style.ts`):** one color + shape per `NodeLabel`; highlighted nodes/edges get a `.hl` class (thick border, full opacity); everything else dims to 30% when a highlight exists. Layout: `cose` for overview, `breadthfirst` for traces.

## 16. Anti-clash rules (enforced, not advisory)

1. API shapes: Pydantic -> OpenAPI -> generated `schema.d.ts`. CI step fails if `schema.d.ts` differs from a fresh generation.
2. Cypher: only `queries.py`. A grep test fails if `MATCH`, `MERGE`, or `CALL` string literals appear in `mcp_server/` or `brain_api/` (ingest loaders are the only other allowed place).
3. Ids: all nodes expose `id`; edges expose `source|TYPE|target`. UI never uses internal DB ids.
4. Labels and edge types: `NodeLabel` and `EdgeType` Literals are the only enumerations; `graph_payload.py` rejects unknown values; `style.ts` is typed `Record<NodeLabel, ...>` so a new label breaks the TypeScript build.
5. Time: epoch seconds everywhere; only the frontend formats.
6. Config: one `.env`; `config.py` is the only reader of `os.environ`.
7. Network: frontend uses `/api` only (D10).
8. Freshness: one function (section 10).
9. Evidence integrity: citations validated against this turn's tool evidence.
10. Embedding config guarded by `Meta`.

## 17. Verification gates and tests

**Gates** (run `python scripts/smoke_falkordb.py` right after `docker compose up -d falkordb`; each prints PASS/FAIL with the exact error; the build does not proceed on FAIL):

| Gate | Checks | If it fails |
|---|---|---|
| G1 | DDL: range index and vector index with `dimension=EMBED_DIM`, cosine | Adjust syntax in `schema.py` to the pinned image's docs |
| G2 | `db.idx.vector.queryNodes` returns scores; determine whether lower = closer, set sort direction accordingly | Fix ordering in `search_knowledge` |
| G3 | Pattern predicate `NOT (pr)-[:IMPLEMENTS]->(d)` inside `WHERE` | Rewrite with `OPTIONAL MATCH ... WHERE x IS NULL` |
| G4 | `shortestPath((a)-[*..6]-(b))` with both ends bound | Fall back to `algo.SPpaths` or bounded `MATCH` |
| G5 | `algo.pageRank('Person','COLLABORATES_WITH')` yields `node, score` | Check procedure name/signature in the pinned version's docs |
| G6 | All 11 MCP tool JSON Schemas convert to accepted Gemini `FunctionDeclaration`s with the pinned `google-genai` version | Simplify the offending schema (e.g., drop defaults) |
| G7 | Re-run G1 to G5 against FalkorDB Cloud with `FALKORDB_USERNAME/PASSWORD/SSL` set, from a machine on the same kind of network as the live host | Adjust connection args in `db.py`; if Cloud's server version differs from the Docker tag, pin the tag to match or make the syntax work on both |
| G8 | One `generate_content` call to `GEMINI_MODEL` with a function declaration and `GEMINI_THINKING_LEVEL` returns a function call; one embedding call with `EMBED_DIM` returns a vector of exactly that length | Fix the model id, the thinking-level parameter name, or `output_dimensionality` handling |

`smoke_falkordb.py` uses a scratch graph named `smoke_scratch` and deletes it on exit; it never touches `FALKORDB_GRAPH`.

Pin the FalkorDB image tag and the `google-genai` and `mcp` package versions at project start and record them in `docs/decisions.md`.

**Test safety (mandatory):** tests write fixtures and call reset. `scripts/test.sh` sets `FALKORDB_HOST=localhost`, `FALKORDB_PORT=6379`, empty username and password, `FALKORDB_SSL=false`, `FALKORDB_GRAPH=company_brain_test`, then runs pytest. `tests/conftest.py` aborts the whole session if the graph name does not end in `_test` or the host is not `localhost`, `127.0.0.1` or `falkordb`. Never run tests with FalkorDB Cloud credentials in the environment.

**Tests** (`backend/tests/`, pytest, need FalkorDB running):

| ID | Test |
|---|---|
| T1 | Ingest a tiny fixture snapshot; node and edge counts match expectations |
| T2 | Q09 freshness for every decision equals `ground_truth.json` |
| T3 | `simulate_pr` flips exactly the decisions whose modules match; `reset_demo` restores T2 |
| T4 | Each MCP tool: valid call returns `ok=True` with non-empty evidence; unknown id returns `ok=False`; response validates as `ToolResult` |
| T5 | With FalkorDB stopped: `/api/health` degraded, `/api/chat` returns 503 `GRAPH_UNAVAILABLE` |
| T6 | Citation filter removes `[[unknown_id]]` and keeps valid ones |
| T7 | Contract: every route's response validates against its Pydantic model |
| T8 | Grep test for rule 2 in section 16 |

## 18. Deployment (`docker-compose.yml`)

```yaml
services:
  falkordb:
    image: falkordb/falkordb:<PINNED_TAG>      # pin at start (gate G1..G5)
    ports: ["6379:6379", "3000:3000"]
    volumes: ["falkordb_data:/var/lib/falkordb/data"]
    healthcheck: { test: ["CMD", "redis-cli", "ping"], interval: 5s, retries: 10 }
  api:
    build: ./backend
    env_file: .env
    environment: { FALKORDB_HOST: falkordb }
    depends_on: { falkordb: { condition: service_healthy } }
    ports: ["8000:8000"]
    command: uvicorn brain_api.main:app --host 0.0.0.0 --port 8000 --workers 1
  web:
    build: ./web                                # multi-stage: vite build -> nginx
    depends_on: [api]
    ports: ["8080:80"]
volumes: { falkordb_data: {} }
```

`nginx.conf`: `location /api/ { proxy_pass http://api:8000; proxy_read_timeout 90s; }` and SPA fallback `try_files $uri /index.html`.
The `redis-cli` healthcheck and the data path are checked in G1; adjust if the image differs.

**Local run**
```bash
cp .env.example .env            # fill I1, I2, I3, GEMINI_API_KEY
docker compose up -d falkordb
python scripts/smoke_falkordb.py
cd backend && pip install -e . && python -m ingest all
cd .. && docker compose up --build
# UI: http://localhost:8080   FalkorDB browser: http://localhost:3000
```

## 18b. Live deployment (FalkorDB Cloud + one Docker image)

**Topology:** Browser -> one public service (the `deploy/Dockerfile.prod` image: FastAPI serving `/api/*` and the built SPA) -> FalkorDB Cloud. The MCP server still runs as a stdio child of the API process inside the same container.

**Image (`deploy/Dockerfile.prod`, multi-stage):**
1. Node stage: `cd web && npm ci && npm run build` produces `web/dist`.
2. Python stage: install `backend`, copy `web/dist` to `/app/static`, set `SERVE_STATIC=true`.
3. Start: `uvicorn brain_api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1`.

**Static serving rule (`main.py`):** when `SERVE_STATIC=true`, mount `/app/static` at `/` after all `/api` routers. Any non-`/api` path that is not a file returns `index.html`. Unknown `/api/*` paths return 404 `NOT_FOUND` and never fall through to the SPA.

**Host requirements (I4):** runs a Docker image, injects env vars, health check path `/api/health`, outbound TLS to FalkorDB Cloud and the Gemini API, exactly one instance (the rate limiter and the MCP child are per process).

**Railway notes (I4):** Railway provides `PORT`; point the service at `deploy/Dockerfile.prod` (service settings, or the `RAILWAY_DOCKERFILE_PATH` variable; confirm in Railway's docs); health check path `/api/health`; one replica; set variables in the service Variables tab. Confirm gate G7 from Railway's network, not only from your laptop: if FalkorDB Cloud has an IP allowlist, Railway's outbound IPs must be permitted.

**Host environment variables:** everything in section 5 except local-only values, with `FALKORDB_HOST/PORT/USERNAME/PASSWORD/SSL` from I5, `SERVE_STATIC=true`, `DEMO_MODE=true`, `ENABLE_INGEST_REFRESH=false`, `CHAT_RATE_LIMIT_PER_MIN=10`. Secrets (`GEMINI_API_KEY`, FalkorDB password, `GITHUB_TOKEN`) live only in the host dashboard and your local `.env`; `.env` is in `.gitignore`.

**Loading data into Cloud (once, from your laptop):**
```bash
# .env points FALKORDB_* at FalkorDB Cloud
python scripts/smoke_falkordb.py                  # gate G7
cd backend && python -m ingest all --reset        # uses committed data/cache, no GitHub calls needed
```
The live container never ingests. Because `data/cache/` is committed, the load is reproducible without a GitHub token.

**Behaviors to plan for:**
- Free tiers may sleep, so the first request after idle can be slow. Hit `/api/health` a few minutes before judging or recording.
- Demo state is global: `simulate-pr` changes what every visitor sees until `reset`. Reset before submitting and before recording the video.
- Free-tier limits (FalkorDB Cloud, Gemini quota) can change. Check them at signup and keep `CHAT_RATE_LIMIT_PER_MIN` low.
- Post-deploy check: `curl https://<host>/api/health` shows `falkordb:true, mcp:true`, then run the demo flow from section 20 on the live URL.

## 19. Build order for Antigravity

Give Antigravity this file first with: *"ARCHITECTURE.md is the source of truth. Implement one task at a time in the order below. Do not deviate from names, paths, or shapes. If a verification gate fails, stop and report the exact error. Comment all code heavily (docstring on every function plus 'why' comments), because I must explain every file."*

| Task | Deliverable | Done when |
|---|---|---|
| B0 | Repo skeleton, `.gitignore`, `.env.example`, compose, `config.py`, `db.py`, `smoke_falkordb.py`, `test.sh` | Gates G1 to G5 and G8 pass against local Docker; G7 passes against FalkorDB Cloud (G6 is checked after B6) |
| B1 | `models.py`, `queries.py`, `schema.py`, `freshness.py`, `scoring.py`, `graph_payload.py` | Imports clean; `gen_queries_doc.py` writes `docs/queries.md` |
| B2 | `ingest fetch` + `load` (pseudonymize, scrub) | Real repo loaded; counts printed; no raw logins in cache |
| B3 | `synthetic_gen.py` + `load --synthetic` + `derive` | `verify` passes; `ground_truth.json` written |
| B4 | `ingest embed` | Vector search returns sane hits |
| B5 | `services.py` | T2 and T3 tests pass |
| B6 | `mcp_server/server.py` | Gate G6 and T4 pass via a standalone MCP client script |
| B7 | `brain_api` routes (no agent yet) | T7 contract tests pass; OpenAPI served |
| B8 | Agent loop + `/api/chat` | Each row of the question table in section 12 uses the expected tools; T6 passes |
| B9 | Frontend: `gen:types`, store, ChatPanel, GraphView, TracePanel | Chat answer renders with citations and highlighted graph |
| B10 | DecisionsBoard, ReviewsPanel, DemoControls, NodeDrawer | Simulate change flips a decision to stale in the UI; flag creates a review |
| B11 | README, `docs/decisions.md`, tests T5 and T8, demo script | Submission checklist complete except the live URL (added in B12) |
| B12 | Live deploy: `deploy/Dockerfile.prod`, static mount, rate limit + `RATE_LIMITED` handling, FalkorDB Cloud load, live URL added to README | Gate G7 passes; `/api/health` on the live URL shows `falkordb:true, mcp:true`; demo flow works end to end |
| B13 (optional) | `ingest synth --llm` text upgrade | `ground_truth.json` unchanged; test T2 still passes; fallback to templates verified by a forced failure |

Task ids are `B#`; test ids are `T#` (section 17). They are separate namespaces.

## 20. Submission checklist (maps to the hackathon rules)

- [ ] README states **Track 03: Company Brain** at the top
- [ ] FalkorDB is the primary store; test T5 proves the app breaks without it
- [ ] README has local setup steps (section 18) and a graph data model section (sections 6.1 and 6.2)
- [ ] `docs/queries.md` (generated) documents every Cypher query and the PageRank algorithm
- [ ] Docker Compose present; public repo; live URL in README (section 18b); secrets only in host env and local `.env`
- [ ] Data policy statement in README: GitHub data from a public repo, pseudonymized (D5), no emails/real names; all Slack/Jira-style data is synthetic
- [ ] AI disclosure paragraph in README (AI coding assistant used; you reviewed and can explain the code)
- [ ] `docs/decisions.md` explains D1 to D11, scoring weights, pinned versions
- [ ] Code is commented as required
- [ ] Demo: (1) "Why do we use X?" shows the traced path; (2) "Is that still valid?" shows freshness; (3) Simulate change flips it to stale; (4) "Flag it for review" creates a ReviewRequest; (5) stop the local FalkorDB container and show the app failing (record this locally, not on the live URL)
- [ ] Submit at least 3 hours before Oct 18, 11:59 PM IST
