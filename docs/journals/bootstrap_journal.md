# Bootstrap — journal

**ID:** RUN-001 · **Systems:** RUN (+ CFG, TST, DOC) · **Type:** feature · **Status:** in progress · **Milestone:** — (runbook steps 3–5) ·
**Issues:** — (before the issue queue exists) · **Branch:** main (bootstrap is the one exception to PR-only work)

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
  - The privacy sweep checked all 75 files: host paths, user names, emails, secrets, image files, private files and the 110 words specific to the human's labels. Its one real hit, an example row echoing a real label, was fixed in CLS-001.7.
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
- **RUN-005.D4:** **Job logs use the resolved path.** The README said to write `<AGENT_LOG_ROOT>/<role>/<issue>.md`, and `AGENT_LOG_ROOT` is the relative `../agent-logs`, which each desk resolved from inside its worktree. The README now gives the command that prints the absolute folder: `bash -c '. .claude/hooks/common.sh; log_dir'`. The test-runner already uses it. The two misplaced files from step 6 were moved by hand on 2026-10-06.

## RUN-005 — Tasks

- [x] RUN-005.1 — Guard governs the repo tree (D1) + `tests/unit/test_role_guard.py` in a throwaway repo with a real linked worktree
- [x] RUN-005.2 — External model volumes, created by `make init` (D2); verify that no warning appears in a worktree test run
- [x] RUN-005.3 — ASCII hook messages (D3) and the resolved job-log path in the roles README (D4)
- [x] RUN-005.4 — PR #9 review round 1: real-path resolution and case-insensitive matching (D1 amended), image folders protected (D5); 13 new tests; real NTFS junction checked on the host

## RUN-005 — Results

- **Status:** DONE (after review round 1 → RUN-005.4).
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
  - **Hardlinks:** out of scope. They can't be told apart from ordinary files, and creating one needs a shell command, which the guard doesn't path-check by design.
- **For the lead (index, D13/D16):**
  - add rows for **RUN-004**: the deferred lockfile (RUN-001.D9), `proposed`;
  - add a row for **RUN-005**: this work, `done`;
  - set Next free to **RUN-006**.
- **Self-rating:** 9/10, proud: yes (after round 1). Round 1 rightly caught two bypasses that my first 32 cases missed. Gap: Bash-based writes, like `echo > file`, are outside the guard by design. It covers Claude's file tools and the merge, tag and push commands, not every shell command.
