# Work index

Every work ID, its journal and its state. The rules are in `CLAUDE.md` §1 (DOC-001). Search by ID with `git log --grep CLS-004`, or grep the ID across `docs/`. Only the lead edits this file.

- **Work IDs** (`CLS-004`) are units of work.
- **Spec IDs** (`R-CLS-4`) are DESIGN.md requirements. A work item cites the spec IDs it implements.

DOC-001 to DOC-003 and CLS-001's design were done on 2026-10-05, before the repo existed. They were committed at bootstrap as one commit per work item, so their task lines read `pre-repo` instead of per-task hashes.

**Next free:** ING-001 · SAN-001 · CLS-002 · CAP-001 · RAG-001 · NAME-001 · FOP-001 · API-001 · MOD-001 · PIPE-001 · CFG-001 · RUN-004 · DB-001 · CLI-001 · TST-001 · DOC-004

## Work items

| ID | Title | Systems | Type | Status | Milestone | Issues | Journal | Branch | Date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CLS-001 | Two category axes: a required format and an optional topic, `<Topic>/<Format>/` folders, derived `animated` flag, labels converted from the human's sample | CLS, NAME, FOP, DB, API, TST | feature | in progress (design done; build in M3) | m3 | — | [categories_journal.md](categories_journal.md) | main | 2026-10-05 |
| RUN-001 | Repo bootstrap: Docker runtime (read-only source, internal network), CUDA image, Makefile, config, models pulled | RUN, CFG, TST | feature | in progress (push pending) | — | — | [bootstrap_journal.md](bootstrap_journal.md) | main | 2026-10-05 |
| RUN-002 | Agent configuration: settings layers, hooks, pre-push gate, subagents, desk briefs, templates, gate stubs | RUN, DOC, TST | feature | in progress (live-session check in step 6) | — | — | [bootstrap_journal.md](bootstrap_journal.md) | main | 2026-10-05 |
| RUN-003 | agent-office installed from the fork's source; floor for this repo | RUN | feature | proposed | — | — | [bootstrap_journal.md](bootstrap_journal.md) | — | 2026-10-05 |
| DOC-001 | Process standard: work IDs, journals, index, commits, triage, completion status, self-rating, test tiers (adopted from the pygame project) | DOC, TST | process | done | — | — | [process_standard_journal.md](process_standard_journal.md) | main | 2026-10-05 |
| DOC-002 | Design review: the plan reconciled into DESIGN.md (C-1 to C-20, open questions answered) | DOC, all | process | done | — | — | [design_review_journal.md](design_review_journal.md) | main | 2026-10-05 |
| DOC-003 | Windows-native workspace: Docker Desktop host, `file-sorter-full` layout, agent-office from the fork | DOC, RUN | process | done | — | — | [workspace_journal.md](workspace_journal.md) | main | 2026-10-05 |

## Plans and designs

| Document | Serves |
| --- | --- |
| [../../DESIGN.md](../../DESIGN.md) | DOC-002 (spec for every milestone) |
| [../PLAN.md](../PLAN.md) | DOC-002 (source plan, rationale) |
| [../../CLAUDE.md](../../CLAUDE.md) | DOC-001, DOC-003 |
| [TEMPLATE.md](TEMPLATE.md) | DOC-001 |
| [../plans/TEMPLATE.md](../plans/TEMPLATE.md) | DOC-001 |
| [../../.claude/roles/README.md](../../.claude/roles/README.md) | RUN-002 |
| `../../fixtures/labels.csv` (git-ignored) | CLS-001, M3 gate |
