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
- **Self-rating:** 8/10, proud: yes. The gap is the live-session check above, which step 6 closes.

---

## RUN-003 — Requirement (human, 2026-10-05)

- **Objective:** Install agent-office from the fork clone in `file-sorter-full\agent-office` (runbook step 5).
- **Details:** `npm install` (which also builds) and `npm install -g .`, per its README.
- **Constraint:** The first start (GitHub sign-in, code folder, floor) is the human's. The repo path stays fixed (DOC-003.D3).

## RUN-003 — Tasks

- [x] RUN-003.1 — `npm install` (16 s, builds `dist/`) and `npm install -g .`, which links to the fork clone, so a rebuild updates the command; `agent-office --help` answers. The fork's working tree is untouched.
- [ ] RUN-003.2 — Human: first start with the repo as `[dir]` (command in `.claude/roles/README.md`)
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

- **Status:** in progress.
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
