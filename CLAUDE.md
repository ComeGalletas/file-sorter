# CLAUDE.md — file-sorter (Image Classification Bot, MVP)

A local bot on an RTX 5080 box that sanitizes, classifies, names and files images into category folders. Adult content is mirrored under `Adult/` with an `nsfw_` name prefix. **The source folder is read-only**: sorted copies go to a separate results folder, and originals are never moved, modified or deleted. Python 3.12, LangGraph, PyTorch (SigLIP + NSFW gate), Ollama, Postgres 16 + pgvector, FastAPI + htmx, Typer CLI. Everything runs in Docker Compose.

## Sources of truth (read in this order)

1. **`DESIGN.md`** is the normative spec: spec requirement IDs (`R-CLS-4`), data model, config, milestones and gates.
2. **`docs/journals/INDEX.md`** lists every work ID (`CLS-004`) with its status, journal, issues and branch. Each journal is the plan, todo list and record for its work (§1).
3. **`docs/PLAN.md`** holds the rationale and narrative (a copy of the original plan, archived at the workspace root). DESIGN.md is confirmed: where the two disagree, DESIGN.md wins (its §13 lists every deviation).
4. Only the human changes the decisions in DESIGN.md or this file. If you think a decision is wrong, open an issue labelled `design-question`. Do not work around it.

**Current phase:** pre-bootstrap. Runbook steps 1 (host) and 2 (fixtures) belong to the human. The first agent action is runbook step 3 (repo bootstrap). DESIGN.md §14 lists the open questions; ask the human, don't assume.

## Hard rules — never

- Read anything under `source_root/` or `results_root/` in tests. Use `fixtures/` only.
- Write to, rename, move or delete anything under `source_root/`. It is mounted `:ro`; never change that mount in `docker-compose.yml`.
- Commit images, model weights, `.env`, `sanitize.yaml`, `fixtures/labels.csv`, agent logs, host paths, or real names or handles. Commit only the `*.example*` counterparts, with placeholders. **The repo is public:** issues, PRs, commit messages, journals and `docs/` must never contain fixture file names, captions, references or anything that describes the human's images. Use hashes.
- Add a network route, outbound HTTP call or open port beyond the localhost services (`db`, `ollama`, `searxng`). All ports bind to `127.0.0.1`.
- Call a model except through the clients in `classifier/models/` (SigLIP, NSFW, Ollama) and `classifier/sanitize/` (Anthropic, text-only, opt-in). Never send pixels to any remote service.
- Delete or overwrite files outside `classifier/fileops/delete.py`. No sorting step (`sort`, `watch`, `dry-run`, `reclassify`) ever deletes or modifies an original. `purge-sources` and `delete` are CLI-only, never appear in the UI, and refuse to run unless `deletion.enabled: true` (default `false`). Never change that default.
- Log or store original sensitive values, EXIF values or unsanitized filenames. Log hashes instead.
- Install packages on the host or touch the host GPU directly. Every build, test and run goes through `docker compose`.
- Start milestone N before `docs/plans/mN.md` has `status: approved`. Plan milestone N+1 before the git tag `mN-approved` exists.
- Skip a hook (`--no-verify`), skip a test to make it green, or commit a red task as done.

---

## 1. Process standard (DOC-001)

### 1.1 Every requirement gets a work ID

A requirement is one request from the human, or one unit of milestone scope from DESIGN.md. Each gets a permanent work ID `<SYS>-<NNN>`, numbered in sequence within its system and **never reused**. The system codes match DESIGN.md's spec prefixes:

