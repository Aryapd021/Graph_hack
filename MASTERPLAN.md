# Company Brain: Masterplan

**Event:** Graph Hacks (WeMakeDevs x FalkorDB) | **Track:** 03, Company Brain | **Team:** solo
**Deadline:** Oct 18, 2026, 11:59 PM IST
**This file answers "when, in what order, how to verify, what to cut."** `ARCHITECTURE.md` answers "what exactly to build." If they conflict, `ARCHITECTURE.md` wins and this file gets fixed.

Time figures below are my planning estimates, not measurements. Section 7 tells you how to re-plan once you have real timings.

---

## 1. Reality check: pick your scope by hours left

Today is the deadline day. Before anything else, check the clock and compute **hours left = 11:59 PM IST minus now**. Then use this table.

| Hours left | Scope | Skip |
|---|---|---|
| 22 or more | All tasks B0 to B12 (B13 only if ahead of schedule) | nothing |
| 21 to 22 | B0 to B12 | B13 |
| 19 to 21 | Tier 1 + Tier 2a (B10). README says "local setup" only | B12 (live deploy), B13 |
| 17.5 to 19 | Tier 1 only | B10, B12, B13 |
| 12 to 17.5 | Tier 1 with a minimal UI (chat + trace only, no graph view), short README, automated test T2 only | B10, B12, B13, polish |
| under 12 | B0 to B8 and a README. Demo through the API's built-in Swagger page at `/docs` | all UI, B10, B12, B13 |

Where the numbers come from: required hours = sum of task estimates (section 5) + 1h demo/recording + 3h submission buffer. Tier 1 is 13.5h + 1h + 3h = 17.5h. Adding B10 (1.5h) gives 19h. Adding B12 and the remaining B11 tests (1.75h) gives about 21h. Adding B13 (1h) gives about 22h.

The 3h buffer is the spec's own rule: submit at least 3 hours before the deadline.

## 2. Tiers

| Tier | Contents | Why it is valid on its own |
|---|---|---|
| **Tier 1 (must ship)** | B0 to B8, B9, B11 (README, decisions, test T2) | FalkorDB is the core, all Cypher is documented, the agent answers who-owns / who-knows / why-decided / is-it-stale with cited graph paths, README meets every rule |
| **Tier 2** | B10 (Decisions board, simulate change, flag for review, Reviews tab), B12 (live deploy), automated tests T5 and T8 | The "keeping knowledge current" and "get work done" demos, a live URL |
| **Tier 3** | B13 (Gemini text upgrade), neighborhood expand, node drawer polish | Nice to have |

Rule: never start a higher tier while a lower tier's acceptance checks fail.

## 3. Pre-flight checklist (do before B0)

**Accounts and keys** (put values only in `.env` / `.env.cloud`, never in chat, files you commit, or screenshots)
- [ ] New GitHub token: read-only, public repositories only (old one was revoked)
- [ ] New Gemini API key (old one was revoked)
- [ ] FalkorDB Cloud instance reachable; password rotated if you pasted it in chat earlier
- [ ] Railway account with GitHub connected (only needed for B12)
- [ ] `openssl rand -hex 16` run once for `PSEUDONYM_SALT`; do not change it later or contributor ids change

**Local tools**
- [ ] Docker Desktop running
- [ ] Python (a version supported by the pinned dependencies) and Node (same)
- [ ] `git`, `curl`, optionally `jq`
- [ ] Antigravity open on an empty repo `company-brain`

**Repo hygiene (first commit)**
- [ ] `.gitignore` contains: `.env`, `.env.*`, `!.env.example`, `__pycache__/`, `node_modules/`, `web/dist/`, `.venv/`
- [ ] `ARCHITECTURE.md` and `MASTERPLAN.md` committed in the repo root
- [ ] License file chosen (MIT is the common default; your call)
- [ ] Repository is public (hackathon rule)

**Env files**
- `.env` holds local Docker values (`FALKORDB_HOST=localhost`, empty username and password, `FALKORDB_SSL=false`) plus Gemini and GitHub values.
- `.env.cloud` holds FalkorDB Cloud values (host, port 54711, username, password in single quotes, `FALKORDB_SSL=true`) plus the same Gemini and GitHub values. Select it with `ENV_FILE=.env.cloud`.
- Develop and test against local Docker. Touch Cloud only for gate G7 and the final data load.

