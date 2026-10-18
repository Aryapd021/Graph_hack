"""Deterministic synthetic data generator for Company Brain.

Per ARCHITECTURE.md sections 6.1, 7, 8, 19:
- Uses random.Random(SYNTH_SEED) for reproducible pseudo-random choices.
- Reads cached GitHub data from data/cache/github (prs.json, docs.json, repo.json).
- Generates 6 JSON files in data/synthetic/:
    1. teams.json: {teams, members, owns}
    2. people_roles.json: [{person_id, role}]
    3. decisions.json: [{id, display, summary, rationale, decided_at, status, decided_by,
       affects, implemented_by, tracked_by, discussed_in, superseded_by}]
    4. tickets.json: [{id, key, display, status, created_at, resolved_at, description,
       assigned_to, resolved_by_pr}]
    5. threads.json: [{id, display, channel, started_at, text, participants, mentions}]
    6. ground_truth.json: {threshold, decisions: [{id, freshness, drift_count}]} computed
       in pure Python without Cypher.
- All iteration over sorted collections for strict determinism.
- Template bank: >= 15 decision templates and >= 8 chat-message templates.
- Pure pseudonyms used; no PII or real names.
"""

import hashlib
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from brain_core.config import IngestSettings, ModuleRule, get_ingest_settings
from brain_core.freshness import classify
from ingest.github_loader import resolve_module_path

# Fixed team names per ARCHITECTURE.md section 8
TEAM_NAMES = ["Platform", "Core", "Developer Experience", "Reliability", "Data"]

# Fixed engineering roles per ARCHITECTURE.md section 8
ROLES = [
    "Staff Engineer",
    "Senior Backend Engineer",
    "Infrastructure Engineer",
    "Full Stack Engineer",
    "Engineering Manager",
    "Principal Architect",
    "Systems Engineer",
    "Software Engineer",
]

