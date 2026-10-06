# Desk roles (RUN-002.D1)

One file per agent-office desk. These are **briefs for whole Claude Code sessions**, not subagents. The only subagents are in `.claude/agents/` (reviewer, privacy-auditor, test-runner).

| Role | Brief | Settings layer | Works in |
| --- | --- | --- | --- |
| Lead | [lead.md](lead.md) | `.claude/settings.lead.json` | the main checkout |
| Pipeline engineer | [pipeline.md](pipeline.md) | `.claude/settings.worker.json` | its own worktree per task |
| ML engineer | [ml.md](ml.md) | `.claude/settings.worker.json` | its own worktree per task |
| Data/RAG engineer | [rag.md](rag.md) | `.claude/settings.worker.json` | its own worktree per task |
| API/UI engineer | [api-ui.md](api-ui.md) | `.claude/settings.worker.json` | its own worktree per task |
| QA engineer | [qa.md](qa.md) | `.claude/settings.worker.json` | its own worktree per task |

## Starting a desk

- Lead: `claude --settings .claude/settings.lead.json`
- Worker: `claude --worktree <task-id>-<slug> --settings .claude/settings.worker.json`

First message to the desk: `You are the <role>. Read .claude/roles/<file>.md, then CLAUDE.md, then take issue #<n>.`

## Every worker task starts like this

1. In the worktree: `make init` (copies `.env` and `sanitize.yaml` from the main checkout, RUN-002.D3).
2. Write `.task` at the worktree root (git-ignored, RUN-002.D4):

   ```
   role=<pipeline|ml|rag|api-ui|qa>
   issue=<n>
   acceptance=<the acceptance test the issue names>
   ```

3. Post the triage block and a short plan as the first issue comment (CLAUDE.md §2.1–§2.2). Wait for the lead's approval.
4. Build, one commit per subtask (CLAUDE.md §1.6). Tick your own task lines in the journal in the same commit.
5. `git push -u origin HEAD`; the pre-push gate runs. `gh pr create` with the template filled in.
6. Write `<AGENT_LOG_ROOT>/<role>/<issue>.md` (plan, steps, test results) as you go.

Never edit outside your role's paths; open an issue for the owner instead.
