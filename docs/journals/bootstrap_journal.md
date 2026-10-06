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

- [x] RUN-001.1 — Python project: `pyproject.toml`, `classifier/` packages, CLI stub, `.dockerignore`, `Dockerfile`
- [x] RUN-001.2 — Runtime: `docker-compose.yml`, egress and purge overrides, SearXNG settings, `config.yaml`, `sanitize.example.yaml`, `.env.example`
- [x] RUN-001.3 — `Makefile` and `scripts/fetch_models.py`
- [x] RUN-001.4 — Test tiers by path (`tests/conftest.py`), a smoke test and a db-reachability test
- [x] RUN-001.5 — Verify `make up` and `make test` in Docker
- [x] RUN-001.6 — `make models`: Ollama tags and HF weights into volumes
- [ ] RUN-001.7 — README; privacy check; public GitHub repo; push

## RUN-001 — Results

(filled as tasks land)

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
- **RUN-002.D7:** The hooks parse their JSON input with `sed`. `jq` isn't on Git Bash, and host Python isn't a project dependency.

## RUN-002 — Tasks

- [x] RUN-002.1 — Hook scripts (`.claude/hooks/`) and the pre-push gate (`.githooks/pre-push`)
- [x] RUN-002.2 — Settings layers (D6) and worktree-aware Makefile and compose (D2, D3)
- [x] RUN-002.3 — Subagents (`.claude/agents/`) and desk role briefs (`.claude/roles/`)
- [ ] RUN-002.4 — GitHub issue and PR templates; `scripts/gate_1.py`–`gate_8.py` stubs that fail
- [ ] RUN-002.5 — Verify: a lint finding comes back from an edit; a failing test blocks a push; logs land per role
- [ ] RUN-002.6 — CLAUDE.md and DESIGN.md updated for D1–D5

---

## RUN-003 — Requirement (human, 2026-10-05)

- **Objective:** Install agent-office from the fork clone in `file-sorter-full\agent-office` (runbook step 5).
- **Details:** `npm install` (which also builds) and `npm install -g .`, per its README.
- **Constraint:** The first start (GitHub sign-in, code folder, floor) is the human's. The repo path stays fixed (DOC-003.D3).

## RUN-003 — Tasks

- [ ] RUN-003.1 — `npm install` and `npm install -g .` in the fork clone; `agent-office --help` answers
- [ ] RUN-003.2 — Human: first start; add `file-sorter` as a floor
- [ ] RUN-003.3 — Verify whether the existing clone was adopted (or junction it), and where worktrees go
