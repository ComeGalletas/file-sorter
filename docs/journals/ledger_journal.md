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
  - [x] DB-001.1.3 — Migration `0001_files` with its db-tier test (the acceptance test)
  - [ ] DB-001.1.4 — Journal Results

## DB-001 — Results

### DB-001.1 (worker: pipeline)

- **Status:**
- **Triage:**
- **Tests:**
- **Self-rating:**
- **Review:**
- **Deferred:**
