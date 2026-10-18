"""Ingestion and graph verification gate.

Per ARCHITECTURE.md sections 7, 8, 10, 19:
- Node and edge counts verification against defined minimums.
- Numeric minimums defined in a single constants block with documentation note.
- Decision freshness verification: compares query Q09 + freshness.classify()
  with ground_truth.json oracle for every decision.
- Freshness distribution assertion: fails unless there are at least 3 stale,
  3 fresh, and 1 superseded decision.
- PII rescan of all stored text properties across nodes in the database:
    PR (display, body_excerpt)
    Doc (body)
    Thread (text)
    Ticket (description)
    Decision (summary, rationale)
- Exit 0 on PASS; raises AssertionError or exits 1 on failure.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from brain_core import queries
from brain_core.config import get_ingest_settings
from brain_core.db import get_graph
from brain_core.freshness import classify
from ingest.loaders import print_counts_table
from ingest.scrub import scan_for_pii

# ==============================================================================
# NUMERIC VERIFICATION MINIMUMS
# Note: Defined as per ARCHITECTURE.md Section 19 (Task B3 verification gate).
# Any change to these minimums must be documented in docs/decisions.md.
# ==============================================================================
MIN_TEAMS = 4
MIN_TICKETS = 22
MIN_THREADS = 24
MIN_PRS = 100
MIN_PERSONS = 15
MIN_MODULES = 8
MIN_DOCS = 20

MIN_FRESH_DECISIONS = 3
MIN_STALE_DECISIONS = 3
MIN_SUPERSEDED_DECISIONS = 1
# ==============================================================================


def verify_counts(graph: Any, expected_decisions: int) -> Dict[str, Dict[str, int]]:
    """Assert minimum node counts per label and edge counts per type."""
    print("Verifying graph entity and relationship counts...", flush=True)
    counts = print_counts_table(graph)
    nodes = counts["nodes"]
    edges = counts["edges"]

    teams_count = nodes.get("Team", 0)
    decisions_count = nodes.get("Decision", 0)
    tickets_count = nodes.get("Ticket", 0)
    threads_count = nodes.get("Thread", 0)
    prs_count = nodes.get("PR", 0)
    persons_count = nodes.get("Person", 0)
    modules_count = nodes.get("Module", 0)
    docs_count = nodes.get("Doc", 0)

    errors = []
    if teams_count < MIN_TEAMS:
        errors.append(f"Team count {teams_count} < required minimum {MIN_TEAMS}")
    if decisions_count != expected_decisions:
        errors.append(f"Decision count {decisions_count} != required SYNTH_DECISIONS {expected_decisions}")
    if tickets_count < MIN_TICKETS:
        errors.append(f"Ticket count {tickets_count} < required minimum {MIN_TICKETS}")
    if threads_count < MIN_THREADS:
        errors.append(f"Thread count {threads_count} < required minimum {MIN_THREADS}")
    if prs_count < MIN_PRS:
        errors.append(f"PR count {prs_count} < required minimum {MIN_PRS}")
    if persons_count < MIN_PERSONS:
        errors.append(f"Person count {persons_count} < required minimum {MIN_PERSONS}")
    if modules_count < MIN_MODULES:
        errors.append(f"Module count {modules_count} < required minimum {MIN_MODULES}")
    if docs_count < MIN_DOCS:
        errors.append(f"Doc count {docs_count} < required minimum {MIN_DOCS}")

    # Check key relationship types exist
    required_edges = [
        "AUTHORED", "TOUCHES", "PART_OF", "MEMBER_OF", "OWNS",
        "PARTICIPATED_IN", "ASSIGNED_TO", "RESOLVES", "DECIDED_BY",
        "AFFECTS", "IMPLEMENTS", "DISCUSSED_IN", "TRACKED_BY",
        "SUPERSEDED_BY", "MENTIONS", "COLLABORATES_WITH",
    ]
    for edge_name in required_edges:
        if edges.get(edge_name, 0) == 0:
            errors.append(f"Missing required relationship type in graph: {edge_name}")

    if errors:
        print("\nCOUNT VERIFICATION FAILURES:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        raise AssertionError("Count verification failed.\n" + "\n".join(errors))

    print("Counts verification PASSED.", flush=True)
    return counts


def verify_freshness(
    graph: Any,
    synthetic_dir: Optional[Path] = None,
    threshold: Optional[int] = None,
) -> Dict[str, int]:
    """Verify Q09 query output matches ground_truth.json oracle and assert distribution."""
    print("Verifying decision freshness against ground_truth.json oracle...", flush=True)
    base_dir = synthetic_dir or (Path(__file__).resolve().parent.parent.parent / "data" / "synthetic")
    gt_file = base_dir / "ground_truth.json"

    if not gt_file.exists():
        raise FileNotFoundError(f"ground_truth.json oracle not found in {base_dir}. Run 'python -m ingest synth' first.")

    gt_data = json.loads(gt_file.read_text(encoding="utf-8"))
    gt_threshold = threshold if threshold is not None else gt_data.get("threshold", 1)
    gt_decisions = {d["id"]: d for d in gt_data["decisions"]}

    # Execute Q09 Cypher query on FalkorDB
    q09_res = graph.query(queries.Q09)
    # Columns: id, title, decided_at, status, drift_count, latest, decider, module_ids
    q09_decisions = {}
    for row in q09_res.result_set:
        d_id = row[0]
        title = row[1]
        decided_at = row[2]
        status = row[3]
        drift_count = int(row[4] or 0)
        q09_decisions[d_id] = {
            "id": d_id,
            "status": status,
            "drift_count": drift_count,
        }

    freshness_distribution = {"fresh": 0, "stale": 0, "superseded": 0}
    mismatches = []

    for d_id, gt_entry in gt_decisions.items():
        if d_id not in q09_decisions:
            mismatches.append(f"Decision {d_id} in ground_truth.json not found in Q09 graph results.")
            continue

        q09_entry = q09_decisions[d_id]
        status = q09_entry["status"]
        drift_count = q09_entry["drift_count"]

        # Classify via brain_core.freshness.classify
        computed_freshness = classify(status=status, drift_count=drift_count, threshold=gt_threshold)
        freshness_distribution[computed_freshness] += 1

        expected_freshness = gt_entry["freshness"]
        expected_drift = gt_entry["drift_count"]

        if drift_count != expected_drift or computed_freshness != expected_freshness:
            mismatches.append(
                f"Decision {d_id} mismatch: Graph has (drift={drift_count}, freshness={computed_freshness}), "
                f"Oracle expected (drift={expected_drift}, freshness={expected_freshness})"
            )

    print(f"\nFreshness Distribution: {freshness_distribution}")
    for f_state, f_count in sorted(freshness_distribution.items()):
        print(f"  {f_state:<12} : {f_count}")

    if mismatches:
        print("\nFRESHNESS ORACLE MISMATCHES:", file=sys.stderr)
        for mm in mismatches:
            print(f"  - {mm}", file=sys.stderr)
        raise AssertionError("Decision freshness oracle comparison failed.\n" + "\n".join(mismatches))

    # Assert minimum distribution requirements
    dist_errors = []
    if freshness_distribution["fresh"] < MIN_FRESH_DECISIONS:
        dist_errors.append(
            f"Fresh decisions {freshness_distribution['fresh']} < required minimum {MIN_FRESH_DECISIONS}"
        )
    if freshness_distribution["stale"] < MIN_STALE_DECISIONS:
        dist_errors.append(
            f"Stale decisions {freshness_distribution['stale']} < required minimum {MIN_STALE_DECISIONS}"
        )
    if freshness_distribution["superseded"] < MIN_SUPERSEDED_DECISIONS:
        dist_errors.append(
            f"Superseded decisions {freshness_distribution['superseded']} < required minimum {MIN_SUPERSEDED_DECISIONS}"
        )

    if dist_errors:
        print("\nFRESHNESS DISTRIBUTION REQUIREMENT FAILED:", file=sys.stderr)
        for err in dist_errors:
            print(f"  - {err}", file=sys.stderr)
        print(
            "Note per ARCHITECTURE.md: Change SYNTH_SEED or SYNTH_DECISIONS in .env.example defaults, rerun, and record in docs/decisions.md.",
            file=sys.stderr,
        )
        raise AssertionError("Freshness distribution verification failed.\n" + "\n".join(dist_errors))

    print("Decision freshness and ground_truth oracle comparison PASSED.", flush=True)
    return freshness_distribution


def verify_pii_scan(graph: Any) -> None:
    """Scan stored text properties in graph for PII patterns (email, @mentions, profile URLs, trailers)."""
    print("Running PII pattern verification scan on graph text properties...", flush=True)

    violations = []

    # 1. PR (display, body_excerpt)
    pr_res = graph.query("MATCH (pr:PR) RETURN pr.id, pr.display, pr.body_excerpt")
    for row in pr_res.result_set:
        pr_id, display, body = row[0], row[1] or "", row[2] or ""
        v1 = scan_for_pii(display)
        v2 = scan_for_pii(body)
        if v1: violations.append(f"PR {pr_id} display: {v1}")
        if v2: violations.append(f"PR {pr_id} body_excerpt: {v2}")

    # 2. Doc (body)
    doc_res = graph.query("MATCH (d:Doc) RETURN d.id, d.body")
    for row in doc_res.result_set:
        d_id, body = row[0], row[1] or ""
        v = scan_for_pii(body)
        if v: violations.append(f"Doc {d_id} body: {v}")

    # 3. Thread (text)
    th_res = graph.query("MATCH (th:Thread) RETURN th.id, th.text")
    for row in th_res.result_set:
        th_id, text = row[0], row[1] or ""
        v = scan_for_pii(text)
        if v: violations.append(f"Thread {th_id} text: {v}")

    # 4. Ticket (description)
    tk_res = graph.query("MATCH (tk:Ticket) RETURN tk.id, tk.description")
    for row in tk_res.result_set:
        tk_id, desc = row[0], row[1] or ""
        v = scan_for_pii(desc)
        if v: violations.append(f"Ticket {tk_id} description: {v}")

    # 5. Decision (summary, rationale)
    dec_res = graph.query("MATCH (d:Decision) RETURN d.id, d.summary, d.rationale")
    for row in dec_res.result_set:
        d_id, summary, rationale = row[0], row[1] or "", row[2] or ""
        v1 = scan_for_pii(summary)
        v2 = scan_for_pii(rationale)
        if v1: violations.append(f"Decision {d_id} summary: {v1}")
        if v2: violations.append(f"Decision {d_id} rationale: {v2}")

    if violations:
        print("\nPII SCAN VIOLATIONS DETECTED IN GRAPH:", file=sys.stderr)
        for v in violations[:10]:
            print(f"  - {v}", file=sys.stderr)
        raise AssertionError(f"PII pattern verification failed with {len(violations)} violations.")

    print("PII scan PASSED: Zero emails, mentions, profile URLs, or trailers found in stored graph text.", flush=True)


def run_verify(
    graph: Optional[Any] = None,
    synthetic_dir: Optional[Path] = None,
    settings: Optional[Any] = None,
) -> bool:
    """Execute all verification gates.

    Order:
    1. verify_counts() against defined minimums
    2. verify_freshness() against ground_truth.json
    3. verify_pii_scan() on all stored node text
    """
    target_graph = graph if graph is not None else get_graph()
    cfg = settings or get_ingest_settings()

    print("\n=============================================")
    print("RUNNING INGESTION VERIFICATION GATES")
    print("=============================================", flush=True)

    verify_counts(target_graph, expected_decisions=cfg.SYNTH_DECISIONS)
    verify_freshness(target_graph, synthetic_dir=synthetic_dir, threshold=cfg.STALE_PR_THRESHOLD)
    verify_pii_scan(target_graph)

    print("\n=============================================")
    print("ALL VERIFICATION GATES PASSED (EXIT 0)")
    print("=============================================\n", flush=True)
    return True


if __name__ == "__main__":
    try:
        run_verify()
        sys.exit(0)
    except Exception as exc:
        print(f"\nFATAL: Verification failed: {exc}", file=sys.stderr)
        sys.exit(1)
