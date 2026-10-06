<!-- Title: <TASK-ID>: <summary>. Public repo: no image file names, captions, references or host paths. -->

Closes #<issue> · **Implements:** R-… · **Journal:** `docs/journals/<feature>_journal.md`

## Triage (CLAUDE.md §2.1)

```
Size: small | medium | large — why
Tests: which tiers / paths — why
Agents: solo | subagents (which, on what) — why
Branch: <branch> in <worktree path>
```

## What changed

<one line per subtask commit: ID.n.m: what, and the measured result>

## Tests run

| Tier | Passed / total |
| --- | --- |
| unit | |
| db | |
| integration | |
| gpu (if models/ or prompts/ changed) | |
| acceptance: `<path>` | |

Eval (if prompts, thresholds or models changed): <numbers>

## Status and rating

- **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- **Self-rating:** <n>/10, proud: yes | no. Gaps: <named gaps>
- **Concerns / deferred:** <with new IDs or issues>

## Checklist

- [ ] Only my role's paths are touched (CLAUDE.md "Roles")
- [ ] Every behavior change has a test in the right tier; no skip-to-green
- [ ] My journal task lines are ticked; commit subjects start with their IDs
- [ ] No hand-tuned value folded in (§1.7); no secrets, host paths or image descriptions