**Help**
- FalkorDB Discord (link on the hackathon page) is open for the whole event, including for graph-model problems.

## 4. Antigravity operating rules

Use one fresh Antigravity session per task. Paste the preamble, then the task prompt from section 6.

**Preamble (paste every time):**
```
ARCHITECTURE.md in the repo root is the source of truth. Implement ONLY the task named below
(section 19 of ARCHITECTURE.md). Rules:
1. Use exact names, paths, ids, env vars and JSON shapes from the spec. Do not invent endpoints,
   fields, labels or environment variables.
2. Cypher lives only in backend/brain_core/queries.py (ingest loaders are the only exception).
   Environment variables are read only in backend/brain_core/config.py.
3. Comment heavily: a docstring on every function and "why" comments on non-obvious lines.
4. Never write secrets into any file except the untracked .env / .env.cloud. Never print secrets.
5. If the spec is ambiguous, wrong, or a gate fails: STOP. Report the exact error and the spec
   section. Do not guess or work around it.
6. When done, list every file created or changed and every deviation from the spec.
```

**After every task (you, 5 minutes):**
1. Run the task's acceptance commands (section 6). All must pass.
2. Skim the diff for: Cypher or env reads outside the allowed files, hardcoded hosts or ports, hand-written API types, `print` to stdout in `mcp_server/`, any secret.
3. `git add -A && git commit -m "B<n>: <what>" && git tag b<n>`. Tags let you roll back cleanly.
4. If Antigravity reported a spec deviation, either fix the code or update `ARCHITECTURE.md` and add a line to `docs/decisions.md`. Never leave them different.

## 5. Dependency graph and schedule

```
B0 -> B1 -> B2 -> B3 -> B4 -> B5 -> B6 -> B7 -> B8 -> B10 -> B12
                                           \-> B9 (starts when the B7 OpenAPI exists; may overlap B8)
B11 starts after B8 and finishes after B12.   B13 only after B12.
```

| Task | Est. hours | Cumulative | Output | Tier |
|---|---|---|---|---|
| B0 | 0.75 | 0.75 | Skeleton, config, DB client, smoke gates | 1 |
| B1 | 1.0 | 1.75 | Models, Cypher registry, schema, freshness, generated queries doc | 1 |
| B2 | 1.5 | 3.25 | GitHub fetch and load, pseudonymization, PII scans | 1 |
| B3 | 1.5 | 4.75 | Synthetic data, derive, verify, ground truth | 1 |
| B4 | 0.5 | 5.25 | Embeddings | 1 |
| B5 | 1.5 | 6.75 | Services + tests T1 to T3 | 1 |
| B6 | 1.25 | 8.0 | MCP server, 11 tools, test T4, gate G6 | 1 |
| B7 | 1.0 | 9.0 | REST API, OpenAPI, test T7 | 1 |
| B8 | 1.5 | 10.5 | Agent loop, `/api/chat`, test T6 | 1 |
| B9 | 2.0 | 12.5 | Frontend: chat, trace, graph | 1 |
| B10 | 1.5 | 14.0 | Decisions board, simulate, flag, reviews | 2 |
| B11 | 1.25 | 15.25 | README, decisions doc, tests T5 and T8 (Tier 1 needs about 1.0h of this) | 1 and 2 |
| B12 | 1.5 | 16.75 | Live deploy on Railway + Cloud load | 2 |
| B13 | 1.0 | 17.75 | Optional text upgrade | 3 |
| Demo + recording | 1.0 | | Section 9 | |
| Submission buffer | 3.0 | | Section 12 | |

## 6. Task playbook

Each task: **Read** (spec sections for Antigravity), **Build**, **Done when** (commands you run), **If it fails**.

