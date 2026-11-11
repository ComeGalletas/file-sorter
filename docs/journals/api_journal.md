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
  - [x] API-001.1.2 — `create_app`, the read-only engine, `/api/files`, the fixed 422, the access log off · (this commit)
  - [ ] API-001.1.3 — `/api/status` (counts, the grid, the last error, the loaded models or "n/a")
  - [ ] API-001.1.4 — the run state and imgs/min (after DB-007.1, #207)
- [ ] API-001.2 — `/api/events` (SSE, API-001.D3) · #211 · API/UI · acceptance: `tests/db/api/test_events.py`
- [ ] API-001.3 — `/thumbs/{source_hash}`, the blur flag in the views · #212 · API/UI · acceptance: `tests/db/api/test_thumbs.py`
- [ ] API-001.4 — `index.html`, the dashboard and the review queue, the fragments, the escaping helper · #214 · API/UI · acceptance: `tests/db/api/test_ui.py`
- [ ] API-001.5 — `render_report` · #213 · API/UI · acceptance: `tests/db/api/test_report.py`

## API-001 — Results

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
