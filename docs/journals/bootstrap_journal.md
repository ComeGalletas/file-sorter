# Bootstrap — journal

**ID:** RUN-001 (+ RUN-002, RUN-003, RUN-004, RUN-005, RUN-006, RUN-007, RUN-008) · **Systems:** RUN (+ CFG, TST, DOC) · **Type:** feature · **Status:** done (RUN-002 with concerns); RUN-004 proposed · **Milestone:** — (runbook steps 3–5 and their follow-ups) ·
**Issues:** — (before the issue queue exists) · **Branch:** main for the bootstrap; one human-side PR branch per follow-up (RUN-007: `run-007-network-rule-scope`)

---

## RUN-001 — Requirement (human, 2026-10-05)

- **Objective:** Bootstrap the repo and its Docker runtime (runbook step 3), and publish it as the public GitHub repo `ComeGalletas/file-sorter`.
- **Details:**
  - `docker-compose.yml` (db, ollama, searxng, app, test) plus the egress and purge overrides.
  - `Dockerfile` with PyTorch for CUDA 12.8+.
  - `Makefile` (init, up, down, models, test, test-gpu, lint, gate-N).
  - `config.yaml`, `sanitize.example.yaml`, `.env.example`, `pyproject.toml`.
  - Empty packages and test-tier folders.
  - `make models` pulls every model except the adult VLM.
- **Constraint:**
  - Nothing private enters the public repo: no `.env`, labels, images, host paths or real names.
  - The source folder is mounted read-only.
  - Ports bind to 127.0.0.1 only.
- **Implements:** R-RUN-1 to R-RUN-5, R-MOD-2, R-FOP-8, R-CFG-1, DESIGN §6, §9, §9a, §10.

## RUN-001 — Confirmed reading

- **RUN-001.D1:** Pinned images:
  - `ollama/ollama:0.35.1` (latest, 2026-09-29; Qwen3-VL support predates it);
  - `pgvector/pgvector:0.8.7-pg16`;
  - `searxng/searxng:2026.10.4-d48c4b555`;
  - `ghcr.io/astral-sh/ruff:0.16.10`.
  
  All were looked up in their registries on 2026-10-05.
- **RUN-001.D2:** PyTorch `2.14.1` from the `cu130` index. That satisfies R-RUN-5 (CUDA ≥ 12.8 for Blackwell sm_120), and host driver 610.62 supports CUDA 13.
- **RUN-001.D3:** The base image is `python:3.12-slim` with PyTorch's CUDA wheels, which bundle the CUDA runtime. There is no `nvidia/cuda` base image; Docker Desktop provides the driver.
- **RUN-001.D4:** Two networks:
  - `internal`, with no internet route: db, app, test.
  - `egress`: ollama (for model pulls) and searxng (it forwards queries).
  - The Hugging Face downloads run in a separate one-off `fetch` service (profile `tools`) on `egress`, so `app` never needs internet (R-MOD-2).
- **RUN-001.D5:** Docker cannot publish a port for a container that is only on an `internal` network. So `app` publishes nothing until M4, which adds a localhost-only proxy (`127.0.0.1:8000` → `app:8000`) on its own network. That keeps `app` off the internet while the UI stays reachable (R-API-1).
- **RUN-001.D6:** The `test` service has **no** source or results mounts. "Tests never read the human's folders" is enforced by the container layout, not by discipline. Tests see the repo, which includes the git-ignored `fixtures/`.
- **RUN-001.D7:** `.dockerignore` lets only `pyproject.toml` and `classifier/` into the build context, so images, `.env` and labels can never end up in an image layer.
- **RUN-001.D8:** `make init` generates `DB_PASSWORD` and `SEARXNG_SECRET` into the local `.env`. `.env.example` documents them without values.
- **RUN-001.D9:** Dependencies are declared with lower bounds. A lockfile is deferred to a follow-up (RUN-004), because resolving torch from a custom index needs its own task.
- **RUN-001.D10:** Commits use a repo-local git identity, the same one as the human's other repo. The global git config is untouched.
- **RUN-001.D11:** `app` idles (`sleep infinity`) until M1 adds real CLI commands. It exists now so `docker compose run/exec app classifier …` works from day one.

## RUN-001 — Plan

1. Scaffold the files, all under the ownership exception for bootstrap (CLAUDE.md "Roles").
2. `make init` → `make up` → `make test` (smoke and db-reachability tests) → `make models`.
3. Privacy check of `git ls-files`, then `gh repo create --public` and push.

## RUN-001 — Tasks

- [x] RUN-001.1 — Python project: `pyproject.toml`, `classifier/` packages, CLI stub, `.dockerignore`, `Dockerfile` → `da82362`
- [x] RUN-001.2 — Runtime: `docker-compose.yml`, egress and purge overrides, SearXNG settings, `config.yaml`, `sanitize.example.yaml`, `.env.example` → `002aebd`
- [x] RUN-001.3 — `Makefile` and `scripts/fetch_models.py` → `f881ad2`
- [x] RUN-001.4 — Test tiers by path (`tests/conftest.py`), a smoke test and a db-reachability test → `2aadb2c`
- [x] RUN-001.5 — Verify `make up` and `make test` in Docker → `3d401d9`
- [x] RUN-001.6 — `make models`: Ollama tags and HF weights into volumes → `8b340ae`
- [x] RUN-001.7 — README; privacy check; public GitHub repo; push

## RUN-001 — Results

- **Status:** DONE_WITH_CONCERNS.
- **RUN-001.7 (2026-10-05):**
  - The privacy sweep checked all 75 files: host paths, user names, emails, secrets, image files, private files and the words specific to the human's labels. Its one real hit, an example row echoing a real label, was fixed in CLS-001.7.
  - `gh repo create ComeGalletas/file-sorter --public`. The first push of `main` went through the pre-push gate (3 passed) with `ALLOW_MAIN_PUSH=1`, the bootstrap exception.
  - GitHub's file tree shows 75 files and none forbidden.
  - The commit author is the human's existing identity, so its email is public. Switching future commits to the GitHub noreply address is offered to the human.
- **Triage:** large (new runtime contract) · tests: unit + db tiers, plus live checks inside the running stack · solo.
- **Verified in the running stack (2026-10-05):**
  - `make up`: all four services up, db healthy.
  - `make test`: 3 passed (unit 2, db 1).
  - `/source` mounted `ro`, `/results` `rw`.
  - `app` can't reach the internet (connection to 1.1.1.1:443 refused).
  - The `test` container has no `/source` or `/results`.
- **GPU:** RTX 5080, capability (12, 0), torch 2.14.1+cu130 (CUDA 13.0); a matmul on the GPU works.
- **Services:** ollama 0.35.1 answers; searxng healthz returns 200.
- **Models, loaded offline (`HF_HUB_OFFLINE=1`):**
  - SigLIP image vector 1152-d and bge-m3 1024-d, so C-4 holds.
  - SigLIP + NSFW together use 2.0 GiB of VRAM.
  - The NSFW model labels a synthetic image `normal` at 0.998.
  - qwen3-vl:8b answers correctly; its first call takes 58 s (a cold 6 GB load), which supports per-stage batching (R-PIPE-1).
- **Timings:** image build 6 min 56 s; `make models` 3 min 45 s (Ollama 7.3 GB, HF ~3.8 GB).
- **Lessons:**
  - Git Bash rewrites container paths in `docker run` (`-w /io`), so `MSYS_NO_PATHCONV=1` is required.
  - Bash heredocs in this environment mangle backslash escapes, so generated files come from script files.
- **Concerns:**
  - No lockfile yet (D9 → follow-up RUN-004).
  - The UI port waits for the M4 proxy (D5).
  - Mounting `/results` created the empty results root on the host.
