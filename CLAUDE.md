# CLAUDE.md — file-sorter (Image Classification Bot, MVP)

A local bot on an RTX 5080 box that sanitizes, classifies, names and files images into category folders. Adult content is mirrored under `Adult/` with an `nsfw_` name prefix. **The source folder is read-only**: sorted copies go to a separate results folder, and originals are never moved, modified or deleted. Python 3.12, LangGraph, PyTorch (SigLIP + NSFW gate), Ollama, Postgres 16 + pgvector, FastAPI + htmx, Typer CLI. Everything runs in Docker Compose.

## Sources of truth (read in this order)

1. **`DESIGN.md`** is the normative spec: spec requirement IDs (`R-CLS-4`), data model, config, milestones and gates.
2. **`docs/journals/INDEX.md`** lists every work ID (`CLS-004`) with its status, journal, issues and branch. Each journal is the plan, todo list and record for its work (§1).
3. **`docs/PLAN.md`** holds the rationale and narrative (a copy of the original plan, archived at the workspace root). DESIGN.md is confirmed: where the two disagree, DESIGN.md wins (its §13 lists every deviation).
4. Only the human changes the decisions in DESIGN.md or this file. If you think a decision is wrong, open an issue labelled `design-question`. Do not work around it.
5. **The human's changes come as PRs from the human's own session** (RUN-002.D16). That is the human, or Claude working in the human's session, from any branch or worktree. They may touch DESIGN.md, CLAUDE.md, `.claude/` and the hooks. The role guard doesn't apply to them, because it only acts on agent-office desks. Like every PR, they get the reviewer and the privacy auditor, and the lead merges them. They never edit `docs/journals/INDEX.md`: the lead reconciles the index (RUN-002.D13).

**Current phase:** M2 (Sanitize) is in progress, with its plan approved on 2026-10-07; M1 is approved (`m1-approved`). Next: M2 G1, when gate 2 runs. DESIGN.md §14 lists the open questions; ask the human, don't assume.

## Hard rules — never

- Read anything under `source_root/` or `results_root/` in tests. Use `fixtures/` only.
- Write to, rename, move or delete anything under `source_root/`. It is mounted `:ro`; never change that mount in `docker-compose.yml`.
- Commit images, model weights, `.env`, `sanitize.yaml`, `fixtures/labels.csv`, agent logs, host paths, or real names or handles. Commit only the `*.example*` counterparts, with placeholders. **The repo is public:** issues, PRs, commit messages, journals and `docs/` must never contain fixture file names, captions, references or anything that describes the human's images, **including aggregates**: counts, sizes, the file-type mix, a content profile or label distributions (DOC-005.D1). Use hashes, and state gates against `fixtures/labels.csv` rather than a number.
- Add a network route, outbound HTTP call or open port **in the app runtime** beyond the localhost services (`db`, `ollama`, `searxng`). All ports bind to `127.0.0.1`. The runtime means the Compose services, the code under `classifier/`, and anything that runs inside the containers. The designed runtime exceptions, each in its own container, are: the `fetch` service's Hugging Face download (R-MOD-2), the `ollama` service's model pulls (`make models`), SearXNG's forwarding of query text (C-14), and the opt-in egress backends (R-RUN-2). Model weights arrive only through the first two. **Host-side process tooling (`.claude/hooks/`, `.githooks/`, scripts run on the host such as the review router, Makefile recipes that don't run in a container, and the desks' own `gh` use)** may reach **only** (a) GitHub, through `gh`, for PR and issue metadata, and (b) these registries, **download only and at build or setup time**, never from app runtime code: Docker Hub, the GitHub Container Registry (`ghcr.io`), the Debian package archive, PyPI and the PyTorch index (`download.pytorch.org`), as pinned in the Dockerfile, `docker-compose.yml`, the Makefile and the lint hook. Adding a registry takes its own rule-change PR (RUN-007.D2). No other host, no uploading file contents anywhere, and never image data, `fixtures/`, `.env` or any other git-ignored file (RUN-007.D1, D4, D5).
- Call a model except through the clients in `classifier/models/` (SigLIP, NSFW, Ollama) and `classifier/sanitize/` (Anthropic, text-only, opt-in). Never send pixels to any remote service.
- Delete or overwrite files outside `classifier/fileops/delete.py`. No sorting step (`sort`, `watch`, `dry-run`, `reclassify`) ever deletes or modifies an original. `purge-sources` and `delete` are CLI-only, never appear in the UI, and refuse to run unless `deletion.enabled: true` (default `false`). Never change that default.
- Log or store original sensitive values, EXIF values or unsanitized filenames. Log hashes instead. **The one exception is the source path itself** (DOC-004.D3): its container path (`/source/...`) may be stored in the local ledger (`files.source_path`, `files.duplicate_paths`) and in the local reports under `results_root/reports/`, because the bot needs it to read the original. The exception is **permanent** (ING-001.D2), with two limits: no model ever receives the path or the raw file name, only `files.original_sanitized` (P-2), and the API and UI (M4) show sanitized names and hashes, never `source_path`. The dry-run CSV keeps `source_path` beside `sanitized_name`. Logs, console and test output, issues, PRs and journals still carry hashes only (DOC-007.D1).
- Install packages on the host or touch the host GPU directly. Every build, test and run goes through `docker compose`.
- Start milestone N before `docs/plans/mN.md` has `status: approved`. Plan milestone N+1 before the git tag `mN-approved` exists.
- Skip a hook (`--no-verify`), skip a test to make it green, or commit a red task as done.
- Set `ALLOW_MAIN_PUSH=1`. It exists only for the bootstrap push; afterwards `main` changes only through `gh pr merge` (RUN-002.D5).

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