### B0: Skeleton, config, DB client, gates
**Read:** sections 2, 4, 5, 17, 18.
**Build:** folder layout from section 4; `.gitignore`; `.env.example` with every key from section 5 and no values; `docker-compose.yml` with the `falkordb` service only for now; `backend/pyproject.toml` (dependencies: `falkordb`, `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `httpx`, `mcp`, `google-genai`, `pytest`); `brain_core/config.py` (fail-fast validation, `ENV_FILE` support); `brain_core/db.py` (host, port, username, password, ssl as separate arguments); `scripts/smoke_falkordb.py` (gates G1 to G5 and G8, scratch graph `smoke_scratch`, prints PASS or FAIL with the exact error); `scripts/test.sh` (section 17 test-safety rule). After the first successful install, pin exact versions of `falkordb`, `mcp`, `google-genai` and the FalkorDB image tag, and record them in `docs/decisions.md`.
**Prompt:** `Task B0. Read sections 2, 4, 5, 17, 18 of ARCHITECTURE.md. Build exactly what the B0 row of section 19 lists, plus pin versions as described in section 17.`
**Done when:**
```bash
docker compose up -d falkordb
python scripts/smoke_falkordb.py                       # local: PASS for G1, G2, G3, G4, G5, G8
ENV_FILE=.env.cloud python scripts/smoke_falkordb.py   # Cloud: same PASS lines = gate G7
```
**If it fails:**
- G1 to G5 syntax errors: open the FalkorDB docs for the pinned image tag and fix `schema.py` / the query. Do not change the architecture.
- Cloud auth or SSL errors: confirm the password is in single quotes, `FALKORDB_SSL=true`, and port 54711.
- Cloud connection timeouts: check for an IP allowlist in the FalkorDB Cloud dashboard.
- G8 fails: check the model id, the key, and the thinking-level parameter name for the pinned `google-genai` version.
- Two hours into B0 with gates still failing: ask in the FalkorDB Discord with the exact error text, and keep going with the other gates.

### B1: Shared core
**Read:** sections 6, 9, 10, 13.
**Build:** `models.py` (all Pydantic types), `queries.py` (Q01 to Q23, Q10 unused), `schema.py` with `apply()` (indexes and the `Meta` node, idempotent), `freshness.py` (`classify`), `scoring.py`, `graph_payload.py` (prop allow-lists, edge ids), `scripts/gen_queries_doc.py`.
**Done when:**
```bash
cd backend && pip install -e .
python -c "import brain_core.models, brain_core.queries, brain_core.freshness; print('imports ok')"
python scripts/gen_queries_doc.py && head -40 docs/queries.md
FALKORDB_GRAPH=company_brain_test python -c "from brain_core import schema; schema.apply(); schema.apply(); print('idempotent ok')"
```
Plus a unit test for `classify()` covering fresh, stale, superseded and the threshold edge.
**If it fails:** vector index dimension mismatch means `EMBED_DIM` is not 3072 in the env used; fix the env, not the code.

### B2: GitHub fetch and load
**Read:** sections 5, 6, 7.
**Build:** `ingest fetch` and `ingest load` for Persons, Modules, Files, PRs, Docs and their edges, with `MODULE_RULES`, bot skipping, `DOC_PATH_PREFIXES`, `DOC_EXCLUDE`, pseudonymization and scrubbing as specified. Cache in `data/cache/github/` (reduced, scrubbed JSON only).
**Done when** (against local Docker, graph `company_brain`):
```bash
python -m ingest fetch      # ends with the in-memory login scan: must report zero remaining logins
python -m ingest load
# PII spot checks on the cache:
grep -rE "avatar_url|\"login\"|html_url" data/cache/github | head        # expect nothing
grep -rE "@[A-Za-z0-9_-]+" data/cache/github | grep -v "@contributor" | head   # expect nothing
```
In the FalkorDB browser at `http://localhost:3000`:
```cypher
MATCH (p:Person) RETURN p.id, p.display LIMIT 5      // ids look like p_ + 8 hex, display "Contributor ..."
MATCH (m:Module) RETURN m.id, m.path ORDER BY m.path // fastapi/..., docs/en/docs/..., tests; no docs/<other language>
MATCH (d:Doc) RETURN d.path ORDER BY d.path LIMIT 50 // no path containing people, sponsors, release-notes, contributing
```
**If it fails:**
- GitHub 403 or rate limit: token missing or wrong scope; the cache makes re-runs cheap once fetched.
- Too few PRs kept: raise `MAX_PRS` or loosen `MODULE_RULES` prefixes; record the change in `docs/decisions.md`.
- Persons under 15: acceptable only if the PR pool is small; check with `MATCH (p:Person) RETURN count(p)`.

### B3: Synthetic data, derive, verify
**Read:** sections 6, 7, 8.
**Build:** `synthetic_gen.py`, `ingest synth`, `ingest load --synthetic`, `ingest derive`, `ingest verify` (counts, ground-truth comparison, PII pattern scan), plus test T1 (tiny fixture snapshot).
**Done when:**
```bash
python -m ingest synth && python -m ingest load --synthetic && python -m ingest derive && python -m ingest verify
```
`verify` exits 0 and prints counts at or above these targets (adjust only with a note in `docs/decisions.md`): Team 4, Decision 12, Ticket 22 or more, Thread 24 or more, PR 100 or more, Person 15 or more, Module 8 or more, Doc 20 or more.
It must also print the freshness distribution with **at least 3 stale, at least 3 fresh and at least 1 superseded** decision, because the demo needs each kind. If not, change `SYNTH_SEED` or `SYNTH_DECISIONS` and rerun; note the change.
**If it fails:** `ground_truth.json` disagrees with Q09 means a bug in either the Python oracle or the Cypher; the oracle has no Cypher, so debug the query first (gate G3 area).

### B4: Embeddings
**Read:** sections 6, 7.
**Build:** `ingest embed` with batching, retry with backoff, `text_hash` skip, `output_dimensionality = EMBED_DIM`, `vecf32` storage.
**Done when:**
```bash
python -m ingest embed       # reports N embedded
python -m ingest embed       # second run reports 0 embedded, N skipped (hash unchanged)
```
```cypher
MATCH (n) WHERE n.embedding IS NOT NULL RETURN labels(n)[0] AS label, count(*)   // Doc, Decision, Thread only
```
**If it fails:** 429 or quota errors: lower batch size, add sleep between batches. Dimension errors: `EMBED_DIM` must equal the length of the returned vector (gate G8).

### B5: Services
**Read:** sections 9, 10, 13.
**Build:** every function in `services.py` listed in section 10; tests T2 and T3; a search sanity test: for 3 loaded Docs, query by the Doc's own title and assert the Doc appears in the top 3 hits.
**Done when:**
```bash
bash scripts/test.sh -k "T2 or T3 or search_sanity"
```
Tests run on local Docker graph `company_brain_test` only (the test-safety rule aborts otherwise).
**If it fails:** vector search ordering wrong means gate G2's result was not applied (distance versus similarity); fix the sort direction in one place.

### B6: MCP server
**Read:** sections 11, 13.
**Build:** `mcp_server/server.py` with the 11 tools exactly as in the contract table (stdio, logs to stderr, schemas limited to str/int/bool/Literal/list[Literal] with defaults), `scripts/mcp_probe.py` (lists tools, calls each once with sample arguments, prints `ok` and `summary`), test T4, and gate G6 added to the smoke script.
**Done when:**
```bash
python scripts/mcp_probe.py        # 11 tools listed; each call returns ok=true except the deliberate unknown-id check
python scripts/smoke_falkordb.py   # now includes PASS G6
bash scripts/test.sh -k T4
```
**If it fails:**
- Probe hangs or garbled output: something prints to stdout. Move all logging to stderr.
- G6 fails on a tool schema: remove `Optional`/`Union`, or simplify the default.

### B7: REST API
**Read:** sections 13, 14.
**Build:** `brain_api/main.py` (lifespan: DB, `Meta` guard, MCP child; health; error handlers returning `ErrorResponse`), all routes, with `/api/chat` as a placeholder that returns the spec's `INTERNAL` error ("agent not implemented") until B8, exposure flags, rate limiter, test T7.
**Done when:**
```bash
cd backend && uvicorn brain_api.main:app --port 8000
curl -s localhost:8000/api/health
curl -s localhost:8000/api/decisions | head -c 600
curl -s localhost:8000/api/modules | head -c 400
curl -s localhost:8000/openapi.json | head -c 300
bash scripts/test.sh -k T7
```
**If it fails:** startup refuses with a `Meta` mismatch message: rerun `python -m ingest all --reset` with the same env that the API uses.

### B8: Agent and chat
**Read:** sections 11, 12, 13.
**Build:** `agent/mcp_client.py` (schema conversion), `agent/loop.py` (manual function-calling loop, step cap, trace, evidence collection, citation validation), `agent/prompts.py`, `/api/chat`, test T6.
**Done when:** each question below is sent and the listed tools appear in `.trace[].tool`, with non-empty `citations` on every factual answer:
```bash
ask() { curl -s localhost:8000/api/chat -H 'content-type: application/json' \
  -d "{\"message\":\"$1\",\"history\":[]}" | jq '{answer, tools:[.trace[].tool], cites:[.citations[].node_id]}'; }
ask "Which decisions need review?"                       # list_stale_decisions
ask "Who owns <module path from /api/modules>?"          # who_owns
ask "Who knows the most about <topic from a Doc title>?" # who_knows
ask "Why did we decide <decision title>?"                # search_knowledge, trace_decision
ask "Is that decision still valid? <decision title>"     # check_decision_freshness
ask "What changed recently in <module path>?"            # recent_changes
ask "Who are the key connectors?"                        # key_connectors
```
Then `bash scripts/test.sh -k T6`.
**If it fails:**
- Wrong tool chosen: edit the **tool descriptions** (docstrings in `server.py`), not the loop.
- No function call returned: check `GEMINI_THINKING_LEVEL` and that tool declarations were passed.
- Answer without citations: tighten the system prompt rule that every factual sentence ends with `[[node_id]]`.

### B9: Frontend core
**Read:** sections 14, 15, 16.
**Build:** Vite + React + TypeScript + Tailwind scaffold, dev proxy to `localhost:8000`, `npm run gen:types`, `api/client.ts`, `brainStore`, `ChatPanel` (citation chips), `TracePanel`, `GraphView` (Cytoscape, highlight class), `HealthBadge`, graph styling typed as `Record<NodeLabel, ...>`.
**Done when:**
```bash
cd web && npm install && npm run gen:types && npx tsc --noEmit && npm run build
npm run dev     # open the printed URL, backend running on :8000
```
In the browser: ask "Why did we decide ...", see the answer, clickable citation chips, trace steps with tool names, and highlighted graph nodes.
**If it fails:** TypeScript errors on API shapes mean the backend model changed: rerun `gen:types`, never hand-edit `schema.d.ts`.

### B10: Decisions board, demo controls, reviews
**Read:** sections 14, 15.
**Build:** `DecisionsBoard` (freshness badges, Trace, Flag for review), `ReviewsPanel`, `DemoControls` (Simulate change, Reset, Refresh data, shown by health flags), `NodeDrawer` with Expand.
**Done when:** in the UI, simulate a change on a module that a fresh decision affects: that decision flips to stale and the toast names it; flag a decision: it appears in Reviews and the assignee is the decider; Reset restores the original state.
**If it fails:** nothing flips: check that the module chosen is in the decision's `AFFECTS` list (Q08/Q09 logic) and that the threshold is 1.

### B11: Docs and remaining tests
**Read:** sections 17, 20.
**Build:** `README.md` (section 10 below), `docs/decisions.md`, tests T5 and T8, regenerated `docs/queries.md`.
**Done when:**
```bash
python scripts/gen_queries_doc.py && git diff --stat docs/queries.md    # no unexpected changes
bash scripts/test.sh                                                      # T1 to T8 pass (T5 stops and restarts local FalkorDB)
```
**If it fails:** T5 flaky: wait for the container health check before asserting recovery.

### B12: Live deploy
**Read:** sections 5, 18b.
**Build:** `deploy/Dockerfile.prod`, static mount in `main.py`, README live URL.
**Steps:**
1. Load Cloud data from your laptop (the live container never ingests):
   ```bash
   ENV_FILE=.env.cloud python scripts/smoke_falkordb.py
   cd backend && ENV_FILE=.env.cloud python -m ingest all --reset
   ```
2. In Railway: new service from your GitHub repo, point it at `deploy/Dockerfile.prod` (service settings, or the `RAILWAY_DOCKERFILE_PATH` variable; confirm in Railway's docs), one replica, health check path `/api/health`.
3. Variables tab: `FALKORDB_HOST`, `FALKORDB_PORT`, `FALKORDB_USERNAME`, `FALKORDB_PASSWORD`, `FALKORDB_SSL=true`, `FALKORDB_GRAPH`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_THINKING_LEVEL`, `GEMINI_EMBED_MODEL`, `EMBED_DIM`, `LLM_TIMEOUT_S`, `GITHUB_REPO`, `STALE_PR_THRESHOLD`, `AGENT_MAX_STEPS`, `SERVE_STATIC=true`, `DEMO_MODE=true`, `ENABLE_INGEST_REFRESH=false`, `CHAT_RATE_LIMIT_PER_MIN=10`. Do not add `GITHUB_TOKEN` or `PSEUDONYM_SALT`.
4. Deploy, then verify:
   ```bash
   curl -s https://<your-railway-domain>/api/health     # falkordb:true, mcp:true, demo_mode:true, ingest_refresh:false
   ```
5. Run the full demo flow (section 9) on the live URL, then Reset, then add the URL to the README.
**If it fails:**
- `falkordb:false`: Cloud allowlist, wrong password quoting, or `FALKORDB_SSL` not `true`.
- Blank page: `SERVE_STATIC` not `true` or the build stage missed `web/dist`.
- Meta mismatch refusal: the Cloud graph was loaded with different `EMBED_DIM`, model or repo; reload with `--reset`.
- Slow first load: free-tier cold start; warm it before judging (section 12).

### B13 (optional): Gemini text upgrade
**Read:** section 8, step 7.
**Done when:** `python -m ingest synth --llm` runs; `ground_truth.json` is byte-identical; `bash scripts/test.sh -k T2` still passes; forcing a Gemini failure makes the run fall back to templates without error. Reload and re-embed afterwards (`load --synthetic`, `embed`), then reload Cloud if B12 is done.

## 7. Checkpoints and decision rules

| Checkpoint | When | Pass condition | If not passing |
|---|---|---|---|
| C0 | End of B0 | G1 to G5, G8 pass locally; G7 passes on Cloud | Do not start B1 until local gates pass. If only G7 fails, continue and fix Cloud in parallel (allowlist, TLS) before B12 |
| C1 | End of B3 | Data loaded, `verify` exits 0, distribution has stale, fresh and superseded decisions | Compare actual elapsed time with cumulative 4.75h. If actual is above 1.3 times the estimate, move one row down in the section 1 table |
| C2 | End of B8 | All 7 questions in B8 use the right tools with citations | Same 1.3 times rule against 10.5h. At this point you must have a working product without any UI |
| C3 | Deadline minus 5h (6:59 PM IST) | Feature freeze. No new features after this | Only bug fixes, docs and deploy |
| C4 | Deadline minus 4h (7:59 PM IST) | Live URL verified, or local-only decision made | If the live deploy is not working, drop it, switch the README to local setup, and spend the time on the demo |
| C5 | Deadline minus 3h (8:59 PM IST) | Submitted | Remaining time is buffer for form problems |

## 8. Risk register

| ID | Risk | Likelihood | Impact | Mitigation | Trigger to act |
|---|---|---|---|---|---|
| R1 | FalkorDB syntax differs (vector index, shortestPath, pageRank, pattern predicates) | Medium | High | Gates G1 to G5 first; fix queries per the pinned version's docs; spec lists fallbacks | Any gate FAIL |
| R2 | Cloud and Docker FalkorDB versions differ | Medium | Medium | Gate G7; pin the Docker tag to the Cloud version if known | G7 FAIL while local passes |
| R3 | Gemini function-calling schema rejection or model-call errors | Medium | High | Schema constraints in section 11, gates G6 and G8 | G6 or G8 FAIL |
| R4 | Agent picks wrong tools or skips citations | Medium | High | Tune tool descriptions and system prompt; citation validation drops invented ids | B8 question list failing |
| R5 | GitHub rate limits or slow fetch | Medium | Medium | Token, cache committed, MAX_PRS 150 | 403 or 429 during fetch |
| R6 | PII leaks into graph or cache (names, handles, emails, profile links) | Low to medium | High (rule violation) | Pseudonymization, scrub rules, `DOC_EXCLUDE`, fetch-time login scan, `verify` pattern scan | Any scan hit |
| R7 | Secrets committed or shown on screen | Medium | High | `.gitignore` first, `.env.cloud` separate, rotate keys that appeared in chat, review diffs, check `git log -p` for key patterns before making the repo public | Before first push and before submission |
| R8 | Test run damages the real graph | Low | High | `scripts/test.sh` test graph, conftest abort rule, never export Cloud credentials in the shell for tests | n/a |
| R9 | Antigravity drifts from the spec | Medium | Medium | One task per session, preamble, diff review, tags for rollback | Deviation list not empty |
| R10 | Live demo state changed by visitors | Medium | Low | `DEMO_MODE` is global by design; Reset before judging and recording | Before demo and submission |
| R11 | Public URL abuse burns Gemini quota | Low to medium | Medium | Per-IP rate limit, rotate key after the event, consider disabling the chat route after judging if quota is a concern | Unexpected usage |
| R12 | Time overrun | High | High | Tiers, hours-left table, checkpoints, feature freeze | C1 or C2 slipping |
| R13 | Free-tier cold start during judging | Medium | Low | Warm `/api/health` before judging; mention in README | Slow first response |
| R14 | Generated TS types drift | Low | Medium | `gen:types` in the build, CI-style check `npm run gen:types && git diff --exit-code web/src/api/schema.d.ts` | Type errors |

## 9. Demo plan

**Pick the demo data after B3 (data-driven, not guessed):**
1. `curl -s localhost:8000/api/decisions` and choose:
   - **Decision S**: stale with `drift_count` 2 or more (for the staleness story)
   - **Decision F**: fresh, with a module in `module_ids` (for the simulate step)
2. Note the module path of F's affected module, and one person display name from `/api/modules` owners.

**Script (about 3 minutes):**

| Step | You do | Shows |
|---|---|---|
| 1 | Ask: "Why did we decide `<S title>`?" | search then trace: decider, PR, ticket, Slack thread, doc; graph path highlighted; citations clickable |
| 2 | Ask: "Is that decision still valid?" | freshness tool: stale, with the later PRs listed |
| 3 | Ask: "Who owns `<module>` and who actually knows it best?" | formal owner team versus actual top contributors, ownership gap flag |
| 4 | Ask: "Which decisions need review?" then "Flag `<S title>` for review" | list of stale decisions; write action creates a ReviewRequest assigned to the decider; Reviews tab shows it |
| 5 | Simulate change on F's module | F flips from fresh to stale live, toast names it; Reset |
| 6 | Open the FalkorDB browser (`localhost:3000`), run the trace Cypher from `docs/queries.md` | The same answer comes straight from the graph |
| 7 | Locally stop the FalkorDB container; reload the app | Health shows degraded, chat returns 503: the product cannot function without FalkorDB (record this locally, not on the live URL) |

**Fallbacks:** if Gemini is slow or rate limited, keep one answered chat visible and demonstrate steps 5 to 7, which do not call the LLM. Record the video from local Docker if the live host is unstable.

**Pre-demo checklist:** Reset run, health green, one warm-up chat sent, browser zoom set, no secrets on screen (terminals, `.env` files, dashboards).

The hackathon page I was shown does not list submission-form fields. Check the actual form for required items (demo video, description, links) and use this script for any of them.

## 10. README and docs content

**`README.md` sections, in this order:**
1. Title, one-line pitch, **Track 03: Company Brain** (declared at the top)
2. Live demo URL (if B12 done) and screenshot
3. What it does (the 5 capabilities from the demo)
4. Why the graph matters: the product stops working without FalkorDB (name test T5)
5. Architecture overview (diagram from section 3 of the spec)
6. **Graph data model** (node and relationship tables from spec section 6)
7. Cypher queries and algorithms (link to `docs/queries.md`, mention PageRank)
8. Local setup (copy the commands from spec section 18)
9. Deployment (Railway, FalkorDB Cloud; link to spec section 18b)
10. Data and privacy statement
11. Testing
12. AI disclosure
13. License

**Data and privacy statement (adapt if facts change):**
> GitHub data comes from the public repository `fastapi/fastapi` and contains only public information. Contributor identities are pseudonymized (hashed with a private salt) and emails, names and profile links are removed before anything is stored. All Slack-style and Jira-style records (teams, tickets, chat threads, decisions) are synthetic and generated deterministically from the public data. No private, login-protected, paywalled or personal data is used.

**AI disclosure (edit to match exactly what you used):**
> This project was built with AI assistance. Claude (Anthropic) helped design the architecture and plan. Antigravity (AI coding assistant) generated much of the code. I reviewed, tested and can explain every part of it, and the design decisions are documented in `docs/decisions.md`. At runtime the agent uses Google's Gemini models (`gemini-3.8-flash`, `gemini-embedding-001`).

**`docs/decisions.md` contents:** pinned versions (FalkorDB image, `google-genai`, `mcp`, Python, Node), D1 to D14 with rationale, scoring weights (1, 2, 3), `STALE_PR_THRESHOLD`, `MODULE_RULES` and why, `DOC_EXCLUDE` and why, any `verify` threshold changes, any `SYNTH_SEED` change, any spec deviations.

## 11. Git and repo hygiene

- Single branch `main`; commit after every task; tag `b0` to `b13`.
- Commit `data/cache/github/` and `data/synthetic/` (public or synthetic only) so judges can run without a GitHub token.
- Before the repo goes public: `git log -p | grep -Ei "github_pat_|AIza|AQ\.|password"` returns nothing; `git ls-files | grep -E "^\.env"` shows only `.env.example`.
- Rotate the GitHub token and Gemini key after the event ends. Rotate the FalkorDB Cloud password if it was shared anywhere.

## 12. Submission day timeline

| Time (IST) | Action |
|---|---|
| Deadline minus 5h (6:59 PM) | Feature freeze (C3) |
| Deadline minus 4h (7:59 PM) | Live URL verified or dropped (C4); Reset demo state; final full test run `bash scripts/test.sh` |
| Deadline minus 3h (8:59 PM) | Submit (C5), then verify the submission page shows the right repo and links |
| Until 11:59 PM | Buffer only. No risky changes after submitting; if you change anything, rerun tests and the live health check |

**Final checklist (mirrors spec section 20):**
- [ ] README has Track 03 at the top, setup steps, graph data model, data statement, AI disclosure, live URL if deployed
- [ ] `docs/queries.md` regenerated and current
- [ ] FalkorDB dependency proven (test T5 and the demo step)
- [ ] Docker Compose works from a clean clone (`cp .env.example .env`, fill, `docker compose up`, ingest, UI loads)
- [ ] All tests T1 to T8 pass locally
- [ ] Repo public; no secrets in history; `.env*` ignored
- [ ] Code comments present on every function; you can explain each file
- [ ] Demo state reset; health check green
- [ ] Keys rotated after submission (or scheduled)

## 13. Requirement traceability

| Requirement (rules and brief) | Where satisfied | How verified |
|---|---|---|
| FalkorDB is the primary graph DB, does real work, product breaks without it | Spec sections 1, 9, 14; all retrieval and freshness logic in Cypher | Test T5; demo step 7 |
| Aligned with an official track | Track 03 declared in README | README review |
| Only public, synthetic or own data; no private or personal data | Spec D5, scrub rules, `DOC_EXCLUDE`, synthetic generator | `fetch` login scan, `verify` PII scan, grep spot checks |
| Any stack, FalkorDB via Docker, self-hosted or Cloud | Compose locally, FalkorDB Cloud live | Gates G1 to G5, G7 |
| README with local setup and graph data model | B11 | Clean-clone run |
| All Cypher and algorithms documented | `docs/queries.md` generated from `queries.py` | Regeneration shows no diff; test T8 |
| Deployment config or exhaustive local instructions | `docker-compose.yml`, `deploy/Dockerfile.prod` | B12 checks |
| Track declaration in documentation | README top | README review |
| Explainable, commented code; architectural documentation | Comment rules, `docs/decisions.md` | Diff review after each task |
| AI-use disclosure in README | Section 10 text | README review |
| Track 03 key focus: knowledge from docs, tickets, chats in one graph | Doc, Ticket, Thread, Decision nodes in one graph | `verify` counts |
| Who owns what, who knows what | `who_owns`, `who_knows`, ownership-gap flag | B8 questions, demo step 3 |
| Tracing decisions back to their source | `trace_decision`, evidence chain, graph highlight | Demo step 1 |
| Keeping knowledge current | Derived freshness, simulate change, refresh route | Test T3, demo step 5 |
| Answers with clear sources | Validated `[[node_id]]` citations | Test T6 |
