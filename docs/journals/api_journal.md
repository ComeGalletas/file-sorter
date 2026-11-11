# Status UI and API — journal

**ID:** API-001 (+ CLI-008) · **Systems:** API (+ CLI, UI, DB, MOD) · **Type:** feature ·
**Status:** proposed (M4 G0) · **Milestone:** m4 ·
**Issues:** API-001: #210, #211, #212, #214 (.4), #213 (.5); CLI-008: #215 · **Branch:** per task (`office/*`)

<!--
Rules: CLAUDE.md §1 (DOC-001). Public repo: never write image file names, captions, references or host paths here. Use hashes.
-->

---

## API-001 — Requirement (DESIGN.md m4, 2026-11-10)

- **Objective:** Make a dry run reviewable end to end in the browser and in a self-contained report, read-only.
- **Details:**
  - `GET /api/status`, `GET /api/events` (SSE) and `GET /api/files?status=&format=&topic=&needs_review=&page=`;
  - a thumbnail route over `.work/thumbs/`;
  - one `classifier/ui/index.html` with vendored htmx: the dashboard (run banner, topic × format grid split safe vs adult, the latest 20 files, errors) and the review queue (unsorted and `needs_review`, with adult thumbnails blurred by default and click-to-reveal);
  - `classifier report`'s HTML, built from the same view models.
- **Constraint:**
  - read-only: no write route, and no deletion ever (R-API-3 is M8; R-API-8);
  - no `source_path`, `duplicate_paths` or raw name anywhere (ING-001.D2);
  - the page makes no outbound call (answer 4);
  - the report has no thumbnails (answer 3).
- **Implements:** R-API-1, R-API-2, R-API-5, R-API-7, R-API-8; ING-001.D2, P-2, DOC-007.D1.

## API-001 — Confirmed reading

- **What exists:**
  - `classifier/api/` and `classifier/ui/` are empty packages;
  - FastAPI and uvicorn are already dependencies;
  - ING-002 writes `.work/thumbs/<source_hash>.webp` from the sanitized working copy;
  - the ledger has every field the review queue needs (§5), and the cross-check is `review_reason = nsfw_disagreement` (CLS-004.D5, D13);
  - there is no `runs` table yet (DB-007).
- **The human's G0 answers (2026-11-10):** 1 (the dry run starts from the CLI), 2 (the review fields), 3 (the thumbnails, none in the report), 4 (htmx, vendored), 5 (localhost only, through the proxy) and 7 (VRAM and the model from `/api/ps`, else "n/a"). They are recorded in `docs/plans/m4.md`.
- **API-001.D1 — "latest", not "filed"** (lead, 2026-11-10, provisional): in a dry run the dashboard lists the latest 20 rows by `updated_at`. The label becomes "filed" in M7.
- **API-001.D2 — errors with no retry** (lead, provisional): a row shows the short hash, the status and the fixed error code. Retry is M8.
- **API-001.D3 — the SSE content** (lead, provisional):
  - the status JSON whenever it changes, checked every 2 s, plus a keep-alive comment;
  - a few lines of `EventSource` script make htmx refresh its fragments, so no SSE extension is vendored.
- **API-001.D4 — HTML escaping** (lead, provisional): one helper over `html.escape` in `classifier/ui/`, with no new dependency.
- **API-001.D5 — paging** (lead, provisional):
  - 50 per page, newest `updated_at` first, `page` from 1;
  - the filters combine with AND;
  - a bad value gets a 422 with fixed text.
- **API-001.D6 — the report's default path** (lead, provisional): `/results/reports/report-<UTC timestamp>.html`, opened exclusively; `--out` overrides it.
- **API-001.D7 — imgs/min** (lead, provisional): the rows whose `updated_at` falls inside the current (or last) run's window, divided by its elapsed minutes.

## API-001 — Plan

