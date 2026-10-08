# Work index

Every work ID, its journal and its state. The rules are in `CLAUDE.md` §1 (DOC-001). Search by ID with `git log --grep CLS-004`, or grep the ID across `docs/`. Only the lead edits this file.

- **Work IDs** (`CLS-004`) are units of work.
- **Spec IDs** (`R-CLS-4`) are DESIGN.md requirements. A work item cites the spec IDs it implements.

DOC-001 to DOC-003 and CLS-001's design were done on 2026-10-05, before the repo existed. They were committed at bootstrap as one commit per work item, so their task lines read `pre-repo` instead of per-task hashes.

**Next free:** ING-003 · SAN-004 · CLS-002 · CAP-001 · RAG-001 · NAME-001 · FOP-002 · API-001 · MOD-002 · PIPE-002 · CFG-003 · RUN-014 · DB-003 · CLI-004 · TST-008 · DOC-008

## Work items

| ID | Title | Systems | Type | Status | Milestone | Issues | Journal | Branch | Date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CLS-001 | Two category axes: a required format and an optional topic, `<Topic>/<Format>/` folders, derived `animated` flag, labels converted from the human's sample | CLS, NAME, FOP, DB, API, TST | feature | in progress (design done; build in M3) | m3 | — | [categories_journal.md](categories_journal.md) | main | 2026-10-05 |
| RUN-001 | Repo bootstrap: Docker runtime (read-only source, internal network), CUDA image, Makefile, config, models pulled | RUN, CFG, TST | feature | done | — | — | [bootstrap_journal.md](bootstrap_journal.md) | main | 2026-10-05 |
| RUN-002 | Agent configuration: settings layers, hooks, pre-push gate, subagents, desk briefs, templates, gate stubs | RUN, DOC, TST | feature | done, with concerns (the RUN-002.D14 verdict comment isn't enforced mechanically) | — | PRs #4, #6, #7, #12 (RUN-002.11: current phase and subagent lists) | [bootstrap_journal.md](bootstrap_journal.md) | main | 2026-10-05 |
| RUN-003 | agent-office installed from the fork's source; floor for this repo | RUN | feature | done | — | — | [bootstrap_journal.md](bootstrap_journal.md) | main | 2026-10-05 |
| RUN-004 | Dependency lockfile, deferred by RUN-001.D9 (torch from a custom index needs its own task) | RUN | feature | proposed (human-side; after M3, the human 2026-10-07) | — | — | [bootstrap_journal.md](bootstrap_journal.md) | — | 2026-10-05 |
| RUN-005 | Runtime hygiene: guard scope (real paths, case folding, trailing dots, streams, image roots), external model volumes, ASCII hook messages, job-log path | RUN, TST | feature | done | — | PR #9 | [bootstrap_journal.md](bootstrap_journal.md) | `run-005-runtime-hygiene` | 2026-10-06 |
| RUN-006 | Review routing by size and paths (`scripts/review_route.sh`, `reviewer-quick`), scoped re-reviews, verdict comment with `Reviewed at` | RUN, DOC, TST | feature | done | — | PR #10 | [bootstrap_journal.md](bootstrap_journal.md) | `run-006-review-speed` | 2026-10-06 |
| RUN-007 | The no-outbound-call hard rule covers the app runtime; host tooling limited to `gh` metadata and five named registries | RUN, DOC | process | done | — | PR #11 | [bootstrap_journal.md](bootstrap_journal.md) | `run-007-network-rule-scope` | 2026-10-06 |
| RUN-008 | A worker may bring `origin/main` into its own branch with a normal merge, and nothing else; the guard reads commands the way bash does and fails closed (D4 threat model); `json_field` reads whole quoted values (D5) | RUN, DOC, TST | feature | done | — | PR #39 | [bootstrap_journal.md](bootstrap_journal.md) | `run-008-worker-sync` | 2026-10-07 |
| RUN-009 | The main checkout's `fixtures/images/` is mounted read-only in every `test` container, so the gate runs in a worker worktree; workers never copy or link the fixtures | RUN, TST, DOC | feature | done | — | PR #40 | [bootstrap_journal.md](bootstrap_journal.md) | `run-009-fixtures-mount` | 2026-10-07 |
| RUN-010 | Follow-ups from the PR #39 and #40 reviews: residuals (ANSI-C quoting, brace expansion), CLAUDE.md's backstop wording, `create_host_path` on the fixtures mount, IDs on human-side merges; and then: the current-phase line, a prune of stale per-worktree test projects | RUN, DOC, TST | process | done | — | PR #43 | [bootstrap_journal.md](bootstrap_journal.md) | `run-010-review-followups` | 2026-10-07 |
| RUN-011 | The `gpu` tier reaches Ollama from a worktree's compose project without starting it by hand (from PR #64's review) | RUN, TST | feature | done (human-side; option 1, RUN-011.D1) | — | PR #76 | [bootstrap_journal.md](bootstrap_journal.md) | — | 2026-10-07 |
| RUN-012 | Session lifecycle: `SessionEnd` tears down a desk's own test stack (the lead's: an idle `db-test` only); `SessionStart` and `make init` prune leftovers | RUN | feature | done (human-side) | — | PR #76 | [bootstrap_journal.md](bootstrap_journal.md) | `run-011-012-gpu-ollama-session-cleanup` | 2026-10-08 |
| RUN-013 | Every lead merge names the reviewed head (`gh pr merge … --match-head-commit <sha>`, enforced by the guard), after PR #72's slip; plus PR #76's follow-ups | RUN, DOC | process | done (human-side) | — | PR #79 | [bootstrap_journal.md](bootstrap_journal.md) | `run-013-merge-head-check` | 2026-10-08 |
| CLI-001 | `classifier --version` prints the package version (harness dry run, runbook step 6) | CLI | feature | done | — | #2 (PR #5) | [harness_journal.md](harness_journal.md) | `office/nibble-2cb1` | 2026-10-05 |
| TST-001 | Deliberately failing probe test: proves the pre-push gate blocks a red branch; never fixed or merged | TST, RUN | process | blocked (by design: the push was rejected, TST-001.D1) | — | #3 (open, no PR) | [harness_journal.md](harness_journal.md) | `office/sprocket-0819` (local only, never pushed) | 2026-10-05 |
| CFG-001 | Typed config loader; refuse nested source and results roots | CFG, FOP | feature | done | m1 | #13 (PR #26) | [config_journal.md](config_journal.md) | `office/pixel-0686` | 2026-10-06 |
| CFG-002 | Config loader hardening from PR #26's review: leading `//` and absolute roots, errors without input values, `DB_DSN` always wins (CFG-001.D2) | CFG | refactor | done | m2 | #44 (PR #74) | [config_journal.md](config_journal.md) | `office/byte-3ea0` | 2026-10-06 |
| DB-001 | Alembic set-up and the `files` ledger | DB | feature | done | m1 | #14 (PR #30) | [ledger_journal.md](ledger_journal.md) | `office/pixel-7049` | 2026-10-06 |
| ING-001 | Hashing, discovery, frame probing and the ingest node | ING, PIPE, DB | feature | done | m1 | #15 (PR #27), #16 (PR #33), #34 (PR #36) | [ingest_journal.md](ingest_journal.md) | per task (`office/*`) | 2026-10-06 |
| PIPE-001 | Batch graph skeleton with dry-run mode | PIPE | feature | done | m1 | #17 (PR #35) | [pipeline_journal.md](pipeline_journal.md) | `office/pixel-3a83` | 2026-10-06 |
| CLI-002 | `classifier dry-run [--csv]` | CLI, PIPE, FOP | feature | done | m1 | #18 (PR #38) | [pipeline_journal.md](pipeline_journal.md) | `office/pixel-9618` | 2026-10-06 |
| TST-002 | Db fixture, tier audit, read-only source test, gate 1 | TST, RUN | feature | done (.2 with named gaps; gate 1 PASS at G1) | m1 | #19 (PR #31), #20 (PR #28), #21 (PR #29), #22 (PR #41) | [test_infra_journal.md](test_infra_journal.md) | `office/*` per task | 2026-10-06 |
| TST-003 | A shared private-schema fixture for integration tests (from PR #35's `schema_support.py`) | TST | refactor | done | m2 | #53 (PR #63) | [test_infra_journal.md](test_infra_journal.md) | `office/widget-eeb1` | 2026-10-06 |
| TST-004 | Tier audit enforces §3's fixtures rule: only `gate` and `gpu` may reference `fixtures/images` or `fixtures/labels.csv` (from PR #40's review) | TST | refactor | done | m2 | #54 (PR #67) | [test_infra_journal.md](test_infra_journal.md) | `office/widget-6095` | 2026-10-07 |
| SAN-001 | Sanitizer: `sanitize.yaml` rules (literal, regex, entity, `exif_field`), lossless metadata strip through exiftool, `sanitize_log`, the `sanitize` node, failing closed | SAN, PIPE, MOD, DB | feature | done | m2 | #47 (PR #65), #48 (PR #73), #52 (PR #77), #56 (PR #81) | [sanitize_journal.md](sanitize_journal.md) | per task (`office/*`) | 2026-10-07 |
| FOP-001 | The working copy in `results_root/.work/`: read-only source, temp file, transform, atomic rename; write-new helper | FOP, SAN | feature | done | m2 | #46 (PR #62) | [sanitize_journal.md](sanitize_journal.md) | `office/byte-d173` | 2026-10-07 |
| DB-002 | Migration `0002`: `sanitize_log` and `files.original_sanitized` | DB, SAN | feature | done | m2 | #45 (PR #70) | [ledger_journal.md](ledger_journal.md) | `office/byte-dd9b` | 2026-10-07 |
| ING-002 | Thumbnails from the sanitized working copy (R-ING-5, moved from M1 by ING-001.D1) | ING, FOP | feature | done | m2 | #49 (PR #66) | [ingest_journal.md](ingest_journal.md) | `office/byte-60e5` | 2026-10-07 |
| MOD-001 | Ollama text client with a transport seam; entity-detection prompt, `detect_entities`, its eval and recordings | MOD, SAN, TST | feature | done, with concerns (held-out recall 99.1%) | m2 | #50 (PR #64), #51 (PR #72) | [models_journal.md](models_journal.md) | — | 2026-10-07 |
| CLI-003 | `classifier dry-run` reports the sanitize node: counts, `sanitized_name` column | CLI, SAN | feature | done | m2 | #57 (PR #83) | [pipeline_journal.md](pipeline_journal.md) | `office/byte-a55b` | 2026-10-07 |
| TST-005 | Ollama replay for the default tiers (`tests/recordings/`); gate 2 | TST, MOD, SAN | feature | done (gate 2 PASS at G1) | m2 | #55 (PR #71), #58 (PR #84) | [test_infra_journal.md](test_infra_journal.md) | — | 2026-10-07 |
| TST-006 | The integration fixture `empty_ledger` empties `files` and the tables that reference it (`truncate files cascade`), unblocking DB-002.1 | TST, DB | refactor | done | m2 | #68 (PR #69) | [test_infra_journal.md](test_infra_journal.md) | `office/gizmo-0712` | 2026-10-07 |
| TST-007 | Gate 1 runs only the ingest node, so it stays an M1 measure once `sanitize` registers (unblocked SAN-001.4) | TST | refactor | done | m2 | #78 (PR #80) | [test_infra_journal.md](test_infra_journal.md) | `office/byte-afbe` | 2026-10-08 |
| SAN-002 | The committed example's entity rule asks for `LOCATION` too (R-SAN-3), found by gate 2's first real run | SAN, CFG | bug | done | m2 | #82 (PR #85) | [sanitize_journal.md](sanitize_journal.md) | `office/nibble-e2bf` | 2026-10-08 |
| SAN-003 | Hardening from the M2 audits: `NodeContext` root repr, `O_NOFOLLOW` on originals, `pillow_heif` log cap, the missing-exiftool reason, an fd leak, D18 on other paths, CLI `OSError` tracebacks | SAN, PIPE, FOP, CLI | refactor | proposed (not scheduled; the human picks M3 or later) | — | — | [sanitize_journal.md](sanitize_journal.md) | — | 2026-10-08 |
| DOC-001 | Process standard: work IDs, journals, index, commits, triage, completion status, self-rating, test tiers (adopted from the pygame project) | DOC, TST | process | done | — | — | [process_standard_journal.md](process_standard_journal.md) | main | 2026-10-05 |
| DOC-002 | Design review: the plan reconciled into DESIGN.md (C-1 to C-20, open questions answered) | DOC, all | process | done | — | — | [design_review_journal.md](design_review_journal.md) | main | 2026-10-05 |
| DOC-003 | Windows-native workspace: Docker Desktop host, `file-sorter-full` layout, agent-office from the fork | DOC, RUN | process | done | — | — | [workspace_journal.md](workspace_journal.md) | main | 2026-10-05 |
| DOC-004 | M1 G0 rule changes: workers write their own task tests (QA owns shared test infrastructure), `classifier/config.py` owned by Pipeline, container source paths stored only in the local ledger and reports | DOC, TST, CFG, ING | process | done | — | PR #24 | [process_standard_journal.md](process_standard_journal.md) | `doc-004-test-ownership` | 2026-10-06 |
| DOC-005 | No aggregates about the human's folder, fixtures or labels in the repo (counts, file-type mix, sizes, label distributions); gate reports use percentages and "0 new ledger rows" (DOC-005.D1) | DOC, TST | process | done | — | PR #25 | [process_standard_journal.md](process_standard_journal.md) | `doc-005-no-folder-aggregates` | 2026-10-06 |
| DOC-006 | R-ING-9 `animated` becomes the ING-001.D3 allow-list (GIF, WEBP, PNG with `is_animated`); R-ING-6 reads the first frame, page or image of any multi-frame file | DOC, ING | process | done | — | PR #32 | [design_review_journal.md](design_review_journal.md) | `doc-006-animated-allow-list` | 2026-10-06 |
| DOC-007 | M2 G0 rule and spec changes: the source-path exception is permanent with two limits (ING-001.D2 A), HMAC `before_hash` with `SANITIZE_LOG_KEY` (SAN-001.D5), ICC kept (SAN-001.D4), thumbnails by `source_hash` (ING-002.D1), workers commit their own recordings (TST-005.D1) | DOC, SAN, ING, TST, RUN | process | done | m2 | PR #60 | [process_standard_journal.md](process_standard_journal.md) | `doc-007-m2-rules` | 2026-10-07 |

## Plans and designs

| Document | Serves |
| --- | --- |
| [../../DESIGN.md](../../DESIGN.md) | DOC-002 (spec for every milestone) |
| [../PLAN.md](../PLAN.md) | DOC-002 (source plan, rationale) |
| [../../CLAUDE.md](../../CLAUDE.md) | DOC-001, DOC-003 |
| [TEMPLATE.md](TEMPLATE.md) | DOC-001 |
| [../plans/TEMPLATE.md](../plans/TEMPLATE.md) | DOC-001 |
| [../plans/m1.md](../plans/m1.md) | M1: CFG-001, DB-001, ING-001 (incl. ING-001.3, #34), PIPE-001, CLI-002, TST-002 |
| [../plans/m2.md](../plans/m2.md) | M2 (approved 2026-10-07): SAN-001, FOP-001, DB-002, ING-002, MOD-001, CLI-003, TST-005, and from the backlog CFG-002, TST-003, TST-004; added mid-run TST-006, TST-007, SAN-002; rule changes DOC-007; follow-up SAN-003 |
| [../../.claude/roles/README.md](../../.claude/roles/README.md) | RUN-002 |
| `../../fixtures/labels.csv` (git-ignored) | CLS-001, M3 gate |
