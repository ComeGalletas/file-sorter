# Pipeline and dry run — journal

**ID:** PIPE-001 (+ CLI-002) · **Systems:** PIPE, CLI (+ FOP) · **Type:** feature · **Status:** proposed · **Milestone:** m1 ·
**Issues:** #17, #18 · **Branch:** per task, named by agent-office (`office/*`)

<!--
Rules: CLAUDE.md §1 (DOC-001). Public repo: never write image file names, captions,
references or host paths here. Use hashes.
-->

---

## PIPE-001 — Requirement (DESIGN.md M1, 2026-10-06)

- **Objective:** Build the batch graph skeleton that runs the pipeline's nodes in order over the ledger, with the ingest node wired in.
- **Details:**
  - A LangGraph graph of batch nodes (R-PIPE-1). Each node selects its files by ledger `status`, so a crashed run resumes where it stopped (P-4).
  - In M1 the only node is `ingest`. Later milestones add `sanitize → classify → caption → retrieve → name → fileops` in that order (DESIGN.md §3, C-7).
  - A `dry_run` flag runs every node except `fileops` (R-PIPE-2). In M1, `fileops` doesn't exist yet.
  - Each run returns summary counts per node.
- **Constraint:**
  - Nodes are idempotent: re-running a node on a file already past it is a no-op.
  - No model is loaded in M1.
- **Implements:** R-PIPE-1, R-PIPE-2 (partly, see PIPE-001.D1), P-4, DESIGN.md §3.

## PIPE-001 — Confirmed reading

- `langgraph>=0.6` is already a dependency. The CLI is a Typer app in `classifier/cli/__init__.py`, with `version` and `--version` (CLI-001).
- C-8 settles the conflict between per-file flow and per-stage batching: batch nodes with the ledger as checkpoint, and `fileops` per file.
- **PIPE-001.D1** — **Open, for the human:** what `dry-run` ends at in M1.
  - R-PIPE-2 says a dry run "ends at status `proposed`" and writes `source → proposed output`. In M1 there is no naming step, so there is no proposed output.
  - Options:
    1. **(Recommended)** Rows stay at the last status a node set (`queued` or `skipped`), and the CSV's proposed-output column stays empty. `proposed` starts once `name` exists (M5).
    2. Mark every ingested row `proposed` now. That would make later milestones skip those rows, because nodes select by status.

## PIPE-001 — Plan

1. `classifier/graph/`: the state type (run id, batch of hashes, counts), node registration in §3 order, a status-driven batch selector, and `run(config, dry_run)`.
2. Integration test: a folder of synthetic images. Run it twice. The second run selects nothing new and reports every file as skipped-known. The ledger row count is unchanged.

## PIPE-001 — Tasks

- [ ] PIPE-001.1 — Batch graph skeleton with the ingest node and dry-run mode · #17 · acceptance: `tests/integration/test_dry_run_graph.py`

## PIPE-001 — Results

### PIPE-001.1 (worker: pipeline)

- **Status:**
- **Triage:**
- **Tests:**
- **Self-rating:**
- **Review:**
- **Deferred:**

---

## CLI-002 — Requirement (DESIGN.md M1, 2026-10-06)

- **Objective:** Add `classifier dry-run [--csv]`, which runs the pipeline over `source_root` without filing anything and reports what it saw.
- **Details:**
  - It loads the config (CFG-001), runs the root check (R-FOP-9), then runs the graph with `dry_run=True` (PIPE-001).
  - It prints counts: new, skipped-known, skipped (by reason), duplicates.
  - `--csv` writes `results_root/reports/dry-run-<run timestamp>.csv`. The columns are `source_hash`, `short_hash`, `status`, `reason` and `proposed_output` (empty in M1, PIPE-001.D1). A `source_path` column is included only if ING-001.D2 allows it.
  - The exit code is 0 on success, and non-zero on a config or root-check failure.
- **Constraint:**
  - Nothing is written under `source_root`. Under `results_root` it writes only `reports/`; the category folders don't exist before M7 (CLAUDE.md "Milestone gates").
  - Console output and logs carry hashes, not names.
- **Implements:** R-PIPE-2, DESIGN.md §7 (`dry-run [--csv]`), R-FOP-9.

## CLI-002 — Confirmed reading

- DESIGN.md §7 lists `dry-run [--csv]`.
- The `app` service runs `sleep infinity` "until M1 adds real commands" (RUN-001.D11). The command runs with `docker compose run --rm app classifier dry-run`. Changing the service's default command isn't needed in M1.
- The `test` profile has no `/source` mount (RUN-001.D6), so tests point the command at a temporary folder through the config.

## CLI-002 — Plan

1. Add the `dry-run` command to `classifier/cli/__init__.py`, calling `graph.run(config, dry_run=True)`, with a CSV writer.
2. Integration test: invoke it through Typer's `CliRunner` on a temporary folder of synthetic images, with a temporary `results_root`. Check the counts, the CSV header and rows, that nothing exists in `results_root` except `reports/`, and that a second invocation reports every file as skipped-known.

## CLI-002 — Tasks

- [ ] CLI-002.1 — `classifier dry-run [--csv]` · #18 · acceptance: `tests/integration/test_dry_run_cli.py`

## CLI-002 — Results

### CLI-002.1 (worker: pipeline)

- **Status:**
- **Triage:**
- **Tests:**
- **Self-rating:**
- **Review:**
- **Deferred:**
