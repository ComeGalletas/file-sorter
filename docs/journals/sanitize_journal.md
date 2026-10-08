# Sanitize — journal

**ID:** SAN-001 (+ FOP-001) · **Systems:** SAN (+ FOP, PIPE, DB, MOD) · **Type:** feature · **Status:** in progress (SAN-001.1, .2 and FOP-001 done) · **Milestone:** m2 ·
**Issues:** SAN-001.1 #47, SAN-001.2 #48, SAN-001.3 #52, SAN-001.4 #56, FOP-001.1 #46 · **Branch:** per task (`office/*`)

<!--
Rules: CLAUDE.md §1 (DOC-001). Public repo: never write image file names, captions,
references, host paths or the human's sanitize.yaml values here. Use hashes.
-->

---

## SAN-001 — Requirement (DESIGN.md M2, 2026-10-07)

- **Objective:** Sanitize every queued file before any later model sees it: strip its metadata on a working copy, redact its name, and log every redaction without storing the original value.
- **Details:**
  - **Rules:** load the git-ignored `sanitize.yaml` (`sanitizer.rules_file`) into typed models. Rule types `literal`, `regex`, `entity` and `exif_field` (R-SAN-3), applied in the order literal → regex → entity (R-SAN-4).
  - **Metadata:** EXIF, XMP and IPTC are stripped on the working copy (`exif.mode: strip_all`), except the keep list (default `Orientation`, `DateTimeOriginal`) (R-SAN-2).
  - **Names:** the original file name and its folder segments under `source_root` are redacted before they are stored or used as a hint (R-SAN-3).
  - **Entity rule:** `PERSON`, `ORG` and `LOCATION` through the local text LLM (`models.text_llm`), on text that has already passed the literal and regex rules (R-SAN-4), through MOD-001's client only.
  - **Log:** every redaction writes a `sanitize_log` row: `source_hash, rule_id, field, before_hash, after_value` (R-SAN-6).
  - **Node:** a `sanitize` graph node takes `queued` rows to `sanitized`, after `ingest` and before `classify` (DESIGN §3). It is batch-oriented and idempotent (R-PIPE-1, P-4).
  - **Thumbnails** (R-ING-5, ING-002) are made by this node from the sanitized copy.
- **Constraint:**
  - The source is never written (P-1, R-SAN-1). The working copy lives in `<results_root>/.work/` (R-FOP-1), and only `classifier/fileops/` writes or replaces files there (R-FOP-6).
  - No original value, EXIF value or unsanitized name in logs, console, test output, issues, PRs or journals. The source path stays in the ledger and the local reports only, and never reaches a model: models get `files.original_sanitized` (ING-001.D2, DOC-007.D1).
  - No pixels to any model. The `claude` backend and OCR stay off (SAN-001.D6).
  - Tests use synthetic images and synthetic strings only. No real `sanitize.yaml` value appears in a test, a recording or a commit.
- **Implements:** R-SAN-1, R-SAN-2, R-SAN-3, R-SAN-4, R-SAN-6, R-SAN-8, P-2, P-4, R-PIPE-1; with FOP-001: R-FOP-1 (step 1), R-FOP-6.

## SAN-001 — Confirmed reading

What the code and DESIGN.md already say:

- `classifier/sanitize/` is empty and owned by Pipeline (C-12, DOC-004.D2). `classifier/models/` is empty and owned by ML (C-13).
- **exiftool is already in the image** (`libimage-exiftool-perl`, `Dockerfile` line 15), so the lossless strip needs no new dependency and no Dockerfile change. It writes JPEG, PNG, WebP, GIF, TIFF and HEIC metadata. BMP carries no EXIF, XMP or IPTC block, so a BMP is copied as is and checked by read-back.
- `config.yaml` already has `sanitizer.backend: local`, `sanitizer.rules_file: sanitize.yaml`, `sanitizer.ocr: false` and `thumbs.size: 256`. `sanitize.example.yaml` has the §4.2 structure. No config schema change is needed beyond loading the rules file.
- The repo is mounted at `/app` in both `app` and `test`, so `/app/sanitize.yaml` is readable in both. `make init` creates it from the example, and copies it into worktrees.
- The `test` container reaches `ollama` over the `internal` network, which the `gpu` and `gate` tiers need.
- `files.status` already has `sanitized` (DB-001). `PIPELINE_ORDER` already lists `sanitize` second (`classifier/graph/nodes.py`). `NodeContext` has `source_root` and `dry_run` only, so the node needs `results_root` and the loaded config added.
- DESIGN §3 lists "sanitized original name" among the node's writes, but §5 has no column for it. DB-002 adds one (SAN-001.D8).
- DESIGN §3 allows `.work/` and `reports/` under `results_root` before M7, so a dry run may write working copies and thumbnails there.
- R-SAN-5 (OCR), R-SAN-7 (re-running the rules on the rendered name, M5) and the `claude` backend are outside M2's gate. `sanitize_text` must still be a reusable function, because R-SAN-7 calls it again in M5.