- **`classifier/api/views.py`:** the read model, `StatusView`, `FileRow` and `FilePage`, as pydantic models with an explicit allowlist. Every route, the UI and the report use it.
- **`classifier/api/app.py`:** `create_app(config, *, engine=None, ollama=None)`.
  - The routes: `/api/status`, `/api/files`, `/api/events`, `/thumbs/{source_hash}`, and `/` with its fragments.
  - Its database session is read-only (`SET TRANSACTION READ ONLY`).
  - The access log is off (privacy item 15).
- **`classifier/ui/`:**
  - `index.html`;
  - the escaping helper and the fragment renderers;
  - `vendor/htmx.min.js` (RUN-021);
  - the blur: CSS `filter: blur()` on adult thumbnails by default, and a click toggles that one image.
- **`classifier/api/report.py`:** `render_report(status, files) -> str`, with inline CSS, no script needed, no thumbnails and no external reference.
- **Tests:** the `db` tier with a throwaway migrated schema and synthetic rows, through FastAPI's `TestClient`. The privacy plants are proved served before absence is asserted (M4 checklist 11–15).

## API-001 — Tasks

- [ ] API-001.1 — The read model, `create_app`, `/api/status` and `/api/files`, the read-only session · #210 · API/UI · acceptance: `tests/db/api/test_status_files.py`
  - [x] API-001.1.1 — the read model (`views.py`: the allowlisted row query, `FileRow`, `FilePage`, `StatusView`), unit tests · 835937f
  - [x] API-001.1.2 — `create_app`, the read-only engine, `/api/files`, the fixed 422, the access log off · a6ed61b
  - [x] API-001.1.3 — `/api/status` (counts, the grid, the last error, the loaded models or "n/a") · 1fbc71b
  - [x] API-001.1.4 — the run state and imgs/min (after DB-007.1, #207) · bc0d624
  - [x] API-001.1.8 — the malformed-DSN check moves from `tests/unit/api` to the db tier (the tier audit counts `create_engine` as db work) · d7d202c
  - [x] API-001.1.9 — PR #224 round 2: the real-client "n/a" test proves the planted body was read (an error status and a malformed 200 entry), and the pool listeners are removed in a `finally` · (this commit)
  - [x] API-001.1.5 — PR #224 round 1, items 1–5: a fixed, unchained 500 for any other failure, the plants proved able to fail (422, 503, 500), Ollama probed with no connection held, fixed text on a malformed DSN; plus REPEATABLE READ and the `make_read_only` docstring · 4a32f7b
  - [x] API-001.1.6 — PR #224 round 1, item 6: the real `OllamaClient` over a fake transport (after MOD-003.1, #209) · bc274c4
  - [x] API-001.1.7 — API-001.D8 as corrected: `views.ADULT_BRANCH` and `is_adult(branch)`, pinned to `classify_rules.branch_for_level`; the grid's safe-vs-adult split (`GridCell.adult`) keys on `is_adult` · 22a3d15
- [ ] API-001.2 — `/api/events` (SSE, API-001.D3) · #211 · API/UI · acceptance: `tests/db/api/test_events.py`
  - [x] API-001.2.1 — the stream (`events.py`: frames on change, the keep-alive after 15 s (API-001.D10), one fixed `unavailable` per transition with the stream open (API-001.D11), the end on disconnect or cancellation), unit tests · fa82e19
  - [x] API-001.2.2 — the `GET /api/events` route, its db acceptance test and the privacy plant · (this commit)
- [ ] API-001.3 — `/thumbs/{source_hash}`, the blur flag in the views · #212 · API/UI · acceptance: `tests/db/api/test_thumbs.py`
  - [x] API-001.3.1 — `FileRow.blurred` (the 16th field, approved on #212) from `is_adult(branch)` (API-001.D8); an `nsfw` row is blurred, safe and null rows are not · 1569e84
  - [x] API-001.3.2 — `GET /thumbs/{source_hash}`: ledger-hash-only paths, non-regular files and symlinks refused, one fixed 404 for every refusal (API-001.D12) · 20f8ed0
  - [x] API-001.3.3 — #236 round 1: an `OSError` from `os.close` is a refusal too (None, never an escape), tested with a plant through the reader and the route; the field-count comment in `views.py` says 16 · (this commit)
- [ ] API-001.4 — `index.html`, the dashboard and the review queue, the fragments, the escaping helper · #214 · API/UI · acceptance: `tests/db/api/test_ui.py`
- [ ] API-001.5 — `render_report` · #213 · API/UI · acceptance: `tests/db/api/test_report.py`

## API-001 — Results

### API-001.1 (#210, PR #224)

- **Tests:**
  - acceptance `tests/db/api/test_status_files.py`: 37 passed;
  - `tests/unit/api`: 16 passed;
  - the default tiers at pre-push: see the PR body.
- **Round 1 (PR #224):** the reviewer approved the draft scope; the privacy auditor failed it on test strength. That was addressed by API-001.1.5 and .1.6, and API-001.D8's correction by .1.7. **Round 2:** the reviewer approved; privacy failed one test, addressed by API-001.1.9.
- **Status:** DONE.
- **Self-rating:** 9/10, proud: yes. The gap: imgs/min counts every row whose `updated_at` falls inside the run's window, so a concurrent writer would be counted too. That is API-001.D7 as written, and the run lock (PIPE-002) keeps a second run out.
- **Deferred:** `serve` should also pass `access_log=False` (noted on #215, CLI-008.1).

### API-001.2 (#211)

- **Tests:**
  - acceptance `tests/db/api/test_events.py`: 6 passed;
  - `tests/unit/api/test_events_stream.py`: 10 passed;
  - no test sleeps for real.
- **Decisions applied:** API-001.D10 (a keep-alive after 15 s with no frame) and API-001.D11 (one `unavailable` event per transition, with the stream open).
- **Status:** DONE.
- **Self-rating:** 9/10, proud: yes. The gaps:
  - `app.state.events_max_ticks` is a test-only bound that lives in production code, where it is always None;
  - each open stream probes Ollama's `/api/ps` every 2 s, which is cheap on the box;
  - while a run is running, its imgs/min changes every tick, so the stream sends a frame every 2 s (API-001.D3 as written).

### API-001.3 (#212)

- **Tests:**
  - acceptance `tests/db/api/test_thumbs.py`: 17 passed;
  - `tests/unit/api/test_thumbs_reader.py`: 19 passed;
  - round 1 on #236: the reviewer approved; privacy failed one hole (an escaping `os.close` error), fixed by API-001.3.3;
  - the required D8 test: the `nsfw`, safe and null rows, through `/api/files` (db) and `file_row` (unit).
- **Decisions applied:** API-001.D12 (one fixed 404 for every refusal, an unmatched path included); `blurred` is the 16th `FileRow` field, from `is_adult`; the route serves the same bytes for adult rows, and the UI blurs them.
- **Status:** DONE.
- **Self-rating:** 9/10, proud: yes. The gaps:
  - the folder names `.work` and `thumbs` are repeated in `classifier/api/thumbs.py` rather than imported, because importing the sanitize node would pull in its model clients. A unit test pins them to the node's;
  - the app's 404 handler now gives every 404 the body `{"detail": "not found"}`, including unknown `/api/...` routes, which is a small change to API-001.1's behaviour.

---

## CLI-008 — Requirement (DESIGN.md m4, 2026-11-10)

- **Objective:** Add `classifier serve` and `classifier report [--out]`.
- **Details:**
  - `serve [--host] [--port]` defaults to `api.host` and `api.port` and runs uvicorn on `create_app`. In compose, RUN-019 passes `--host 0.0.0.0` (RUN-019.D2).
  - `report` writes `render_report`'s HTML to API-001.D6's path, or to `--out`.
- **Constraint:** both are thin wrappers, with no logic beyond config and file handling. Errors are fixed text and unchained, and `report` never overwrites a file.
- **Implements:** R-API-1, R-API-7, §7.

## CLI-008 — Tasks

- [ ] CLI-008.1 — `serve` and `report` · #215 · Pipeline · acceptance: `tests/db/cli/test_serve_report_cli.py`

## CLI-008 — Results
