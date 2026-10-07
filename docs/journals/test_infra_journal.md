# Test infrastructure — journal

**ID:** TST-002 · **Systems:** TST (+ RUN) · **Type:** feature · **Status:** in progress (TST-002.1, .3 done; .2 in review; .4 waits for CLI-002.1); TST-003 proposed · **Milestone:** m1 ·
**Issues:** #19, #20, #21, #22 · **Branch:** per task, named by agent-office (`office/*`)

<!--
Rules: CLAUDE.md §1 (DOC-001). Public repo: never write image file names, captions,
references or host paths here. Use hashes.
-->

---

## TST-002 — Requirement (DESIGN.md M1 and CLAUDE.md §3, 2026-10-06)

- **Objective:** Give M1 the shared test infrastructure CLAUDE.md §3 promises, and turn `scripts/gate_1.py` from a stub into the M1 gate.
- **Details:**
  - **Db fixture:** one migrated test database per session (`alembic upgrade head` on `db-test`), with each test in a transaction that is rolled back.
  - **Tier audit:** `tests/devtools/test_tier_audit.py` fails if a `unit` test opens a db connection, loads a model or calls Ollama, and names the `tests/conftest.py` line to add.
  - **Read-only source:** a test asserts that `app` mounts the source read-only (R-FOP-8).
  - **Gate 1:** "Re-running on the same folder skips 100% of files, with no new ledger rows."
- **Constraint:**
  - Never skip to green. Missing prerequisites fail with a message naming them.
  - The gate reports aggregates and hashes only, never file names.
  - Tests never read `source_root` or `results_root`.
- **Implements:** CLAUDE.md §3 (tiers, tier audit, shared setup), R-FOP-8, DESIGN.md §11 M1 gate.

## TST-002 — Confirmed reading

- `tests/conftest.py` assigns tiers by path, and its docstring already promises "The tier audit (M1, TST)". A `tests/devtools/` module is `unit` by default.
- `tests/db/test_db_reachable.py` connects with `DB_DSN` and runs no migrations. The fixture needs DB-001.1's Alembic set-up.
- `scripts/gate_1.py` is a stub that exits 1 (RUN-002.4).
  - `make gate-1` runs it in the `test` container. That container has the repo and `fixtures/` but no `/source` mount (RUN-001.D6), and `db-test` (tmpfs, empty on every start).
  - `fixtures/images/` is the git-ignored set of real fixtures (DOC-003.5), and the gate tier may read it.
- **R-FOP-8:** the test parses `docker-compose.yml` instead of touching the mount, because tests may not read `source_root`.
- **TST-002.D1** — **The implementing worker writes its own task's tests** (confirmed by the human, 2026-10-06, option 1 as recommended). The rule change is DOC-004.D1, merged in PR #24: CLAUDE.md, DESIGN.md §12 and the desk briefs.
  - Each worker writes its tests in the same commit as the code, under `tests/<tier>/<package>/`.
  - QA owns the shared infrastructure (conftest, fixtures, tier audit, gate scripts, recordings) and reviews test quality. So TST-002's four tasks stay QA's: they are shared infrastructure and the gate.
  - The rejected option, QA writing every acceptance test first, would double the issues and serialise every task.
- **TST-002.D2** — **Gate 1 runs on `fixtures/images/`** (confirmed by the human, 2026-10-06). It ingests the folder twice against a fresh `db-test`, in the `test` container.
  - It measures run 2: the share of files skipped as known (target 100%), and new ledger rows (target 0).
  - The real source folder isn't mounted in the `test` profile, and `fixtures/images/` holds the same real images.

## TST-002 — Plan

