# Test infrastructure — journal

**ID:** TST-002 · **Systems:** TST (+ RUN) · **Type:** feature · **Status:** proposed · **Milestone:** m1 ·
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
  - `fixtures/images/` holds the 150 labelled real images (DOC-003.5), git-ignored, and the gate tier may read them.
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

- [ ] TST-002.1 — Db-tier fixture: one migrated database per session, a rolled-back transaction per test · #19 · acceptance: `tests/db/test_db_fixture.py`
- [ ] TST-002.2 — Tier audit for `unit` tests · #20 · acceptance: `tests/devtools/test_tier_audit.py`
- [ ] TST-002.3 — `app` mounts the source read-only (R-FOP-8) · #21 · acceptance: `tests/unit/runtime/test_source_mount_readonly.py`
- [ ] TST-002.4 — `scripts/gate_1.py`: re-run skips 100%, with 0 new ledger rows · #22 · acceptance: `scripts/gate_1.py`

## TST-002 — Results

### TST-002.1 (worker: qa)

- **Status:**
- **Triage:**
- **Tests:**
- **Self-rating:**
- **Review:**
- **Deferred:**

### TST-002.2 (worker: qa)

- **Status:**
- **Triage:**
- **Tests:**
- **Self-rating:**
- **Review:**
- **Deferred:**

### TST-002.3 (worker: qa)

- **Status:**
- **Triage:**
- **Tests:**
- **Self-rating:**
- **Review:**
- **Deferred:**

### TST-002.4 (worker: qa)

- **Status:**
- **Triage:**
- **Tests:**
- **Self-rating:**
- **Review:**
- **Deferred:**
