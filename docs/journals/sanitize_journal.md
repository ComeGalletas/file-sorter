# Sanitize — journal

**ID:** SAN-001 (+ FOP-001) · **Systems:** SAN (+ FOP, PIPE, DB, MOD) · **Type:** feature · **Status:** proposed · **Milestone:** m2 ·
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

## SAN-001 — Plan

1. **SAN-001.1, rules and text redaction (pure):** `classifier/sanitize/rules.py` loads and validates `sanitize.yaml` (pydantic). `sanitize_text(text, field, rules, entity=None) -> (text, list[Redaction])` applies literal then regex, then the entity callable when one is given (D1). `Redaction` carries `rule_id`, `field`, `before_hash`, `after_value`. Unit tests on synthetic values, with the separator variants and an empty or missing rules file.
2. **SAN-001.2, metadata strip (pure, exiftool):** `classifier/sanitize/exif.py`: `strip_metadata(path, keep, always_drop) -> list[Redaction]` and `read_tags(path)`, both through exiftool in a subprocess with fixed arguments (D3). Unit tests generate JPEG, PNG, WebP, GIF, TIFF and HEIC files in code, with seeded GPS, serial, artist, software, XMP and IPTC tags, and check that only the keep list survives and that the pixels are unchanged.
3. **SAN-001.3, the entity rule:** `classifier/sanitize/entity.py` adapts MOD-001.2's `detect_entities` to the callable that `sanitize_text` takes. Spans not literally present in the text, and labels the rule doesn't name, are dropped. Failures raise one typed error that the node maps to D2. Unit tests use a fake detector.
4. **SAN-001.4, the node:** `classifier/graph/sanitize.py` and its registration in `REGISTRY`. `NodeContext` gains `results_root` and the config. It selects `queued` rows (P-4), applies D9 per file, writes `files.original_sanitized`, the log rows and the status. It returns typed counts (sanitized, errored). Integration test: ingest then sanitize, on synthetic images with seeded metadata and seeded names, with recorded entity responses (TST-005.1); a re-run is a no-op; the source tree is unchanged; logs carry no name.

## SAN-001 — Tasks

- [x] SAN-001.1 — Rules loader and literal/regex `sanitize_text` · #47 · acceptance: `tests/unit/sanitize/test_rules.py` · SAN-001.1.1 03abdcd, SAN-001.1.2 ce2a55a, SAN-001.1.3 866a1be, SAN-001.1.4 c093623 + ce407f4, SAN-001.1.5 (PR #65 round 3, hash in the PR)
- [ ] SAN-001.2 — Lossless metadata strip and read-back through exiftool · #48 · acceptance: `tests/unit/sanitize/test_exif.py`
  - [x] SAN-001.2.1 — `read_tags`, `Tags`, the structure allow-list and the guarded `field` names (D14) · `2a03903`
  - [x] SAN-001.2.2 — `strip_metadata`: strip, targeted second pass, read-back check, redactions and `exif_field` drops
  - [ ] SAN-001.2.3 — Results
- [ ] SAN-001.3 — The entity rule on top of MOD-001's detector · #52 · acceptance: `tests/unit/sanitize/test_entity.py`
- [ ] SAN-001.4 — The `sanitize` graph node · #56 · acceptance: `tests/integration/test_sanitize_node.py`

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
  - Re-review pending.

### SAN-001.2 (worker: pipeline)

- **Status:**

### SAN-001.3 (worker: pipeline)

- **Status:**

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
- **Review:** pending, PR #62.
- **Deferred:** the R-FOP-6 grep test for unlink/remove calls outside `delete.py`/`copy_move.py` (not in this issue), and R-FOP-3 clean-on-start (not in M2, see above).