| Code | System | Covers |
| --- | --- | --- |
| `ING` | ingest | hashing, the ingest node, skips, thumbnails (R-ING) |
| `SAN` | sanitize | `classifier/sanitize/`, `sanitize.example.yaml` (R-SAN) |
| `CLS` | classify | SigLIP scoring, NSFW gate, categories, thresholds (R-CLS) |
| `CAP` | caption | VLM captions, `prompts/` (R-CAP) |
| `RAG` | retrieve | `classifier/rag/`, reference store, judge, web branch (R-RAG) |
| `NAME` | naming | `classifier/naming/`, templates, tokens (R-NAME) |
| `FOP` | file ops | `classifier/fileops/`, the copy transaction, `watch`, deletion (R-FOP) |
| `API` | API and UI | `classifier/api/`, `classifier/ui/`, `report` (R-API) |
| `MOD` | models | `classifier/models/`, Ollama swapping, weights (R-MOD) |
| `PIPE` | pipeline | `classifier/graph/` orchestration, batching, resume (R-PIPE) |
| `CFG` | config | `config.yaml`, `.env.example`, config loading (R-CFG) |
| `RUN` | runtime | Docker Compose, Dockerfile, Makefile, hook scripts (R-RUN) |
| `DB` | data model | `classifier/db/`, Alembic migrations (DESIGN §5) |
| `CLI` | CLI | `classifier/cli/` (DESIGN §7) |
| `TST` | tests | the suite itself: tiers, fixtures, recordings, gate scripts, tier audit |
| `DOC` | process | `docs/`, CLAUDE.md, DESIGN.md, working standards |

- **Work IDs and spec IDs are different things.** `R-CLS-4` is a spec requirement in DESIGN.md (what the system must do). `CLS-004` is a unit of work (what someone was asked to build). A work item cites the spec IDs it implements.
- A requirement that touches several systems takes the code of the system it mainly changes; the index lists the others.
- A follow-up to existing work gets a **new** ID, appended as a new block in the existing journal. A journal can hold several IDs, and its own ID is its first requirement's.
- Bugs, balance changes and refactors are requirements too. The index's `type` column tells them apart: `feature`, `bug`, `balance`, `refactor`, `process`.

### 1.2 Tasks, subtasks and decisions carry their parent's ID

| Level | ID | Maps to |
| --- | --- | --- |
| Requirement | `CLS-004` | one journal block and one index row |
| Task (≤ 1 day) | `CLS-004.2` | **one GitHub issue = one worktree = one PR** |
| Subtask | `CLS-004.2.1` | **one commit** |
| Decision | `CLS-004.D1` | one entry in the journal's Confirmed reading, citable from code comments, PRs, DESIGN.md and memory |

### 1.3 Every requirement lives in a journal

Journals live in `docs/journals/<feature>_journal.md`; copy `docs/journals/TEMPLATE.md`. A new feature gets a new journal, and a follow-up goes into the existing one. The journal is the plan, the todo list and the record, in this order: **Requirement → Confirmed reading → Plan → Tasks → Results.**

- **Requirement** is a distilled statement (Objective, Details, Constraint, cited R-IDs), never a quote or retelling of the request. A second round inside one session goes in the same block, introduced with "and then:". A later, separate request gets a new ID and a new block.
- **Confirmed reading** checks each item against what the code and DESIGN.md already say, and states every open decision as `<ID>.D<n>`. Decisions that are the human's call are asked in the issue, not guessed.
- **Plan and Tasks** are written **before** the first code change and kept current:
  - Tick tasks as they land, with the commit hash.
  - Add tasks discovered along the way with the next free number. Never renumber.
  - Strike dropped tasks through (`~~CLS-004.4~~ dropped: <why>`); never delete them.
- **Results** holds the tests run per tier, eval numbers, the completion status (§2.3), the self-rating (§2.4), the Reviewer and Privacy auditor verdicts, and what was deferred and why.
- **Who writes what.** The lead writes the Requirement, Confirmed reading, Plan and Tasks at G0. A worker edits only its own task lines and its own Results subsection, so parallel PRs don't conflict.

### 1.4 The index

`docs/journals/INDEX.md` lists every work ID: title, systems, type, status, milestone, issues, journal, branch, date. It also maps plans and design documents to the IDs they serve.

