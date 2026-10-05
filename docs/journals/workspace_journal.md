# Workspace — journal

**ID:** DOC-003 · **Systems:** DOC (+ RUN) · **Type:** process · **Status:** done · **Milestone:** — ·
**Issues:** — (pre-repo) · **Branch:** pre-repo, committed at bootstrap

---

## DOC-003 — Requirement (human, 2026-10-05)

- **Objective:** Set the project up Windows-native with Docker, with everything in one workspace folder.
- **Details:**
  - Rename the docs folder to `file-sorter-full`.
  - Put the code repo in `file-sorter-full\file-sorter`, linked to the public GitHub repo.
  - Put agent-office next to it.
  - Swap every WSL reference for Windows-native with Docker.
- **Constraint:**
  - Confirm the understanding first.
  - The repo stays at its fixed path even if agent-office expects another layout.
- **Implements:** DESIGN.md §9, §9a, R-RUN-5, R-FOP-7 (polling).

## DOC-003 — Confirmed reading

- **DOC-003.D1:** The host is Windows 11 with Docker Desktop for the GPU. Its WSL2 backend is internal: there is no Linux distro to manage and no code in WSL.
- **DOC-003.D2:** Workspace layout:
  - `file-sorter-full\` contains `agent-office\` (the fork, built from source), `agent-logs\<role>\` (local logs) and `file-sorter\` (the repo).
  - The original plan is archived at the workspace root.
- **DOC-003.D3:** The repo path is fixed. If agent-office can't adopt an existing clone, use a directory junction (`mklink /J`). Never a second clone. (human, 2026-10-05)
- **DOC-003.D4:** `make` comes from `winget install ezwinports.make`. The Makefile sets `SHELL := bash`, with Git Bash on `PATH`. (human, 2026-10-05)
- **DOC-003.D5:** agent-office is installed from the fork's source. Verified: the fork's `install.sh` hard-codes `REPO="AgentSystemLabs/agent-office"` and downloads upstream releases, and the fork has no releases. On 2026-10-05 the fork was identical to upstream `main`.
- **DOC-003.D6:** Host paths live only in the git-ignored `.env`, as forward-slash Windows paths, quoted. Inside the containers the source is `/source` (read-only) and the results are `/results`.
- **DOC-003.D7:** LF line endings everywhere, through `.gitattributes`.
- **DOC-003.D8:** The RTX 5080 (Blackwell, sm_120) needs PyTorch built for CUDA 12.8 or newer (R-RUN-5). The GPU check command uses a CUDA 12.8 image.
- **DOC-003.D9:** The native agent-teams fallback (runbook 5B) is dropped, because it needs tmux.
- **DOC-003.D10:** There is no CLAUDE.md at the workspace root, so agent-office's own sessions don't inherit this project's rules.
- **DOC-003.D11:** Node 20+ is the requirement, from agent-office's README; the plan said Node 22, and the host has v24. Git Bash must precede `WindowsApps` on `PATH`: on this host `bash` resolved to `WindowsApps\bash.exe`, the WSL launcher, which would run hooks and make recipes inside the stopped `docker-desktop` distro.

## DOC-003 — Plan

1. Rewrite the host sections of DESIGN.md (§9a) and CLAUDE.md (environment notes).
2. Create the repo folder with the docs and a protective `.gitignore`.
3. Move `.env` into the repo folder.
4. The human renames the workspace folder.

## DOC-003 — Tasks

- [x] DOC-003.1 — Rewrite WSL → Windows-native in DESIGN.md and CLAUDE.md → `pre-repo`
- [x] DOC-003.2 — Create `file-sorter\` with CLAUDE.md, DESIGN.md, `docs/PLAN.md`, `.env` and `.gitignore` → `pre-repo`
- [x] DOC-003.3 — Rename the workspace to `file-sorter-full` (human) → done 2026-10-05
- [x] DOC-003.5 — Runbook step 2, fixtures (human labels + copy), 2026-10-05: `fixtures/labels.csv` has 150 rows (CLS-001). `fixtures/images/` holds 150 files, 266.1 MiB, each SHA-256-verified against its source; the source was only read. Both are git-ignored.
- [x] DOC-003.4 — Runbook step 1, host prerequisites (human), verified 2026-10-05:
  - GPU: `docker run --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi` shows the RTX 5080 (driver 610.62, 16 GB).
  - Docker: engine 29.6.2.
  - Shells: a fresh PATH resolves `bash` to Git Bash; GNU Make 4.4.1 with `SHELL := bash` runs recipes in Git Bash (`MINGW64`) and reaches Docker.
  - Tools: git 2.54, gh 2.101 (logged in), Node v24, Claude Code 2.1.282.

## DOC-003 — Results

- **Status:** DONE_WITH_CONCERNS.
  - Unverified until setup step 5: whether agent-office can adopt the existing clone (D3), and where it creates worker worktrees. The worktrees must stay on the same drive.
- **Triage:** medium · no tests (docs only) · solo.
- **Self-rating:** 8/10, proud: yes. The gap is the agent-office behavior, which can only be checked once it is installed.
