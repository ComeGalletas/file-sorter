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

---

## DOC-004 — Requirement (human, 2026-10-06)

**Objective:** settle the three ownership and storage rules the M1 G0 plan (PR #23) raised, before any M1 work is assigned.

**Details:**
- Who writes a task's acceptance and unit tests (TST-002.D1).
- Who owns the config loader at the package root (CFG-001.D1).
- Whether the ledger may store source paths before the M2 sanitizer exists (ING-001.D2).

**Constraint:** a rule change goes in its own PR, judged under `main`'s rules (RUN-007.D2). Human-side PR (RUN-002.D16), so the index row is the lead's to add (RUN-002.D13).

## DOC-004 — Confirmed reading

- **DOC-004.D1 (= TST-002.D1):** **The implementing worker writes its own task's tests**, in the same commit as the code, under `tests/<tier>/<package>/`. §3 already requires that every behavior change ships its test in the same commit; the roles table giving all of `tests/` to QA contradicted it. QA owns the shared test infrastructure (`tests/conftest.py`, `tests/devtools/`, `tests/recordings/`, `fixtures/`, `scripts/gate_*.py`) and reviews test quality. The role guard is location-based and needs no change. (human, 2026-10-06)
- **DOC-004.D2 (= CFG-001.D1):** **The config loader is `classifier/config.py`, owned by Pipeline.** The roles table had no owner for the package root. (human, 2026-10-06)
- **DOC-004.D3 (= ING-001.D2):** **The source path is the one stored exception to "no unsanitized filenames".** DESIGN.md §5 already puts `source_path` and `duplicate_paths` in the ledger, and the bot needs the path to read the original. The container path (`/source/...`) may be stored in the local ledger and in the local reports under `results_root/reports/`, and nowhere else. Logs, console and test output, issues, PRs and journals carry hashes only. P-2 is unchanged: no model sees the unsanitized filename. (human, 2026-10-06)
- The M1 plan's other answers stay in their own journals, recorded by the lead: PIPE-001.D1 (an M1 dry run ends at the last status a node set), ING-001.D1 (thumbnails move to M2) and TST-002.D2 (gate 1 ingests `fixtures/images/` twice against a fresh `db-test`). (human, 2026-10-06)

## DOC-004 — Tasks

- [x] DOC-004.1 — CLAUDE.md (the hard rule, the roles table, the line under it), DESIGN.md §12, and the QA, Pipeline and README desk briefs

## DOC-004 — Results

- **Status:** DONE.
- **Triage:** small. Rule text only, in docs and briefs, with no behavior change. The tests come from the pre-push gate.
- **Self-rating:** 9/10, proud: yes. Gap: ownership of `tests/` is now split by path and purpose rather than by one folder. The tier audit and the reviewer are what catch a worker editing shared infrastructure.

---

## DOC-005 — Requirement (human, 2026-10-06)

**Objective:** the public repo states nothing about the human's image folder or labels, aggregates included.

**Details:** PR #23's privacy audit failed two lead lines that gave a count and a file-type mix, and the lead found the same kind of text already on `main`: the target folder profile in DESIGN.md §1, the gate wording, and counts and distributions in four journals. None named or captioned an image, but the auditor reads the hard rule's "anything that describes the human's images" as covering aggregates, and `main` should meet the standard it enforces.

**Constraint:** a rule change in its own PR (RUN-007.D2); human-side (RUN-002.D16), so the index row is the lead's (RUN-002.D13). `main`'s history can't be rewritten (no force-push), so the removed text stays in the history.

## DOC-005 — Confirmed reading

- **DOC-005.D1:** **No aggregates about the human's folder or labels in the public repo**: no counts, sizes, file-type mix, content profile or label distributions. Gates are stated against `fixtures/labels.csv` ("every real image labelled"), not a number; the numbers live in the git-ignored files. CLAUDE.md's hard rule and the privacy auditor's check 4 now say so explicitly. (human, 2026-10-06)
- The design itself stays: the format and topic vocabularies, the decisions' rules and their example folder mappings describe the classifier, not the folder.

## DOC-005 — Tasks

- [x] DOC-005.1 — Rule text (CLAUDE.md, the privacy auditor's check 4); scrub DESIGN.md (§1 profile, `products` note, M3/M4 gates, Q-8) and the categories, design review, workspace and bootstrap journals
- [x] DOC-005.2 — Review round 1: the gate 3 and gate 5 stubs' docstrings and `CRITERION` strings (finding 1, missed because the first search skipped `*.py`); DESIGN.md §4.3's filename hint stated as the Windows default (finding 2)

## DOC-005 — Results

- **Status:** DONE.
- **Triage:** small. Docs, journals and one auditor-brief clause; no behavior change. Tests from the pre-push gate.
- **Check:** the first search skipped `*.py` and missed two gate stubs (review round 1, finding 1). The repeat search covers every tracked file, scripts included, and finds no count, size or profile of the human's folder. No test asserts a gate's `CRITERION` text. The only remaining numbers are the archived plan's own sample size in `docs/PLAN.md` (the original plan, not the human's folder) and model download sizes in `scripts/fetch_models.py`.
- **Self-rating:** 9/10, proud: yes. Gap: the old text remains in `main`'s public history; only a history rewrite would remove it, which the rules forbid.

---

## DOC-007 — Requirement (human, 2026-10-07)

**Objective:** carry the M2 G0 answers that change standing rules or the spec, in their own PR (RUN-007.D2), before the tasks that depend on them merge.

**Details:** the human accepted all nine decisions in `docs/plans/m2.md` (PR #59) as recommended. Four of them change CLAUDE.md, DESIGN.md or the runtime, which is human-side work (RUN-002.D16). The other five are the lead's to record in its journals: the backlog scope (CFG-002, TST-003 and TST-004 in M2, RUN-004 after M3), SAN-001.D6 (no `claude` backend or OCR in M2), SAN-001.D7 (working copies persist in `.work/`) and TST-005.D2 (gate 2's seeded names).

**Constraint:** human-side PR; the index row is the lead's (RUN-002.D13).

## DOC-007 — Confirmed reading

- **DOC-007.D1 (= ING-001.D2, option A):** **The source-path exception is permanent**, for the ledger and the local reports, with two limits from M2 on: no model ever receives the path or the raw file name, only `files.original_sanitized` (P-2); and the M4 API and UI show sanitized names and hashes, never `source_path`. The dry-run CSV keeps `source_path` beside a new `sanitized_name`. (human, 2026-10-07)
- **DOC-007.D2 (= SAN-001.D5):** **`sanitize_log.before_hash` is HMAC-SHA256** keyed with `SANITIZE_LOG_KEY`. `make init` generates the key into the local `.env`, `.env.example` names it, and compose passes it to the app and test containers (DESIGN.md R-SAN-6). A plain hash of a short value, such as a first name, could be reversed by hashing guesses. (human, 2026-10-07)
- **DOC-007.D3 (= SAN-001.D4):** **The ICC colour profile is kept**, with the file-structure tags (dimensions, encoding). Without it, wide-gamut images render with shifted colours (DESIGN.md R-SAN-2). (human, 2026-10-07)
- **DOC-007.D4 (= ING-002.D1):** **Thumbnails are `.work/thumbs/<source_hash>.webp`.** 8 hex chars collide on a big folder (DESIGN.md R-ING-5). (human, 2026-10-07)
- **DOC-007.D5 (= TST-005.D1):** **The worker whose task makes a recording commits it**, under `tests/recordings/<package>/`, from synthetic strings only. QA owns the recording format and the replay fixture, as DOC-004.D1 split the tests (CLAUDE.md §3, the roles table, and the QA and README briefs). (human, 2026-10-07)

## DOC-007 — Tasks

- [x] DOC-007.1 — CLAUDE.md (the exception, §3 recordings, the QA row), DESIGN.md (R-ING-5, R-SAN-2, R-SAN-6), the Makefile's `init`, `.env.example`, `docker-compose.yml`'s shared env, and the QA and README briefs

## DOC-007 — Results

- **Status:** DONE.
- **Triage:** small to medium. Rule and spec text, plus one generated secret wired through `init` and compose; no product code.
