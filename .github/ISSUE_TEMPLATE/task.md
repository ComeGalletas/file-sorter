---
name: Task
about: One task (at most one day of work), opened by the lead at G0 (CLAUDE.md §2.2)
title: "<TASK-ID>: <imperative summary>"
labels: []
---

<!-- Public repo: no image file names, captions, references or host paths. Use hashes. -->

**Work item:** <REQ-ID> · journal: `docs/journals/<feature>_journal.md`
**Implements:** R-… (DESIGN.md)
**Owner role:** <pipeline | ml | rag | api-ui | qa> · labels: `mN`, `role:<role>`
**Depends on:** #… or none

## What

<the task, from the journal's Plan>

## Acceptance test

`<tests/... pytest path | scripts/gate_N.py>`, tier `<unit | db | integration | gpu | gate>`. The worker puts this path in `.task` as `acceptance=`.

## Notes

<constraints, decisions to respect (ID.Dn), anything the worker must not touch>
