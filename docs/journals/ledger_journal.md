# Ledger — journal

**ID:** DB-001 (+ DB-002) · **Systems:** DB · **Type:** feature · **Status:** DB-001 done; DB-002 proposed · **Milestone:** m1 (DB-002: m2) ·
**Issues:** #14, #45 (DB-002.1) · **Branch:** `office/pixel-7049` (DB-001.1)

<!--
Rules: CLAUDE.md §1 (DOC-001). Public repo: never write image file names, captions,
references or host paths here. Use hashes.
-->

---

## DB-001 — Requirement (DESIGN.md M1, 2026-10-06)

- **Objective:** Create the `files` ledger table through Alembic, as the pipeline's only checkpoint.
- **Details:**
  - Set up Alembic in `classifier/db/`, reading the DSN from the config loader (CFG-001) or `DB_DSN`.
  - The first migration enables the `vector` extension and creates `files` with the §5 key columns.
  - It also creates the `files.status` enum: `queued, sanitized, classified, captioned, resolved, named, proposed, filed, skipped, error, deleted`.
  - Columns later milestones fill (scores, caption, reference, template, output) are created now, nullable.
  - SQLAlchemy 2.0 models mirror the table.
- **Constraint:** Only `files` and `schema_version` in M1. The other §5 tables arrive with the milestones that use them. Alembic keeps one head (CLAUDE.md "Migrations").
- **Implements:** DESIGN.md §5 (`files`, `files.status`), P-4, R-ING-1 (`source_hash` primary key, `short_hash`), R-ING-7 (`duplicate_paths`).

## DB-001 — Confirmed reading

- The `pgvector/pgvector:0.8.7-pg16` images back both `db` and `db-test`. `tests/db/test_db_reachable.py` already proves pgvector loads in `db-test`.
- `sqlalchemy>=2.0`, `alembic>=1.13`, `psycopg[binary]>=3.2` and `pgvector>=0.3` are already dependencies.
- §5 says "Unsorted" is a format, not a status, and review is `needs_review` + `review_reason ∈ {unsorted, ambiguous_reference}`. Both go in as columns now, so M3 needs no enum change.
- `source_path` is a §5 key column. **ING-001.D2** (the human, 2026-10-06; rule change DOC-004.D3) allows it, and `duplicate_paths`, to hold the container path (`/source/...`) in the local ledger. This migration creates both columns.

## DB-001 — Plan

1. `classifier/db/`: `alembic.ini` location per Alembic convention, `env.py` reading the DSN, `models.py` with `File` and the `FileStatus` enum.
2. Migration `0001_files`: `create extension if not exists vector`, the enum and `files`, with indexes on `status` and `short_hash`.
3. A db-tier test: `alembic upgrade head` on `db-test`, then check the columns, the enum values and the primary key, and that `downgrade base` and `upgrade head` round-trip.

## DB-001 — Tasks

- [x] DB-001.1 — Alembic set-up and the `files` migration · #14 · acceptance: `tests/db/ledger/test_files_migration.py`
  - [x] DB-001.1.1 — Alembic set-up: `alembic.ini`, `env.py`, DSN through `load_config` · ac31e11
  - [x] DB-001.1.2 — SQLAlchemy `File` model and `FileStatus` enum · 34f81e8
  - [x] DB-001.1.3 — Migration `0001_files` with its db-tier test (the acceptance test) · c3a8f70
  - [x] DB-001.1.4 — Journal Results, and a db test that env.py loads the DSN through `load_config` · 9967104

## DB-001 — Results

### DB-001.1 (worker: pipeline)

- **Status:** DONE
- **Triage:** medium. Alembic set-up, models and the first migration, all inside `classifier/db/`. Tests: unit and db tiers plus lint; no gpu or eval, since no models or prompts are touched. Solo.
- **Tests:** `make test` (unit + db + integration): 168 passed. Acceptance `tests/db/ledger/test_files_migration.py`: 6 passed. It covers the columns and their nullability, the primary key, the enum order, the indexes, the defaults and checks, the downgrade round trip, a single head, no model/migration drift, and that `env.py` takes the DSN from `load_config`. Unit: `tests/unit/db/` has 8 tests, for the URL helper and the model. `make lint` is clean.
- **Self-rating:** 9/10, proud: yes. Pass 1: rated 8, because `env.py`'s `load_config` path was untested. Pass 2: added that test. The remaining point is that `reference_id` is a bigint with no FK, and its final type is decided when `references` arrives (R-RAG), which is a deferral, not a defect.
- **Review:** PR #30, merged as `72a24e0`, closing #14. Reviewer APPROVE (full, 3 minor), Privacy auditor PASS, at `9967104`; the verdict comment is on the PR. Minor 1, the bare `KeyError` on a missing `DB_DSN`, was fixed by TST-002.1 (PR #31). Minor 2 is closed here. Minor 3 (the `vector` extension stays after downgrade) is intended.
- **Deferred:**
  - `reference_id` type and FK, until the `references` table lands (a later migration).
  - `updated_at` refreshes only through the ORM (`onupdate`, per the lead's note). Raw SQL updates must set it.
  - `status` is a native Postgres enum. Adding a value later needs `alter type ... add value` in its own migration.
  - Test isolation: the tests run in a throwaway schema dropped with `cascade`, so the shared `db-test` is left as found (see the test docstring).

---

## DB-002 — Requirement (DESIGN.md M2, 2026-10-07)

- **Objective:** Add the `sanitize_log` table and the column that holds a file's sanitized name.
- **Details:**
  - Migration `0002`: `sanitize_log` with `id` (bigserial), `source_hash` (FK to `files`), `rule_id`, `field`, `before_hash` (64 hex), `after_value` (nullable), `created_at`; an index on `source_hash` (R-SAN-6).
  - `files.original_sanitized` (text, nullable): the sanitized stem (SAN-001.D8).
  - SQLAlchemy models mirror both.
- **Constraint:** Alembic keeps one head: `down_revision` is `0001`. `after_value` holds only the replacement token, never an original value. No other §5 table yet.
- **Implements:** DESIGN.md §5 (`sanitize_log`), R-SAN-6, SAN-001.D8.

## DB-002 — Confirmed reading

- `0001_files.py` is the only migration, so `0002` is the head after it.
- **DB-002.D1** — **`field` values** (lead, 2026-10-07): `filename`, `path_segment`, or `exif:<tag name>` (SAN-001.D3, D8), enforced by a check constraint on the prefix. Tag names aren't sensitive; their values are only ever hashed.
- **DB-002.D2** — **No cascade** (lead, 2026-10-07): a `files` row is never deleted (`deleted` is a status), so the FK has no `on delete cascade`.
- The hash in `before_hash` follows SAN-001.D5 (open, for the human). The column is 64 hex characters either way.

## DB-002 — Tasks

- [ ] DB-002.1 — Migration `0002`: `sanitize_log` and `files.original_sanitized` · #45 · acceptance: `tests/db/ledger/test_sanitize_log_migration.py`

## DB-002 — Results

### DB-002.1 (worker: pipeline)

- **Status:**
