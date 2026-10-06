# Ledger — journal

**ID:** DB-001 · **Systems:** DB · **Type:** feature · **Status:** proposed · **Milestone:** m1 ·
**Issues:** #14 · **Branch:** per task, named by agent-office (`office/*`)

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

- [ ] DB-001.1 — Alembic set-up and the `files` migration · #14 · acceptance: `tests/db/ledger/test_files_migration.py`
  - [x] DB-001.1.1 — Alembic set-up: `alembic.ini`, `env.py`, DSN through `load_config` · ac31e11
  - [x] DB-001.1.2 — SQLAlchemy `File` model and `FileStatus` enum · 34f81e8
  - [x] DB-001.1.3 — Migration `0001_files` with its db-tier test (the acceptance test) · c3a8f70
  - [x] DB-001.1.4 — Journal Results, and a db test that env.py loads the DSN through `load_config` (this commit)

## DB-001 — Results

### DB-001.1 (worker: pipeline)

- **Status:** DONE
- **Triage:** medium. Alembic set-up, models and the first migration, all inside `classifier/db/`. Tests: unit and db tiers plus lint; no gpu or eval, since no models or prompts are touched. Solo.
- **Tests:** `make test` (unit + db + integration): 168 passed. Acceptance `tests/db/ledger/test_files_migration.py`: 6 passed. It covers the columns and their nullability, the primary key, the enum order, the indexes, the defaults and checks, the downgrade round trip, a single head, no model/migration drift, and that `env.py` takes the DSN from `load_config`. Unit: `tests/unit/db/` has 8 tests, for the URL helper and the model. `make lint` is clean.
- **Self-rating:** 9/10, proud: yes. Pass 1: rated 8, because `env.py`'s `load_config` path was untested. Pass 2: added that test. The remaining point is that `reference_id` is a bigint with no FK, and its final type is decided when `references` arrives (R-RAG), which is a deferral, not a defect.
- **Review:** pending (lead).
- **Deferred:**
  - `reference_id` type and FK, until the `references` table lands (a later migration).
  - `updated_at` refreshes only through the ORM (`onupdate`, per the lead's note). Raw SQL updates must set it.
  - `status` is a native Postgres enum. Adding a value later needs `alter type ... add value` in its own migration.
  - Test isolation: the tests run in a throwaway schema dropped with `cascade`, so the shared `db-test` is left as found (see the test docstring).
