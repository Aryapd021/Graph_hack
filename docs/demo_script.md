# Company Brain — Hackathon Demo Script & Video Recording Guide

This document provides the exact step-by-step walkthrough for demonstrating **Company Brain (Track 03)** during video recording and judge evaluation.

---

## 🎬 5-Minute Demo Flow

### Step 1: Decision Provenance & Rationale Tracing
- **Prompt:**
  ```text
  Why did we decide Implement structured request lifecycle telemetry in tests?
  ```
- **What happens:**
  1. The agent invokes `search_knowledge` to locate the decision, then `trace_decision` and `get_decision`.
  2. The answer cites the exact historical rationale: distributed tracing was incomplete without module-level span boundaries, causing delays in root-cause analysis.
  3. Every factual sentence terminates in an evidence chip: `[[dec_004]]`.
  4. In the central canvas, the **Cytoscape graph automatically highlights** the decision node (`dec_004`) and its connected PRs, tickets, and affected modules (`m_fastapi`, `m_tests`).
  5. The right sidebar switches to the **Trace** tab, showing each MCP tool round, cypher queries executed (`Q05`, `Q06`, `Q08`), and execution durations in milliseconds.

---

### Step 2: Live Freshness & Architectural Drift Check
- **Prompt:**
  ```text
  Is that decision still valid? Implement structured request lifecycle telemetry in tests
  ```
- **What happens:**
  1. The agent invokes `check_decision_freshness(decision_id="dec_004")`.
  2. Rather than relying on a static boolean, FalkorDB evaluates `Q08` to count all subsequent merged PRs that touched the affected modules after the decision date.
  3. The agent reports that the decision is **stale** with **81 drifting code changes**.

---

### Step 3: Interactive Decision Drift Simulation
- **Action:**
  1. Switch to the **Decisions** tab in the right inspector. Notice decision `dec_006` (**"Introduce formal state machine validation for background tasks"**) is currently **`fresh`** (drift count: 0).
  2. In the top navigation bar, click **Simulate PR**.
  3. Select Target Module: `m_tests_benchmarks` (the module affected by `dec_006`).
  4. Keep the title: `"Simulate benchmark update"`.
  5. Click **Simulate Merge**.
- **What happens:**
  1. The backend creates a synthetic merged PR touching that module and recalculates drift dynamically.
  2. A toast notification pops up: `PR pr_900000 merged! Drift updated: dec_006: fresh ➔ stale`.
  3. In the Decisions board, `dec_006` immediately shifts to an amber **`stale`** badge.

---

### Step 4: Flag Decision for Review
- **Action:**
  1. Click the **Flag** button on `dec_006` (or in chat prompt: `"Flag dec_006 for review"`).
  2. Enter note: `"Simulated PR introduced architectural drift in test benchmarks; lead review required."`.
  3. Click **Create Review Request**.
- **What happens:**
  1. Tool `flag_for_review` executes `Q15a-c`, creating a `ReviewRequest` node and linking it via `[:REVIEWS]` to `dec_006` and `[:ASSIGNED_TO]` to the original authoring decider.
  2. Switch to the **Reviews** tab: the new review request appears assigned to the decider.

---

### Step 5: Proof of FalkorDB Dependency (Test T5)
- **Action:**
  1. In terminal, stop the FalkorDB Docker container:
     ```bash
     docker compose stop falkordb
     ```
  2. Send any chat question or refresh the browser.
- **What happens:**
  1. The top bar displays a persistent red alert banner:  
     `FalkorDB Graph Engine is unavailable (503 GRAPH_UNAVAILABLE). The knowledge graph is offline.`
  2. Health check reports `status: "degraded", falkordb: false`.
  3. All data queries return `503 GRAPH_UNAVAILABLE`.
  4. In terminal, run:
     ```bash
     pytest backend/tests/test_t5_degradation.py -v
     ```
     Result: **100% PASSED**.
  5. Restart FalkorDB:
     ```bash
     docker compose start falkordb
     ```
     The system immediately recovers to healthy status.