1. **TST-002.1:** add a session-scoped `migrated_db` fixture and a function-scoped `db` fixture (connection plus outer transaction, rolled back) to `tests/conftest.py`, or a `tests/db/conftest.py`. Add a test that a write in one test is invisible in the next.
2. **TST-002.2:** the tier audit, by static scan plus import inspection of `unit` modules: no `psycopg`, `sqlalchemy.create_engine`, `transformers` model loads or `httpx` to Ollama. It names the conftest line to add.
3. **TST-002.3:** load `docker-compose.yml` with PyYAML and assert that `app`'s `/source` mount is `read_only: true`, and that no non-`purge` file remounts it.
4. **TST-002.4:** `gate_1.py`. Migrate a fresh database, run `classifier dry-run` (or `graph.run`) on `fixtures/images/` twice, and assert run 2 has 100% skipped-known and 0 new rows. Print aggregates only.

## TST-002 — Tasks

- [x] TST-002.1 — Db-tier fixture: one migrated database per session, a rolled-back transaction per test · #19 · acceptance: `tests/db/test_db_fixture.py`
  - [x] TST-002.1.1 — `tests/db/db_support.py` (the `DB_DSN` check) and `tests/db/conftest.py` (`db_dsn`, `migrated_db`, `db`) · b9947fb
  - [x] TST-002.1.2 — `tests/db/test_db_fixture.py`: head, rollback in one test, ordered pair, missing-DSN message · fcaceef
  - [x] TST-002.1.3 — PR #30's migration test and `test_db_reachable.py` take the shared `DB_DSN` check · 9516686
  - [x] TST-002.1.4 — Results · f49fd16
- [x] TST-002.2 — Tier audit for `unit` tests · #20 · acceptance: `tests/devtools/test_tier_audit.py`
  - [x] TST-002.2.1 — The audit and its tests, in one module (the scanner lives in the test file: `--import-mode=importlib` rules out a sibling helper import) · `0ffb5a3`
  - [x] TST-002.2.2 — Point the `tests/conftest.py` docstring at the audit · `e112d07`
  - [x] TST-002.2.3 — Record the results and the named gaps · `9ef33e4`
  - [x] TST-002.2.4 — Fix the audit after review round 1: drop the `DB_DSN` check, alias and from-import HTTP calls, dynamic imports, async fixtures, the fake-transport fix text · `f6731b7`
- [x] TST-002.3 — `app` mounts the source read-only (R-FOP-8) · #21 · acceptance: `tests/unit/runtime/test_source_mount_readonly.py`
  - [x] TST-002.3.1 — `app`'s `/source` mount in `docker-compose.yml` is read-only (long and short forms) · e7747f9
  - [x] TST-002.3.2 — no other service mounts `/source` writably; the egress file doesn't touch it · 83054ce
  - [x] TST-002.3.3 — the purge file is the only read-write remount, for `app` only, with its DANGER header · 5d97934
  - [x] TST-002.3.4 — Results, self-rating and the local regression check · 401f437
  - [x] TST-002.3.5 — hardening from the round-1 review: short-form target read from the right; `read_only` true only for a real `True` or `"true"` · 4a8097d