- **Only the lead edits it.** The lead adds the row when the ID is allocated, and updates the status at G0, at merge and at G1: `proposed → in progress → done`, or `parked` / `superseded by <ID>`.
- Before allocating an ID, read the **Next free** line, and update it in the same commit.
- Search by ID with `git log --grep CLS-004`, or grep it across `docs/`.

### 1.5 Branches

- Every worker task runs in its own worktree (agent-office desk). There is no "worktree or current branch?" question.
- Name the branch `<task-id-lowercase>-<slug>`, e.g. `cls-004.2-nested-margin`. If agent-office names the branch itself, keep its name.
- Record the branch in the journal header and the index.

### 1.6 Commits and PRs

- **One commit per subtask** (or per task, if it has no subtasks), made when it is done, not batched at the end.
- **Subject:** the ID, then an imperative summary: `CLS-004.2.1: Skip the margin check for ancestor/descendant pairs`.
- **Body:** what changed and the measured result (numbers, not adjectives). No image names, captions or paths (public repo).
- **Journal tick:** the same commit carries the journal tick for that subtask. The hash is filled in by the next commit or in Results.
- **Stage by path.** Never sweep unrelated working-tree changes into a task commit.
- Run the tests that cover the subtask before committing (§3). Never commit a red task as done.
- End every commit message with the attribution trailer the harness supplies.
- **PR title:** `<task ID>: <summary>`.
- **PR body:**
  - `Closes #<issue>` and the cited R-IDs;
  - the triage block (§2.1);
  - which tiers and acceptance test ran, with their counts;
  - the completion status (§2.3) and the self-rating (§2.4).
- **Merging:** the lead merges with a merge commit (`gh pr merge --merge`), so each subtask commit and its ID stay in `main`'s history. Workers never merge.

### 1.7 Hand-tuned values — flag and ask

The human tunes some values by hand, often while other work is in flight:

- thresholds and margins in `config.yaml`;
- caption, judge and sanitizer prompts in `prompts/`;
- category prompts and template seeds in migrations.

When the working tree or a diff shows such a change that the current task did not make:

- **Say so.** Name the file, the key and the old → new value.
- **Ask how to handle it**, with two options:
  1. **Leave it out** of the current work: not staged, not committed, not reverted.
  2. **Commit it separately**, in its own commit containing only that change. It gets a work ID of type `balance` in its system (e.g. `CLS-007.1: Raise anime min_score from 0.40 to 0.46`) and an index row.
- Until the human answers, never fold such a change into a task commit, never revert it, and never "fix" code or tests to agree with it.

---

## 2. Working a task

### 2.1 Triage block — before any work

Every task starts with a printed triage block. The worker posts it at the top of its plan comment on the issue and repeats it in the PR body:

```
Size: small | medium | large — why
Tests: which tiers / paths (§3) — why
Agents: solo | subagents (which, on what) — why
Branch: <branch> in <worktree path>
```

| Size | What it is | Tests | Self-rating |
| --- | --- | --- | --- |
| **small** | Typo, docs, config default, rename; one or two files with no behavior change | The touched package's `unit` tests and lint. No new test needed for a non-behavioral change. | One line |
| **medium** | A behavior change or bug fix inside one package | The touched package's `unit` and `db`/`integration` tests. A bug fix ships its regression test. | Full loop (§2.4) |
| **large** | Cross-package or contract change (DB schema, config schema, graph state, API shape, prompts or thresholds), or anything judgment-heavy | All default tiers, plus `gpu` if models or prompts are touched, plus an `eval/` run when quality can move | Full loop |

- When torn between two sizes, pick the smaller and say so. Escalate the moment the change turns out bigger, by printing an updated block and saying what changed.
- "Test what you touch" is the default. The blast radius decides, not habit.
- The Reviewer and Privacy auditor run on **every** PR, whatever the size. Triage scales the tests, the subagents and the self-rating, never the review.
- Sub-agents that write in parallel must run with `isolation: "worktree"`.

