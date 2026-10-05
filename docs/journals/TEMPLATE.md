# <Feature> — journal

**ID:** CLS-004 · **Systems:** CLS (+ PIPE) · **Type:** feature | bug | balance | refactor | process ·
**Status:** proposed | in progress | done | parked | superseded by <ID> · **Milestone:** mN ·
**Issues:** #<n>, #<n> · **Branch:** <branch per task>

<!--
Rules: CLAUDE.md §1 (DOC-001). Copy this file to docs/journals/<feature>_journal.md.
Public repo: never write image file names, captions, references or host paths here. Use hashes.
A follow-up requirement is appended below as a new set of blocks with its own ID.
-->

---

## CLS-004 — Requirement (human | DESIGN.md mN, YYYY-MM-DD)

- **Objective:** one imperative sentence naming what is to be done.
- **Details:** the specifics: numbers, scope, files, config keys.
- **Constraint:** what must be confirmed first, left untouched, or preserved.
- **Implements:** R-CLS-4, R-CLS-3 (DESIGN.md spec IDs).

## CLS-004 — Confirmed reading

What the code and DESIGN.md already say, each item of the requirement checked against them, and every open decision:

- **CLS-004.D1** — <decision>: <chosen option> (<who decided, date>). <Why.>

## CLS-004 — Plan

Modules, nodes, data, migrations, prompts, tests (with tiers), evals: the proposal.

## CLS-004 — Tasks

- [ ] CLS-004.1 — <task> · issue #<n> · acceptance: `<pytest path | scripts/gate_N.py>`
  - [ ] CLS-004.1.1 — <subtask>
- [x] CLS-004.2 — <task> · issue #<n> → `abc1234`
- ~~CLS-004.3~~ dropped: <why>

## CLS-004 — Results

### CLS-004.1 (worker: <role>)

- **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
- **Triage:** <size> · <tiers run> · <agents>
- **Tests:** unit <passed>/<total> · db … · integration … · gpu … · acceptance: <result>
- **Eval:** <numbers, if prompts/thresholds/models changed>
- **Self-rating:** <score>/10, proud: yes | no; gaps: <named gaps>
- **Review:** Reviewer <verdict> · Privacy auditor <verdict> · PR #<n>
- **Deferred:** <what and why, with the new ID or issue>
