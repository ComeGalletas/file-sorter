# Harness dry run — journal

**ID:** CLI-001 · **Systems:** CLI (+ TST, RUN) · **Type:** feature, process · **Status:** proposed · **Milestone:** — (runbook step 6) ·
**Issues:** opened after the plan PR merges · **Branch:** per task, named by agent-office (`office/*`)

<!--
Rules: CLAUDE.md §1 (DOC-001). Public repo: never write image file names, captions,
references or host paths here. Use hashes.
-->

This is runbook step 6 (docs/PLAN.md, "Harness dry run"): one trivial task that must flow end to end, and one task whose test is designed to fail so the pre-push gate must reject it. It is not a milestone, so there is no `docs/plans/mN.md`. It closes the live-session checks that RUN-002 and RUN-003 left open.

---

## CLI-001 — Requirement (human, 2026-10-05)

- **Objective:** Make `classifier --version` print the package version.
- **Details:**
  - An eager `--version` option on the Typer app callback in `classifier/cli/`, printing `classifier.__version__` and exiting 0.
  - Acceptance test: `tests/unit/cli/test_version_option.py` (tier `unit`).
  - Owner role: pipeline (owns `classifier/cli/`); the test file is the pipeline worker's acceptance test for this dry run.
- **Constraint:** The existing `classifier version` subcommand and its test (`tests/unit/test_smoke.py`) keep working. No other CLI change.
- **Implements:** no R-CLI spec ID exists; it exercises the DESIGN.md §7 CLI surface and the C-17 gate (pre-push is the hard block).

## CLI-001 — Confirmed reading

- `classifier/__init__.py` holds `__version__ = "0.0.1"`, matching `pyproject.toml`. `classifier/cli/__init__.py` already has a `version` **subcommand** but no `--version` **option**: the requirement is new behavior, not a duplicate.
- `tests/conftest.py` tiers by first path segment, so `tests/unit/cli/` is `unit`.
- **CLI-001.D1** — `--version` is an eager callback option (`is_eager=True`) that prints and raises `typer.Exit()`, so it works without a subcommand despite `no_args_is_help=True` (lead, 2026-10-05). It is the idiomatic Typer form.
- **CLI-001.D2** — The `version` subcommand stays; removing it is out of scope (lead, 2026-10-05).

## CLI-001 — Plan

1. Add the `--version` option to the app callback in `classifier/cli/__init__.py`.
2. Add `tests/unit/cli/test_version_option.py`: `CliRunner().invoke(app, ["--version"])` exits 0 and its stdout is exactly `classifier.__version__`.
3. Push through the pre-push gate (default tiers + acceptance), open the PR, Reviewer and Privacy auditor, lead merges.

## CLI-001 — Tasks

- [x] CLI-001.1 — `classifier --version` prints the package version · #2 (pipeline) · acceptance: `tests/unit/cli/test_version_option.py`
  - [x] CLI-001.1.1 — eager `--version` callback option + acceptance test (hash in Results)

## CLI-001 — Results

### CLI-001.1 (worker: pipeline)

- **Status:** DONE
- **Triage:** medium: a behavior change inside one package (lead corrected it from small on #2). Tiers: unit + lint; the pre-push gate runs the default tiers and the acceptance test. Solo.
- **Tests:** `make test`: 5 passed (unit 4, db 1; no integration tests exist yet), including the acceptance test `tests/unit/cli/test_version_option.py` (2 passed) and `tests/unit/test_smoke.py` (2 passed, CLI-001.D2). `make lint`: clean. In the container, the installed entry point `classifier --version` printed the version and exited 0.
- **Self-rating:** pass 1: 9/10, proud: yes. Gap (−1): the test pins `--version` on its own but not when it is combined with a subcommand (e.g. `--version version` should print once and exit). The acceptance test doesn't require that and Click's eager handling covers it, so I left it out rather than widen the scope. No second pass needed.
- **Review:**
- **Deferred:** none.

---

## TST-001 — Requirement (human, 2026-10-05)

- **Objective:** Prove the pre-push gate blocks a branch whose tests fail.
- **Details:**
  - Add `tests/unit/test_harness_probe.py`, a deliberately failing test (tier `unit`), and name it as the acceptance test in `.task`.
  - Push the branch. The expected result is a **blocked** push (`pre-push BLOCKED: default test tiers failed`), with no remote branch and no PR.
  - Owner role: qa (owns `tests/`).
- **Constraint:** The probe **must never be fixed, skipped or merged**. The task is complete when the push is rejected, not when the test is green. No `--no-verify`.
- **Implements:** C-17 (DESIGN.md §13: pre-push runs the full suite + gate and is the hard block), RUN-002 (pre-push gate).

## TST-001 — Confirmed reading

- `.githooks/pre-push` runs the default tiers before the acceptance test, so a failing `unit` test is caught at step 4 and the acceptance step never runs. Either way the push exits non-zero.
- The worker's `Stop` hook also runs touched tests and will report the failure. That is expected; the worker does not "fix" it.
- **TST-001.D1** — Success is the rejected push. The worker records the hook's output in Results and in its job log, and leaves the issue **open** (runbook step 6: "one open issue whose PR could not be pushed") (lead, 2026-10-05).
- **TST-001.D2** — The probe's assertion fails plainly (e.g. `assert False, "harness probe: must fail"`), not through an error or a missing prerequisite, so the failure is unambiguous (lead, 2026-10-05).
- **TST-001.D3** — After the dry run the branch and worktree are discarded with `send_home`; the probe never reaches `main` (lead, 2026-10-05).

## TST-001 — Plan

1. Add the failing probe in `tests/unit/test_harness_probe.py`; commit it locally.
2. `git push -u origin HEAD`; confirm the gate blocks it and the remote has no such branch.
3. Report the blocked push on the issue (status BLOCKED by design, label `blocked`).

## TST-001 — Tasks

- [ ] TST-001.1 — Deliberately failing probe test; the push must be rejected · issue (qa) · acceptance: `tests/unit/test_harness_probe.py` (expected to fail)

## TST-001 — Results

### TST-001.1 (worker: qa)

- **Status:**
- **Triage:**
- **Gate output:**
- **Self-rating:**
- **Review:** none expected (no PR can exist)