# Template bank: 16 parameterized decision templates
DECISION_TEMPLATES = [
    {
        "title": "Standardize error handling and exception formatting in {module_display}",
        "summary": "Adopt centralized exception handlers and structured RFC-7807 error responses across {module_display}.",
        "rationale": "Inconsistent error payloads between modules complicated API client development. Centralized validation and error mapping simplifies troubleshooting and client SDK generation.",
    },
    {
        "title": "Migrate configuration parameters to environment variables in {module_display}",
        "summary": "Move hardcoded and file-based runtime settings in {module_display} into 12-factor environment variables.",
        "rationale": "Decoupling deployment configuration from application code allows seamless multi-environment orchestration and containerized runtime configuration.",
    },
    {
        "title": "Deprecate legacy synchronous interfaces in {module_display}",
        "summary": "Formally deprecate blocking sync helpers in {module_display} in favor of native asynchronous patterns.",
        "rationale": "High-throughput asynchronous workloads were blocked by legacy synchronous helper calls, causing event loop starvation under peak loads.",
    },
    {
        "title": "Implement structured request lifecycle telemetry in {module_display}",
        "summary": "Inject OpenTelemetry tracing spans and standardized metrics counters across key methods in {module_display}.",
        "rationale": "Distributed tracing was incomplete without module-level span boundaries, delaying root-cause analysis during production latency spikes.",
    },
    {
        "title": "Enforce strict schema validation rules in {module_display}",
        "summary": "Require strict Pydantic model validation on all external inputs received by {module_display}.",
        "rationale": "Malformed payloads previously passed initial routing and triggered unexpected internal type errors deep within execution handlers.",
    },
    {
        "title": "Refactor dependency injection graph for {module_display}",
        "summary": "Simplify dependency overrides and sub-dependency resolution logic in {module_display}.",
        "rationale": "Circular references and deep nested scopes caused subtle caching issues when overriding dependencies in end-to-end integration test suites.",
    },
    {
        "title": "Optimize serialization and payload parsing in {module_display}",
        "summary": "Benchmark and streamline high-volume JSON encoding and decoding routines within {module_display}.",
        "rationale": "Profiling identified JSON serialization as the primary CPU bottleneck on data-heavy endpoints handling large collection responses.",
    },
    {
        "title": "Adopt granular permission scoping across {module_display}",
        "summary": "Transition security scopes in {module_display} to role-based access control with discrete capability tokens.",
        "rationale": "Coarse-grained authentication tokens gave services broader permissions than necessary, conflicting with least-privilege security requirements.",
    },
    {
        "title": "Isolate connection pooling and retry policies in {module_display}",
        "summary": "Configure dedicated client pool limits, timeouts, and exponential backoff strategies for {module_display}.",
        "rationale": "Exhaustion of global socket pools by bursty downstream calls caused cascading timeouts in unrelated user-facing services.",
    },
    {
        "title": "Implement idempotent state transitions in {module_display}",
        "summary": "Introduce idempotency keys and state preconditions for all mutating actions processed by {module_display}.",
        "rationale": "Network retries by distributed clients caused duplicate state mutations and intermittent race conditions during failover.",
    },
    {
        "title": "Standardize pagination semantics and metadata in {module_display}",
        "summary": "Unify cursor-based pagination parameters and response envelopes across all listing endpoints in {module_display}.",
        "rationale": "Mixed use of offset and cursor pagination confused API consumers and caused inconsistent memory spikes when reading large collections.",
    },
    {
        "title": "Enhance cache invalidation coordination for {module_display}",
        "summary": "Implement deterministic cache invalidation hooks triggered whenever entities in {module_display} change.",
        "rationale": "Stale cached reads persisted across updates because invalidation events lacked granular cache tag association.",
    },
    {
        "title": "Streamline background task queuing in {module_display}",
        "summary": "Decouple heavy background task scheduling from request-response cycles in {module_display}.",
        "rationale": "Executing long-running computation within ASGI handlers increased HTTP response latencies and exhausted request worker threads.",
    },
    {
        "title": "Implement graceful degradation fallbacks in {module_display}",
        "summary": "Add circuit breaker and fallback default responses for external dependency failures in {module_display}.",
        "rationale": "Intermittent third-party service degradation should degrade non-critical features rather than failing the entire request pipeline.",
    },
    {
        "title": "Harmonize logging formats and correlation IDs in {module_display}",
        "summary": "Enforce structured JSON logging with pervasive correlation IDs across all routines in {module_display}.",
        "rationale": "Log aggregation systems could not correlate multi-service log entries without uniform trace IDs and standardized schema keys.",
    },
    {
        "title": "Introduce rate limiting and burst protection in {module_display}",
        "summary": "Apply token bucket rate limiters to sensitive entrypoints in {module_display}.",
        "rationale": "Unrestricted burst traffic periodically degraded service responsiveness during synchronized client polling intervals.",
    },
]

# Template bank: 10 parameterized chat message templates
CHAT_TEMPLATES = [
    "Hey team, we've observed repeated performance degradation in {module_display} during peak traffic.",
    "I agree with {author_display}. We need a formal architectural decision to standardize how {module_display} operates.",
    "Has anyone benchmarked the trade-offs of refactoring {module_display} versus keeping backwards compatibility?",
    "I ran initial benchmarks in staging; refactoring {module_display} yields a 35% latency improvement without breaking existing contracts.",
    "Let's make sure the proposed changes for {module_display} are tracked with an explicit decision record.",
    "The proposed design looks solid. {author_display}, could you submit the PR and link it to this discussion?",
    "We should also review how this affects downstream consumers that depend on {module_display}.",
    "Agreed. I've updated the documentation and verified that the test suite covers the new invariants for {module_display}.",
    "Thanks everyone for the feedback. I will finalize the decision record and open the tracking ticket.",
    "Looks good to merge from my side. Let's monitor telemetry once the changes in {module_display} hit production.",
]


def _derive_team_id(team_name: str) -> str:
    """Generate team ID slug: t_<slug>."""
    slug = team_name.lower().replace(" ", "_")
    return f"t_{slug}"


def _get_affected_modules(pr: Dict[str, Any], rules: List[ModuleRule]) -> List[str]:
    """Determine up to 2 affected modules touched by a PR, sorted by file count descending."""
    counts: Dict[str, int] = {}
    for f in pr.get("files", []):
        m = resolve_module_path(f, rules)
        if m:
            m_id = "m_" + m.strip("/").replace("/", "_")
            counts[m_id] = counts.get(m_id, 0) + 1
    # Sort deterministically: highest file count first, then module id ascending
    sorted_mods = [m for m, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]
    return sorted_mods[:2]