Decisions:

- **SAN-001.D1** — **Matching** (lead, 2026-10-07).
  - `literal` values match case-insensitively, and treat space, `_`, `-` and `.` as interchangeable, so one value catches the usual file-name spellings of it.
  - `regex` patterns run as written, on the text left after the literals.
  - `entity` runs last, on the text left after both.
  - Rules apply to the file **stem** and to each folder segment between `source_root` and the file. The extension is never rewritten.
  - A missing or invalid `sanitize.yaml` stops the run with a message naming `make init` and the key, never a value.
- **SAN-001.D2** — **Fail closed** (lead, 2026-10-07; P-2). If the entity backend is unreachable, times out or returns something unparseable, the file goes to `error` with a fixed reason (`sanitize_entity_unavailable`), no sanitized name is stored, and the next run retries it (R-ING-2). An unredacted name never moves downstream. The same holds for a metadata strip that fails its read-back check (`sanitize_metadata_residual`).
- **SAN-001.D3** — **Metadata strip** (lead, 2026-10-07).
  - exiftool removes every EXIF, XMP, IPTC, GPS and maker-note tag, then copies back only the keep list from the same file (`-all=` with `-tagsFromFile @`). The image data is not re-encoded.
  - An `exif_field` rule names tags that are **always** removed, even when the keep list names them.
  - After the strip, a read-back of the copy's tags must show nothing outside the keep list and the file-structure tags. Otherwise the file fails closed (D2).
  - Each removed tag writes one `sanitize_log` row: `field = exif:<tag name>`, the hash of its value, `after_value` null.