### 2.2 Per-task workflow

1. **Lead (G0):**
   - Allocates the IDs, writes the journal sections and index rows, and lists them in `docs/plans/mN.md`.
   - Opens one GitHub issue per task. The issue title is `<task ID>: <summary>`. The issue names its acceptance test (a pytest path or `scripts/gate_N.py`) and the cited R-IDs, and carries the labels `mN` and `role:<role>`.
2. **Worker:** works in its own worktree and posts the triage block plus a short plan as the first issue comment. No code until the lead approves it.
3. **Worker:** implements, committing one subtask at a time (§1.6). The `PostToolUse` hook runs ruff on the edited file. The `Stop` hook runs the touched tests.
4. **Worker:** opens the PR. The pre-push hook runs the default tiers, plus `gpu` when `classifier/models/` or `prompts/` changed, plus the task's acceptance test. A non-zero exit blocks the push.
5. **Lead:** runs the Reviewer and Privacy auditor subagents on the PR diff. Blocking findings → PR comment or a new issue.
6. **Lead:** merges (§1.6), closes the issue, updates the index, and checks that the journal's Results section is complete.

**Agent logs (local only, never committed).** Each role logs its own work under `$AGENT_LOG_ROOT/<role>/`. The default is `../agent-logs/`, the workspace's `agent-logs\` folder next to this repo.

- `events.jsonl` gets one JSON line per lifecycle event: session, issue, tool, files touched, test result. Hooks write it.
- `<issue>.md` is the job log: plan, steps taken, test results. The agent writes it.
- `qa/test-history.md` is the test-runner's history (§3).

Use hashes, not image names.

### 2.3 Completion status

Every task ends with exactly one status, written in the PR body and the journal's Results section:

- **DONE:** all steps completed, with evidence for every claim, and tests (and evals, where §2.1 calls for them) in the diff.
- **DONE_WITH_CONCERNS:** completed, but with issues the human should know about. List each concern with its severity and a proposed follow-up (a new ID or issue).
- **BLOCKED:** cannot proceed. State what's blocking and what was already tried. Label the issue `blocked`.
- **NEEDS_CONTEXT:** missing information. State exactly what's needed, asked on the issue.

"Partially done" is not a status.

### 2.4 Self-rating — proud or loop

Rate the work before the final commit, from a fresh read of the diff and the running result, not from memory of building it.

- **Small tasks** get one line: a score and yes/no, with no loop.
- **Medium and large tasks** get the full loop:
  - Score the work 1–10 and answer honestly: am I proud of this? Yes or no.
  - Every point below 10 names a specific gap against the issue's acceptance test and cited R-IDs. A score with no named gaps is a guess.
  - If the answer is no, fix the named gap and re-rate. Each pass states what changed since the last one.
  - **Drift guard:** if the loop reaches a third pass, hand the rating to a fresh Reviewer subagent (diff plus acceptance criteria only). Its score replaces the self-score from then on.
  - If a "no" can't be fixed from here, report DONE_WITH_CONCERNS or BLOCKED with the gap named. Never inflate a score to exit the loop.
- The rating goes in the PR body and the journal. It never substitutes for the Reviewer pass.

---

## 3. Tests

**Tiers.** Each test module's tier is assigned by its path in `tests/conftest.py`, so modules stay plain pytest.

| Tier | Path | What it may touch | When it runs |
| --- | --- | --- | --- |
| `unit` | `tests/unit/` | nothing external: fakes for the db, models and Ollama; synthetic images generated in the test | every save; the `Stop` hook |
| `db` | `tests/db/` | a throwaway, migrated Postgres from the `test` profile | default |
| `integration` | `tests/integration/` | the full graph on `fixtures/`, with recorded model responses | default |
| `gpu` | `tests/gpu/` | real SigLIP, NSFW and Ollama on the box | `make test-gpu`; at pre-push when `models/` or `prompts/` changed |
| `gate` | `scripts/gate_N.py` | the real labelled fixtures, milestone metrics | `make gate-N`, as an acceptance test, and at G1 |