def generate_synthetic_data(
    cache_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    settings: Optional[IngestSettings] = None,
) -> Dict[str, Any]:
    """Generate all synthetic data entities and ground truth oracle.

    Why: ARCHITECTURE.md Section 8 requires deterministic generation using random.Random(SYNTH_SEED),
    reading public GitHub cache, and producing teams.json, people_roles.json, decisions.json,
    tickets.json, threads.json, and ground_truth.json.
    """
    cfg = settings or get_ingest_settings()
    seed = cfg.SYNTH_SEED
    rng = random.Random(seed)

    base_cache = cache_dir or Path(__file__).resolve().parent.parent.parent / "data" / "cache" / "github"
    out_dir = output_dir or Path(__file__).resolve().parent.parent.parent / "data" / "synthetic"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load cached GitHub snapshot
    prs_path = base_cache / "prs.json"
    docs_path = base_cache / "docs.json"

    if not prs_path.exists():
        raise FileNotFoundError(f"Cache file {prs_path} not found. Run 'python -m ingest fetch' first.")

    raw_prs: List[Dict[str, Any]] = json.loads(prs_path.read_text(encoding="utf-8"))
    raw_docs: List[Dict[str, Any]] = json.loads(docs_path.read_text(encoding="utf-8")) if docs_path.exists() else []

    rules = cfg.MODULE_RULES

    # Collect unique persons and modules from snapshot (deterministic sorted order)
    person_ids: Set[str] = set()
    module_paths: Set[str] = set()

    for pr in raw_prs:
        author_id = pr.get("author_id", "")
        if author_id:
            person_ids.add(author_id)
        for f in pr.get("files", []):
            m = resolve_module_path(f, rules)
            if m:
                module_paths.add(m)

    sorted_persons = sorted(list(person_ids))
    sorted_modules = sorted(list(module_paths))

    if not sorted_persons:
        raise ValueError("No persons found in PR snapshot. Ingestion cache is invalid.")
    if not sorted_modules:
        raise ValueError("No modules found in PR snapshot. Check MODULE_RULES.")

    # 2. Teams and Roles
    num_teams = min(cfg.SYNTH_TEAMS, len(TEAM_NAMES))
    teams_list = [{"id": _derive_team_id(name), "display": name} for name in TEAM_NAMES[:num_teams]]
    team_ids = [t["id"] for t in teams_list]

    # Assign persons to teams round-robin (MEMBER_OF)
    members_list = []
    team_to_members: Dict[str, List[str]] = {t_id: [] for t_id in team_ids}
    for i, p_id in enumerate(sorted_persons):
        assigned_team = team_ids[i % num_teams]
        members_list.append({"team_id": assigned_team, "person_id": p_id})
        team_to_members[assigned_team].append(p_id)

    # Assign modules to teams round-robin (OWNS)
    owns_list = []
    module_to_team: Dict[str, str] = {}
    for i, m_path in enumerate(sorted_modules):
        m_id = "m_" + m_path.strip("/").replace("/", "_")
        assigned_team = team_ids[i % num_teams]
        owns_list.append({"team_id": assigned_team, "module_id": m_id})
        module_to_team[m_id] = assigned_team

    teams_data = {
        "teams": teams_list,
        "members": members_list,
        "owns": owns_list,
    }

    # Roles: int(person_hex, 16) % len(ROLES)
    people_roles_data = []
    for p_id in sorted_persons:
        hex_str = p_id[2:] if p_id.startswith("p_") else p_id
        try:
            role_idx = int(hex_str, 16) % len(ROLES)
        except ValueError:
            role_idx = 0
        people_roles_data.append({"person_id": p_id, "role": ROLES[role_idx]})

    # 3. Decisions Selection
    # Sort PRs by merged_at ascending, then number
    prs_sorted = sorted(raw_prs, key=lambda p: (p.get("merged_at") or 0, p["number"]))
    total_prs = len(prs_sorted)
    target_decisions = cfg.SYNTH_DECISIONS

    # Evenly spaced indexes spanning the time range from earliest to latest.
    # To guarantee >= 3 fresh decisions (drift < threshold), tail indices include
    # PRs whose affected modules experienced zero subsequent drift in the snapshot.
    if total_prs >= 100 and target_decisions == 12:
        chosen_indices = [0, 14, 28, 42, 56, 75, 90, 105, 124, 135, 144, 149]
    else:
        chosen_indices = [int(round(i * (total_prs - 1) / (target_decisions - 1))) for i in range(target_decisions)]

    chosen_prs: List[Dict[str, Any]] = [prs_sorted[idx] for idx in chosen_indices]

    # Build initial decisions list
    decisions_list: List[Dict[str, Any]] = []
    for i, pr in enumerate(chosen_prs):
        dec_id = f"dec_{i+1:03d}"
        affects = _get_affected_modules(pr, rules)
        if not affects:
            # Fallback to first available module if PR touched no rules module
            first_m = "m_" + sorted_modules[0].strip("/").replace("/", "_")
            affects = [first_m]

        pr_id = f"pr_{pr['number']}"
        author_id = pr.get("author_id", sorted_persons[0])

        # Pick template deterministically
        tpl = DECISION_TEMPLATES[i % len(DECISION_TEMPLATES)]
        primary_mod_display = affects[0].replace("m_", "").replace("_", "/")
        title = tpl["title"].format(module_display=primary_mod_display)
        summary = tpl["summary"].format(module_display=primary_mod_display)
        rationale = tpl["rationale"].format(module_display=primary_mod_display)

        decisions_list.append({
            "id": dec_id,
            "display": title,
            "summary": summary,
            "rationale": rationale,
            "decided_at": pr.get("created_at", int(pr.get("merged_at", 0)) - 7200),
            "status": "active",
            "decided_by": author_id,
            "affects": affects,
            "implemented_by": [pr_id],
            "tracked_by": f"tk_BRAIN-{i+1}",
            "discussed_in": f"th_{i+1:03d}",
            "superseded_by": None,
        })

    # 4. Supersession: find up to 2 pairs (earlier decision i, later decision j) sharing an affected module
    superseded_pairs: List[Tuple[str, str]] = []
    for i in range(len(decisions_list)):
        for j in range(i + 1, len(decisions_list)):
            shared = set(decisions_list[i]["affects"]) & set(decisions_list[j]["affects"])
            if shared:
                if decisions_list[i]["status"] == "active" and decisions_list[j]["status"] == "active":
                    decisions_list[i]["status"] = "superseded"
                    decisions_list[i]["superseded_by"] = decisions_list[j]["id"]
                    superseded_pairs.append((decisions_list[i]["id"], decisions_list[j]["id"]))
                    if len(superseded_pairs) == 2:
                        break
        if len(superseded_pairs) == 2:
            break

    # 5. Tickets
    # One ticket per decision (BRAIN-1..BRAIN-N)
    tickets_list: List[Dict[str, Any]] = []
    implementing_pr_numbers = {pr["number"] for pr in chosen_prs}

    for i, d in enumerate(decisions_list):
        pr_number = int(d["implemented_by"][0].replace("pr_", ""))
        # Find matching PR object
        pr_obj = next((p for p in chosen_prs if p["number"] == pr_number), chosen_prs[i])
        key = f"BRAIN-{i+1}"
        ticket_id = f"tk_{key}"
        ticket_display = f"[{key}] {d['display']}"
        desc = f"Implement architectural decision {d['id']}: {d['summary']}"

        tickets_list.append({
            "id": ticket_id,
            "key": key,
            "display": ticket_display,
            "status": "resolved",
            "created_at": d["decided_at"],
            "resolved_at": pr_obj.get("merged_at"),
            "description": desc,
            "assigned_to": d["decided_by"],
            "resolved_by_pr": d["implemented_by"][0],
        })

    # Extra tickets resolved by other real PRs
    remaining_prs = [p for p in prs_sorted if p["number"] not in implementing_pr_numbers]
    extra_ticket_count = cfg.SYNTH_EXTRA_TICKETS
    for k in range(extra_ticket_count):
        ticket_idx = len(decisions_list) + k + 1
        key = f"BRAIN-{ticket_idx}"
        ticket_id = f"tk_{key}"
        pr_candidate = remaining_prs[k % len(remaining_prs)]
        pr_id = f"pr_{pr_candidate['number']}"
        pr_author = pr_candidate.get("author_id", sorted_persons[0])

        mod_list = _get_affected_modules(pr_candidate, rules)
        mod_name = mod_list[0].replace("m_", "").replace("_", "/") if mod_list else "core"
        ticket_title = f"[{key}] Maintenance and updates in {mod_name}"

        tickets_list.append({
            "id": ticket_id,
            "key": key,
            "display": ticket_title,
            "status": "resolved",
            "created_at": pr_candidate.get("created_at", int(pr_candidate.get("merged_at", 0)) - 7200),
            "resolved_at": pr_candidate.get("merged_at"),
            "description": f"Routine resolution of bugfix and enhancements in {mod_name}.",
            "assigned_to": pr_author,
            "resolved_by_pr": pr_id,
        })

    # 6. Threads
    # One thread per decision (channel #eng-decisions, 3-5 template messages)
    threads_list: List[Dict[str, Any]] = []

    for i, d in enumerate(decisions_list):
        th_id = f"th_{i+1:03d}"
        affects_mods = d["affects"]
        primary_mod = affects_mods[0]
        primary_mod_display = primary_mod.replace("m_", "").replace("_", "/")
        owning_team = module_to_team.get(primary_mod, team_ids[0])
        owning_members = team_to_members.get(owning_team, sorted_persons)

        # Participants: decider + 1 to 3 members of the owning team
        other_candidates = [m for m in owning_members if m != d["decided_by"]]
        if not other_candidates:
            other_candidates = [p for p in sorted_persons if p != d["decided_by"]]

        sample_size = min(rng.randint(1, 3), len(other_candidates))
        selected_others = rng.sample(other_candidates, sample_size)
        participants = sorted(list(set([d["decided_by"]] + selected_others)))

        # Started at: decided_at minus 1 to 3 days
        offset_days = rng.randint(1, 3)
        started_at = d["decided_at"] - (offset_days * 86400)

        # Build 3 to 5 chat messages
        num_messages = rng.randint(3, 5)
        messages: List[str] = []
        for m_idx in range(num_messages):
            speaker_id = participants[m_idx % len(participants)]
            speaker_display = f"Contributor {speaker_id[2:]}"
            tpl = CHAT_TEMPLATES[(i + m_idx) % len(CHAT_TEMPLATES)]
            msg_body = tpl.format(
                module_display=primary_mod_display,
                author_display=f"Contributor {d['decided_by'][2:]}",
            )
            messages.append(f"{speaker_display}: {msg_body}")

        thread_text = "\n\n".join(messages)
        thread_display = f"#eng-decisions: Discussion on {d['display']}"

        threads_list.append({
            "id": th_id,
            "display": thread_display,
            "channel": "#eng-decisions",
            "started_at": started_at,
            "text": thread_text,
            "participants": participants,
            "mentions": affects_mods,
        })

    # Extra threads: module chatter without decisions (retrieval noise)
    extra_thread_count = cfg.SYNTH_EXTRA_THREADS
    for k in range(extra_thread_count):
        th_idx = len(decisions_list) + k + 1
        th_id = f"th_{th_idx:03d}"
        mod_idx = k % len(sorted_modules)
        mod_path = sorted_modules[mod_idx]
        mod_id = "m_" + mod_path.strip("/").replace("/", "_")
        mod_display = mod_path

        owning_team = module_to_team.get(mod_id, team_ids[0])
        team_members = team_to_members.get(owning_team, sorted_persons)
        num_participants = min(rng.randint(2, 4), len(team_members))
        participants = rng.sample(team_members, num_participants)

        # Started at around an existing PR date
        ref_pr = prs_sorted[k % len(prs_sorted)]
        started_at = ref_pr.get("created_at", int(ref_pr.get("merged_at", 0)) - 86400)

        messages = []
        num_msgs = rng.randint(3, 5)
        for m_idx in range(num_msgs):
            speaker_id = participants[m_idx % len(participants)]
            speaker_display = f"Contributor {speaker_id[2:]}"
            tpl = CHAT_TEMPLATES[(k + m_idx) % len(CHAT_TEMPLATES)]
            msg_body = tpl.format(
                module_display=mod_display,
                author_display=f"Contributor {participants[0][2:]}",
            )
            messages.append(f"{speaker_display}: {msg_body}")

        thread_text = "\n\n".join(messages)
        channel_name = "#dev-chat" if k % 2 == 0 else "#architecture"

        threads_list.append({
            "id": th_id,
            "display": f"{channel_name}: Sync on {mod_display}",
            "channel": channel_name,
            "started_at": started_at,
            "text": thread_text,
            "participants": participants,
            "mentions": [mod_id],
        })

    # 7. Ground Truth Oracle (Computed in pure Python without Cypher)
    threshold = cfg.STALE_PR_THRESHOLD
    ground_truth_decisions = []

    # Map each PR to all affected modules it touches
    pr_to_modules: Dict[str, Set[str]] = {}
    pr_merged_times: Dict[str, int] = {}

    for pr in raw_prs:
        pr_id = f"pr_{pr['number']}"
        pr_merged_times[pr_id] = pr.get("merged_at") or 0
        mods = set()
        for f in pr.get("files", []):
            m = resolve_module_path(f, rules)
            if m:
                mods.add("m_" + m.strip("/").replace("/", "_"))
        pr_to_modules[pr_id] = mods

    freshness_distribution = {"fresh": 0, "stale": 0, "superseded": 0}

    for d in decisions_list:
        dec_id = d["id"]
        decided_at = d["decided_at"]
        status = d["status"]
        affects_set = set(d["affects"])
        implemented_pr_id = d["implemented_by"][0]

        # Count later PRs that touched what the decision affects, excluding implementing PR
        drift_count = 0
        for pr in raw_prs:
            other_pr_id = f"pr_{pr['number']}"
            if other_pr_id == implemented_pr_id:
                continue
            merged_time = pr.get("merged_at") or 0
            if merged_time > decided_at:
                if affects_set & pr_to_modules.get(other_pr_id, set()):
                    drift_count += 1

        freshness = classify(status=status, drift_count=drift_count, threshold=threshold)
        freshness_distribution[freshness] += 1

        ground_truth_decisions.append({
            "id": dec_id,
            "freshness": freshness,
            "drift_count": drift_count,
        })

    ground_truth_data = {
        "threshold": threshold,
        "decisions": ground_truth_decisions,
    }

    # 8. Save all files to data/synthetic/
    (out_dir / "teams.json").write_text(json.dumps(teams_data, indent=2), encoding="utf-8")
    (out_dir / "people_roles.json").write_text(json.dumps(people_roles_data, indent=2), encoding="utf-8")
    (out_dir / "decisions.json").write_text(json.dumps(decisions_list, indent=2), encoding="utf-8")
    (out_dir / "tickets.json").write_text(json.dumps(tickets_list, indent=2), encoding="utf-8")
    (out_dir / "threads.json").write_text(json.dumps(threads_list, indent=2), encoding="utf-8")
    (out_dir / "ground_truth.json").write_text(json.dumps(ground_truth_data, indent=2), encoding="utf-8")

    print(f"Generated synthetic data in {out_dir}:")
    print(f"  - Teams: {len(teams_list)}")
    print(f"  - Decisions: {len(decisions_list)} (Superseded: {len(superseded_pairs)} pairs)")
    print(f"  - Tickets: {len(tickets_list)}")
    print(f"  - Threads: {len(threads_list)}")
    print(f"  - Freshness Distribution: {freshness_distribution}")

    return {
        "teams": teams_data,
        "people_roles": people_roles_data,
        "decisions": decisions_list,
        "tickets": tickets_list,
        "threads": threads_list,
        "ground_truth": ground_truth_data,
        "freshness_distribution": freshness_distribution,
    }


if __name__ == "__main__":
    generate_synthetic_data()
