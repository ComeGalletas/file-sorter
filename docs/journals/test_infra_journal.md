# Test infrastructure — journal

**ID:** TST-002 · **Systems:** TST (+ RUN) · **Type:** feature · **Status:** TST-002 done (.2 with named gaps); TST-003 to TST-007 done (TST-005.2's real PASS at G1) · **Milestone:** m1 (TST-003 to TST-007: m2) ·
**Issues:** #19 (PR #31), #20 (PR #28), #21 (PR #29), #22 (PR #41); M2: #53 (TST-003.1), #54 (TST-004.1), #55 (TST-005.1), #58 (TST-005.2), #68 (TST-006.1), #78 (TST-007.1) · **Branch:** `office/pixel-0e36` (.1), `office/sprocket-debd` (.2), `office/nibble-f70d` (.3), `office/nibble-7c73` (.4)

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
  - [x] TST-002.2.5 — Journal the round-1 fixes · `cb6e735`
  - [x] (human-side sync, RUN-002.D16) `main` merged into the branch, journal conflict resolved · `9e3f058`
- [x] TST-002.3 — `app` mounts the source read-only (R-FOP-8) · #21 · acceptance: `tests/unit/runtime/test_source_mount_readonly.py`
  - [x] TST-002.3.1 — `app`'s `/source` mount in `docker-compose.yml` is read-only (long and short forms) · e7747f9
  - [x] TST-002.3.2 — no other service mounts `/source` writably; the egress file doesn't touch it · 83054ce
  - [x] TST-002.3.3 — the purge file is the only read-write remount, for `app` only, with its DANGER header · 5d97934
  - [x] TST-002.3.4 — Results, self-rating and the local regression check · 401f437
  - [x] TST-002.3.5 — hardening from the round-1 review: short-form target read from the right; `read_only` true only for a real `True` or `"true"` · 4a8097d
- [x] TST-002.4 — `scripts/gate_1.py`: re-run skips 100%, with 0 new ledger rows · #22 · acceptance: `scripts/gate_1.py`
  - [x] TST-002.4.1 — `scripts/gate_1.py`: prerequisites (`DB_DSN`, `fixtures/images/`), fresh migrated schema, two dry runs, the verdict on run 2 and an aggregates-only report · 1601434
  - [x] TST-002.4.2 — `tests/unit/gate/` (verdict logic, no counts printed, named prerequisites) and `tests/integration/test_gate_1_script.py` (end to end on synthetic images) · 6e6227f
  - [x] TST-002.4.3 — Results, and the first push once RUN-009 (PR #40) is on main · 557e1f0
  - [x] TST-002.4.4 — PR #41 round 1: run 1 must have ingested an image (no vacuous pass), an error prints only its type, `check_roots` after validation · da68bcc

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
- **Tests:** `tests/devtools/test_tier_audit.py`: 36 pass (25 before round 1). Round 1 found the `DB_DSN` check red on `main`'s config tests, so it is gone: setting the variable opens no connection. The merged-tree run is done: after the human-side merge of `main` (`9e3f058`), the pre-push gate passed, and round 3's static scan found **0 violations** across all 13 unit-tier modules on `main`, including PR #38's two new ones (lead, at close-out). `make lint` is clean.
- **Self-rating:** 8/10, proud: yes. The 2 points are the named gaps below; the acceptance test and the lead's two additions are met.
- **Review:** PR #28, merged as `d0e59eb`, closing #20.
  - Round 1, at `9ef33e4`: Reviewer REQUEST_CHANGES. The blocker was the `DB_DSN` check going red on `main`, caused by the lead's own instruction. There were 2 majors (aliased HTTP calls and dynamic imports missed) and 3 minors. Privacy auditor PASS.
  - Round 2, scoped, at `cb6e735`: APPROVE, with one condition: merge `main` before landing.
  - Round 3, scoped to the merge `9e3f058`: APPROVE and PASS.
  - The verdict comments are on the PR.
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
- **Tests:** 13 new (10 `unit` in `tests/unit/gate/`, 3 `integration`), all green in the test container; ruff clean. `make gate-1` against the real fixtures: skipped on re-run 100.0%, new ledger rows 0, PASS, exit 0 (percentages only, DOC-005.D1). Without the fixtures it fails naming `fixtures/images/`.
- **Self-rating:** 9/10, proud: yes. Gap: it calls `run()` (the entry point `classifier dry-run` uses) rather than the CLI, so the CLI wiring is covered by CLI-002.1's own tests, not by the gate; and the private schema comes from `schema_support.py` until TST-003.
- **Review:** PR #41, merged as `537c72c`, closing #22. Round 1 at `557e1f0`: Reviewer REQUEST_CHANGES (1 major: a fixtures folder of only non-images could pass vacuously; 3 minor: an unwrapped traceback, `check_roots` not called, a missing hash), Privacy auditor PASS. Round 2, scoped, at `da68bcc`: APPROVE and PASS. The verdict comments are on the PR.
  - **Lead's G1 run** (main checkout, `537c72c`, `make gate-1`, real fixtures via the read-only mount): skipped on re-run **100.0%**, new ledger rows **0**, **PASS**, exit 0.
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

- Not in the approved M1 plan. **Proposed for M2** at M2 G0 (lead, 2026-10-07): SAN-001.4 and CLI-003.1 add integration tests that need the same helper, so it goes first. **Confirmed into M2 by the human, 2026-10-07.**

## TST-003 — Tasks

- [x] TST-003.1 — A shared private-schema fixture for integration tests; the existing tests moved onto it · #53 · acceptance: `tests/integration/test_dry_run_graph.py` (unchanged behaviour) · PR #63 → `cf77ff3`
  - [x] TST-003.1.1 — `tests/integration/conftest.py`: module-scoped `schema_dsn`, opt-in `empty_ledger`; `schema_support.py` documented as the shared helper · `8393773`
  - [x] TST-003.1.2 — `test_dry_run_graph.py` and `test_dry_run_cli.py` take `schema_dsn` and opt in to `empty_ledger`; their local fixtures removed, test bodies untouched · `0a6a3f3`
  - [x] TST-003.1.3 — `tests/integration/test_schema_fixture.py`: private schema at the single head, `empty_ledger` ordered pair, own schema per call, dropped on exit · `5a5d881`
  - [x] TST-003.1.4 — Results

## TST-003 — Results

### TST-003.1 (worker: qa)

- **Status:** DONE.
- **What landed:** `tests/integration/conftest.py` gives every integration module a module-scoped `schema_dsn` (its own uuid-named schema at Alembic head, dropped with `cascade` at module teardown) and an opt-in `empty_ledger` that truncates `files` in that private schema only. Neither is autouse, so `test_gate_1_script.py` pays for no migration. `schema_support.py` stays as the importable helper, because `scripts/gate_1.py` calls `migrated_schema` outside pytest. The two dry-run modules opt in with `pytestmark = pytest.mark.usefixtures("empty_ledger")`; their test bodies are untouched.
- **Coexistence:** the db tier's `session_*` schema (TST-002.1) and PR #30's per-test schema are never touched: each fixture works in its own `module_*` schema, and `test_schema_fixture.py` asserts `files` resolves there.
- **Tests (`make test`, unit + db + integration):** before 442 passed; after 446 passed (+4, `test_schema_fixture.py`). Integration per module before and after: `test_dry_run_cli.py` 10, `test_dry_run_graph.py` 8 (the acceptance test, unchanged), `test_gate_1_script.py` 3. Mutation check: without `empty_ledger` on the pair's second test, the module fails (1 failed, 3 passed). `make lint` clean.
- **Self-rating:** 9/10, proud: yes. Gap: the db tier's `migrated_db` (tests/db/conftest.py) still repeats the schema-plus-upgrade steps of `migrated_schema`; folding it onto the shared helper touches the db tier's fixture, so it is left as a possible follow-up, as the lead directed on #53.
- **Review:** PR #63, merged as `cf77ff3`, closing #53. Reviewer APPROVE (full, 3 minor: the ordered pair is guarded, the lead's ticks, the branch behind `main` with no overlap) and Privacy auditor PASS, at `714c70d`. The verdict comment is on the PR. `empty_ledger` later became `truncate files cascade` in TST-006.1 (#68), when `sanitize_log` arrived.
- **Deferred:** the `migrated_db` duplication above. It is not allocated: a low-value refactor, left for a quiet moment.

---

## TST-004 — Requirement (lead, from PR #40's review, 2026-10-07)

- **Objective:** Make the tier audit enforce CLAUDE.md §3's fixtures rule: only the `gate` and `gpu` tiers read the real fixtures.
- **Details:**
  - RUN-009 (PR #40) mounts the main checkout's `fixtures/images/` read-only into every `test` container, whatever the tier.
  - Nothing stops a `unit`, `db` or `integration` module from opening it. Extend `tests/devtools/test_tier_audit.py` so a module outside `gate` and `gpu` that references `fixtures/images` (a string constant or a path join) fails, naming the module and the line.
  - Self-tests use synthetic modules only.
- **Constraint:** The audit never opens the fixtures. Synthetic images under `tmp_path` stay legal. QA owns it (DOC-004.D1).
- **Implements:** CLAUDE.md §3 (images), RUN-009, TST-002.2.

## TST-004 — Confirmed reading

- Not in M1's plan. **Proposed for M2** at M2 G0 (lead, 2026-10-07): gate 2 is the first M2 code to read the real fixtures, so the audit should guard the other tiers before it lands. **Confirmed into M2 by the human, 2026-10-07.**
- **TST-004.D1** — **A pinned exemption registry for modules that name the real fixtures without reading them** (QA, chosen by the lead on #54, 2026-10-07). Two `unit` modules name the path legitimately: `tests/unit/gate/test_gate_1_verdict.py` matches gate 1's error text, and `tests/unit/runtime/test_fixtures_mount.py` (RUN-009) asserts the compose mount and `make init`'s output and builds a tmp sandbox repo. `NAMES_FIXTURES_WITHOUT_READING` in the audit lists each such module with a one-line reason, pinned to the exact source text of every reference it may make, once per occurrence. A new reference in a listed module still fails, and so does a pin or an entry the tree no longer has. It is central and reviewed by QA; there is still no per-line escape hatch. Rejected: exempting whole modules (a later read would get through), and rewriting the two tests to dodge the literal (evasion).
- **Scope** (lead, on #54): `fixtures/labels.csv` is covered too, by the same scanner and registry, because the labels are as private as the images. The committed `fixtures/labels.example.csv` stays legal. Only `test_fixtures_mount.py` names the labels file (five references), so no follow-up is needed.

## TST-004 — Tasks

- [x] TST-004.1 — The tier audit flags references to the real fixtures outside `gate` and `gpu` · #54 · acceptance: `tests/devtools/test_tier_audit.py` · PR #67 → `01d550e`
  - [x] TST-004.1.1 — `scan_fixture_refs`: string constants (f-string parts included) and path joins naming `fixtures/images` or `fixtures/labels.csv`, with the exact source text; synthetic self-tests · `0716374`
  - [x] TST-004.1.2 — `audit()` applies it to every module outside `gate` and `gpu`, conftests and helpers included; the pinned `NAMES_FIXTURES_WITHOUT_READING` registry (TST-004.D1); audit-level tests on a synthetic tree · `a6c0859`
  - [x] TST-004.1.3 — Results
  - [x] TST-004.1.4 — A pin covers one occurrence even when an identical reference repeats on the same line (found in the self-rating: the scanner deduplicated them); regression test · `fefdc13`

## TST-004 — Results

### TST-004.1 (worker: qa)

- **Status:** DONE.
- **What landed:** `tests/devtools/test_tier_audit.py` gains `scan_fixture_refs`, a static (`ast`) scan for `fixtures/images` and `fixtures/labels.csv`. It catches string constants (f-string parts, bytes and implicit literal concatenation included; case-insensitive; either slash; whole path segments only, so `labels.example.csv` stays legal) and path joins (`/` chains, `Path(...)`, `os.path.join`, `.joinpath`). Docstrings are prose and don't count. `audit()` applies it to every module whose tier isn't `gate` or `gpu`, `conftest.py`, `__init__.py` and helper modules included. Each message names the module, line, tier and fix: synthetic data under `tmp_path` first, then the move to `tests/gpu/`. The unit-only db, model, Ollama and HTTP checks are unchanged; the real-tree test is renamed `test_every_test_module_stays_in_its_tier`.
- **TST-004.D1 registry:** two modules, ten pinned references (see Confirmed reading). A new or repeated reference in a pinned module fails, and so does a stale pin or entry.
- **Tests:** the module went from 36 to 69 tests (+33: 16 flagged forms, 10 clean forms and 1 source-text check for the scanner, 5 audit tests on synthetic `tmp_path` trees, 1 `fix_for` test). `make test` (unit + db + integration): 546 → 579 passed, 2 deselected. `make lint` clean. The audit never opens a fixture.
  - **Mutation checks on the real tree:** two references injected into an integration module are both reported; dropping one pin from the registry reports that line; with the old same-line dedup, the TST-004.1.4 regression case reports 0 instead of 1.
- **Self-rating:**
  - Pass 1: 8/10, proud: no. Gap: identical references on one line were merged, so a pin counted once covered two (against D1's "once per occurrence"). Fixed in TST-004.1.4.
  - Pass 2: 9/10, proud: yes. Gap: a static scan can't see a path built from variables, by runtime concatenation, or from an env var or config (named in the docstring). Pins are exact source text, so reformatting a pinned line makes the entry stale; it fails loudly and QA re-pins it.
- **Review:** PR #67, merged as `01d550e`, closing #54. Reviewer APPROVE (full, 2 minor: re-pinning after a reformat is accepted, the lead's ticks) and Privacy auditor PASS, at `edd2d62`. The verdict comment is on the PR.
- **Deferred:** none.

---

## TST-005 — Requirement (DESIGN.md M2, 2026-10-07)

- **Objective:** Replay recorded LLM responses outside the `gpu` tier, and measure gate 2.
- **Details:**
  - **Replay (TST-005.1):** an `httpx` transport that serves recorded Ollama responses from `tests/recordings/`, keyed by the request, plugged into MOD-001.1's transport seam through a shared fixture. Outside `gpu`, a missing recording fails, naming its key and the test. It never falls through to live Ollama. In the `gpu` tier, record mode writes new recordings.
  - **Gate 2 (TST-005.2):** `scripts/gate_2.py` measures §11's criterion:
    - **names:** 50 seeded names, deterministic (pinned seed), sanitized by the real `sanitize` path; 0 seeded values may survive;
    - **metadata:** synthetic images with seeded EXIF, XMP, IPTC and GPS tags, plus the sanitized copies of the real fixtures; every output's tags must be inside the keep list and the file-structure tags.
  - It prints percentages, counts of the synthetic seeds, and PASS or FAIL. Never a name, a value or a count about the real fixtures (DOC-005.D1).
- **Constraint:** Recordings are made from synthetic strings only (SAN-001.D10). The gate never prints or records the human's `sanitize.yaml` values. Never skip: a missing prerequisite (Ollama, the model, `sanitize.yaml`) fails with a message naming it.
- **Implements:** CLAUDE.md §3 (determinism, recordings), DESIGN.md §11 M2 gate, R-SAN-2, R-SAN-3, R-SAN-4.

## TST-005 — Confirmed reading

- `scripts/gate_2.py` is a stub that exits 1 (RUN-002.4). `make gate-2` already runs it in the `test` container, which reaches `ollama` and mounts the real fixtures read-only (RUN-009).
- `tests/recordings/` is empty and QA-owned.
- **TST-005.D1** — **The worker whose task makes a recording commits it** (confirmed by the human, 2026-10-07, as recommended; rule change DOC-007.D5, PR #60). Recordings go under `tests/recordings/<package>/`, made from synthetic strings only. QA owns the recording format and the replay fixture (TST-005.1), as DOC-004.D1 split the tests. So MOD-001.2 commits the entity recordings, and no extra QA recording task is needed.
- **TST-005.D2** — **Gate 2's seeded names come from three sources** (confirmed by the human, 2026-10-07, as recommended). The gate builds 50 names with a pinned seed from:
  1. the `literal` values in the local, git-ignored `sanitize.yaml`, read inside the `test` container and never printed, recorded or committed, so the gate measures the human's real rules;
  2. synthetic emails and phone numbers;
  3. a committed list of fictional person, organisation and place names, for the entity rule.

  The residual check is a case-insensitive search for each seeded value in the sanitized name, with SAN-001.D1's separators. The gate prints PASS or FAIL and the residual share as a percentage only (DOC-005.D1); TST-005.D4 sets how it draws.
- **TST-005.D3** — **Recording format** (lead, 2026-10-07): one JSON file per request under `tests/recordings/<package>/`, named by the SHA-256 of the canonical request (model, prompt, schema, options). It stores the request and the response, so a reviewer can read both.
- **TST-005.D4** — **Gate 2 reveals nothing about the local rules** (lead, 2026-10-07, from PR #61's privacy audit).
  - The share of names per source is fixed in the gate's code, never derived from the size of the local `literal` pool. Literal values are drawn **with replacement**, so the drawn set looks the same whatever the pool holds.
  - Output is PASS or FAIL and percentages only. Never a count, a pool size, a per-source split, or a "fewer than N" message.
  - Every error is value-free: a failing literal is reported by its rule id and a hash at most, and no traceback may echo a value. An empty or missing `literal` rule fails with a message naming `sanitize.yaml` and the rule id.
- **TST-005.D5** — **The canonical recording key** (lead, 2026-10-07, on #51 and #55; refines D3). The key is the SHA-256, in UTF-8, of `json.dumps({model, prompt, format, options, think?, raw?}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. `think` and `raw` are present only when the `/api/generate` body carries them, because both change the answer. `raw` was added with MOD-001.D5. `keep_alive` and `stream` are excluded. Files are `tests/recordings/<package>/<key>.json`, holding `{"request": …, "response": …}`. TST-005.1 implements it, and its lint checks every committed recording.
- **TST-005.D6** — **Where gate 2's two halves run** (lead, 2026-10-07, on #58). The names half calls `sanitize_name` on string paths, so no file is ever named with the human's values. The metadata half runs ingest and the sanitize node end to end, in a temporary results tree that is removed afterwards.
- **TST-005.D7** — **A node `error` fails gate 2** (lead, 2026-10-07, on #58). Any gate input, synthetic or real, that the node sets to `error` fails the gate. Otherwise "only the allow-list" would pass by dropping files, and a real file that trips SAN-001.2's structure allow-list would stay hidden.
- **TST-005.D8** — **Shares and the per-word check** (lead, 2026-10-07, on #58). 20 literal, 10 email/phone and 20 fictional entity seeds, fixed in code. For **person** seeds only, each first or last name word of 3+ letters is also searched. Orgs and places are checked as the full value, so common words a template may contain (`Bay`, `Club`) cause no false failures. The structure-tag check imports a public predicate from `classifier/sanitize/exif.py`, which #56 exposes, never a private one.
- **TST-005.D9** — **One review push with the integration acceptance** (lead, 2026-10-07, on #58). The first real `make gate-2` failed only on the names half. That is configuration, not code: the human's local rule set is incomplete; the committed example is fixed in #82 (SAN-002.1). So review isn't blocked on the human's local file: TST-005.2 is pushed once with `acceptance=tests/integration/test_gate_2_script.py`, and `scripts/gate_2.py` goes back right after. The gate is neither changed nor skipped, and it must PASS at G1, after the human's local change. D2, D4 and D8 are unchanged.

## TST-005 — Tasks

- [x] TST-005.1 — The Ollama replay transport and fixture · #55 · acceptance: `tests/devtools/test_recordings.py` · PR #71 → `4835b93`
  - [x] TST-005.1.1 — `tests/recordings/replay.py`: the TST-005.D5 key, `ReplayTransport`, `RecordingTransport`, `RecordingError(BaseException)`; unit tests · `db5fc45`
  - [x] TST-005.1.2 — The shared `ollama_transport` fixture and `--record-ollama` (gpu tier only) in `tests/conftest.py`; `pytester` tests · `b2639e6`
  - [x] TST-005.1.3 — A lint test over every committed recording; the "how to record" README · `e2994d6`
  - [x] TST-005.1.4 — Results · `354324f`
  - [x] TST-005.1.5 — PR #71 privacy audit: stray file and folder names are reported by a short SHA-256 of their path, a bad package by a fixed message; record mode forwards only to `OllamaClient`'s allowed hosts (`check_host`, imported) · `91d62a0`
  - [x] TST-005.1.6 — PR #71 privacy audit, round 2: `lint_recordings` reports a non-regular file by its `describe()` label, and `load_recording` turns an `OSError` into a labelled, unchained `RecordingError` · `3442ea8`
  - [x] TST-005.1.7 — PR #71 privacy audit, round 3: every filesystem call in `replay.py` (the lint's walk and stat, replay's stat and load, record mode's stat, `mkdir` and write) turns an `OSError` into an unchained `RecordingError` with a label or a fixed message · `693f18a`
  - [x] TST-005.1.8 — PR #71 privacy audit, round 4: record mode encodes the recording to UTF-8 bytes before opening the file; a lone surrogate in Ollama's reply gives a fixed, unchained `RecordingError` and writes nothing · `456c5b7`
- [ ] TST-005.2 — Gate 2 · #58 · acceptance: `scripts/gate_2.py`
  - [x] TST-005.2.1 — The seed draw (fixed shares, one random stream per purpose, literals with replacement), the gate's own residual matcher and the names judge; `tests/unit/gate/test_gate_2_names.py` · `507212a`
  - [x] TST-005.2.2 — The synthetic seeded images (7 formats, ICC, Adobe APP14) and the metadata judge, plus the marker-bytes check; `tests/unit/gate/test_gate_2_metadata.py`. The judge takes the structure predicate as an argument. The test against #56's public `is_structure_tag` comes with TST-005.2.5. · `bdcc1ef`
  - [x] TST-005.2.3 — `measure()`/`main()` and the prerequisite checks; `tests/integration/test_gate_2_script.py`; replaces the RUN-002.4 stub. The ingest and sanitize nodes are picked by name, as TST-007.1 pins gate 1. · `1632b49`
  - [ ] TST-005.2.4 — `make gate-2` on the box once #56 lands; Results. First run (2026-10-08, main `b020c31`): FAIL on the names half only. The reason class is reported on #58; the lead decides.
  - [x] TST-005.2.5 — After #56: the node reads the gate's own rules file (`sanitizer.rules_file`); tests against the public `is_structure_tag`/`is_allowed`, and a metadata PASS through the real sanitize node; the repo goes on `sys.path` at import (the first `make gate-2` died with `ModuleNotFoundError`), with a regression test · `12b2038`
  - [x] TST-005.2.6 — PR #84 privacy audit, round 1: the real-fixtures metadata line prints a verdict only (a share would reveal a small set's size), with tests. The journal and the PR body drop the per-source split and the description of the human's local rules. · `2bcf6bd`
  - [x] TST-005.2.7 — PR #84 privacy audit, round 2 (text only): the recorded run block shows the real-fixtures line in its verdict-only form, the synthetic set is named where 100.0% is quoted, and the worked numbers leave `judge_metadata`'s docstring.

## TST-005 — Results

### TST-005.1 (worker: qa)

- **Status:** DONE.
- **What landed:**
  - **`tests/recordings/replay.py`:**
    - `recording_key()` implements TST-005.D5 exactly: `model`, `prompt`, `format` and `options`, plus `think` and `raw` only when sent; `keep_alive` and `stream` excluded.
    - `ReplayTransport` serves only `POST /api/generate` and never opens a socket.
    - `RecordingTransport` (record mode) forwards to an upstream the caller builds. It writes `{"request", "response"}` without Ollama's `context`. It keeps an existing file with the same answer and refuses a different one.
    - `lint_recordings()` checks the committed tree.
    - `RecordingError` derives from `BaseException`, so neither `OllamaClient`'s `httpx` handling nor a fail-closed `except Exception` can swallow a miss. Every error names only the package, the 64-hex key and the test id, and is raised unchained.
  - **`tests/conftest.py`:**
    - `ollama_transport(package)` always replays outside `gpu`. In `gpu` it gives the real transport, or record mode with `pytest -m gpu --record-ollama`.
    - The option is a usage error when the selection, after `-m`, holds a non-gpu test.
    - A miss the code under test swallowed fails the test at teardown, once.
  - **`tests/recordings/README.md`:** usage, format and the record command. No Makefile or compose change (the lead, on #55).
- **Tests:** `tests/devtools/test_recordings.py` has 52 unit tests:
  - the key, replay and record mode through a real `OllamaClient` on synthetic `tmp_path` recordings;
  - four `pytester` runs of the real conftest in a synthetic tree;
  - the lint on the real tree and on a synthetic tree with five planted problems.

  A planted secret prompt is asserted absent from every error and from the inner pytest output. Totals: devtools 121 passed (69 audit + 52); `make test` 726 → 729 passed, 2 deselected (the 726 includes .1.1 and .1.2); `make lint` clean.
- **Mutation checks:** each mutation fails the module:
  - `RecordingError(Exception)`: 1 failed;
  - no teardown net: 1 failed;
  - teardown net without the call-failed guard (a miss reported twice): 1 failed;
  - `raw` dropped from the key: 1 failed;
  - errors chained: 9 failed.
- **Live check (gpu box, throwaway script, not committed):** record mode against the real `ollama` service (`models.text_llm`, a synthetic one-word prompt, temperature 0, seed 7) wrote one file into a temp folder. `lint_recordings` passed on it, and replay returned the identical answer. The real reply's top-level fields match what the format expects (`response` is a string).
- **Self-rating:** 9/10, proud: yes. Gaps:
  - The fixture's `gpu and` guard on record mode survives its mutation. The collection check refuses `--record-ollama` on any non-gpu selection first, so the guard is defence in depth that the CLI can't reach.
  - The MOD-001.2 recordings weren't pushed when this landed, so they haven't been run through the lint yet. It checks them on merge (the lead's rule on #55: if they fail it, that's theirs to fix).
  - A thinking model's reply keeps its `thinking` text in the recording. That's bulky but readable, and MOD-001.D5's raw mode avoids it.
- **Review:** round 1 (`354324f`): Reviewer APPROVE; Privacy auditor FAIL, low severity. Fixed in TST-005.1.5:
  - `describe()` shows only a valid `<package>/<64-hex key>.json` as it is. Any other file or folder name is reported by a 12-hex SHA-256 of its path relative to the lint root, so one stray file has one label in every message. `package_dir()` refuses a bad package with a fixed message, and an unsupported method is no longer echoed.
  - `RecordingTransport` checks each request's host with `classifier.models.ollama.check_host` before forwarding, and a refusal names no host.
  - Tests: the planted secret now sits in a stray file name, a nested folder name, an unkeyed name in a package and a bad package folder, and no lint, load or package message carries it. Seven host cases were added (four refused before any forward, three allowed). The module went from 52 to 61 tests. Mutations: dropping the host check fails 4, and echoing names in `describe()` fails 2.
- **Review, round 2** (`91d62a0`): Reviewer APPROVE; Privacy auditor FAIL, low severity, on one remaining path: `read_bytes()` raised an uncaught `OSError` whose text carries the full path (a folder named `*.json`, an unreadable file). Fixed in TST-005.1.6:
  - `lint_recordings` reports anything that isn't a regular file (a folder, a broken link) as `<label> is not a regular file`.
  - `load_recording` catches `OSError` and raises `<label> cannot be read as a file`, unchained.
  - Tests: a folder named `<secret>.json`, in the lint and loaded directly, and an unreadable file in the lint, in `load_recording` and through replay. The test container runs as root, so the unreadable case is a monkeypatched `PermissionError`. The secret appears in no problem or exception. The module went from 61 to 64 tests. Mutations: dropping the `OSError` catch fails 2, and dropping the regular-file check fails 1.
- **Review, round 3** (`3442ea8`): Reviewer APPROVE; Privacy auditor FAIL, low severity: `is_file()` in the lint can still raise an `OSError` (e.g. access denied on a stat), and the lead asked to close the class in one go. Fixed in TST-005.1.7:
  - `_is_file()` wraps every stat: `<label> cannot be read as a file`, unchained.
  - The lint's `rglob` walk is in a `try`. A failure gives one fixed problem, `the recordings tree cannot be walked; no recording was checked`.
  - Record mode's `mkdir` and `write_text` give `recording <package>/<key>.json cannot be written`, unchained.
  - `read_bytes` was already wrapped (TST-005.1.6). Every filesystem call in `replay.py` is now inside one of these.
  - Tests patch `Path.is_file` (in the lint on a stray `<secret>.json`, in replay and in record mode), `Path.mkdir`, `Path.write_text` and `Path.rglob` to raise a `PermissionError` carrying the full path. They assert that neither the secret nor the temp path appears and that no error is chained. The module went from 64 to 70 tests. Mutations: unwrapping the stat fails 3, the walk fails 1, and the write fails 2.
- **Review, round 4** (`693f18a`): Privacy auditor FAIL, low severity, one last case: `write_text` raised a `UnicodeEncodeError` (a `ValueError`, not an `OSError`) quoting the character when Ollama's reply held a lone surrogate. Fixed in TST-005.1.8:
  - The text is encoded to bytes before `mkdir` and the write, and `write_bytes` replaces `write_text`, so nothing is left half-written.
  - The encode failure gives `Ollama's reply for <package>/<key>.json is not valid UTF-8 text`, unchained. The `OSError` wrap stays.
  - Tests: a reply whose JSON decodes to a lone surrogate beside the planted secret. Neither appears in the error, nothing is written (not even the folder), and the record-mode filesystem test now patches `write_bytes`. The module went from 70 to 71 tests. Mutation: unwrapping the encode fails 1.
- **Review, round 5** (`456c5b7`): Reviewer APPROVE and Privacy auditor PASS. Merged as `4835b93` (PR #71), closing #55. The verdict comments for every round are on the PR.
- **Deferred:** none.

### TST-005.2 (worker: qa)

- **Status:** DONE_WITH_CONCERNS.
  - **Concern (medium; config, not code):** the real gate fails on the names half. That is configuration, not code: the human's local rule set is incomplete; the committed example is fixed in #82 (TST-005.D9). Follow-ups: the human's local `sanitize.yaml`, #82 (SAN-002.1) for the example file, and the lead's G1 re-run of `make gate-2` on `main`.
- **Tests:**
  - `tests/unit/gate/test_gate_2_names.py`: 32 tests; `tests/unit/gate/test_gate_2_metadata.py`: 28 (23 before TST-005.2.6); `tests/integration/test_gate_2_script.py`: 20. Synthetic data only: a planted-secret rules file, a fake detector over `entity_synthetic.yaml`, and seeded images.
  - The names half runs through the real `load_rules` and `sanitize_name`. The metadata half runs through SAN-001.2's real strip and through ingest plus #56's node, which gives 100.0% sanitized and clean on the synthetic set. The judge agrees with `exif.is_allowed` on every tag of the seeded set.
  - Privacy: every prerequisite fails through `main`, naming it, and the planted secret appears in no output, error or traceback. An unexpected error prints its type only.
  - Regression: `python scripts/gate_2.py` died with `ModuleNotFoundError`. The test loads the script in `python -I` from outside the repo, and it fails without the fix.
  - `make test` (default tiers): 1103 passed, 24 deselected; ruff clean.
- **`make gate-2`** (2026-10-08, on main `b020c31` plus this branch):

  ```
  names: residual seeded values 8.0% (required 0.0%): FAIL
  metadata, synthetic: 100.0% sanitized, 100.0% of outputs clean (required 100.0% and 100.0%): ok
  metadata, synthetic: seeded values in results files: ok
  metadata, real fixtures: every input sanitized and clean (required): ok
  gate 2 FAIL: 50 seeded names come out with 0 residual sensitive values; EXIF on outputs contains only the allow-list.
  ```

  The real-fixtures line is shown in the verdict-only form that TST-005.2.6 introduced; the run itself predates it.
- **Self-rating:** 8/10, proud: yes. Gaps:
  1. The acceptance gate hasn't passed for real yet: it waits on the human's config (above).
  2. No single integration test runs `main` to PASS. The names half needs the entity rule, and the node would then call live Ollama, which the integration tier forbids. So the two halves are tested separately, and `main`'s composition with a stubbed `measure`.
  3. A literal value holding `/` would become a path separator and show as a false residue. A file name can't hold `/`, so a real rule can't need it. Left as is.
- **Push (TST-005.D9):** pushed once with `acceptance=tests/integration/test_gate_2_script.py`; `.task` restored to `scripts/gate_2.py` right after.
- **Review (lead):** PR #84, merged as `361ac3f`, closing #58.
  - Round 1 at `28f075e`: Reviewer APPROVE, Privacy auditor FAIL: a per-source split and a description of the local rules in the write-ups. Fixed in TST-005.2.6, which also made the real-fixtures line verdict-only.
  - Round 2 at `2bcf6bd`: Reviewer APPROVE, Privacy auditor FAIL (text only: the recorded run block). Fixed in TST-005.2.7.
  - Round 3 at `e04c356`: Reviewer APPROVE and Privacy auditor PASS.

  The lead edited two #58 comments (its own and the desk's) to the same standard. The verdict comments are on the PR.
- **Deferred:** the PASS run of `make gate-2` goes to G1 (the lead, after the human's config change).

---

## TST-006 — Requirement (lead, from DB-002.1's blocker on #45, 2026-10-07)

- **Objective:** Make the integration tier's `empty_ledger` empty `files` and every table that references it.
- **Details:** DB-002.1 adds `sanitize_log` with a foreign key to `files` and no cascade on delete (DB-002.D2). Postgres then refuses `truncate files`. The fixture runs `truncate files cascade`, still only in the module's private schema.
- **Constraint:** Never truncate a shared schema. It must pass on `main` before the migration lands. QA owns the file (DOC-004.D1), so the Pipeline desk on #45 didn't edit it.
- **Implements:** CLAUDE.md §3 (shared setup), TST-003.1, DB-002.D2.

## TST-006 — Confirmed reading

- The cascade can't leave the module's schema. Every `module_*` schema is migrated with its own `search_path`, so each foreign key stays local, and no migration writes a cross-schema one (PR #69's review).
- Allocated mid-run by the lead and done by a short extra QA desk, so DB-002.1 wasn't blocked. That was one desk over the plan's limit of 4 for the length of the task.

## TST-006 — Tasks

- [x] TST-006.1 — `empty_ledger` runs `truncate files cascade`; a test with a child table that has a foreign key to `files` · #68 · acceptance: `tests/integration/test_schema_fixture.py` · PR #69 → `2716ea5`

## TST-006 — Results

### TST-006.1 (worker: qa)

- **Status:** DONE. One commit, `1a28598` (TST-006.1.1). The worker's results are in PR #69's body.
- **Tests:** the new test fails against the old fixture (`FeatureNotSupported`) and passes with the cascade. `make test` 678 passed, per the PR.
- **Review:** PR #69, merged as `2716ea5`, closing #68. Reviewer APPROVE (full, informational only) and Privacy auditor PASS, at `1a28598`. The verdict comment is on the PR.

---

## TST-007 — Requirement (lead, from SAN-001.4's blocker on #56, 2026-10-08)

- **Objective:** Keep gate 1 an ingest-only measure once the sanitize node registers.
- **Details:** `scripts/gate_1.py` ran `run(config, dry_run=True)` with the default `REGISTRY`. With `sanitize` registered, gate 1 and its integration test would sanitize with the local rules: a `SanitizeConfigError` before the entity wiring, and live entity calls from the integration tier after it, which CLAUDE.md §3 forbids. Pin it to `nodes=(ingest,)`.
- **Constraint:** Gate 1's criterion and output stay unchanged. It must pass on `main` before and after SAN-001.4.
- **Implements:** DESIGN.md §11 M1 gate, CLAUDE.md §3.

## TST-007 — Tasks

- [x] TST-007.1 — Gate 1 runs only the ingest node, with a test that fails on the old gate · #78 · acceptance: `tests/integration/test_gate_1_script.py` · `2e4a6f3`, PR #80 → `fb07cc0`

## TST-007 — Results

### TST-007.1 (worker: qa)

- **Status:** DONE. The worker's results are in PR #80's body. The new test fails on the old gate (1 failed) and passes now.
- **Review:** PR #80, merged as `fb07cc0`, closing #78. Reviewer APPROVE (2 informational minors). The Privacy auditor's first pass flagged the gate wording "100.0% skipped on re-run, 0 new ledger rows". On the lead's request it re-judged that against DOC-005.D1's established reading (gate results as percentages and a zero delta) and revised to PASS.