- **Default invocation.** `make test` runs `unit + db + integration` (`addopts = -m "not gpu and not gate"`).
- **Tier audit.** A module that lands unlisted is `unit`. `tests/devtools/test_tier_audit.py` fails if a `unit` test opens a db connection, loads a model or calls Ollama, and names the conftest line to add.
- **Never skip to green.** No `skip` or `skipif` for a missing GPU, db or fixture. Deselect by marker instead. A test whose prerequisites are missing fails with a message naming them.
- **Determinism.**
  - Anything random (sampling, `templates preview --sample`, shuffles) takes a pinned seed.
  - Outside the `gpu` tier, model and LLM calls replay recorded responses from `tests/recordings/`. They never call live Ollama.
  - `gpu` tests call Ollama with temperature 0 and a fixed seed.
- **Share expensive setup.** Load models once per session (a session-scoped fixture). Use one migrated test database per session, with each test in a transaction that is rolled back.
- **Images.** Never commit images. `unit`, `db` and `integration` tests generate small synthetic images in code. Only the `gpu` and `gate` tiers read the git-ignored real fixtures.
- **What ships with a change.**
  - Every behavior change ships its test in the same commit.
  - Every bug fix ships a regression test that fails with the bug present.
  - A change to prompts, thresholds or models also ships an `eval/` run against the labelled fixtures, with the numbers in the journal.
- **Test-runner subagent** (`.claude/agents/test-runner.md`, Sonnet):
  - Runs the requested tiers and compares them with the previous run: NEW FAILURES, FIXED, STILL FAILING, NEW TESTS.
  - Gives the likely cause of each new failure, with file and line.
  - Appends an entry to `$AGENT_LOG_ROOT/qa/test-history.md` (local, last 20 entries).
  - Never edits code, tests or config.

## Commands (all via Docker)

```bash
make init          # create .env and sanitize.yaml from their .example files if missing
make up            # docker compose up -d db ollama searxng app
make models        # pull Ollama tags + HF weights (SigLIP, NSFW) into volumes
make test          # unit + db + integration in the test profile
make test-gpu      # gpu tier (real models) in the test profile
make lint          # ruff check + ruff format --check inside the app image
make gate-N        # docker compose --profile test run --rm test python scripts/gate_N.py
docker compose run --rm app classifier <command>   # e.g. dry-run, categories list
```

The UI is at `http://127.0.0.1:8000` (`classifier serve`).

## Roles and file ownership

Edit only the folders your role owns. Need a change elsewhere? Open an issue for the owner.

| Role | Model | Owns |
| --- | --- | --- |
| Lead | Opus | `docs/` (plans, journals, index); no code. Plans, opens issues, assigns, approves plans, merges, writes reports |
| Pipeline engineer | Sonnet | `classifier/{graph,naming,fileops,db,cli,sanitize}/` |
| ML engineer | Sonnet | `classifier/models/`, `prompts/`, `eval/` |
| Data/RAG engineer | Sonnet | `classifier/rag/`, `references*` migrations |
| API/UI engineer | Sonnet | `classifier/api/`, `classifier/ui/` |
| QA engineer | Sonnet | `tests/`, `fixtures/` (except `fixtures/images/`), `scripts/gate_*.py` |
| Reviewer | Sonnet subagent, read-only | — |
| Privacy auditor | Haiku subagent, read-only | — |
| Test runner | Sonnet subagent | writes only `$AGENT_LOG_ROOT/qa/test-history.md` |

Every worker also edits its own task lines and Results subsection in the journal (§1.3). The repo bootstrap (runbook steps 3–4) is the one exception to ownership: the lead session generates the scaffolding.

**Migrations:** Alembic keeps one head. A task that adds a migration rebases on `main` and fixes `down_revision` before merge.

## Milestone gates

