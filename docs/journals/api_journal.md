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
- **API-001.D8 — thumbnail markup and the adult predicate** (lead, 2026-11-10, on #214 and #216; **corrected** the same night, as the human's session pointed out).
  - Every thumbnail in served HTML is `<img class="thumb" src="/thumbs/<source_hash>" data-hash="<short_hash>" data-blur="1|0" alt="">`, with no `title`.
  - `data-blur="1"` is set server-side by default for adult rows. The click-to-reveal toggles one image in the browser and is never persisted.
  - "Adult" is **one predicate**: `classifier.api.views.is_adult(branch)` against `ADULT_BRANCH`, the ledger's `branch = 'nsfw'` (R-CLS-1), pinned by a test to `classify_rules.branch_for_level`. The UI, the grid's split (`GridCell.adult`), the report and gate 4 all use it, and never retype the string. The first wording keyed on `'adult'`, a value the ledger never holds, which would have left every real adult thumbnail unblurred.
  - `FileRow.blurred` (the 16th field, API-001.3) carries it.
- **API-001.D9 — the review queue route** (lead, on #214 and #216). `GET /ui/review?page=N`, 50 per page, newest first. It returns one `<tr data-hash data-source-hash>` per queued row: `needs_review`, or the `unsorted` fallback format (imported from the classify rules). An empty page is the end.
- **API-001.D10 — SSE keep-alive** (lead, on #211): a comment after 15 s with no frame.
- **API-001.D11 — SSE on failure** (lead, on #211): one fixed `unavailable` event per transition, and the stream stays open.
- **API-001.D12 — one fixed 404** (lead, on #212): every refusal on `/thumbs/` (malformed, unknown, not regular, a link, too big, any `OSError`) is the same `{"detail": "not found"}`.
- **API-001.D13 — the UI's CSP** (lead, on #214): `default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`, plus `Referrer-Policy: no-referrer` and `X-Content-Type-Options: nosniff`. The page has no inline script; the few lines of `EventSource` and click-to-reveal live in a served `classifier/ui/app.js`.

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
  - [x] API-001.4.1 — `classifier/ui/{queries,fragments,routes}.py`, `index.html`, `app.js` (API-001.D13), the one-line include in `create_app`; unit tests · 381cd13
  - [x] API-001.4.2 — the db acceptance test `tests/db/api/test_ui.py` (plants, escaping, D8, D9, no outbound reference, read-only, headers) · d701b0b
  - [ ] API-001.4.3 — the vendored htmx route's test, once RUN-021 is on `main` (nothing stubbed before then)
  - [x] API-001.4.4 — round 1 on #241: the review row's full cell run asserted by position, and the D13 CSP asserted as a typed literal
- [ ] API-001.5 — `render_report` · #213 · API/UI · acceptance: `tests/db/api/test_report.py`
  - [x] API-001.5.1 — `classifier/ui/html.py:esc`, the one escaping helper (API-001.D4), with its unit tests · 8fdc9b2
  - [x] API-001.5.2 — `classifier/api/report.py:render_report`; null-branch grid cells get their own "not classified" table, no timestamp (lead, #213) · 34f5190
  - [x] API-001.5.3 — round 1 (privacy): the unit test's no-script check proves the planted row is rendered and escaped before asserting absence · 69142ee
  - [x] API-001.5.4 — after API-001.3 (#236): the report shows `FileRow.blurred` as a column (no thumbnail), and the unit rows carry it

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

### API-001.5 (#213)

- **Tests:**
  - acceptance `tests/db/api/test_report.py`: 5 passed (planted secrets proved served then absent; escaping; no outbound reference; the three-way adult split through `is_adult`; every ledger row, streamed once, newest first);
  - `tests/unit/api/test_report_render.py`: 7 passed; `tests/unit/ui/test_html.py`: 15 passed;
  - `make test` (unit + db + integration): 2612 passed, 48 deselected; `make lint` clean.
- **Status:** DONE.
- **Self-rating:** 9/10, proud: yes. Pass 1 found a gap (no test for a row with no sanitized name yet), fixed in pass 2. The remaining point: the report holds every row in one string, so a very large ledger costs memory in CLI-008.1; the signature returns `str`, so streaming would be a contract change.

### API-001.4 (#214)

- **Decision applied, API-001.D13 (lead, #214):** the page's script (the `EventSource` refresh and click-to-reveal) is the served `classifier/ui/app.js`, never inline. Every UI response carries a CSP that allows only the page's own origin and no inline script (`default-src 'none'; script-src 'self'; …; form-action 'none'; frame-ancestors 'none'`), plus `no-referrer`, `nosniff` and `no-store`.
- **Also applied:** the router is in `classifier/ui/routes.py`, included by `create_app` (lead, #214, answer 1). Errors are 50 per page with `?page=N` (answer 2). The review queue and errors refresh only when the run's id or state changes, not on every status frame, so a revealed thumbnail there isn't re-blurred every 2 s.
- **Tests:**
  - acceptance `tests/db/api/test_ui.py`: 15 passed (14, plus the D13 literal from API-001.4.4). Mutating the blur flag or the queue predicate fails its test;
  - `tests/unit/ui/test_fragments.py`: 13 passed;
  - `make test` (unit + db + integration): 2751 passed, 48 deselected; `make lint` clean.
- **Status:** BLOCKED on RUN-021 for API-001.4.3 only (the vendored htmx route's test). Nothing is stubbed; until then `/ui/vendor/htmx.min.js` is the fixed 404, and the page loads no fragment.
- **Self-rating:** 8/10, proud: yes. The gaps:
  - API-001.4.3 waits for RUN-021;
  - `app.js` has no automated test: the image has no JS runtime, and nothing may be installed on the host. Its markup contract (the triggers, the `status` event name, `data-blur`) is pinned from the Python side;
  - the latest-rows fragment refreshes on every status frame, so a thumbnail revealed there blurs again within 2 s while a run is running. That errs toward blurred.

---

## CLI-008 — Requirement (DESIGN.md m4, 2026-11-10)

- **Objective:** Add `classifier serve` and `classifier report [--out]`.
- **Details:**
  - `serve [--host] [--port]` defaults to `api.host` and `api.port` and runs uvicorn on `create_app`. In compose, RUN-019 passes `--host 0.0.0.0` (RUN-019.D2).
  - `report` writes `render_report`'s HTML to API-001.D6's path, or to `--out`.
- **Constraint:** both are thin wrappers, with no logic beyond config and file handling. Errors are fixed text and unchained, and `report` never overwrites a file.
- **Implements:** R-API-1, R-API-7, §7.

## CLI-008 — Confirmed reading

- **CLI-008.D1 — the report makes no Ollama call** (lead, on #215): a static file depends on nothing live, so its models section is "n/a".
- **The split** (lead, on #215): CLI-008.1 is `serve` only (#215), so RUN-019.2 could land early. `report` is CLI-008.2 (#234).

## CLI-008 — Tasks

- [x] CLI-008.1 — `serve` and `report` · #215 · Pipeline · acceptance: `tests/db/cli/test_serve_report_cli.py` (the lead split it on #215: `serve` only; `report` is CLI-008.2, #234) (`65d4435`; PR #237, merged as `4eb347b`)
- [x] CLI-008.2 — `report [--out]` · #234 · Pipeline · acceptance: `tests/db/cli/test_serve_report_cli.py` (the report cases) (`5494aaa`; PR #240, merged as `6c017d5`)
  - [x] CLI-008.2.1 — Round 1 on PR #240: a fixed `ConfigError` text in `report` and `serve`, a broad catch around the render, and the reviewer's test gaps (`4102537`)

## CLI-008 — Results

### CLI-008.1 (#215, Pipeline): `serve`

- **What:** `classifier/cli/serve.py`, registered as `classifier serve [--host] [--port] [--config]`. The host and port default to `api.host` and `api.port`; the port is checked to be 1–65535. It calls `uvicorn.run(create_app(config), host, port, access_log=False, server_header=False, log_config=None)`.
  - `access_log=False` is m4 item 15 (Nibble's note on #215), on top of `create_app` disabling `uvicorn.access`.
  - There is no request logging of its own. It prints one line, `serving on <host>:<port>`.
- **Errors:** fixed text, and none echoes a value.
  - A config error exits 2 with `load_config`'s own fixed text; for a missing DSN that's `no database DSN: set DB_DSN`.
  - `create_app` failing exits 2 with `error: the app could not start`.
  - When uvicorn can't bind or start, it logs the OS error, address included, on `uvicorn.error`, then `sys.exit(1)`. `serve` therefore drops ERROR records on that logger while it runs (the filter is removed afterwards) and exits 1 with `error: could not listen on the configured address`. An `OSError` gets the same treatment, and a clean stop exits 0.
- **Tests:**
  - acceptance `tests/db/cli/test_serve_report_cli.py`: 13 passed. `uvicorn.run` is replaced by a recorder, so no port is opened. The tests cover:
    - the defaults and the overrides (`--host 0.0.0.0 --port 8123`);
    - the exact keyword set, including `access_log=False`;
    - the app as `create_app`'s read-only API, through TestClient: `GET /api/status` 200, `POST` 405, `/docs` 404;
    - bad ports and a missing DSN or config, all before serving;
    - a bind failure with a planted message, hidden, with the filter removed afterwards;
    - an `OSError`, a clean stop, and a `create_app` failure;
  - `make test`: 2636 passed, 48 deselected;
  - `make lint`: clean.
- **Status:** DONE. **Self-rating:** 9/10, proud: yes. Gap: while `serve` runs, any ERROR on `uvicorn.error` is dropped, not only the bind message. A protocol-level error's detail is then invisible on the box console too. This trades local diagnostics for never echoing OS or exception text. Request handling itself is guarded in `create_app`, so the API's own errors never reach uvicorn.

### CLI-008.2 (#234, Pipeline): `report`

- **What:** `classifier/cli/report.py`, registered as `classifier report [--out PATH] [--config]`.
  - One read-only, repeatable-read transaction (`read_only_engine`) builds `build_status` and every `file_row` from `rows_query(FileFilters())`. `render_report` (API-001.5) turns them into HTML, encoded UTF-8 (strict) in memory before any file is created.
  - **CLI-008.D1 (lead):** no Ollama probe, so the models section stays "n/a".
- **Where it writes:**
  - by default, `results_root/reports/report-<UTC %Y%m%dT%H%M%SZ>.html` (API-001.D6), opened `"xb"`, with `-1`, `-2` on a same-second clash, like the dry-run CSV;
  - with `--out`, opened `"xb"`, so an existing file is refused.

  It prints `report written: <file name>`, never a folder.
- **Errors:** fixed text, unchained, and none echoes a value.
  - an existing `--out` exits 2 and leaves the file unchanged;
  - a write failure, including a file where `reports/` goes, exits 1 with `error: could not write the report`. The first test run caught that `mkdir`'s `FileExistsError` was being reported as the `--out` message, and the handling was fixed;
  - a database error exits 1 without the DSN;
  - a missing DSN exits 2 with `load_config`'s fixed text.
- **Tests:**
  - acceptance `tests/db/cli/test_serve_report_cli.py`: 20 passed, 7 of them `report` cases. They cover:
    - a planted made-up name in `source_path`, `duplicate_paths`, `proposed_path` and `caption`, proved held in the ledger first; then the sanitized name and the short hashes proved served in the HTML; and only then the plant, `/source/`, `/results/` and a live `<script>` asserted absent, with the escaped form present and "n/a" for the models;
    - no Ollama client is built;
    - the UTC-stamp name, and the `-1` on a clash, with the first file unchanged;
    - `--out` new and existing;
    - an unwritable folder;
    - a database error without the DSN;
    - a missing DSN;
  - `make test`: 2731 passed, 48 deselected;
  - `make lint`: clean.
- **Status:** DONE. **Self-rating:** 9/10, proud: yes. Gap: a write that fails after the file was created (a full disk) leaves the partial file in place, as the dry-run CSV does, because deleting is `fileops/delete.py`'s alone. A re-run writes under the next free name.
- **CLI-008.2.1 (round 1 on PR #240; the privacy auditor's FAIL):**
  - **The config path.** `report` and `serve` echoed `load_config`'s `ConfigError` text, which can carry the `--config` path. Both now print the fixed `error: the config could not be loaded; check the config file and DB_DSN` (the same text as `categories.py`), and a missing DSN gives the same line. Every `typer.Exit` is raised outside its `except`, so the errors are unchained (`__cause__` and `__context__` both None).
  - **The render:** any exception from it becomes the fixed database text.
  - **New tests:**
    - for each command, a plant in the `--config` path, first proved present in the raw `ConfigError` text, then shown absent from the output;
    - the snapshot is pinned, by reading `transaction_isolation` and `transaction_read_only` inside the render: `repeatable read` and `on`;
    - unchained `Exit`s on the config, database, write and `--out`-exists paths, with the commands called directly;
    - a render failure with a planted message gives fixed text and no folder;
    - an encode failure (a lone surrogate) leaves no file and no `reports/` folder, and with `--out` no file;
    - the written report has no `<img`, `http:`, `https:`, `="//`, `src=`, `url(` or `/thumbs/`.

      A bare `http` matches the CSP's `<meta http-equiv>` from API-001.5, which is no URL, so the URL forms are checked instead, and the CSP meta is asserted present.
  - On the round-1 code, the planted-path, no-DSN and broad-catch tests fail (5 tests, checked).
  - Results: acceptance 27 passed; `make test` 2738 passed, 48 deselected; `make lint` clean.
