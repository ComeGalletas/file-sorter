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
- **Real data exercises every path:** the target folder (DESIGN.md §1) also holds non-image files and OS metadata files, so the skip and ignore paths both run on real data.
- **Dependencies:** `pillow>=11.0` and `pillow-heif>=0.18` are already dependencies. Pillow's `is_animated` covers GIF, WebP and APNG (R-ING-9).
- **R-ING-2's "except error":** a file whose last run ended in `error` is retried. That matters from M7. In M1 no node writes `error` except an unreadable file, which R-ING-3 marks `skipped`.
- **Where the code lives:** ingest is a graph node, so it goes in `classifier/graph/` (Pipeline). Pure helpers (hashing, discovery, frame probing) sit beside it and are unit-tested without a database.
- **ING-001.D1** — **R-ING-5 thumbnails move to M2** (confirmed by the human, 2026-10-06). DESIGN generates them "from the **sanitized** copy", and §11 doesn't list them in M1's scope.
- **ING-001.D2** — **Store the container source path only in the local ledger and the local reports** (confirmed by the human, 2026-10-06, option 1 as recommended). The rule change is DOC-004.D3, merged in PR #24: CLAUDE.md's hard rule now names this as its one exception.
  - `files.source_path` and `files.duplicate_paths` hold the container path (`/source/...`).
  - The `dry-run` CSV under `results_root/reports/` may carry it too.
  - Logs, console and test output, issues, PRs and journals carry hashes only. Host paths are never stored.
  - The rejected option was hashes only until M2, which would make `dry-run` output hard to review by hand.
  - **Open, for the human:** PR #24's review noted that neither the rule nor D3 says whether this exception ends when the M2 sanitizer lands or is permanent. It stands as written until the human decides.
- **ING-001.D3** — **`animated` is an allow-list** (decided by the human, 2026-10-06; it replaces the earlier default). `animated` is true only when Pillow's `format` is in {GIF, WEBP, PNG} (PNG covers APNG) **and** `is_animated` is true. Every other format is false, including TIFF, MPO and HEIC. Classification reads frame or page 0.
- **ING-001.D4** — **Decompression bombs: Pillow's default stands** (lead, 2026-10-06). `Image.MAX_IMAGE_PIXELS` stays at its default, 89,478,485 pixels. Above that Pillow warns (`DecompressionBombWarning`); above twice that (~179 MP) it raises `DecompressionBombError`, which `probe_image` catches and returns as `Skipped` (ING-001.2.1). A test pins the limit, so changing it is a deliberate act.
- **ING-001.D5** — **Skip reasons live in `files.error`; only `status = error` is retried** (lead, 2026-10-06). A skipped file has `status = skipped` and its reason in `files.error`: a fixed string or an exception type, never a path. No migration. A `skipped` row counts as known under R-ING-2 and is never retried. That holds although `error` also stores skip reasons, because retries key on the status, not the column.
- **ING-001.D6** — **Symlinks and unreadable folders get no ledger row** (lead, 2026-10-06). They can't be hashed safely, so they count as skipped-unreadable on every run and are never "new". A non-image or undecodable *file* is hashed (read-only) and recorded as `skipped`. The node takes the root as a parameter, and `source_path` is the container path as walked (DOC-004.D3).
- **ING-001.1.2 alias:** `tif` is accepted as an alias of `tiff`, beside the MVP types in DESIGN.md §1. Extensions are matched case-insensitively, and `discover` filters by extension only: `probe_image` is the sole judge of decodability (R-ING-3).

## ING-001 — Plan

1. **ING-001.1, pure functions:** `hash_file`, `discover(root)` (yields image candidates, skipped-with-reason entries, and drops OS metadata), and `probe_image(path)` (decodes the first frame or page and returns `animated`). Unit tests use synthetic images generated in code: a 2-frame GIF and WebP, a multi-page TIFF, a truncated PNG, a text file named `.png`, and an OS metadata file.
2. **ING-001.2, the ledger node:** `ingest(batch)` writes `queued` rows for new hashes, `skipped` rows with a reason, and appends duplicate paths. A known hash is a no-op. It returns counts: new, skipped-known, skipped-unreadable, duplicate. Db-tier tests run against the TST-002.1 fixture.

## ING-001 — Tasks

- [x] ING-001.1 — Hashing, discovery and frame probing (pure functions) · #15 · acceptance: `tests/unit/ingest/test_discovery.py`
  - [x] ING-001.1.1 — `hash_file`: `source_hash` and `short_hash` · commit: d096c44
  - [x] ING-001.1.2 — `discover(root)`: extension filter, OS metadata dropped · commit: fa0d4b1
  - [x] ING-001.1.3 — `probe_image(path)`: first frame or page, `animated`, `mtime` · commit: 000f57c
  - [x] ING-001.1.4 — `animated` as an allow-list (ING-001.D3 decided) · commit: (next commit)
- [ ] ING-001.2 — Ingest node: ledger writes, known-hash skip, duplicate paths · #16 · acceptance: `tests/db/ingest/test_ingest_ledger.py`
  - [x] ING-001.2.1 — `probe_image`: catch only Pillow's error families · commit: (next commit)
  - [x] ING-001.2.2 — `discover`: file symlinks are `Skipped("symlink")` · commit: (next commit)
  - [x] ING-001.2.3 — `discover`: an unreadable subfolder is a `Skipped`, via `os.walk` `onerror` · commit: (next commit)
  - [x] ING-001.2.4 — Record ING-001.D4 (decompression bombs) and pin the Pillow limit in a test · commit: (next commit)
  - [x] ING-001.2.5 — `ingest` node and its typed result, with the db tests (the lead folded .2.6 into this commit) · commit: (next commit)
  - ~~ING-001.2.6~~ folded into ING-001.2.5 (tests ship with their code, DOC-004.D1)
  - [ ] ING-001.2.7 — Results and self-rating

## ING-001 — Results

### ING-001.1 (worker: pipeline)

- **Status:** DONE. ING-001.D3 was decided by the human (allow-list) and is implemented in ING-001.1.4.
- **Triage:** medium, solo. New behavior inside `classifier/graph/`, pure functions, no schema or contract change.
- **Tests:** unit tier. The acceptance test `tests/unit/ingest/test_discovery.py` has 28 tests (4 for `hash_file`, 8 for `discover`, 16 for `probe_image`), all passing. `make test` (unit + db + integration) shows 155 passed. `make lint` is clean. Images are synthetic and generated in code: GIF, WebP and APNG with 2 frames, a 3-page TIFF, a 2-image MPO, a HEIC, a truncated PNG, a text file named `.png`, an empty file and a missing file.
- **Self-rating:** 10/10, proud: yes (second pass). Since the first pass (9/10, gap: ING-001.D3 unconfirmed), the human decided D3 and `probe_image` now follows the allow-list, with a test per case. No gap is left against the acceptance test or R-ING-1, 3, 4, 6, 8, 9.
- **Review:** pending (Reviewer and Privacy auditor, run by the lead).
- **Deferred:** the ledger node (ING-001.2, #16). Thumbnails (R-ING-5) wait for M2 (ING-001.D1). A HEIC with several images is read as a still, the first image only; that has no test, since no requirement covers it.

### ING-001.2 (worker: pipeline)

- **Status:**
- **Triage:**
- **Tests:**
- **Self-rating:**
- **Review:**
- **Deferred:**