- [x] TST-002.4 — `scripts/gate_1.py`: re-run skips 100%, with 0 new ledger rows · #22 · acceptance: `scripts/gate_1.py`
  - [x] TST-002.4.1 — `scripts/gate_1.py`: prerequisites (`DB_DSN`, `fixtures/images/`), fresh migrated schema, two dry runs, the verdict on run 2 and an aggregates-only report · 1601434
  - [x] TST-002.4.2 — `tests/unit/gate/` (verdict logic, no counts printed, named prerequisites) and `tests/integration/test_gate_1_script.py` (end to end on synthetic images) · 6e6227f
  - [x] TST-002.4.3 — Results, and the first push once RUN-009 (PR #40) is on main · this commit

## TST-002 — Results

### TST-002.1 (worker: qa)

- **Status:** DONE (commits b9947fb, fcaceef, 9516686, f49fd16).
- **Triage:** medium. Db-tier test infrastructure only, no production code. Solo.
- **Design:**
  - `tests/db/db_support.py` holds `require_db_dsn()`; `tests/db/conftest.py` holds `db_dsn` (session), `migrated_db` (session) and `db` (function). It is imported as `tests.db.db_support` because the repo runs pytest in `importlib` mode, which does not put `tests/db/` on `sys.path`.
  - **`migrated_db` migrates its own schema, not `public`.** I first migrated `public`, as planned. With `search_path = <schema>, public`, PR #30's migration test then saw `public.alembic_version` (and the enum) and skipped its upgrade, so 2 tests failed whenever they ran after the fixture. They only passed in the default order by luck of alphabetical order (`ledger/` before `test_db_fixture.py`). The fix: the fixture creates the `vector` extension in `public` first, migrates a `session_<uuid>` schema through `options=-c search_path=...` in the yielded DSN, and drops it at session end. `public` keeps only the extension.
  - **The ordered pair:** `test_pair_2_does_not_see_it` asserts that `test_pair_1_writes_a_row` recorded its hash in a module-level holder before it checks the row is gone, so it fails alone. **Also proven inside one test:** `test_rollback_inside_one_test` writes, sees the row, rolls back, and a second connection sees no row.
  - Plain `rollback()`, no savepoints. A test that must commit isolates itself in its own schema, as #30 does. **A `commit()` on the `db` connection persists its rows in the session schema until session end**, when the schema is dropped: the rollback undoes only what was never committed.
- **Tests:**
  - `make test`: 201 passed (db: 12, including 5 new; unit: 189). `make lint`: clean.
  - **Coexistence with PR #30's migration test, in the same session:** `pytest tests/db/test_db_fixture.py tests/db/ledger tests/db/test_db_reachable.py` (fixture first) passed 12/12. `test_db_reachable.py` first, then the fixture, then the ledger tests, passed 12/12. The full `make test` (ledger first) passed 201/201.
  - `-k pair_2` alone fails with the message naming the pair's first test. That is intended.
  - A pre-existing polluted `db-test` (left by my own first, wrong attempt) made later runs fail until `docker compose down`. That was not a code problem. The tmpfs database does not outlive its container.
- **Self-rating:** 9/10, proud: yes. Gaps: (1) the missing-DSN test exercises `require_db_dsn`, not the `db_dsn` fixture itself, because a session fixture can't be re-run inside a test; they share the one function. (2) `db` has no savepoint support, which nothing needs yet. (3) No random-order plugin; three orders were checked by hand.
- **Review:** PR #31, merged as `6cb1279`, closing #19. Round 1: Reviewer APPROVE (full, 5 minor) and Privacy auditor PASS at `f49fd16`. The lead held the merge for minors 1–3 (a single-head check instead of a hardcoded `0001`, the `commit()` docstring, the journal hashes), fixed in `ba2a24b`. Round 2, scoped: APPROVE and PASS at `ba2a24b`. The verdict comments are on the PR.
- **Deferred:** `db` has no savepoint support for tests that need to roll back part of their work. Nothing needs it yet.

### TST-002.2 (worker: qa)

- **Status:** DONE_WITH_CONCERNS (the named gaps below)
- **Triage:** medium; unit tier plus lint; solo.
- **Tests:** `tests/devtools/test_tier_audit.py`: 36 pass (25 before round 1). Round 1 found the `DB_DSN` check red on `main`'s config tests, so it is gone: setting the variable opens no connection. The merged-tree run (0 violations expected) is pending the merge of `main` into this branch. `make lint` is clean.
- **Self-rating:** 8/10, proud: yes. The 2 points are the named gaps below; the acceptance test and the lead's two additions are met.
- **Review:** pending.
- **Deferred / named gaps:**
  - The scan is static and per module. A unit test that reaches the db or a model through a `classifier.*` helper is caught only if the helper's dotted name is in `INDIRECT_DB` / `INDIRECT_MODEL`. Both lists start empty, because no helper that needs the db or a model exists yet. A task that adds one registers it there.
  - Not detected: `httpx.Client(...)` built with a real transport (module-level calls, aliases and `from httpx import post` are flagged, so a fake `MockTransport` stays legal), a db reached through an autouse fixture in a `conftest.py`, and dynamic imports whose argument is not a string constant.
  - The scanner lives in the test file, because `--import-mode=importlib` rules out importing a sibling helper.

### TST-002.3 (worker: qa)

- **Status:** DONE. Commits e7747f9 (3.1), 83054ce (3.2), the 3.3 commit and the 3.4 commit; the PR body carries the final hashes.
- **Triage:** small. One new unit test file that parses compose YAML with PyYAML; no dependency, no behavior change. Solo.
- **Tests:** `tests/unit/runtime/test_source_mount_readonly.py`: 7 tests, all pass. `make test`: 189 passed. `make lint` clean. Regression check (local, not committed): setting `read_only: false` on app's `/source` in `docker-compose.yml` fails 2 tests (`test_app_mounts_source_read_only`, `test_no_other_compose_file_mounts_source_writable`); reverted. The test globs `docker-compose*.yml` at the repo root only and never reads `source_root` or the mount.
- **Self-rating:** 9/10, proud: yes. Gap: it checks the compose files as written, not the merged result of `docker compose config` (which would need env and the Docker CLI, and would break the unit tier). The purge override is covered by its own tests instead.
- **Review:** PR #29, merged as `a5eb4e5`, closing #21. Round 1: Reviewer APPROVE (full, 4 minor) and Privacy auditor PASS at `401f437`. The lead held the merge for minors 1–2 (a drive-letter host path in the short form; a quoted `read_only: "false"`), both ways a writable mount could slip through. They were fixed in TST-002.3.5. Round 2, scoped: APPROVE with no findings, and PASS, at `4a8097d`. The verdict comments are on the PR.
- **Deferred:** a check on the merged compose config, if the lead wants one; it would belong to a non-unit tier.

### TST-002.4 (worker: qa)

- **Status:** DONE.
- **Triage:** medium; solo; unit and integration tiers plus the gate itself as the acceptance test.
- **Tests:** 9 new (8 `unit` in `tests/unit/gate/`, 1 `integration`), all green in the test container; ruff clean. `make gate-1` against the real fixtures: skipped on re-run 100.0%, new ledger rows 0, PASS, exit 0 (percentages only, DOC-005.D1). Without the fixtures it fails naming `fixtures/images/`.
- **Self-rating:** 9/10, proud: yes. Gap: it calls `run()` (the entry point `classifier dry-run` uses) rather than the CLI, so the CLI wiring is covered by CLI-002.1's own tests, not by the gate; and the private schema comes from `schema_support.py` until TST-003.
- **Review:** pending.
- **Deferred:** none.

---

## TST-003 — Requirement (lead, from PR #35's review, 2026-10-06)

- **Objective:** Make the private-schema helper for integration tests shared test infrastructure.
- **Details:**
  - `tests/integration/schema_support.py` (PR #35) creates a uuid-named schema, migrates it with Alembic, points a DSN at it through `search_path`, and drops it with `cascade`.
  - It lives next to PIPE-001.1's test because the lead kept it out of a conftest, and DOC-004.D1 gives shared infrastructure to QA. CLI-002.1 needs the same helper, and later integration tests will too.
  - Move it into QA-owned shared infrastructure: a module-scoped fixture in `tests/integration/conftest.py`, or a documented helper module. Move the existing tests onto it, unchanged in behaviour.
- **Constraint:**
  - It must coexist with the db tier's session schema (TST-002.1) and with PR #30's per-test migration schema.
  - Never truncate a shared schema.
  - Never skip: a missing `DB_DSN` fails with the TST-002.1 message.
- **Implements:** CLAUDE.md §3 (shared expensive setup), DOC-004.D1.

## TST-003 — Confirmed reading

- Not in the approved M1 plan. **The human schedules it**, with M1 before G1 or with M2. Until then, CLI-002.1 may import `schema_support.py` as is.

## TST-003 — Tasks

- [ ] TST-003.1 — A shared private-schema fixture for integration tests; the existing tests moved onto it · issue: opened when scheduled · acceptance: `tests/integration/test_dry_run_graph.py` (unchanged behaviour)

## TST-003 — Results

### TST-003.1 (worker: qa)

- **Status:**
