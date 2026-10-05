# Process standard — journal

**ID:** DOC-001 · **Systems:** DOC (+ TST) · **Type:** process · **Status:** done · **Milestone:** — ·
**Issues:** — (pre-repo) · **Branch:** pre-repo, committed at bootstrap

---

## DOC-001 — Requirement (human, 2026-10-05)

- **Objective:** Adopt the human's pygame project conventions for development, indexes, journals, IDs, commits and testing in this project.
- **Details:** Review that project's CLAUDE.md, map each convention onto file-sorter's design, and write it into CLAUDE.md, DESIGN.md and `docs/`.
- **Constraint:**
  - PRs keep this project's already configured flow: agent-office issues and PRs, hooks, and the lead's allow/deny permissions.
  - Confirm the mapping with the human before writing.
- **Implements:** DESIGN.md §12 (process).

## DOC-001 — Confirmed reading

- **DOC-001.D1:** The conventions come from pygame commit `7c72ca4`, the last full CLAUDE.md. That project's `main` CLAUDE.md lost its process section in `ddd4677`, and `58fdf16` restored only fragments, so HEAD is not a usable source. A separate repair task was suggested for that repo.
- **DOC-001.D2:** Work IDs `<SYS>-<NNN>` are separate from DESIGN.md's spec IDs `R-<SYS>-<n>`. Work items cite the spec IDs they implement. (human, 2026-10-05)
- **DOC-001.D3:** The system codes are DESIGN.md's spec prefixes (ING, SAN, CLS, CAP, RAG, NAME, FOP, API, MOD, PIPE, CFG, RUN), plus DB, CLI, TST and DOC.
- **DOC-001.D4:** A task is one GitHub issue, one worktree and one PR. A subtask is one commit. Decisions are `.Dn`.
- **DOC-001.D5:** Journals in `docs/journals/` replace the plan's `docs/tasks/<id>.md`. The lead owns `docs/` and the index. A worker edits only its own task lines and Results subsection, so parallel PRs don't conflict.
- **DOC-001.D6:** This project's PR flow, hooks (C-17) and lead allow/deny rules (C-16) win over the pygame rules "no CI, hooks or gates" and "PRs only when asked". (human, 2026-10-05)
- **DOC-001.D7:** There is no "worktree or current branch?" question, because workers always get a worktree. Branches are named `<task-id>-<slug>`, or keep agent-office's name if it assigns one.
- **DOC-001.D8:** Test tiers are assigned by path: `unit`, `db`, `integration`, `gpu`, `gate`. A tier audit catches mis-tiered tests. Tests never skip themselves to green. Seeds are pinned, recorded model responses replace live calls outside `gpu`, and expensive fixtures are shared.
- **DOC-001.D9:** The test-runner history lives in `$AGENT_LOG_ROOT/qa/test-history.md`, local only and not in the public repo.
- **DOC-001.D10:** The template's triage block, completion status and self-rating loop are adopted. Its talk-style rules and its fan-out/critic tournament are not. (human, 2026-10-05)
- **DOC-001.D11:** The pygame DOC-002 rule (hand-tuned `data/` values: flag and ask) maps to `config.yaml` thresholds, `prompts/`, and category and template seeds.
- **DOC-001.D12:** PRs merge with a merge commit (`gh pr merge --merge`), so each subtask's ID stays searchable in `main`'s history.

## DOC-001 — Plan

- **CLAUDE.md:** §1 process standard, §2 working a task (triage, workflow, completion status, self-rating), §3 tests, plus the ownership update (the lead owns `docs/`).
- **DESIGN.md:** the §10 layout and §12 process summary.
- **New files:** `docs/journals/INDEX.md`, `docs/journals/TEMPLATE.md`, `docs/plans/TEMPLATE.md`.
- **Backfill:** this session's earlier work as DOC-002 and DOC-003.

## DOC-001 — Tasks

- [x] DOC-001.1 — Review the pygame conventions (CLAUDE.md history, INDEX.md, journals, commits, pytest tiers, settings, test-runner agent) → `pre-repo`
- [x] DOC-001.2 — Write the process standard, triage, status, self-rating and test sections into CLAUDE.md → `pre-repo`
- [x] DOC-001.3 — Update the DESIGN.md §10 layout and §12 process summary → `pre-repo`
- [x] DOC-001.4 — Add the index, journal template and milestone plan template → `pre-repo`
- [x] DOC-001.5 — Backfill DOC-002 and DOC-003 journals and index rows → `pre-repo`

## DOC-001 — Results

- **Status:** DONE.
- **Triage:** medium (docs only, several files, process contract) · no tests (no code exists yet) · solo.
- **Tests:** none applicable before bootstrap. The tiers, the tier audit and the test-runner agent are built in M1 by QA.
- **Self-rating:** 8/10, proud: yes. Gaps:
  - Branch naming depends on how agent-office names worktree branches, which is unverified until setup step 5.
  - Hook scripts that enforce the tiers don't exist yet (bootstrap step 4).
- **Deferred:** `.claude/agents/test-runner.md`, `tests/conftest.py` tier mapping and `tests/devtools/test_tier_audit.py`, all built in M1 bootstrap tasks (TST).
