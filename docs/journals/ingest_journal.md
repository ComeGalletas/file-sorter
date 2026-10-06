# Ingest — journal

**ID:** ING-001 · **Systems:** ING (+ PIPE, DB) · **Type:** feature · **Status:** proposed · **Milestone:** m1 ·
**Issues:** #15, #16 · **Branch:** per task, named by agent-office (`office/*`)

<!--
Rules: CLAUDE.md §1 (DOC-001). Public repo: never write image file names, captions,
references or host paths here. Use hashes.
-->

---

## ING-001 — Requirement (DESIGN.md M1, 2026-10-06)

- **Objective:** Hash every file in the source folder and record it once in the ledger, skipping anything already known.
- **Details:**
  - **Discovery:** walk `source_root` recursively, read-only.
    - OS metadata files (`desktop.ini`, `Thumbs.db`, `.DS_Store`) are ignored silently.
    - A file that isn't one of the MVP image types, or can't be decoded, is `skipped` with a reason.
  - **Hashing:** `source_hash` is the SHA-256 of the bytes, and `short_hash` its first 8 hex chars.
  - **Per image:**
    - capture the source mtime;
    - decode the first frame or page (GIF, TIFF, HEIC via `pillow-heif`);
    - derive `animated`, true when the file has more than one frame.
  - **Ledger node:**
    - A new hash gets a `queued` row.
    - A hash already in the ledger, in any status except `error`, is skipped with no side effects.
    - The same hash at a second path is appended to `duplicate_paths`, not re-processed.
- **Constraint:**
  - The source is never written to. It is mounted `:ro`, and the code opens files read-only.
  - Logs carry hashes, never file names.
  - Thumbnails (R-ING-5) are made from the sanitized copy, so they wait for M2 (ING-001.D1).
- **Implements:** R-ING-1, R-ING-2, R-ING-3, R-ING-4, R-ING-6, R-ING-7, R-ING-8, R-ING-9, P-1, P-4.

## ING-001 — Confirmed reading

- **MVP types:** jpg, jpeg, png, webp, gif, bmp, heic, tiff (DESIGN.md §1).
- **The real folder's profile:** mostly png, then jpg/jpeg and gif, one webp, plus a few non-image files (audio, `desktop.ini`). So the skip and ignore paths both run on real data.
- **Dependencies:** `pillow>=11.0` and `pillow-heif>=0.18` are already dependencies. Pillow's `is_animated` covers GIF, WebP and APNG (R-ING-9).
- **R-ING-2's "except error":** a file whose last run ended in `error` is retried. That matters from M7. In M1 no node writes `error` except an unreadable file, which R-ING-3 marks `skipped`.
- **Where the code lives:** ingest is a graph node, so it goes in `classifier/graph/` (Pipeline). Pure helpers (hashing, discovery, frame probing) sit beside it and are unit-tested without a database.
- **ING-001.D1** — **Lead reading, for the human to confirm:** R-ING-5 thumbnails move to M2. DESIGN says to generate them "from the **sanitized** copy", and §11 doesn't list them in M1's scope.
- **ING-001.D2** — **Open, for the human:** may M1 store `source_path` and `duplicate_paths` in the ledger, and write source paths to the dry-run CSV, before the M2 sanitizer exists?
  - CLAUDE.md's hard rules forbid storing "unsanitized filenames". DESIGN §5 has `source_path` as a key column, and R-PIPE-2's CSV maps `source → proposed output`.
  - Options:
    1. **(Recommended)** Store the container path (`/source/...`) in the local ledger, which is never committed, and in the git-ignored `results_root/reports/` CSV. Logs and test output carry hashes only. The rule is read as covering logs and anything persisted beyond the local ledger and reports.
    2. Store only hashes until M2. Ingest re-walks the folder to map hash → path on every run, and the CSV has no source column.
  - Option 2 makes `dry-run` output hard to review by hand.

## ING-001 — Plan

1. **ING-001.1, pure functions:** `hash_file`, `discover(root)` (yields image candidates, skipped-with-reason entries, and drops OS metadata), and `probe_image(path)` (decodes the first frame or page and returns `animated`). Unit tests use synthetic images generated in code: a 2-frame GIF and WebP, a multi-page TIFF, a truncated PNG, a text file named `.png`, and an OS metadata file.
2. **ING-001.2, the ledger node:** `ingest(batch)` writes `queued` rows for new hashes, `skipped` rows with a reason, and appends duplicate paths. A known hash is a no-op. It returns counts: new, skipped-known, skipped-unreadable, duplicate. Db-tier tests run against the TST-002.1 fixture.

## ING-001 — Tasks

- [ ] ING-001.1 — Hashing, discovery and frame probing (pure functions) · #15 · acceptance: `tests/unit/ingest/test_discovery.py`
- [ ] ING-001.2 — Ingest node: ledger writes, known-hash skip, duplicate paths · #16 · acceptance: `tests/db/ingest/test_ingest_ledger.py`

## ING-001 — Results

### ING-001.1 (worker: pipeline)

- **Status:**
- **Triage:**
- **Tests:**
- **Self-rating:**
- **Review:**
- **Deferred:**

### ING-001.2 (worker: pipeline)

- **Status:**
- **Triage:**
- **Tests:**
- **Self-rating:**
- **Review:**
- **Deferred:**