- **SAN-001.D4** — **The ICC colour profile is kept** (confirmed by the human, 2026-10-07, as recommended; rule change DOC-007.D3, PR #60). It counts as a file-structure tag, not metadata, so the strip keeps it and the read-back check (D3) and gate 2 allow it. Without it, wide-gamut images render with shifted colours (R-SAN-2 as amended).
- **SAN-001.D5** — **`before_hash` is HMAC-SHA256 keyed with `SANITIZE_LOG_KEY`** (confirmed by the human, 2026-10-07, as recommended; rule change DOC-007.D2, PR #60). `make init` generates the key into the local `.env`, and compose passes it to `app` and `test` only (R-SAN-6 as amended). A missing key stops the run with a message naming `make init`, never a value. A plain hash of a short value could be reversed by hashing guesses.
- **SAN-001.D6** — **The `claude` backend and OCR stay out of M2** (confirmed by the human, 2026-10-07, as recommended). `sanitizer.backend: claude` and `sanitizer.ocr: true` fail fast with a message naming the key. OCR waits for the VLM (M5 at the earliest); the `claude` backend for a later request.
- **SAN-001.D7** — **Working copies persist in `results_root/.work/` during dry runs** (confirmed by the human, 2026-10-07, as recommended). Classify (M3) and caption (M5) read only the sanitized copy (P-2), so it stays from sanitize until M7 files it; `.work/` needs about as much space as the source folder. **For M7's plan:** R-FOP-3's clean-on-start must be narrowed to temp files and the copies of `filed` or `error` rows, or it deletes the copies a resumed run needs.
- **SAN-001.D8** — **Where the sanitized name lives** (lead, 2026-10-07). A new nullable column `files.original_sanitized` holds the sanitized stem. It feeds the `{original_sanitized}` token (R-NAME-2) and the caption hint (DESIGN §4.3). Sanitized folder segments are logged in `sanitize_log` (`field = path_segment`) and not stored anywhere else. DB-002 adds the column.
- **SAN-001.D9** — **One file is all or nothing** (lead, 2026-10-07). Per file, the node makes the working copy (FOP-001), strips and checks its metadata, redacts the name, writes the thumbnail (ING-002) and its `sanitize_log` rows, then sets `sanitized`. Any failure sets `error` with a fixed reason and writes no log rows for that file. The node never commits; `run` commits once per node (PIPE-001.D3).
- **SAN-001.D10** — **Recordings never hold real data** (lead, 2026-10-07). Recorded LLM responses (TST-005) are made only from synthetic strings in the `gpu` tier. The gate's entity calls on the human's values are never recorded or printed.
- **SAN-001.D11** — **The `exif_field` rule's shape** (lead, 2026-10-07, on #47). `{id, type: exif_field, fields: [<tag>, …]}`: the tags SAN-001.2 always removes (D3). `sanitize.example.yaml` gains a placeholder rule only if SAN-001.2 needs one.
- **SAN-001.D12** — **Rule ids of metadata rows** (lead, 2026-10-07, on #48). A tag removed by the keep-list strip logs `rule_id = exif-strip-all`; a tag removed by an `exif_field` rule logs that rule's own id.
- **SAN-001.D13** — **Adobe APP14 is a file-structure tag, like ICC** (lead, 2026-10-07, on #48). `DCTEncodeVersion`, `APP14Flags0/1` and `ColorTransform` decide how an Adobe CMYK/YCCK JPEG decodes, so the strip keeps them. JFIF, which can carry a thumbnail, is still removed.
- **SAN-001.D14** — **Tag names read from a file are free text** (lead, 2026-10-07, on #48). A PNG text keyword or an unknown XMP namespace becomes exiftool's tag or group name. So `field = exif:<group0>:<tag>` only when `<tag>` is in exiftool's own known-tag list (`exiftool -list`), else `exif:<group0>:unknown`; it fits DB-002.D1's check. Exceptions and `repr` never carry a tag name read from a file.
- **SAN-001.D15** — **An `exif_field` rule beats the keep list, never the structure or ICC tags** (lead, 2026-10-07, on #48). Removing a structure tag (a TIFF's `ImageWidth` or `StripOffsets`) corrupts the image.
- **SAN-001.D16** — **The node's error handling** (lead, 2026-10-07, from the PR #66, #72 and #73 audits). SAN-001.4 must:
  - treat **any** exception from `make_working_copy`, `strip_metadata`, `read_tags`, `make_thumbnail` or the entity rule as a failed file. That includes a bare `RecursionError` and a decode error from Pillow. The file then goes to `error` with a fixed reason (D2), recorded as text or `type(exc).__name__`, never `str(exc)`;
  - check that the working copy's resolved path lies under the results `.work/` and never under `source_root`, because a symlinked parent folder could redirect a write;
  - log only hashes, counts and fixed reasons, checked with a planted-secret test over the captured logs.

## SAN-001 — Plan

1. **SAN-001.1, rules and text redaction (pure):** `classifier/sanitize/rules.py` loads and validates `sanitize.yaml` (pydantic). `sanitize_text(text, field, rules, entity=None) -> (text, list[Redaction])` applies literal then regex, then the entity callable when one is given (D1). `Redaction` carries `rule_id`, `field`, `before_hash`, `after_value`. Unit tests on synthetic values, with the separator variants and an empty or missing rules file.
2. **SAN-001.2, metadata strip (pure, exiftool):** `classifier/sanitize/exif.py`: ~~`strip_metadata(path, keep, always_drop) -> list[Redaction]`~~ superseded by `strip_metadata(path, rules) -> list[Redaction]` (approved on #48: the keep list, the `exif_field` drops and the log key all come from the loaded `Rules`) and `read_tags(path)`, both through exiftool in a subprocess with fixed arguments (D3). Unit tests generate JPEG, PNG, WebP, GIF, TIFF and HEIC files in code, with seeded GPS, serial, artist, software, XMP and IPTC tags, and check that only the keep list survives and that the pixels are unchanged.
3. **SAN-001.3, the entity rule:** `classifier/sanitize/entity.py` adapts MOD-001.2's `detect_entities` to the callable that `sanitize_text` takes. Spans not literally present in the text, and labels the rule doesn't name, are dropped. Failures raise one typed error that the node maps to D2. Unit tests use a fake detector.
4. **SAN-001.4, the node:** `classifier/graph/sanitize.py` and its registration in `REGISTRY`. `NodeContext` gains `results_root` and the config. It selects `queued` rows (P-4), applies D9 per file, writes `files.original_sanitized`, the log rows and the status. It returns typed counts (sanitized, errored). Integration test: ingest then sanitize, on synthetic images with seeded metadata and seeded names, with recorded entity responses (TST-005.1); a re-run is a no-op; the source tree is unchanged; logs carry no name.

## SAN-001 — Tasks

- [x] SAN-001.1 — Rules loader and literal/regex `sanitize_text` · #47 · acceptance: `tests/unit/sanitize/test_rules.py` · SAN-001.1.1 03abdcd, SAN-001.1.2 ce2a55a, SAN-001.1.3 866a1be, SAN-001.1.4 c093623 + ce407f4, SAN-001.1.5 57f025b
- [x] SAN-001.2 — Lossless metadata strip and read-back through exiftool · #48 · acceptance: `tests/unit/sanitize/test_exif.py`
  - [x] SAN-001.2.1 — `read_tags`, `Tags`, the structure allow-list and the guarded `field` names (D14) · `f8a4008`
  - [x] SAN-001.2.2 — `strip_metadata`: strip, targeted second pass, read-back check, redactions and `exif_field` drops · `c883721`
  - [x] SAN-001.2.3 — Results · `e269df7`
  - [x] SAN-001.2.4 — Read DB-002.D1's field check from `SanitizeLog` instead of a copy (DB-002 landed during the task) · `51e1b95`
  - [x] SAN-001.2.5 — PR #73 round 1: fail closed on an OSError or symlink at the working copy, on a key of another shape, and on unexpected JSON; known tags from the name lines only · `fbb228d`
- [x] SAN-001.3 — The entity rule on top of MOD-001's detector · #52 · acceptance: `tests/unit/sanitize/test_entity.py`
  - [x] SAN-001.3.1 — `classifier/sanitize/entity.py`: `EntityDetector`, `EntityUnavailableError` (D2), `check_backend` (D6), and the acceptance tests · `7534f9a`
  - [x] SAN-001.3.2 — Results
- [ ] SAN-001.4 — The `sanitize` graph node · #56 · acceptance: `tests/integration/test_sanitize_node.py` · branch `office/nibble-e4d1`
  - [x] SAN-001.4.1 — Public `is_structure_tag(tag)` and `is_allowed(tag, rules)` in `exif.py` for gate 2 (#58), one allow-list; unit tests
  - [ ] SAN-001.4.2 — `O_NOFOLLOW` temp files in `copy_move.py` (closes FOP-001's stale-temp symlink item); regression tests
  - [ ] SAN-001.4.3 — `NodeContext`/`run`/`RunResult.sanitize`/`SanitizeResult`, the node with the D16 checks and D17 reasons, `REGISTRY`; the acceptance test; the dry-run tests updated for the new node and `.work/`
  - [ ] SAN-001.4.4 — Entity wiring through SAN-001.3's `EntityDetector`, with the replayed and fail-closed entity tests (after #52 merges)
  - [ ] SAN-001.4.5 — Results

## SAN-001 — Results

### SAN-001.1 (worker: pipeline)

- **Built:** `classifier/sanitize/rules.py`: `load_rules`, `sanitize_text` and `sanitize_name`.
  - Load errors name `make init` and the key location only. Pydantic and YAML errors are rebuilt from location and type, unknown keys aren't named, and nothing is chained.
  - `field` values are `filename` and `path_segment` (DB-002.D1).
  - The entity callable is `entity(text, labels) -> [(span, label)]`, for SAN-001.3 to adapt.
  - `sanitize_name` keeps only an image extension (ingest's `IMAGE_EXTENSIONS`) out of the rules. Any other dotted tail is redacted as part of the name: fail closed, P-2.
- **Tests:** `tests/unit/sanitize/test_rules.py` (acceptance), unit tier: 71 passed (after round 3). `make lint` clean. Default tiers: at pre-push.
- **Status:** DONE.
- **Self-rating:** 9/10, proud: yes. Gap: the entity callable's shape is this task's choice; SAN-001.3 confirms it against MOD-001.2's detector. Entity spans are matched case-sensitively, as the detector returns them from the text.
- **Reviewer / Privacy auditor:** round 1 at d9b741d: Reviewer APPROVE, Privacy auditor FAIL. SAN-001.1.3 fixes it: rule values, regex patterns and `exif_field` tags are hidden from `repr` and `str` (`Rules` shows ids and types only), and every `SanitizeConfigError`, and the validators' own errors, is raised outside its `except` block, so `__context__` is `None`.
  - Round 2 at 866a1be: Reviewer APPROVE, Privacy auditor FAIL. SAN-001.1.4 (c093623) fixes it:
    - `exif.keep` and `exif_field` `fields` must be EXIF tag names, or the load fails without echoing the entry, and both are hidden from `repr`;
    - `replace` is hidden from `repr`;
    - a non-UTF-8 rules file raises an unchained `SanitizeConfigError`.
  - Round 3 at c093623 (exhaustive): Reviewer APPROVE, Privacy auditor FAIL. SAN-001.1.5 fixes it:
    - `Redaction.after_value` and `SanitizedName`'s stem, segments and redactions are hidden from `repr`;
    - `before_hash` encodes with `surrogatepass`, and a log key that isn't clean UTF-8 is refused, naming only `SANITIZE_LOG_KEY` and `make init`, unchained;
    - rule ids must match `^[a-z0-9][a-z0-9_-]{0,63}$`, or the load fails without echoing the id.
  - Round 4 at `57f025b`: Reviewer APPROVE, Privacy auditor PASS (exhaustive). Merged as `bb06ff8` (PR #65), closing #47. The verdict comments are on the PR. Carried forward: SAN-001.3 wraps the detector's errors, unchained (the entity callable gets the raw text). The human should keep rule ids generic, because they are stored as `sanitize_log.rule_id`.

### SAN-001.2 (worker: pipeline)

- **Built:** `classifier/sanitize/exif.py`: `read_tags(path) -> Tags` and `strip_metadata(path, rules) -> list[Redaction]`. FOP-001's transform is `partial(strip_metadata, rules=rules)`.
  - exiftool runs with fixed argument lists, no shell, on an absolute path, with a fixed 120 s timeout. No tag value ever enters an argument.
  - The strip is `-all=` with `--ICC_Profile:all --Adobe:all` (D4, D13), then `-tagsFromFile @` for the keep list minus `exif_field` tags (D3, D15).
  - **Measured on exiftool 13.25:** on TIFF, `-all=` leaves the IFD0 `Artist`, `Software`, `Copyright` and `ImageDescription` in place. A targeted second pass (`-<group1>:<tag>=`) removes every tag left outside the allow-list. It never names a structure tag, because exiftool will delete a TIFF's `ImageWidth` if asked.
  - **Read-back allow-list:** the keep list, the ICC groups, Adobe APP14, and a fixed per-group list of structure tags (File, TIFF IFD0, PNG, RIFF, GIF, HEIC QuickTime/Meta, the BMP header). It also allows the containers exiftool recreates for the keep list. Anything else raises `MetadataStripError` with `reason = sanitize_metadata_residual` (D2), as fixed text, unchained.
  - BMP is not written, only read back.
  - **Redactions:** one per removed tag value, with `rule_id` `exif-strip-all` or the `exif_field` rule's id (D12), an HMAC `before_hash`, and `after_value` None. The `field` is guarded per D14.
- **Tests:** `tests/unit/sanitize/test_exif.py` (acceptance), unit tier: 39 passed; `tests/unit/sanitize/` 110 passed. Lint clean. Default tiers: at pre-push.
  - JPEG, PNG, WebP, GIF, TIFF and HEIC are generated in code with an sRGB profile and seeded with synthetic GPS, serial, artist, software, copyright, description, comment, XMP and IPTC values. Only the keep list, ICC and structure survive. Decoded pixels and ICC bytes are identical, and the hashes match the seeded values.
  - Also tested:
    - the TIFF second pass; BMP is unchanged byte for byte; a second strip is a no-op;
    - a CMYK JPEG keeps APP14 and its pixels; JFIF is removed; an empty keep list;
    - `exif_field` on a keep tag, on another tag, and on structure/ICC tags (ignored, D15);
    - residual, failing, missing and hung exiftool, a non-image, and error or unparseable output;
    - option-like values and a file named `-ver`: the path is always absolute, and no value reaches an argument;
    - planted secrets, including a PNG keyword, are absent from every `repr`/`str`, every `field`, the exceptions and the logs; a lone surrogate is hashed;
    - every `field` matches DB-002.D1's check, read from `SanitizeLog`'s constraint so the two cannot drift.
  - **Mutation checks, run on a copy:** 7 of 8 were caught (removing the second pass, the ICC exclusion, the known-tag guard, D15's order, D12's rule id, the absolute path, or the residual check). Removing `--Adobe:all` is not observable, because exiftool's `-all=` already keeps APP14. The flag stays as an explicit statement of D13.
- **Status:** DONE_WITH_CONCERNS.
  - **Concern (low):** the structure allow-list comes from synthetic files. A real file may carry a structure tag that isn't listed, most likely in HEIC from a phone. That file then fails closed (`error`, retried) rather than leaking. Gate 2 on the real fixtures will show it. Follow-up: widen the list in a `SAN` balance task if gate 2 reports residuals.
- **Self-rating:** 9/10, proud: yes. Gap: the allow-list concern above. Maker notes aren't seeded, because exiftool can't create them from scratch; `-all=` removes the whole EXIF block that holds them.
- **Reviewer / Privacy auditor:** round 1 at 51e1b95: Reviewer APPROVE with minors, Privacy auditor FAIL. SAN-001.2.5 fixes all six findings:
  - `_absolute` raises fixed text, unchained, when `is_symlink`, `resolve` or `is_file` raises an `OSError` (whose message holds the path). It also refuses a symlinked working copy.
  - `read_tags` fails closed on a key that isn't `<group>:<tag>` or `<group0>:<group1>:<tag>` (other than `SourceFile`). Before, such a key was skipped and escaped the read-back check. It also fails closed on JSON of an unexpected shape, and on a read with no `File:FileType`.
  - `_known_tags` takes only the indented lines under `Available tags:`, so header words and the command-line shortcuts aren't known tag names.
  - The Plan line now shows `strip_metadata(path, rules)`.
  - Tests: `test_exif.py` 51 passed; `tests/unit/sanitize/` with `tests/devtools` 191 passed.
  - Round 2 at `fbb228d`: Reviewer APPROVE, Privacy auditor PASS (exhaustive). Merged as `58077bf` (PR #73), closing #48. The verdict comments are on the PR. The auditor's caller-side notes go to SAN-001.4 (SAN-001.D16).

### SAN-001.3 (worker: pipeline)

- **Built:** `classifier/sanitize/entity.py` (SAN-001.3.1, `7534f9a`).
  - `EntityDetector(client, model, detect=detect_entities)` is the `entity(text, labels) -> [(span, label)]` callable that `sanitize_text` and `sanitize_name` take. `rules.py` is unchanged: the shape SAN-001.1 chose fits MOD-001.2's `detect_entities`.
  - **Fail closed (D2):** any `Exception` from the detector or the client, and any answer that isn't a list of `Entity` with `str` fields, raises `EntityUnavailableError`. Its `reason` is `sanitize_entity_unavailable` and its message is fixed text. It is raised after the `except` block, so `__cause__` and `__context__` are `None`. A `BaseException` escapes, so a missing replay recording (`RecordingError`) fails a test instead of passing as a fail-closed file (lead, #52).
  - Spans not literally in the text, blank spans and unasked labels are dropped, as MOD-001.D2 already does.
  - The `repr` shows the model tag only. Nothing is logged.
  - **The backend (D6):** `entity_detector(config, client)` calls `check_backend`, which refuses `sanitizer.backend: claude` with a `SanitizeConfigError` naming the key. `sanitizer.ocr` is checked in SAN-001.4 (lead, #52).
  - **For SAN-001.4:** map `EntityUnavailableError.reason` (`sanitize_entity_unavailable`) and `MetadataStripError.reason` (`sanitize_metadata_residual`) to `error`. Build the callable with `entity_detector`, not `EntityDetector` directly, so the backend check runs.
- **Tests:** `tests/unit/sanitize/test_entity.py` (acceptance), unit tier: 39 passed. `tests/unit/sanitize`, `tests/unit/models` and `tests/devtools`: 397 passed. `make lint` clean. Default tiers: at pre-push.
  - A fake detector covers pass-through, the filters, every exception type and every answer out of shape. Wired into `sanitize_text`, the detector sees only the text after literal and regex, and the redactions come out in order. `sanitize_name` raises with no partial result.
  - The real `detect_entities` runs on `httpx.MockTransport`: connect error, timeout, HTTP 500, a non-JSON body, a non-JSON answer, no list, a bad item, and a cut-off answer all fail closed. A well-formed answer passes through.
  - **Planted secret:** a synthetic secret goes into the text, every exception message and the answer. It is absent from the error's `str` and `repr`, from the full `traceback.format_exception`, from the adapter's `repr`, and from `caplog` and `capsys`.
  - **Mutation checks, each reverted:** raising inside `except`: 16 failed. Catching `BaseException`: 1 failed. Dropping the span filter: 4 failed. Dropping the shape check: 9 failed. Skipping `check_backend`: 1 failed.
- **Status:** DONE.
- **Self-rating:** 9/10, proud: yes. Gap: the backend check runs only through `entity_detector`, so a caller that builds `EntityDetector` directly skips it. It is noted above for SAN-001.4. Live Ollama isn't exercised here; MOD-001.2's `gpu` test covers that.
- **Reviewer / Privacy auditor:** pending.

### SAN-001.4 (worker: pipeline)

- **Status:**

---

## FOP-001 — Requirement (DESIGN.md M2, 2026-10-07)

- **Objective:** Make the working copy that sanitization runs on, in `results_root/.work/`, without ever touching the source.
- **Details:**
  - `classifier/fileops/copy_move.py`: `make_working_copy(source, work_dir, source_hash, ext, transform)` opens the source read-only and copies it to a temp file in `.work/`. It runs `transform` (the metadata strip) on the temp file, checks it, and renames it atomically to `.work/<source_hash>.<ext>` (R-FOP-1 step 1). It returns the final path and the SHA-256 of the copy.
  - A write-new helper for small files (the thumbnails, ING-002) that never replaces a file it didn't make.
- **Constraint:** The source is opened read-only. Only `copy_move.py` removes or replaces anything under `.work/`, and only its own temp files or a stale working copy of a `queued` row (R-FOP-6). No delete code anywhere else.
- **Implements:** R-FOP-1 (step 1), R-FOP-6, R-SAN-1, P-1.

## FOP-001 — Confirmed reading

- `classifier/fileops/` is empty and owned by Pipeline. `delete.py` doesn't exist yet and isn't needed in M2.
- `.work/` sits on the results drive, so the rename is atomic (Q-3).
- **FOP-001.D1** — **The transform runs before the rename** (lead, 2026-10-07). The strip works on the temp file, so a half-sanitized file never appears under its final name. A leftover working copy from a crashed run belongs to a `queued` row, and replacing it is `.work/` clean-up, allowed only in `copy_move.py` (R-FOP-6). Temp files are named `.<source_hash>.<ext>.tmp`.
- **FOP-001.D2** — **`write_new` publishes with `os.link`, with a fallback** (lead, 2026-10-07, on #46). The link fails instead of replacing a file that appeared meanwhile. Hard links aren't guaranteed on the Windows bind mount under Docker Desktop, so when `os.link` raises `EPERM`, `ENOTSUP`, `EOPNOTSUPP` or `EXDEV`, the helper checks `exists()` and then uses `os.rename`. That fallback's only race is two concurrent writers: M2's single run can't have them, and the run lock (R-API-6) closes it later. Both paths are tested. The returned hash of the working copy is named `copy_sha256`, so it can't be taken for `source_hash`.
- R-FOP-3 (`.work/` cleaned on start) is not implemented in M2. See SAN-001.D7 for the conflict it raises in M7.

## FOP-001 — Tasks

- [x] FOP-001.1 — `make_working_copy` and the write-new helper · #46 · acceptance: `tests/unit/fileops/test_working_copy.py`
  - [x] FOP-001.1.1 — `make_working_copy` in `classifier/fileops/copy_move.py`, returning `WorkingCopy(path, copy_sha256)` · `4dfe3c2`
  - [x] FOP-001.1.2 — `write_new`: keep an existing file, publish with `os.link`, fallback per FOP-001.D2 · `8c4e1d4`

## FOP-001 — Results

### FOP-001.1 (worker: pipeline)

- **Status:** DONE. FOP-001.1.1 landed in `4dfe3c2`, FOP-001.1.2 in `8c4e1d4` (PR #62).
- **Triage:** medium, solo, unit tier. New behavior inside one package (`classifier/fileops/`), no contract change.
- **Tests:**
  - **Acceptance:** `tests/unit/fileops/test_working_copy.py`, 35 tests, all passing. All synthetic bytes under `tmp_path`.
  - `make_working_copy`: the transformed copy is published under `<source_hash>.<ext>`, and `copy_sha256` is the hash of the copy, not of the source. The transform runs on `.<source_hash>.<ext>.tmp` before the final name exists. The source's bytes, size, mode and mtime don't change, and a read-only source works. A failing transform, a missing source or a failing rename leaves no file and re-raises. A stale temp and a stale working copy are replaced, and other files are left alone. A bad `source_hash` or `ext` is refused before anything is written.
  - `write_new`: it writes when the file is absent and creates the folder. It keeps an existing file (bytes and mtime) and returns False. A file that appears before the link is kept. A stale temp is replaced. The FOP-001.D2 fallback, with `os.link` monkeypatched to raise each of `EPERM`, `ENOTSUP`, `EOPNOTSUPP` and `EXDEV`, writes the file, keeps one that appeared meanwhile and leaves no temp. Any other link error propagates and leaves nothing.
  - **Mutation checks, each reverted:** (1) fallback without the `exists()` check: 1 failed. (2) `os.link` → `os.replace`: 3 failed. (3) temp clean-up removed: 7 failed. (4) hash taken before the transform: 2 failed.
  - **Lint:** `make lint` clean. **Default tiers:** the pre-push gate ran 501 passed (unit 438, db 42, integration 21), then the acceptance test, 35 passed.
- **Self-rating:** 9/10, proud: yes. Gap: the `os.link` path on the real Windows bind mount isn't exercised here. Unit tests run on the container's own filesystem, so the fallback is proven only by monkeypatching. Which path is actually taken there is first seen when the `sanitize` node writes thumbnails into the real results mount (SAN-001, ING-002).
- **Review:** PR #62, merged as `72ea66c`, closing #46. Reviewer APPROVE (full, 2 minor) at `8c4e1d4`, then a lead hand check of the journal-only `0b86e42`. Privacy auditor PASS. The verdict comment is on the PR.
- **Deferred:**
  - the R-FOP-6 grep test for unlink/remove calls outside `delete.py`/`copy_move.py` (not in this issue);
  - R-FOP-3 clean-on-start (not in M2, see above);
  - **from PR #62's review (lead):** a leftover `.<hash>.<ext>.tmp` that is a symlink would be followed by `open("wb")`. The risk is low, because `.work/` is the app's own. Fix by unlinking a stale temp before opening it, or opening with `O_NOFOLLOW`. It is a FOP follow-up, to be allocated when the M2 run allows.