- **Self-rating:** 9/10, proud: yes. Gap: dependency versions float until RUN-004.

---

## RUN-002 — Requirement (human, 2026-10-05)

- **Objective:** Configure the agent team in the repo (runbook step 4): role briefs, subagents, permissions, hooks, the pre-push gate, GitHub templates and gate stubs.
- **Details:**
  - Permissions: C-16 (the lead's allow/deny rules).
  - Hooks: C-17 (ruff per edit, touched tests on `Stop`, full suite plus acceptance test at pre-push).
  - Logs: C-18 (per-role local logs).
  - Test-runner history: DOC-001.D9.
- **Constraint:**
  - Hooks are POSIX shell for Git Bash.
  - Nothing is installed on the host; lint runs in the ruff container.
  - Agents never read `.env`, `sanitize.yaml`, the labels or the fixture images.
- **Implements:** CLAUDE.md §2–§3, DESIGN.md §12.

## RUN-002 — Confirmed reading

- **RUN-002.D1:** **Desk role briefs live in `.claude/roles/`, not `.claude/agents/`** (a deviation from the plan's runbook step 4). Anything in `.claude/agents/` is a subagent any session may delegate to. A lead delegating a code task to a "pipeline-engineer" subagent would edit code in the lead's own tree, which breaks "the lead writes no code" and the one-worktree-per-task rule. Only the three read-only subagents (reviewer, privacy-auditor, test-runner) are in `.claude/agents/`.
- **RUN-002.D2:** **Each linked worktree gets its own compose project** (`file-sorter-<worktree>`), so parallel test runs never share `db-test`. The `ollama` and `hf` volumes have fixed names, so every project shares the downloaded models. `pgdata` stays per project.
- **RUN-002.D3:** `make init` in a linked worktree copies `.env` and `sanitize.yaml` from the main checkout. Compose needs the `.env` values to parse at all, and a worktree only has tracked files.
- **RUN-002.D4:** Every worktree has a git-ignored `.task` file with `key=value` lines: `role=`, `issue=`, `acceptance=` (a pytest path or `scripts/gate_N.py`).
  - On a task branch (`<sys>-<nnn>…`), the pre-push hook runs the acceptance test, and blocks the push if none is named.
  - The log hooks read the role and issue from the same file. A desk can't set environment variables for its own hooks, and this avoids calling GitHub from a hook.
  - It replaced a first draft that used a `.acceptance` file.
- **RUN-002.D5:** The pre-push hook blocks direct pushes to `main` unless `ALLOW_MAIN_PUSH=1` is set. Only the bootstrap uses it; afterwards `main` changes only through `gh pr merge`.
- **RUN-002.D6:** Three settings layers:
  - `.claude/settings.json` applies to everyone: hooks, safe allow-list, and denies for secrets, labels, images, force pushes, `--no-verify` and the purge override.
  - `settings.worker.json` adds `acceptEdits` and denies merging.
  - `settings.lead.json` allows merging and issue management, and denies edits outside `docs/` and tagging `mN-approved` (the human's gate).
- **RUN-002.D8:** **The roles are enforced by a location-aware PreToolUse guard, not only by per-desk settings files.** agent-office launches every desk with its *own* `--settings` file (its hook bridge; `src/server/providers/claude.ts`), so our `settings.lead.json` and `settings.worker.json` can't be attached to its desks. They stay for desks launched by hand. `.claude/hooks/guard.sh` sits in the shared `settings.json`, which always loads, and acts only when `AGENT_OFFICE_WORKER_ID` is set (agent-office sets it for every desk), so the human's own sessions are never guarded:
  - **Linked worktree = worker:** no `gh pr merge`, `git merge`, `git tag` or push to `main`; no edits to the index, plans, DESIGN.md or CLAUDE.md.
  - **Main checkout = lead:** edits only under `docs/` (and `.task`); `gh pr merge` only with `--merge`; no `mN` tags.
- **RUN-002.D9:** agent-office names its branches `office/*`. The pre-push gate treats them as task branches, so the acceptance test in `.task` is required. Without this, every agent-office branch would have skipped the acceptance check.
- **RUN-002.D10:** **agent-office creates every worker worktree from the branch the main checkout is on** (`startPoint()` in its `src/server/worktrees.ts`). In the first dry-run attempt, both workers forked from the lead's unmerged `harness-plan` commit (`96090c5`). Two fixes:
  - The lead switches the main checkout back to `main` right after pushing a docs branch.
  - Every worker starts with `git fetch && git rebase origin/main`.
- **RUN-002.D11:** **Agents read files with the Read tool, not `cat`.** In the first attempt, workers reading the journals through Git Bash saw `—` and `§` as `�`, because shell output reaches Claude in the Windows console code page. The files are valid UTF-8 (checked: 19 em dashes, 3 `§`, LF only). Only the shell path mangles them.
- **RUN-002.D12:** **agent-office's Changes window is view-only for us.** Its UI source describes it as the files a desk changed and their diff "against the branch the office was opened on, with commit / discard / open-a-PR" (`src/client/ui/changes.ts`). Its buttons would bypass three rules: commit subjects with IDs and journal ticks, never discarding a desk's work, and the PR template. The human asked for this rule on 2026-10-06.
- **RUN-002.D13:** **The index lags GitHub on purpose.** Updating it at every merge would mean a docs PR per merge, or the lead leaving `main` (against D10). Workers can't edit it (guard). In the step 6 run, the lead simply skipped it. So:
  - Between checkpoints, the issue's state on GitHub is the live status.
  - The lead brings the rows in line in its next docs PR, at G1 at the latest, and the G1 check requires them to match.
- **RUN-002.D14:** **Review verdicts go on the PR.** In step 6, the reviewer and auditor ran on every PR, but their verdicts lived only in the lead's local transcripts, so GitHub showed merges with no visible review. The lead now posts both verdict lines and the one-line findings as a PR comment before merging. The auditor never quotes private data, so its summary is safe in a public repo.
- **RUN-002.D15:** **A push that only deletes branches skips the test run.** Deleting a remote branch publishes no code, and a red working tree shouldn't be able to block a cleanup. The `main` rule still applies first.
- **RUN-002.D16:** **Human-side PRs are a defined path** (CLAUDE.md "Sources of truth" item 5). They come from the human's own session (the human, or Claude working in it), from any branch or worktree. They may change DESIGN.md, CLAUDE.md and the agent config. The guard ignores them by design, because they carry no `AGENT_OFFICE_WORKER_ID`. They are reviewed and merged like any PR, and they never edit the index. This came from PR #7's review, finding 3: RUN-002.10 had edited the index itself, against D13 and against "only the lead edits it", and those edits were withdrawn.
- **RUN-002.D7:** The hooks parse their JSON input with `sed`. `jq` isn't on Git Bash, and host Python isn't a project dependency.

## RUN-002 — Tasks

- [x] RUN-002.1 — Hook scripts (`.claude/hooks/`) and the pre-push gate (`.githooks/pre-push`) → `c1f12b9`
- [x] RUN-002.2 — Settings layers (D6) and worktree-aware Makefile and compose (D2, D3) → `558860b`
- [x] RUN-002.3 — Subagents (`.claude/agents/`) and desk role briefs (`.claude/roles/`) → `adfa4ef`
- [x] RUN-002.4 — GitHub issue and PR templates; `scripts/gate_1.py`–`gate_8.py` stubs that fail → `4b40370`
- [x] RUN-002.5 — Verify: a lint finding comes back from an edit; a failing test blocks a push; logs land per role
- [x] RUN-002.6 — CLAUDE.md and DESIGN.md updated for D1–D6 (phase, roles location, `.task`, ALLOW_MAIN_PUSH rule, MSYS note, §9 as built, §10 layout)

- [x] RUN-002.7 — Role guard (D8), `office/*` task branches (D9), `.agent-office/` git-ignored and excluded from lint; verified on agent-office-style worktrees → `b60dffe`
  - [x] RUN-002.7.1 — pre-push runs its cheap checks first (`.env`, acceptance named) before the suite
  - [x] RUN-002.7.2 — Bug fixed: a missing `.task` made the pre-push hook exit silently under `set -e`. Found by the guard verification.

- [x] RUN-002.8 — Fixes from the first dry-run attempt: lead stays on `main` and merges with `--delete-branch`; workers rebase first and read with the Read tool (D10, D11). Opened as a PR for the lead to review and merge.

- [x] RUN-002.9 — Roles README: the Changes window is view-only (D12)

- [x] RUN-002.10 — Review trail and status rules from the step 6 run: verdicts posted on the PR (D14), index lags GitHub until the lead's next docs PR or G1 (D13), `gh pr comment` allowed, deletion pushes skip tests (D15). Standard labels created on GitHub (`blocked`, `m1`–`m8`, `role:*`); `blocked` added to #3; `origin/harness-plan` removed.
  - [x] RUN-002.10.4 — Review finding 4: `tests/unit/test_pre_push.py` (deletion-only, deleting main, pushing to main, mixed push) in a throwaway repo; `git` added to the image after the torch layer (rebuild 1 min)
  - [x] RUN-002.10.5 — Review findings 1–2: index edits withdrawn (the lead reconciles them, D13); RUN-002.10 Results entry; RUN-003.2 ticked, RUN-003 done
  - [x] RUN-002.10.6 — Review finding 3: human-side PRs documented (CLAUDE.md "Sources of truth" item 5, D16)

- [x] RUN-002.11 — Stale lines after the bootstrap: CLAUDE.md's "Current phase" (steps 5–6 and RUN-005 to RUN-007 are done; next is M1 G0), and `reviewer-quick` (RUN-006) added to the subagent lists in CLAUDE.md, DESIGN.md §10 and §12, and the roles README. DESIGN.md §10 also lists `scripts/review_route.sh`.

## RUN-002 — Results

- **Status:** DONE_WITH_CONCERNS.
- **Triage:** large (agent contract) · verification script with 22 scenarios on a real linked worktree and a local bare remote · solo.
- **Verified (RUN-002.5), 22 of 22 passed:**
  - The lint hook returns ruff's F401 for an unused import (exit 2), passes clean files and skips non-Python files.
  - The log hook writes valid JSON under the role's folder.
  - In a worktree: `make init` copies `.env` and `sanitize.yaml`; `.task` is ignored; `make test` uses `file-sorter-<worktree>`.
  - The Stop hook blocks on a failing touched test, doesn't loop, and logs the failure under the `.task` role.
  - The pre-push gate blocks: a failing unit test, a direct push to `main`, and a missing acceptance test.
  - The pre-push gate passes a green branch with a passing acceptance test, and the remote receives it.
  - Cleanup leaves no worktree, branch, compose project or files.
- **Not yet verified:**
  - Claude Code itself invoking the hooks through `settings.json`;
  - the allow and deny rules taking effect in a live session;
  - desks started with the settings layers.

  These need running desks: runbook step 6, the harness dry run.
- **RUN-002.7 verification (guard suite), 29 of 29 passed, on real worktrees under `.agent-office/worktrees/`:**
  - Lead: every allowed action passes and every denied one is blocked.
  - Worker: every allowed action passes and every denied one is blocked.
  - The human's session is not guarded.
  - `.agent-office/` is invisible to git and to ruff.
  - On an `office/*` branch the gate fails fast twice: first for no `.env` ("run 'make init'"), then for no acceptance test, before any test runs.
  
  The RUN-002.5 suite still passes 22 of 22 after the changes.
- **RUN-002.8 (PR #4), DONE:**
  - Triage: small, docs only (CLAUDE.md, role briefs, this journal).
  - Tests: unit 2/2, db 1/1, integration none yet; acceptance `tests/unit/test_smoke.py` 2/2.
  - Self-rating: 9/10, proud: yes.
  - Review: Reviewer REQUEST_CHANGES, for a missing Results entry (this one) and unconfirmed authorship of the CLAUDE.md rule changes. The human confirmed authorship on 2026-10-05. Privacy auditor PASS.
- **RUN-002.9 (PR #6), DONE:**
  - Triage: small, docs only (roles README, this journal).
  - Tests: unit 2/2, db 1/1, integration none yet; acceptance `tests/unit/test_smoke.py` 2/2.
  - Self-rating: 9/10, proud: yes.
  - Review: Reviewer REQUEST_CHANGES for the missing Results entry, again (this one; the lead added it). Privacy auditor PASS.
  - **Recurring gap (proposal, the human decides):** keep the PR template checklist on human-side docs PRs; it would have caught this both times.
- **RUN-002.10 (PR #7), DONE:**
  - **Triage:** medium. Process rules for the lead, plus one behavior change in `.githooks/pre-push` (deletion-only pushes).
  - **Review round 1:** Reviewer REQUEST_CHANGES, Privacy auditor PASS, posted on the PR, which is the first live use of D14. All four findings were accepted:
    1. This Results entry was missing.
    2. The index had been edited without matching journals. The index edits were withdrawn; the lead reconciles them (D13).
    3. Human-side PRs weren't documented (→ D16).
    4. The hook's behavior change had no committed test (→ RUN-002.10.4).
  - **Tests:** unit 8/8 (4 of them new: `tests/unit/test_pre_push.py`), db 1/1, integration none yet; acceptance `tests/unit/test_smoke.py` 2/2.
  - **Regression check:** with the deletion shortcut removed from the hook, exactly `test_deletion_only_push_skips_the_test_run` fails (1 failed, 3 passed). With the hook restored, 4 passed.
  - **Self-rating:** 9/10, proud: yes. Gap: D14 relies on the lead following its brief; nothing blocks a merge without a verdict comment.
- **Live probe, after step 6 (QA desk, 2026-10-06):**
  - Worker `gh pr merge` → `BLOCKED by the role guard … workers never merge or tag`.
  - Worker edit of DESIGN.md → `BLOCKED by the role guard … only the human changes DESIGN.md and CLAUDE.md`. The first attempt didn't reach the guard: Claude Code's auto-mode classifier refused a harmless `tail | od` read beforehand. A retry with a read-free Edit hit the guard.
  - Unused import → the lint hook fed ruff's F401 back as a blocking hook error.
  - The worktree stayed clean and nothing was pushed. The desk was sent home with its worktree and branch deleted.
  - **The hooks and the role guard are now verified in live agent-office desks.**
- **Self-rating:** 9/10, proud: yes. Every hook and gate has now fired in a live desk. Remaining gap: the D14 verdict comment isn't enforced mechanically.
- **RUN-002.11, DONE:**
  - Triage: small, docs only (CLAUDE.md, DESIGN.md §10 and §12, the roles README, this journal). No behavior change, no rule change: status lines and lists brought in line with what's on `main`.
  - Tests: the default tiers and the acceptance `tests/unit/test_smoke.py`, run by the pre-push gate; counts in the PR body.
  - Self-rating: 9/10, proud: yes. Gap: the phase line goes stale again at each milestone; the lead's G1 report is the natural place to flag it to the human.
  - Review (PR #12, routed to the full `reviewer` because it touches `.claude/roles/`):
    - Round 1: REQUEST_CHANGES. DESIGN.md §12 still listed three subagents (minor). Privacy auditor PASS.
    - Round 2, scoped to `855b268..52a8b92`: APPROVE. Privacy auditor PASS.
    - Merged as `1d2c857`. Recorded by the lead.
- **Closed, done with concerns** (the human, 2026-10-06; recorded by the lead in the M1 plan PR). Concern: nothing mechanically stops a merge that has no D14 verdict comment. It relies on the lead's brief, which RUN-006 extended with the reviewer used and `Reviewed at`. Follow-up: if a merge ever lands without the comment, give it a new RUN ID for a check, for example in the route script or a merge hook.

---

## RUN-003 — Requirement (human, 2026-10-05)

- **Objective:** Install agent-office from the fork clone in `file-sorter-full\agent-office` (runbook step 5).
- **Details:** `npm install` (which also builds) and `npm install -g .`, per its README.
- **Constraint:** The first start (GitHub sign-in, code folder, floor) is the human's. The repo path stays fixed (DOC-003.D3).

## RUN-003 — Tasks

- [x] RUN-003.1 — `npm install` (16 s, builds `dist/`) and `npm install -g .`, which links to the fork clone, so a rebuild updates the command; `agent-office --help` answers. The fork's working tree is untouched.
- [x] RUN-003.2 — Human: first start with the repo as `[dir]` (command in `.claude/roles/README.md`), 2026-10-05
- [x] RUN-003.3 — Answered from agent-office's help and source, before the first start:
  - **Existing clone:** `agent-office <dir>` makes that checkout a floor. No junction and no second clone, which resolves DOC-003.D3.
  - **Data:** its data lives in `<dir>/.agent-office/` (password and state), which is git-ignored.
  - **Worktrees:** worker worktrees go in `<dir>/.agent-office/worktrees/`, on the same drive, with branches named `office/*` (→ RUN-002.D9).
  - **Settings:** every desk is launched with agent-office's own `--settings` (→ RUN-002.D8), and `AGENT_OFFICE_WORKER_ID` is set for each desk.

## RUN-003 — Confirmed reading

- **RUN-003.D1:** Start command: `agent-office "<workspace>/file-sorter" --projects "<workspace>" --max-workers 4`.
  - Passing the repo as `[dir]` adopts this checkout.
  - `--projects` keeps any future floor inside the workspace.
  - `--max-workers 4` is the plan's 3–4 desk ceiling.
  - It binds to 127.0.0.1 by default.
- **RUN-003.D2:** The lead desk is hired **without** a worktree, so it works in the main checkout (the guard treats the main checkout as the lead). Every worker desk gets its own worktree.
- **RUN-003.D3:** `npm audit`: 12 findings (6 moderate, 6 high), **all in dev and build dependencies**. `npm audit --omit=dev` finds 0 in what the running office loads. No `npm audit fix`: it would rewrite the fork's lockfile, and that's the human's call on their fork.

## RUN-003 — Results

- **Status:** DONE. The office runs with this checkout as its floor, and runbook step 6 passed in its desks (below).
- **RUN-003.2 (2026-10-05):** the office started with the repo as `[dir]`.
  - The floor shows `file-sorter`; there is still one clone.
  - Its data is in the git-ignored `.agent-office/`, and `git status` is clean.
  - It listens on `127.0.0.1:4600` only.

### Runbook step 6, first attempt (2026-10-06, 02:05–02:11 UTC)

**Proved live:**
- The repo's `settings.json` hooks run inside agent-office desks alongside agent-office's own `--settings`: events were logged from all five desk sessions.
- The lead wrote `.task role=lead` and logged under `lead/`.
- The lead planned CLI-001 and TST-001 through PR #1, ran 3 subagent passes, and merged with a merge commit (`4e85ab3`).
- The lead opened issues #2 and #3 from the template, with the right titles and labels.
- Both workers refused to start on a placeholder issue number (`#<A>`, `#<B>`), citing CLAUDE.md §2.2, and stopped without guessing.

**Not reached:** the worker plan comment → approval → build → Stop-hook tests → pre-push gate → PR → review → merge, and a live role-guard block.

**Causes:**
- The worker prompts were pasted with placeholders, before the lead had opened the issues.
- The workers forked from the lead's docs branch (→ D10).
- The lead left `harness-plan` on GitHub (→ merge with `--delete-branch`).

**Next:** resume both existing worker desks with the real issue numbers, after RUN-002.8 merges.

### Runbook step 6, completed (2026-10-06, 02:24–02:32 UTC)

**Exit criterion met:** one closed issue with a merged PR (#2 → PR #5), and one open issue whose branch the gate refused (#3, never on GitHub).

**Proved live in agent-office desks:**
- Workers rebased on `origin/main`, ran `make init`, wrote `.task`, and logged under `pipeline/` and `qa/`.
- Both posted a triage block and a plan before coding. The lead approved #2's plan and corrected its triage from small to medium (a behavior change), and the worker followed the correction.
- The Stop hook ran the touched tests: `StopTests: pass` (pipeline) and `fail` (QA, by design).
- The pre-push gate: Pipeline `pre-push: all gates passed`; QA `1 failed, 3 passed … pre-push BLOCKED: default test tiers failed`, `rc=1`, no `--no-verify`, and no branch on GitHub.
- PR #5 used the template: `Closes #2`, the corrected triage, tier counts, `DONE`, and a full self-rating (9/10 with a named gap). One commit, `CLI-001.1.1`. Merge commit `77a897c`; branch deleted; #2 closed by the PR.
- Reviewer `VERDICT: APPROVE` and auditor `PRIVACY: PASS` on PR #5, and the same pair on #1, #4 and #6.
- After a merge, a worker's worktree is removed when it goes home.

**Gaps, all addressed in RUN-002.10:**
- The index was not updated (→ D13).
- The verdicts were not visible on GitHub (→ D14).
- The `blocked` label didn't exist, so #3 lacked it (labels created).
- The stale `harness-plan` branch (removed).

**Prompt-induced, not a process gap:** the QA desk pushed without the lead approving its plan, because its first message from the human said to expect the push to be blocked.

**Not yet exercised live:** a role-guard block, and a lint-hook finding. No desk attempted a forbidden action or wrote lint-failing code; the live probe after this PR covers both.


---

## RUN-005 — Requirement (human, 2026-10-06)

- **Objective:** Fix four runtime-hygiene problems found after runbook step 6, before M1 starts.
- **Details:**
  1. Every worktree test run prints a compose warning about the shared `file-sorter_hf` volume.
  2. `§` in hook messages reaches the desks as `�`.
  3. The desks' job logs land in `.agent-office/worktrees/agent-logs/` instead of the workspace's `agent-logs\`.
  4. The role guard blocked the lead from saving to its own memory, a folder outside the repo.
- **Constraint:**
  - The guard must not get weaker inside the repo.
  - Every behavior change ships its test (CLAUDE.md §3).
  - The index is the lead's to update (D13, D16). RUN-004 stays reserved for the deferred lockfile (RUN-001.D9), so the lead adds rows for RUN-004 and RUN-005, and Next free becomes RUN-006.
- **Implements:** RUN-002.D2, D8, D11; CLAUDE.md §2.2.

## RUN-005 — Confirmed reading

- **RUN-005.D1:** **The guard governs the repo tree, not the whole disk.**
  - Before: for the lead, anything that wasn't `docs/` or `.task` was denied, including paths **outside** the repo: its Claude memory and its own job logs in `agent-logs\lead\`.
  - Before, for workers: only the index, plans and spec were denied. A worker could write into the **main checkout**, or another desk's worktree, through an absolute path. That's a hole.
  - Now:
    - **Lead (main checkout):** inside the main checkout tree, only `docs/` and `.task`. That tree includes `.agent-office/worktrees/`, so worker trees are covered too. Outside it, allowed.
    - **Worker (linked worktree):** inside its own worktree, the D8 rules. Anywhere else in the main checkout tree (the main checkout itself, or another desk's worktree), **denied**. Outside it, allowed.
  - Claude Code's own permission system still applies everywhere. The guard only enforces role separation inside the repo.
- **RUN-005.D2:** **The model volumes are `external: true`.**
  - Fixed names (RUN-002.D2) made each worktree's compose project warn that `file-sorter_hf` "was created for project file-sorter".
  - External volumes are shared by design and never claimed by a project.
  - `make init` creates them, idempotently with `docker volume create`, because compose doesn't create external volumes. The existing volumes keep their data.
- **RUN-005.D3:** **Hook messages are ASCII.** They say "section 2.2" instead of `§2.2`, because hook stderr reaches Claude in the Windows console code page (as in D11). The files themselves keep `§`.
- **RUN-005.D1, amended after PR #9 review round 1:** **Classification uses the real path, compared case-insensitively.**
  - String-prefix matching let a link or NTFS junction inside a worktree (`mklink /j escape <main checkout>`, no admin rights needed) make the main checkout's `CLAUDE.md` look like the worker's own: review finding 1, reproduced on this host.
  - Matching the protected names case-sensitively let `claude.md` or `index.md` through, although on NTFS they're the same files: finding 2, reproduced.
  - Now:
    - every target is resolved first: the target itself if it exists (catches a file symlink), else its nearest existing parent folder (`cd && pwd -P`, then `cygpath -m` on Windows);
    - this tree and the main checkout are resolved the same way;
    - every comparison is case-insensitive.
- **RUN-005.D5:** **No desk writes under `SOURCE_ROOT` or `RESULTS_ROOT`.** Review finding 3 noted that once the guard stopped governing paths outside the repo, the human's image folders were protected only by the containers' `:ro` mount (R-FOP-8) and the hard rule, not on the host. The guard now reads both roots from the main checkout's local, git-ignored `.env` (so no host path is committed) and denies every desk's write under them. Only the app writes there, through Docker. The human's own sessions are unaffected.
- **RUN-005.D6:** **Trailing dots and spaces are normalized away, the way Win32 does** (PR #9 review round 2, finding 1).
  - Win32 silently strips them from every path segment, so an Edit on `CLAUDE.md.` or `CLAUDE.md ` writes the real `CLAUDE.md`. This was reproduced on this host with a Windows tool.
  - Under MSYS, `[ -e ]` is false for such a name, so the guard matched the unresolved `claude.md.` and allowed it, on all three protected files.
  - The guard now strips trailing dots and spaces from each segment before any check. Lone `.` segments are kept, and `..` stays refused.
- **RUN-005.D7:** **Alternate data streams are refused** (round 2, finding 2; decided by the human on 2026-10-06). A `:` after the drive letter is denied in every desk write. The project never needs streams, and allowing them would let hidden content be attached to any file, protected or not.
- **RUN-005 note, 8.3 short names** (round 2, finding 3, info): short names like `CLAUDE~1.MD` aren't expanded. That's not exploitable today, because every protected name already fits 8.3 and so has no separate short alias. If a protected name ever grows past 8.3, resolve short names before matching.
- **RUN-005.D4:** **Job logs use the resolved path.** The README said to write `<AGENT_LOG_ROOT>/<role>/<issue>.md`, and `AGENT_LOG_ROOT` is the relative `../agent-logs`, which each desk resolved from inside its worktree. The README now gives the command that prints the absolute folder: `bash -c '. .claude/hooks/common.sh; log_dir'`. The test-runner already uses it. The two misplaced files from step 6 were moved by hand on 2026-10-06.

## RUN-005 — Tasks

- [x] RUN-005.1 — Guard governs the repo tree (D1) + `tests/unit/test_role_guard.py` in a throwaway repo with a real linked worktree
- [x] RUN-005.2 — External model volumes, created by `make init` (D2); verify that no warning appears in a worktree test run
- [x] RUN-005.3 — ASCII hook messages (D3) and the resolved job-log path in the roles README (D4)
- [x] RUN-005.5 — PR #9 review round 2: trailing dot/space normalization (D6), alternate data streams refused (D7), 8.3 note; 30 new tests; Win32 behavior checked on the host
- [x] RUN-005.4 — PR #9 review round 1: real-path resolution and case-insensitive matching (D1 amended), image folders protected (D5); 13 new tests; real NTFS junction checked on the host

## RUN-005 — Results

- **Status:** DONE (after review rounds 1 and 2 → RUN-005.4, RUN-005.5).
- **Triage:** medium. Behavior changes in the role guard and the compose volumes, plus message and docs fixes. Tests: all default tiers, a new 32-case guard suite, and a worktree compose run. Solo.
- **Guard (RUN-005.1):** `tests/unit/test_role_guard.py` runs 32 cases (lead, worker, human; edits and commands) in a throwaway repo with a real linked worktree under `.agent-office/worktrees/`. All 32 pass.
- **Regression check:** run against the old guard from `main`, **exactly the 5 new-behavior cases fail**:
  - the lead's memory write (the bug the lead hit);
  - a worker writing into the main checkout;
  - a worker writing into another desk's tree;
  - the `..` escape;
  - the same escape with backslashes.

  The other 27 pass under both versions, so no existing rule regressed.
- **Volumes (RUN-005.2):** a worktree test run now prints **0** `created for project` warnings (41 passed). The existing volumes kept their data (3.6 GB of HF weights), and the main stack still lists both Ollama models.
- **Messages and logs (RUN-005.3):**
  - There's no non-ASCII character left in any hook's `deny`, `fail` or `printf` output.
  - `log_dir` run from a worktree resolves to the workspace's `agent-logs/<role>`.
- **Tests (round 1):** unit 40/40 (32 new), db 1/1; acceptance `tests/unit/test_role_guard.py` 32/32; ruff check and format clean.
- **Review round 1 (PR #9):** Reviewer REQUEST_CHANGES, Privacy auditor PASS. Findings 1 (junction) and 2 (case) were reproduced on this host before fixing: a junction escape to the main checkout's `CLAUDE.md` gave exit 0, and so did `claude.md` and `docs/journals/index.md`. Finding 3 was closed (D5) rather than only documented.
- **RUN-005.4 tests:**
  - **Suite:** `tests/unit/test_role_guard.py` now has **45 cases**, all passing. The 13 new ones cover a directory and a file symlink out of the worktree, five case variants for the worker, the lead's case-folded `docs/` allowance, writes into both image folders from both desks, a case-folded image root, and the human still allowed there.
  - **Regression:** against the guard from before RUN-005.4, **exactly those 12 desk cases fail**; the human case and the earlier 32 pass under both.
  - **Bug found by the suite:** with an image root that doesn't exist, the parent walk reached `/` and produced `//x`, defeating the comparison. Fixed by trimming the trailing `/`.
  - **On this host:**
    - **NTFS junction:** a real `mklink /J escape <main checkout>` inside a worktree. With the new guard, the junction write, `CLAUDE.md`, `claude.md` and `docs/journals/index.md` all exit 2.
    - **Real `.env` paths** (7 probes): the source with backslashes and a space, a lowercase drive, and the results root are all blocked. A sibling folder that only shares a prefix, the lead's memory and the lead's journal are allowed. The lead's code edit is blocked.
- **Review round 2 (PR #9):** Reviewer REQUEST_CHANGES, Privacy auditor PASS. Round-1 findings 1 and 3 were confirmed resolved and finding 2 partly. New findings:
  1. trailing dot or space bypass (blocker);
  2. alternate data streams (minor);
  3. 8.3 short names (info).

  Findings 1 and 2 were reproduced on this host before fixing: `.`, ` `, `. .` and `:hidden` were all allowed on `CLAUDE.md`, `DESIGN.md` and `docs/journals/INDEX.md`.
- **RUN-005.5 tests:**
  - **Suite:** `tests/unit/test_role_guard.py` now has **75 cases**, all passing; the full default tiers pass 84/84. The 30 new ones cover 5 trailing-dot/space suffixes × 3 protected files, 3 stream forms × 3 files, the lead's stream, a dotted folder segment, and 4 controls (inner dots, a lone `.` segment, the lead's `docs/` with and without a trailing dot).
  - **Regression:** against the round-2 guard, **exactly the 26 attack cases fail**; the 49 others pass under both.
  - **On this host, fixed guard:** all 15 attack paths exit 2. A Windows write to `CLAUDE.md.` still lands in the real file, which is why the guard must normalize. The earlier junction reproduction and the 7 real-`.env` probes are unchanged.
  - **Hardlinks:** out of scope. They can't be told apart from ordinary files, and creating one needs a shell command, which the guard doesn't path-check by design.
- **For the lead (index, D13/D16):**
  - add rows for **RUN-004**: the deferred lockfile (RUN-001.D9), `proposed`;
  - add a row for **RUN-005**: this work, `done`;
  - set Next free to **RUN-006**.
- **Self-rating:** 9/10, proud: yes (after round 1). Round 1 rightly caught two bypasses that my first 32 cases missed. Gap: Bash-based writes, like `echo > file`, are outside the guard by design. It covers Claude's file tools and the merge, tag and push commands, not every shell command.


---

## RUN-006 — Requirement (human, 2026-10-06)

- **Objective:** Make reviews faster where depth isn't needed, without weakening them where it is.
- **Details:** The human asked whether a lower-reasoning reviewer would speed reviews up.
  - Measured review durations from the subagent transcripts (Sonnet reviewer, Haiku auditor):
    - docs-only and small PRs (#1, #4, #5, #6, #8): **1.3–4.6 min**;
    - PR #7: 7.0 + 4.2 min;
    - **PR #9, the role guard: 16.3, then 32.6+ min** (47 and 69 tool calls).
  - The privacy audit takes 0.6–2.5 min everywhere.
  - The long reviews were exactly the ones that found real holes: the junction bypass, the case bypass, the trailing dot. A blanket downgrade would cost the most where it matters.
- **Constraint:** Security-relevant paths keep the full Sonnet review with live reproductions. Which reviewer runs is decided mechanically, not by judgment.
- **Implements:** CLAUDE.md §2.2 step 5; RUN-002.D14.

## RUN-006 — Confirmed reading

- **RUN-006.D1:** **The reviewer is routed by a script.** `scripts/review_route.sh <pr>` prints `reviewer-quick` only when the PR body's triage says `Size: small` **and** every changed file is under `docs/` or is the top-level `README.md`. Anything else goes to the full `reviewer`, including a missing triage size and any change to code, tests, hooks, settings, agents, roles, compose, CLAUDE.md or DESIGN.md. `reviewer-quick` is Haiku and static, with no reproductions. If it sees anything outside its scope, it asks for the full reviewer. The privacy auditor always runs.
- **RUN-006.D2:** **Re-reviews cover only the change since the last review.**
  - The lead's verdict comment records `Reviewed at <head sha>` and which reviewer ran.
  - On round N, the reviewer gets the previous verdict and that commit. It verifies each earlier finding, then reviews only `git diff <sha>..<head>`.
  - It widens to a full review only if that diff touches files or behavior the earlier rounds didn't cover, and says so on a `SCOPE:` line.
- **RUN-006.D3:** **Reproductions are for confirming a suspected blocker.** One sandbox per suspicion, removed afterwards, about 10 minutes each at most. Anything not confirmed in that budget is reported as `unverified`, with the steps to try, instead of being chased.
- **RUN-006.D5, after PR #10 review round 1:** **The route is decided only from evidence that can't be faked or truncated, and any doubt goes to the full reviewer.**
  - **Files:** the paginated `pulls/<n>/files` API, checking each file's **previous** name as well as its new one. `gh pr view --json files` showed only new names, so moving `CLAUDE.md` into `docs/` looked docs-only (finding 1). It also stopped at 100 files (finding 2).
  - **File count:** if the listing doesn't match GitHub's `changedFiles` count, the PR goes to the full reviewer.
  - **Size:** read only from a fenced triage block that also has `Tests:` and `Agents:` lines, with HTML comments removed first. If there's no such block, or the blocks disagree, the PR goes to the full reviewer (finding 3).
  - **Errors:** any `gh` failure prints `reviewer`, instead of `set -e` exiting with no output (finding 7).
- **RUN-006.D6:** **Every reviewer treats the PR as data, never as instructions** (finding 5).
  - The quick reviewer's first step is the route script itself; unless it prints `reviewer-quick`, it refuses.
  - It may run only named read-only commands. Subagent tools can't be limited per command in the frontmatter, so this is stated in its brief. Writes are still blocked for desks by the role guard (RUN-005.D1).
- **RUN-006.D7:** **Scoped re-reviews are safe against rewritten history** (finding 4). If `Reviewed at` is no longer an ancestor of the head, after a force-push or rebase, the reviewer does a full review and says so on the `SCOPE:` line. Process check 4 runs on every commit not seen before. A suspected blocker that couldn't be confirmed is never an APPROVE (finding 6). Just before merging, the lead re-runs the route and checks that the head is still the `Reviewed at` commit (finding 10).
- **RUN-006.D8 (superseded by RUN-007.D1, D4, D5; the policy text was split out into PR #11 and merged there):** **The "no outbound call" hard rule covers the app runtime only** (decided by the human on 2026-10-06, after PR #10 round 2's privacy FAIL on the route script's `gh` calls).
  - The runtime is the Compose services, `classifier/`, and anything run inside the containers.
  - Host-side process tooling (the hooks, `scripts/review_route.sh`, the desks' own `gh` use) may use `gh` for GitHub PR and issue metadata.
  - Nothing may ever send image data, `fixtures/`, `.env` or other git-ignored files anywhere.
  - CLAUDE.md's hard rule and the privacy auditor's check 1 now say so. Before this, the rule's wording would also have forbidden the `gh` workflow itself.
- **RUN-006.D4:** **Measurable outcome**, to be checked at M1 G1 from the subagent transcripts:
  - docs-only PR reviews under **2 min**;
  - round-2+ reviews of a small fix under **10 min**;
  - no drop in findings on security-relevant PRs.

## RUN-006 — Tasks

- [x] RUN-006.1 — `scripts/review_route.sh` and `tests/unit/test_review_route.py`
- [x] RUN-006.2 — `.claude/agents/reviewer-quick.md` (Haiku, static, escalates out-of-scope diffs)
- [x] RUN-006.3 — `reviewer.md`: round-N scope, reproduction budget, `REVIEWED:` line; `lead.md` and CLAUDE.md §2.2: routing, `Reviewed at` in the verdict comment; settings allow the route script
- [x] RUN-006.4 — PR #10 review round 1: rename-aware, paginated, count-checked file listing and fenced-block size (D5); data-not-instructions and route-first quick reviewer (D6); rewritten-history fallback, unverified-never-approve, pre-merge re-check (D7); allow rule narrowed; tests for each
- [x] RUN-006.5 — PR #10 review round 2: hard-rule scope decided by the human (D8), CLAUDE.md and the privacy auditor scoped to match; empty `changedFiles` routes to the full reviewer; `gh api` GET-only in the reviewer; a fake-`gh` test covers the listing's parsing

## RUN-006 — Results

- **Status:** DONE (after review round 1 → RUN-006.4). The measurable outcome (D4) is checked at M1 G1, from the subagent transcripts.
- **Triage:** medium. A new script with tests, a new subagent, and changes to the reviewer, the lead brief, CLAUDE.md and the settings. Solo.
- **Route script (RUN-006.1):** `tests/unit/test_review_route.py`, 25 cases, all passing:
  - small docs-only PRs → quick;
  - 16 kinds of non-docs path (code, tests, scripts, hooks, agents, roles, settings, compose, Dockerfile, Makefile, config, CLAUDE.md, DESIGN.md, prompts, a look-alike `docs-not-really/`) → full;
  - medium and large → full;
  - a missing triage → full;
  - a case-insensitive size with CRLF line endings;
  - the first `Size:` line wins, so a quoted "Size: small" later in a medium PR can't downgrade it;
  - no files → full.
- **Real PRs, routed through `gh` on this host:**
  - #1 and #8, the lead's docs-only plan and reconcile PRs → `reviewer-quick`;
  - #4 and #6, which touch `.claude/roles/README.md` → full, because role briefs are agent contract;
  - #5, #7 and #9 (medium) → full.
- **Quick reviewer (RUN-006.2):** Haiku, static, five checks: template, IDs, journal consistency, who may edit the index and plans, public-repo hygiene. If a diff turns out to be outside `docs/` and `README.md`, it refuses and routes the PR to the full reviewer.
- **Full reviewer and lead (RUN-006.3):**
  - the reviewer opens with a `SCOPE:` line (full, or a re-review of `<sha>..<head>`), works to the reproduction budget, and closes with a `REVIEWED: <head sha>` line;
  - the lead's verdict comment carries which reviewer ran and `Reviewed at`;
  - the settings allow the route script.
- **Review round 1 (PR #10):** Reviewer REQUEST_CHANGES (5 major, 5 minor), Privacy auditor PASS. The lead couldn't run the route script from the unmerged branch (permission denied) and defaulted to the full reviewer, which was correct. All ten findings were accepted:
  1. renames;
  2. the 100-file cap;
  3. where the size is read from;
  4. rewritten history;
  5. prompt injection in the quick reviewer;
  6. an unverified blocker treated as approval;
  7. a `gh` failure printing nothing;
  8. the allow rule;
  9. missing tests;
  10. the pre-merge re-check.
- **RUN-006.4 tests:**
  - **Suite:** `tests/unit/test_review_route.py` now has **38 cases**, all passing. The new ones cover three renames into `docs/` judged by their old path, a rename inside `docs/` staying quick, a truncated listing (100 of 101), a matching count, a size outside a fence, a fence without `Tests:` and `Agents:`, a single-line and a multi-line HTML comment, disagreeing blocks, `Size: smaller`, and the `gh` fallback with nothing usable on PATH.
  - **Regression:** against the round-1 script, **exactly 10 fail**, the ones for findings 1, 2, 3 and 7. The 28 others pass under both (`smaller` was already handled).
  - **Real PRs on the host,** through the paginated, rename-aware API: #1 and #8 → quick; #4–#7, #9 and #10 → full. Unchanged, so the stricter triage parsing doesn't break the lead's real docs PRs.
- **Review round 2 (PR #10):** Reviewer APPROVE, scoped to `0ce96fd..21dc629` (ancestor confirmed). Round-1 findings 1–4 and 6–10 resolved; 5 partly resolved, because the quick reviewer's command limit is prose only, a residual risk recorded in D6. **Privacy auditor FAIL** on the route script's `gh` calls under the "no outbound call" hard rule. The lead held the merge for the human, who decided the rule's scope (D8).
- **RUN-006.5:**
  - **Rule scope:** CLAUDE.md's hard rule and the auditor's check 1 are scoped to the app runtime, per D8.
  - **Round-2 minors:**
    - an empty or non-numeric `changedFiles` now routes to the full reviewer, instead of silently skipping the count check;
    - the reviewer may use `gh api` for GET only;
    - the journal task order is fixed (.3 before .4).
  - **Tests:** a **fake `gh`** on `PATH` now drives the script's real `gh` path: docs-only → quick; a rename → judged by its old name; a count mismatch → full; and `""`, `null` or `many` as the count → full. `tests/unit/test_review_route.py` has **44 cases**; against the round-2 script, exactly the 3 unreadable-count cases fail.
  - **Limit:** the fake `gh` returns output already filtered, so the jq expression itself is exercised only by the real `gh`. That happens on every real routing, as with the real PRs above.
- **Watcher note (this session's tooling, not the repo):** the PR watchers had an invalid jq escape (`\*`) and hid their errors, so they never reported comments on #9 or #10. They were fixed to print "N new comment(s)" before extracting details, without hiding errors.
- **For the lead (index, D13/D16):**
  - add rows for RUN-004 (`proposed`), RUN-005 (`done`) and RUN-006 (`done`);
  - set Next free to **RUN-007**.
- **Self-rating:** 8/10, proud: yes. Gap: D4's speed-up is a prediction until M1's reviews are measured. And the quick reviewer's five checks are only as good as Haiku's reading of a diff, which is why its scope is limited to docs.

---

## RUN-007 — Requirement (human, 2026-10-06)

- **Objective:** Change the wording of the "no outbound call" hard rule, as the human ruled, in a PR of its own, before any code that relies on it.
- **Details:**
  - PR #10 (RUN-006) carried this policy change (its RUN-006.D8) together with the route script, whose `gh` calls needed it.
  - In round 3, the lead had the privacy auditor judge PR #10 against the **rewritten brief inside PR #10 itself**.
  - Claude Code's auto-mode security check flagged the resulting PASS as "Instruction Poisoning", and the lead held the merge.
  - The human chose to split the policy out.
- **Constraint:**
  - This PR changes only the rule wording: CLAUDE.md's hard rule and the privacy auditor's check 1.
  - It is audited under the rules **currently on `main`**, never under its own text.
  - PR #10 then merges `main` and is re-audited under the merged rules.
- **Implements:** CLAUDE.md "Hard rules"; DESIGN.md P-3.

## RUN-007 — Confirmed reading

- **RUN-007.D1:** **The "no outbound call" hard rule covers the app runtime only** (ruled by the human on 2026-10-06; recorded in PR #10 as RUN-006.D8).
  - The runtime is the Compose services, `classifier/`, and anything that runs inside the containers. That includes `scripts/gate_*.py`, which runs in the `test` container.
  - The `fetch` service and the opt-in egress backends remain the designed exceptions.
  - Host-side process tooling may use `gh` for GitHub PR and issue metadata.
  - **Nothing may ever send image data, `fixtures/`, `.env` or other git-ignored files anywhere.**
  - "Never send pixels to any remote service" is unchanged.
- **RUN-007.D2:** **A PR never changes the rules it's judged by.** Rule changes (CLAUDE.md, DESIGN.md, the reviewer and auditor briefs) go in their own PR, audited under the rules on `main`, and merge before any PR that depends on them. This is the lesson from PR #10 round 3.
- **RUN-007.D4:** **The host-tooling clause is exclusive, and it names the toolchain downloads** (PR #11 review round 1, finding 1).
  - **What the human confirmed**, on 2026-10-06, by choosing this option: "Only GitHub via gh for PR/issue metadata, plus download-only access to the registries the toolchain uses (images, packages, model weights). No other host, no uploads of file contents, never private files." So both clauses were confirmed, (a) GitHub and (b) toolchain downloads, not only the exclusivity. This answers round-2 finding 2.
  - Granting GitHub access alone left any other host, and any upload of file contents, neither allowed nor forbidden by CLAUDE.md.
  - ~~Host tooling may reach **only** GitHub through `gh` for PR and issue metadata, plus the declared toolchain's registries (container images, Python packages, model weights), **download only**.~~ **Superseded by D5:** the toolchain is the explicit list of five registries, download only, at build or setup time, with no model weights.
  - The reviewer's "GitHub only" text would have made `make build` (base images, PyPI, the PyTorch index) and the lint hook's `ghcr.io` ruff pull into violations.
  - CLAUDE.md and the auditor now use the same host-tooling list (finding 2), and the `fetch` exception names Hugging Face as its only host (finding 3).
- **RUN-007.D5:** **The toolchain is an explicit list: Docker Hub, `ghcr.io`, the Debian package archive, PyPI and `download.pytorch.org`** (PR #11 review round 2, finding 1; list confirmed by the human on 2026-10-06).
  - These are the five sources the repo pins today: the Dockerfile's base image, `apt-get` and `pip`; the Compose service images; the Makefile's and lint hook's ruff image.
  - Host tooling may use them **for downloads only, at build or setup time**, never from app runtime code. Adding one takes its own rule-change PR (D2), so a PR can't declare a registry and use it at the same time.
  - "Model weights" left clause (b) (round-2 finding 3). Weights arrive only through the runtime exceptions: the `fetch` container (Hugging Face) and the `ollama` container (the Ollama registry). Both are now named in CLAUDE.md and the auditor, together with SearXNG.
  - DESIGN.md P-3 gains a note that it governs the runtime, and that host tooling is limited by CLAUDE.md (round-2 note 4).
- **RUN-007.D3:** The PR #10 round-3 Reviewer's minor note on Makefile wording is applied here: "Makefile recipes that don't run in a container" instead of "the Makefile's host recipes".

## RUN-007 — Tasks

- [x] RUN-007.1 — CLAUDE.md hard rule and privacy auditor check 1 worded per D1 (and D3) → `5702a7d`
- [x] RUN-007.4 — PR #11 review round 2: explicit registry list at build/setup time (D5), the human's confirmation recorded verbatim (D4), weights tied to the runtime exceptions, DESIGN.md P-3 note
- [x] RUN-007.3 — PR #11 review round 1: exclusive host-tooling clause with toolchain downloads (D4), one host-tooling list in both files, Hugging Face named for `fetch`, journal header and hash
- [x] RUN-007.2 — After PR #11 merged (`2e2566f`), PR #10 merged `main` with a normal merge: no history rewrite, so `Reviewed at eb46eae` stays an ancestor. Conflicts: CLAUDE.md's rule and the auditor's check 1 took `main`'s RUN-007 text; `lead.md` combined RUN-006's routing with RUN-007.D2; the journal kept both. Next is a privacy re-audit of PR #10 under the merged brief.

## RUN-007 — Results

- **Status:** DONE.
  - RUN-007.1, .3 and .4 merged with PR #11 (`2e2566f`).
  - RUN-007.2 merged with PR #10 (`5401730`). PR #10 was re-audited under `main`'s merged brief: Reviewer APPROVE, scoped to the merge `eb46eae..eb8f471`; Privacy auditor PASS on the full PR.
  - The lead closed this status line in the M1 plan PR.
- **Review round 2 (PR #11):** Reviewer REQUEST_CHANGES (1 major, 2 minor, 1 note), Privacy auditor PASS under `main`'s brief. Round-1 findings all resolved. New findings:
  1. the toolchain was undefined;
  2. what the human confirmed was unclear;
  3. "model weights" was redundant;
  4. a DESIGN.md note was missing.
  
  All four were addressed in RUN-007.4. The registry list was confirmed by the human (D5).
- **Review round 1 (PR #11):** Reviewer REQUEST_CHANGES (1 major, 3 minor), Privacy auditor PASS, run from `main`'s brief as D2 requires. The reviewer confirmed that every other hard-rule bullet is unchanged byte for byte, and that auditor checks 2–4 are identical to `main`. All four findings were addressed in RUN-007.3. The wording for the major was confirmed by the human (D4).
- **Triage:** medium. A rule-contract change, wording only; no code, so no new tests (non-behavioral for the code). Tests: the default tiers via the pre-push gate.
- **For the lead (index, D13/D16):** add a row for RUN-007, and set Next free to **RUN-008**. This adds to the RUN-004 to RUN-006 rows already pending in the M1 plan PR.
- **Self-rating:** 9/10, proud: yes. Gap: the lesson (D2) is recorded here and in the lead's brief, but not enforced. The route script could send every PR that touches CLAUDE.md or `.claude/agents/` to a "policy" lane in the future.

---

## RUN-008 — Requirement (human, 2026-10-07)

**Objective:** a worker can bring `main` into its own open PR, and still nothing else.

**Details:** in M1, PR #28 (TST-002.2) conflicted with `main` after its round 2 approval. The lead asked the desk to merge `origin/main` in. The role guard refused every `git merge` on a worker desk, and a rebase would need a force-push, which the deny list blocks and which breaks `Reviewed at` (RUN-006.D7). So no worker could ever resolve a conflict with `main` on its own. The desk correctly refused to work around the guard. The same review found that `git pull` wasn't checked at all, although a pull is a merge.

**Constraint:** a guard change with regression tests, in a human-side PR (RUN-002.D16).

## RUN-008 — Confirmed reading

- **RUN-008.D1:** **A worker's only merge is `origin/main` into its own branch.** The guard allows exactly `git merge [--no-edit] [--no-ff] origin/main`, plus `git merge --abort` and `--continue`. Anything else is refused: another branch, extra refs, `-X`, `--squash` or `-m`. Each simple command is checked separately, including those after `;`, `&&`, `|`, inside `$(...)` or backticks, behind `git -c`/`-C`, or behind a prefix like `env`. Once a PR is open, workers sync by merging, never by rebasing. (human, 2026-10-07)
- **RUN-008.D2:** **A worker's only pull is `git pull --ff-only`, with no arguments.** It catches up with its own branch after someone else pushed to it, and can't merge anything. (follows from D1)
- **RUN-008.D3:** `gh pr merge` and `git tag` stay refused for workers, now also behind `git -c`/`-C` or extra spaces. The lead's rules are unchanged.

## RUN-008 — Tasks

- [x] RUN-008.1 — Guard: `worker_sync_ok` (D1, D2) and the per-command check for PR merges and tags (D3); 30 new cases in `tests/unit/test_role_guard.py` (one old case moved from refused to allowed); CLAUDE.md (§1.6, the guard bullet, migrations, the worktree base), the roles README (step 0), and the lead, Pipeline and RAG briefs

## RUN-008 — Results

- **Status:** DONE.
- **Triage:** medium. A behavior change in the guard; the tests are the role guard suite (the acceptance test).
- **Tests:** the default tiers, 297 passed; `make lint` clean.
- **Regression check:** with `main`'s guard restored, 15 of the new cases fail, and with the new guard all pass:
  - **6 sync cases** were refused, because the old rule refused every merge;
  - **9 refused cases** were let through by the old guard: `git -c … merge`, `git -C … merge`, a merge in backticks, four `git pull` forms, `git -c … tag`, and `gh  pr merge` with two spaces. So the per-command check also closes old gaps (D2, D3).
- **Self-rating:** 9/10, proud: yes. Gap: the guard checks command text, not git's behavior. A merge started some way the patterns don't name would get through, and the reviewer is the backstop, as for every Bash rule (RUN-005 Results).
