---
milestone: mN
status: draft            # draft → approved (set by the human only; G0)
---

# Milestone N — <scope from DESIGN.md §11>

<!-- Rules: CLAUDE.md §1 and "Milestone gates". Written by the lead at G0. Public repo: no image names. -->

## Gate (from DESIGN.md §11)

<the acceptance criterion, verbatim> · measured by `scripts/gate_N.py` (`make gate-N`)

## Team

Lead + <roles> (DESIGN.md §12, at most 3–4 teammates)

## Work items

| Work ID | Title | Implements | Journal | Owner role |
| --- | --- | --- | --- | --- |
| CLS-004 | <title> | R-CLS-3, R-CLS-4 | `../journals/<feature>_journal.md` | Pipeline |

## Tasks (one issue each, ≤ 1 day)

| Task | Issue | Acceptance test | Tier | Depends on |
| --- | --- | --- | --- | --- |
| CLS-004.1 | #<n> | `tests/unit/classify/test_margin.py` | unit | — |

## Decisions needed from the human

- <ID>.D<n> — <question> (options, recommendation)

## Results (filled at G1)

- `make gate-N` output: <summary + numbers>
- Token cost per desk: <numbers>
- Index statuses updated: <yes/no>