- **Only the lead edits it.** The lead adds the row when the ID is allocated: `proposed → in progress → done`, or `blocked` / `parked` / `superseded by <ID>`.
- **The index lags GitHub on purpose** (RUN-002.D13). Workers can't edit it, and the lead must stay on `main` (RUN-002.D10), so it can't be updated at every merge. Between checkpoints, the issue's state on GitHub is the live status. The lead brings the rows in line in its next docs PR, at G1 at the latest, and the G1 check requires them to match.
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
- **Merging:** the lead merges with a merge commit (`gh pr merge <n> --merge --delete-branch --match-head-commit <Reviewed at sha>`; the guard requires the last flag, so GitHub refuses the merge if the head moved after the review, RUN-013.D1), so each subtask commit and its ID stay in `main`'s history and no merged branch is left behind. Workers never merge a PR. A worker whose open PR falls behind or conflicts with `main` runs `git fetch && git merge --no-edit origin/main` in its own branch, resolves any conflict, and pushes normally: never a rebase or force-push once the PR is open, so `Reviewed at` stays in the history (RUN-008.D1, RUN-006.D7). **That merge commit carries the task ID too:** before pushing, rename it with `git commit --amend -F <file>`, subject `<task ID>: Merge origin/main` (the file keeps the guard from reading the message as a merge command). Human-side branches follow the same rule (RUN-010.D4).

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
2. **Worker:** works in its own worktree. It runs `make init` there (which copies `.env`, `sanitize.yaml` and `fixtures/labels.csv` from the main checkout), and writes the git-ignored `.task` file (`role=`, `issue=`, `acceptance=`; see `.claude/roles/README.md`). Then it posts the triage block plus a short plan as the first issue comment. No code until the lead approves it.
3. **Worker:** implements, committing one subtask at a time (§1.6). The `PostToolUse` hook runs ruff on the edited file. The `Stop` hook runs the touched tests.
4. **Worker:** opens the PR. The pre-push hook (`.githooks/pre-push`) runs the default tiers, plus `gpu` when `classifier/models/` or `prompts/` changed, plus the acceptance test named in `.task`. A non-zero exit blocks the push, and so does a task branch without `acceptance=`.
5. **Lead:** picks the reviewer with `bash scripts/review_route.sh <n>` (RUN-006.D1). Small, docs-only PRs get `reviewer-quick` (Haiku, static); everything else gets the full `reviewer`. The Privacy auditor always runs. The lead posts both verdicts as one PR comment before merging, with `Reviewed at <sha>` (RUN-002.D14). Blocking findings → the same comment, or a new issue. A re-review checks only the earlier findings and the diff since `Reviewed at` (RUN-006.D2).
6. **Lead:** merges (§1.6), which closes the issue through `Closes #n`, and checks that the journal's Results section is complete. The index catches up with GitHub in the lead's next docs PR, at G1 at the latest (RUN-002.D13).

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
  - **The worker whose task makes a recording commits it**, under `tests/recordings/<package>/`, made from synthetic strings only. QA owns the recording format and the replay fixture (TST-005.D1, DOC-007.D5).
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
make init          # .env + sanitize.yaml + fixtures/labels.csv (copied from the main checkout in a worktree), secrets, git hooks
make build         # build the app/test image (CUDA PyTorch; ~7 min cold)
make up            # docker compose up -d db ollama searxng app
make down          # stop everything; volumes are kept
make models        # pull Ollama tags + HF weights (SigLIP, NSFW) into the shared volumes
make test          # unit + db + integration in the test profile
make test-gpu      # gpu tier (real models) in the test profile; starts ollama (RUN-011)
make lint          # ruff check + ruff format --check inside the app image
make gate-N        # docker compose --profile test run --rm test python scripts/gate_N.py; starts ollama (RUN-011)
docker compose run --rm app classifier <command>   # e.g. dry-run, categories list
```

The UI will be at `http://127.0.0.1:8000` from M4. `app` sits on an internal-only network, so the port is published through a localhost-only proxy that M4 adds (RUN-001.D5). Never add `app` to the `egress` network to expose it.

