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

**Details:** the human accepted all nine decisions in `docs/plans/m2.md` (PR #59) as recommended. Five of them (D1–D5 below) change CLAUDE.md, DESIGN.md or the runtime, which is human-side work (RUN-002.D16). The other five are the lead's to record in its journals: the backlog scope (CFG-002, TST-003 and TST-004 in M2, RUN-004 after M3), SAN-001.D6 (no `claude` backend or OCR in M2), SAN-001.D7 (working copies persist in `.work/`) and TST-005.D2 (gate 2's seeded names).

**Constraint:** human-side PR; the index row is the lead's (RUN-002.D13).

## DOC-007 — Confirmed reading

- **DOC-007.D1 (= ING-001.D2, option A):** **The source-path exception is permanent**, for the ledger and the local reports, with two limits from M2 on: no model ever receives the path or the raw file name, only `files.original_sanitized` (P-2); and the M4 API and UI show sanitized names and hashes, never `source_path`. The dry-run CSV keeps `source_path` beside a new `sanitized_name`. (human, 2026-10-07)
- **DOC-007.D2 (= SAN-001.D5):** **`sanitize_log.before_hash` is HMAC-SHA256** keyed with `SANITIZE_LOG_KEY`. `make init` generates the key into the local `.env`, `.env.example` names it, and compose passes it to the `app` and `test` containers only, never to `fetch`, the one app-image container with internet access (DESIGN.md R-SAN-6). A plain hash of a short value, such as a first name, could be reversed by hashing guesses. (human, 2026-10-07)
- **DOC-007.D3 (= SAN-001.D4):** **The ICC colour profile is kept**, with the file-structure tags (dimensions, encoding). Without it, wide-gamut images render with shifted colours (DESIGN.md R-SAN-2). (human, 2026-10-07)
- **DOC-007.D4 (= ING-002.D1):** **Thumbnails are `.work/thumbs/<source_hash>.webp`.** 8 hex chars collide on a big folder (DESIGN.md R-ING-5). (human, 2026-10-07)
- **DOC-007.D5 (= TST-005.D1):** **The worker whose task makes a recording commits it**, under `tests/recordings/<package>/`, from synthetic strings only. QA owns the recording format and the replay fixture, as DOC-004.D1 split the tests (CLAUDE.md §3, the roles table, and the QA and README briefs). (human, 2026-10-07)

## DOC-007 — Tasks

- [x] DOC-007.1 — CLAUDE.md (the exception, §3 recordings, the QA row), DESIGN.md (R-ING-5, R-SAN-2, R-SAN-6), the Makefile's `init`, `.env.example`, `docker-compose.yml`, and the QA and README briefs
- [x] DOC-007.2 — Review round 1 (PR #60): D1's limits in DESIGN.md (P-2, §5, the dry-run CSV) and in the Pipeline and API/UI briefs; DESIGN.md §12's QA line; the key on `app` and `test` only, not the shared env that `fetch` inherits; the count in Details

## DOC-007 — Results

- **Status:** DONE.
- **Triage:** small to medium. Rule and spec text, plus one generated secret wired through `init` and compose; no product code.
- **Review round 1 (PR #60), all findings fixed (DOC-007.2):**
  - D1's limits are now in the normative spec too: P-2, §5's `source_path` note, and the dry-run CSV under `results_root/reports/`. The Pipeline and API/UI briefs carry them as well.
  - DESIGN.md §12 matches CLAUDE.md on recordings.
  - `SANITIZE_LOG_KEY` is set on `app` and `test` only. `fetch`, on the egress network, no longer inherits it, and no longer fails to start without it.
  - The miscount in Details is fixed.
- **Tests:** the default tiers, 442 passed. `docker compose config` shows the key on `app` and `test` and not on `fetch`.
- **Self-rating:** 9/10, proud: yes. Gap: no unit test covers `init`'s key generation, as for the existing secrets; it was checked by hand.

---

## DOC-008 — Requirement (human, 2026-10-12)

**Objective:** carry the M3 G0 answers that change the spec, the rules or the desk briefs, in their own PR (RUN-007.D2).

**Details:** the human accepted all six decisions in `docs/plans/m3.md` (PR #104) as recommended, with one tweak to TST-008.D1. The lead records the rest in its journals: CLS-003.D1 (calibration scope B), CLS-003.D2 (values in `config.yaml` and migration `0004`) and TST-008.D2 (a `calibration-only` tag).

**Constraint:** human-side PR (RUN-002.D16); the index row is the lead's (RUN-002.D13).

## DOC-008 — Confirmed reading

- **DOC-008.D1 (= CLS-002.D10, option A):** **classify stores the SigLIP image vector** as `files.image_vec vector(1152)`, for `reclassify` and M6 to reuse (DESIGN.md §5). It stays in the local ledger. (human, 2026-10-12)
- **DOC-008.D2 (decision 6):** **the privacy checklist is in every worker's brief**: `.claude/roles/README.md`, as the plan front-loads it into every issue. `ml.md` names ML's ownership of `classifier/models/classify_rules.py`, and says calibrated values stay proposals until the human approves them (CLS-002.D1, CLS-003). CLAUDE.md's "Current phase" says M3. (human, 2026-10-12)
- **DOC-008.D3 (= TST-008.D1, with the human's tweak):** **what gate 3 and the calibration publish.** In public, a verdict per criterion, with a percentage rounded down to a whole percent for the format, topic and unrecognized criteria only. The adult and `suggestive-negative` criteria publish a **verdict only** (DOC-005.D1). There is no breakdown, confusion matrix or count anywhere public; per-category detail stays on the box console. (DESIGN.md §11, M3 row.) (human, 2026-10-12)

and then (the plan's merged version, PR #104 rounds 2 and 3, added three items and two spec edits; the human accepted all, 2026-10-12):

- **DOC-008.D4 (= CLS-002.D12, D2, D9):** recorded in DESIGN.md §13 as C-22 to C-24. **C-22:** an M3 dry run stops at `classified` (option A). **C-23:** R-CLS-6's fall-through never picks the runner-up. **C-24:** `nsfw.mode: separate` fails fast until specified. (human, 2026-10-12)
- **DOC-008.D5 (= CLS-003.D2's spec change):** R-CLS-8 now names where calibrated values land: `config.yaml` for per-axis defaults, and a seed-data migration after `0003` for overrides and prompt edits, committed only after the human approves the values. (human, 2026-10-12)
- **DOC-008.D6:** the M3 gate row's extra-samples clause is neutral: "rows tagged `calibration-only`", not a description of what the fixtures hold. The privacy auditor flagged the old wording while reviewing PR #104. (human, 2026-10-12)

## DOC-008 — Tasks

- [x] DOC-008.1 — DESIGN.md §5 (`image_vec`) and §11 (published results); CLAUDE.md "Current phase"; `ml.md`; the privacy checklist in `.claude/roles/README.md`
- [x] DOC-008.2 — DESIGN.md §13 C-22 to C-24 (D4), R-CLS-8 (D5) and the M3 gate row's clause (D6)
- [x] DOC-008.3 — Review round 1 (PR #105): CLAUDE.md's no-aggregates rule and README checklist items 1 and 10 carry D3's carve-out, so the three texts agree; the reason clauses after "verdict only" are removed (privacy)

## DOC-008 — Results

- **Status:** DONE.
- **Triage:** small. Spec, rule and brief text; no code.

---

## DOC-009 — Requirement (human-side, the M3 VLM re-plan, 2026-10-18)

- **Objective:** bring DESIGN.md and CLAUDE.md in line with the human's VLM decisions (CLS-004), in a PR from the human's own session (RUN-002.D16).
- **Details (the lead's list of what changes):**
  - **R-CLS-1:** the NSFW branch is a VLM level, `>= nsfw.min_level`, on scale A (CLS-004.D2, D3). Falconsai becomes a cross-check (D5).
  - **R-CLS-2:** scoring is one structured VLM call for format and topic (D1). SigLIP keeps `image_vec` only (D7).
  - **R-CLS-3 and 3a:** `min_score` and `margin` don't apply to VLM answers. `unsorted` is the format enum's "none fits", and no topic is `none`.
  - **§13:** C-5 (sigmoid/cosine scoring) is obsolete, and new lines are added for the VLM classifier, scale A and the single resident model.
  - **The `config.yaml` sketch (§6):** CFG-003's keys.
  - **§5:** `files.nsfw_level` (DB-004), and `nsfw_score`'s new meaning.
  - **§11, M3 row:** format ≥ 85% (D12), with the NSFW criteria judged by level at `min_level`. CLS-001.D5 is amended to match.
  - **§4.3:** the VLM-facing category wording the human set (3.3), stated as generic definitions.
  - **The findings (3.7):** the thinking build ignoring `think: false`, and the one CUDA runner crash under memory pressure.
  - **CLAUDE.md:** the "Current phase" line notes the M3 re-plan.
  - The triage block's `Branch:` line is not part of this: it is DOC-010 (PR #138).
- **Implements:** CLS-004's rule changes.

## DOC-009 — Tasks

- [ ] DOC-009.1 — The human's PR with the DESIGN and CLAUDE.md edits above · human-side · acceptance: review only