| Gate | Unblocked by |
| --- | --- |
| G0 plan | The lead allocates work IDs, writes the journals and index rows, writes `docs/plans/mN.md` (from `docs/plans/TEMPLATE.md`), and opens the issues unassigned. The human sets `status: approved`. Only then assign. |
| G1 demo | All mN issues are closed → run `make gate-N`. Post the output, with token cost, in the plan's Results section, and set the index statuses. The human tags `mN-approved`. |
| Standing instruction for the lead | On start, find the highest `mN-approved` tag, plan N+1, wait for G0, run, stop at G1. One lead session per milestone, so shut down after G1. |

Milestones M3–M6 run in **dry-run only**. Before M7, `results_root` gets empty category folders, `.work/` and `reports/`, but no images.

## Code conventions

- Python 3.12, type hints everywhere, `ruff` (lint + format), `pytest`. Paths use `pathlib`.
- Config is loaded once into typed models (pydantic). No hard-coded paths, thresholds, prompts or model tags; they belong in `config.yaml`, `sanitize.yaml`, `.env`, `prompts/` or Postgres. Inside containers, the source is always `/source` and the results are always `/results`.
- Hashes: SHA-256. `source_hash` is the dedup key and `short_hash` is its first 8 hex chars.
- The ledger `files.status` enum is the only pipeline checkpoint; see DESIGN.md §5. "Unsorted" is the fallback format, not a status; a missing topic is `topic = null`.
- Graph nodes are batch-oriented and idempotent. Re-running a node on a file already past it is a no-op.
- A code comment that depends on a decision cites its ID (`# CLS-004.D2`, `# R-CLS-4`).

## Environment notes

- **Host:** Windows 11, native. Docker Desktop provides the GPU (its WSL2 backend is internal; there is no WSL distro and no code in WSL). git, Git Bash, the GitHub CLI, Node 20+ (agent-office minimum), Claude Code and `make` are installed natively. Git Bash (`C:\Program Files\Git\bin`) must come before `WindowsApps` on `PATH`, because `WindowsApps\bash.exe` is the WSL launcher.
- **Workspace:**
  - `file-sorter-full\` holds `agent-office\`, `agent-logs\` and this repo, `file-sorter\`.
  - The repo path is fixed. Never clone it a second time.
  - Don't edit `agent-office\` from this project.
- **Shell:** hooks and Makefile recipes are POSIX shell run by Git Bash (`SHELL := bash`). Don't use Linux-only tools, and don't use PowerShell in hooks.
- **Line endings:** LF everywhere, enforced by `.gitattributes`. Never commit CRLF shell scripts or Dockerfiles.
- **Image folders:** source and results are Windows-drive bind mounts (`/source` read-only, `/results`); their paths are only in the local `.env`. Bind-mount I/O is slower than native. `watch` and dev auto-reload must poll, because file events don't propagate. Paths contain spaces, so always quote them.
- **GPU stack:** the RTX 5080 (Blackwell) needs PyTorch built for CUDA 12.8+ (`cu128`+).
- Remote backends (`sanitizer.backend: claude`, `rag.web_backend: brave|claude`) need `docker-compose.egress.yml` and stay off by default.
- agent-office comes from the fork `https://github.com/ComeGalletas/agent-office`, built from source in `file-sorter-full\agent-office`. Its `install.sh` and `install.ps1` download upstream releases, so never use them.
- The adult VLM tag (`models.vlm_nsfw`) is intentionally unset until M5. Never pick one; the M5 G0 plan asks the human.

## Keeping this file honest

- This file, DESIGN.md and memory must not disagree. When a standing rule changes, change all three in the same step and record the change as a decision (`DOC-<NNN>.D<n>`) in the relevant journal.
- The process standard (§1, §2.1, §2.3, §2.4, §3) was adopted from the human's pygame project as DOC-001. Where the two differ, this file wins for this repo; see `docs/journals/process_standard_journal.md`.
