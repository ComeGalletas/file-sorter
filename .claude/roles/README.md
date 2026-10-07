# Desk roles (RUN-002.D1)

One file per agent-office desk. These are **briefs for whole Claude Code sessions**, not subagents. The only subagents are in `.claude/agents/` (reviewer, reviewer-quick, privacy-auditor, test-runner).

| Role | Brief | Settings layer | Works in |
| --- | --- | --- | --- |
| Lead | [lead.md](lead.md) | `.claude/settings.lead.json` | the main checkout |
| Pipeline engineer | [pipeline.md](pipeline.md) | `.claude/settings.worker.json` | its own worktree per task |
| ML engineer | [ml.md](ml.md) | `.claude/settings.worker.json` | its own worktree per task |
| Data/RAG engineer | [rag.md](rag.md) | `.claude/settings.worker.json` | its own worktree per task |
| API/UI engineer | [api-ui.md](api-ui.md) | `.claude/settings.worker.json` | its own worktree per task |
| QA engineer | [qa.md](qa.md) | `.claude/settings.worker.json` | its own worktree per task |

## Starting a desk

**Through agent-office (the normal way, RUN-003):**
- Start the office with `agent-office "<workspace>/file-sorter" --projects "<workspace>" --max-workers 4`.
- Hire the **lead without a worktree**, so it sits in the main checkout. Hire every **worker with its own worktree**; agent-office puts them in `.agent-office/worktrees/` on `office/*` branches.
- agent-office passes its own `--settings` to each desk, so the per-desk layers below don't apply there. The role guard (`.claude/hooks/guard.sh`, RUN-002.D8) enforces the same rules by location for every agent-office desk.

**By hand (without agent-office), the settings layers apply:**
- Lead: `claude --settings .claude/settings.lead.json`
- Worker: `claude --worktree <task-id>-<slug> --settings .claude/settings.worker.json`

First message to the desk: `You are the <role>. Read .claude/roles/<file>.md, then CLAUDE.md, then take issue #<n>.`

## Every worker task starts like this

0. **Start from the latest `main`:** `git fetch && git rebase origin/main`. agent-office creates your worktree from whatever branch the main checkout was on, which may be behind or on someone else's branch (RUN-002.D10). Rebase only before your first push. **Once your PR is open**, bring `main` in with `git fetch && git merge --no-edit origin/main`, resolve any conflict, then `git add` and `git commit --no-edit` (or `git merge --continue`), and push normally. Never rebase or force-push an open PR: it breaks `Reviewed at` (RUN-006.D7). That merge is the only one the guard lets you run (RUN-008.D1). The guard matches shell commands broadly: a commit message that mentions `git` with `merge`, `pull` or `tag` on one line is refused, so write it to a file and commit with `git commit -F <file>` (RUN-008.D4).
1. In the worktree: `make init` (copies `.env`, `sanitize.yaml` and `fixtures/labels.csv` from the main checkout, RUN-002.D3, RUN-009.D2). The real `fixtures/images/` reaches the test container as a read-only mount from the main checkout, so `make gate-N` and the `gpu` tier work here. Never copy or link it into your worktree, and never open it (RUN-009.D1).
2. Write `.task` at the worktree root (git-ignored, RUN-002.D4):

   ```
   role=<pipeline|ml|rag|api-ui|qa>
   issue=<n>
   acceptance=<the acceptance test the issue names>
   ```

3. Post the triage block and a short plan as the first issue comment (CLAUDE.md §2.1–§2.2). Wait for the lead's approval.
4. Build, one commit per subtask (CLAUDE.md §1.6). Tick your own task lines in the journal in the same commit.
5. `git push -u origin HEAD`; the pre-push gate runs. `gh pr create` with the template filled in.
6. Write your job log (plan, steps, test results) as you go, to `<issue>.md` in the folder this command prints: `bash -c '. .claude/hooks/common.sh; log_dir'`. It prints the absolute path of `agent-logs/<role>/` in the workspace. Never write it to a relative `../agent-logs`: from inside a worktree that lands in `.agent-office/worktrees/` (RUN-005.D4).

Never edit outside your role's paths; open an issue for the owner instead. Your own task's tests are yours: write them in the same commit as the code, under `tests/<tier>/<package>/`. The shared test infrastructure is QA's (DOC-004.D1). If your task records model responses, commit them too, under `tests/recordings/<package>/`, from synthetic strings only (TST-005.D1).

**agent-office's Changes window is for watching only** (RUN-002.D12). That's the panel beside each desk's terminal, showing the desk's changed files and diffs. Don't use its commit, discard or open-a-PR buttons:
- A commit from the panel lacks the `<ID>: …` subject and the journal tick (CLAUDE.md §1.6).
- Discard destroys a desk's uncommitted work.
- A PR from the panel skips the template.

Desks commit and open PRs themselves.

**Read files with the Read tool, not `cat`** (RUN-002.D11). On this Windows host, shell output reaches you in the console code page, so `—` and `§` turn into `�`. That breaks references like "CLAUDE.md §2.2". The files themselves are UTF-8.