In a linked worktree, `make test` and the hooks use their own compose project (`file-sorter-<worktree>`), so parallel runs never share the test database. The model volumes are shared by name (RUN-002.D2). The git-ignored `fixtures/images/` exists only in the main checkout: every `test` container mounts it read-only at `/app/fixtures/images`, from the main checkout in a worktree, so the `gate` and `gpu` tiers work on any desk. Never copy or link the images into a worktree (RUN-009.D1). `ollama` starts only for the `gpu` tier and the gates, in the same project (`make test-gpu`, `make gate-N`, and the pre-push gate's `gpu` and gate runs), so a desk holds GPU memory only while those run; never start it by hand (RUN-011.D1). When a session ends (and on `/clear` or a resume, which end the session too), its test stack goes down: a desk's whole project (`db-test`, `ollama`, the network), and on the main checkout only an idle `db-test`, never the app stack. `SessionStart` and `make init` prune the projects of desks closed without that hook (RUN-012.D1, D2).

## Roles and file ownership

Edit only the folders your role owns. Need a change elsewhere? Open an issue for the owner.

| Role | Model | Owns |
| --- | --- | --- |
| Lead | Opus | `docs/` (plans, journals, index); no code. Plans, opens issues, assigns, approves plans, merges, writes reports |
| Pipeline engineer | Sonnet | `classifier/{graph,naming,fileops,db,cli,sanitize}/`, `classifier/config.py` (DOC-004.D2) |
| ML engineer | Sonnet | `classifier/models/`, `prompts/`, `eval/` |
| Data/RAG engineer | Sonnet | `classifier/rag/`, `references*` migrations |
| API/UI engineer | Sonnet | `classifier/api/`, `classifier/ui/` |
| QA engineer | Sonnet | the shared test infrastructure (`tests/conftest.py`, `tests/devtools/`, the recording format and replay fixture in `tests/recordings/`), `fixtures/` (except `fixtures/images/`), `scripts/gate_*.py`, and its own tasks' tests |
| Reviewer | Sonnet subagent, read-only | — (full review; reproductions only to confirm a suspected blocker) |
| Reviewer, quick | Haiku subagent, read-only | — (small, docs-only PRs, picked by `scripts/review_route.sh`) |
| Privacy auditor | Haiku subagent, read-only | — |
| Test runner | Sonnet subagent | writes only `$AGENT_LOG_ROOT/qa/test-history.md` |

Every worker also edits its own task lines and Results subsection in the journal (§1.3), and **writes the tests for its own task**, in the same commit as the code they cover, under `tests/<tier>/<package>/` (§3; DOC-004.D1). QA owns the shared test infrastructure and reviews test quality: a change to it is QA's task, so open an issue. The repo bootstrap (runbook steps 3–4) was the one exception to ownership.

**Where the roles live (RUN-002.D1):**
- **Desk briefs** are in `.claude/roles/`, one per desk, with launch commands in `README.md`.
- **Under agent-office**, the roles are enforced by the role guard (`.claude/hooks/guard.sh`, RUN-002.D8), decided by location:
  - the main checkout is the lead: inside the repo it edits only under `docs/` (and `.task`), merges only with `--merge`, never tags;
  - a linked worktree is a worker: no PR merges, tags or pushes to `main`. Its only merge is `git merge [--no-edit] origin/main` into its own branch (plus `--abort` and `--continue`), and its only pull is `git pull --ff-only` (RUN-008.D1, D2). Shell commands are matched broadly and fail closed, so a commit message that names `merge`, `pull` or `tag` inline is refused: write it to a file and use `git commit -F <file>` (RUN-008.D4). The guard stops accidents and obvious workarounds; it is not a sandbox. The backstops are the reviewer on every PR and `main` changing only through the lead's `gh pr merge`; the pre-push hook only refuses a direct push to `main` and doesn't inspect merges (RUN-008.D7, RUN-010.D2); no edits to the index, plans, DESIGN.md or CLAUDE.md; and no edits anywhere else in the repo tree, whether the main checkout or another desk's worktree (RUN-005.D1);
  - paths outside the repo tree (Claude memory, the workspace's `agent-logs\`) aren't the guard's concern, and paths with `..` segments are refused;
  - every path is resolved to its real location first (links and NTFS junctions followed) and compared case-insensitively, so neither a junction nor `claude.md` gets around a rule (RUN-005.4);
  - trailing dots and spaces are stripped from each path segment, the way Windows does, so `CLAUDE.md.` is treated as `CLAUDE.md`. NTFS alternate data streams (`CLAUDE.md:hidden`) are refused outright (RUN-005.D6, D7);
  - **no desk writes under `SOURCE_ROOT` or `RESULTS_ROOT`** (read from the local `.env`). Only the app writes there, through Docker (RUN-005.D5).
  - The settings layers `.claude/settings.lead.json` and `.claude/settings.worker.json` apply only to desks launched by hand.
- **Subagents** are only the read-only reviewers: `reviewer`, `reviewer-quick`, `privacy-auditor` and `test-runner`, in `.claude/agents/`. Never add a role as a subagent: a session would then delegate code edits into its own tree.

**Migrations:** Alembic keeps one head. A task that adds a migration merges `origin/main` into its branch and fixes `down_revision` before merge.

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
  - Prefix `docker run` with `MSYS_NO_PATHCONV=1` whenever an argument is a container path (`-w /io`). Otherwise Git Bash rewrites it into a Windows path.
  - Parse hook JSON with `sed`: `jq` isn't available.
  - **Read files with the Read tool, not `cat`** (RUN-002.D11). Shell output reaches Claude in the Windows console code page, so `—` and `§` come back as `�`. The files themselves are valid UTF-8.
- **Worktree base (RUN-002.D10):**
  - agent-office branches every worker worktree from whatever branch the main checkout is on.
  - The lead switches back to `main` right after pushing any docs branch.
  - Every worker starts its task with `git fetch && git rebase origin/main`, before its first push. Once its PR is open, it syncs with `git merge --no-edit origin/main` instead (RUN-008.D1).
- **Line endings:** LF everywhere, enforced by `.gitattributes`. Never commit CRLF shell scripts or Dockerfiles.
- **Image folders:** source and results are Windows-drive bind mounts (`/source` read-only, `/results`); their paths are only in the local `.env`. Bind-mount I/O is slower than native. `watch` and dev auto-reload must poll, because file events don't propagate. Paths contain spaces, so always quote them.
- **GPU stack:** the RTX 5080 (Blackwell) needs PyTorch built for CUDA 12.8+ (`cu128`+).
- Remote backends (`sanitizer.backend: claude`, `rag.web_backend: brave|claude`) need `docker-compose.egress.yml` and stay off by default.
- agent-office comes from the fork `https://github.com/ComeGalletas/agent-office`, built from source in `file-sorter-full\agent-office` and linked globally (`npm install -g .`). Its `install.sh` and `install.ps1` download upstream releases, so never use them.
  - Start it with this repo as its `[dir]`, so this checkout becomes the floor (RUN-003.D1).
  - It keeps its data and the workers' worktrees in `.agent-office/`, which is git-ignored, and names worker branches `office/*`.
- The adult VLM tag (`models.vlm_nsfw`) is intentionally unset until M5. Never pick one; the M5 G0 plan asks the human.

## Keeping this file honest

- This file, DESIGN.md and memory must not disagree. When a standing rule changes, change all three in the same step and record the change as a decision (`DOC-<NNN>.D<n>`) in the relevant journal.
- The process standard (§1, §2.1, §2.3, §2.4, §3) was adopted from the human's pygame project as DOC-001. Where the two differ, this file wins for this repo; see `docs/journals/process_standard_journal.md`.
