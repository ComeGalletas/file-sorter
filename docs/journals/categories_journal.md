# Categories — journal

**ID:** CLS-001 (+ CLS-002, CLS-003, FOP-002, CLI-004, CLS-004, CLS-005, CLI-006, CLS-006) · **Systems:** CLS (+ NAME, FOP, DB, API, TST, MOD, CLI) · **Type:** feature · **Status:** CLS-001 design done; CLS-002, FOP-002, CLI-004 done; CLS-003.2 dropped (superseded by CLS-004); CLS-004 in progress; CLS-005 parked; CLI-006 and CLS-006 open (M3) ·
**Milestone:** m3 (CLS-001 designed pre-repo) · **Issues:** CLS-001: — (pre-repo); M3: see each Tasks section · **Branch:** CLS-001 pre-repo, committed at bootstrap; M3 per task (`office/*`)

---

## CLS-001 — Requirement (human, 2026-10-05)

- **Objective:** Classify every image on two category axes instead of one, with the adult tag and the reference on top.
- **Details:**
  - Images combine two labels, e.g. "videogames + screenshots" or "anime + memes".
  - Review the human's labelled sample (`labels.xlsx`: `category`, `category2`, `adult`, `reference`) and derive the label scheme from it.
- **Constraint:** Change the design only; there is no code yet. The labelled sample stays local (git-ignored).
- **Implements:** R-CLS-0, R-CLS-3, R-CLS-3a, R-CLS-5, R-ING-9, R-NAME-2, DESIGN §5, §6 and §11 (M3).

## CLS-001 — Confirmed reading

What the sample shows (rules only: this repo is public, so no counts or examples, DOC-005.D1):

- **Two axes.** The labels are one **format** (photos, screenshots, memes, artwork, documents) plus one **topic** (videogames, anime, PC equipment, animals, people, cartoons, landscape/beach, music, tv shows, mobile, IDE), typed in either order: both `videogames + screenshots` and `screenshots + videogames` occur. Position-based `category`/`category2` would split identical pairs into two folders.
- **`gif`** describes the file, not the image content. It matches the `.gif` extension wherever it is used.
- **`reference`** mixed named entities (franchise, character, product) with descriptions.
- **Adult:** `yes` or blank; blanks mean `no`.
- **Coverage:** every row matches `fixtures/labels.csv` exactly.

Decisions:

- **CLS-001.D1:** Two axes. **Format** is required (one); **topic** is optional (at most one). They are scored independently from one SigLIP embedding. Adult and reference sit on top. (human, 2026-10-05)
- **CLS-001.D2:** Folder layout `<Topic>/<Format>/`.
  - No topic → `General/<Format>/`. No format → `Unsorted/`.
  - Adult mirrors the whole tree under `Adult/`.
  - (human, 2026-10-05)
- **CLS-001.D3:** `gif` is not a label. `animated` is derived from the file (more than one frame). It feeds the `{animated}` token and an optional `Animated/` subfolder, off by default. (human, 2026-10-05)
- **CLS-001.D4:** `reference` is split into `reference` (a named entity: `Franchise` or `Franchise / Character`, or a product or public person) and `subject` (a description). They are graded separately: reference by M6, subject and name readability by M5. Claude pre-filled the split with a fixed entity table, for the human to review. (human, 2026-10-05)
- **CLS-001.D5:** M3 gate:
  - ≥ 90% format agreement overall;
  - ≥ 85% topic agreement on the rows that have a topic;
  - NSFW: every adult image caught, 0 false positives;
  - unrecognized format < 10%.
  
  (human, 2026-10-05) **Superseded** by CLS-004.D12 (format and topic ≥ 80% on a single run, human, 2026-10-19) and CLS-004.D3 (NSFW by level at `nsfw.min_level`).
- **CLS-001.D6:** Default vocabulary from the sample:
  - Formats: photos, screenshots, memes, artwork, documents.
  - Topics: videogames, anime, cartoons, pc-equipment, animals, people, landscapes (beach merged in), music, tv-shows, software (mobile and IDE merged).
  - The plan's `products` is dropped (it can be re-added with the CLI), and `landscapes` moves to topics.
  - Claude proposed the merges; the human confirmed them on 2026-10-05.
- **CLS-001.D7:** No topic is an outcome, not a review case. Only a missing format sets `needs_review` (P-6).
- **CLS-001.D8:** The C-6 nesting rule (anime under artwork) is moot for the defaults, because anime is now a topic. R-CLS-4 stays as a general rule for user-defined nested categories within one axis.

and then (human review of the noted rows, 2026-10-05):

- **CLS-001.D9:** **Label order means "is, then about".** `videogames + screenshots` is a capture taken *inside* a game (any source, console included). `screenshots + videogames` is a computer screenshot whose content is about games. The difference is visible in the image, so it becomes a format rather than an ordering the classifier would have to guess:
  - new format `game-screenshots` (→ `Videogames/Game Screenshots/`);
  - `screenshots` for computer and app captures (the reversed rows → `Videogames/Screenshots/`).
  
  Other reversed pairs share one folder; their nuance stays in subject and reference. (human, 2026-10-05)
- **CLS-001.D10:** `memes` and `documents` are also topics, meaning the image's meaning, and a topic never repeats its format (R-CLS-3b). When both labels are formats, the first is the format and the second becomes the topic: `photos + memes` → `Memes/Photos/`, and `screenshots + documents` → `Documents/Screenshots/`. (human, 2026-10-05)
- **CLS-001.D11:** **Blank means undecided.** The image stays in the test set and runs end to end, but isn't scored on the blank axis. A former `gif` row gets a topic where its reference settles it. (human, 2026-10-05)
- **CLS-001.D12:** **Adult means explicit sexual imagery.** Suggestive images without it stay `adult = no`. Such rows are deliberate negative tests, tagged `suggestive-negative`, and none may be flagged (R-CLS-1). (human, 2026-10-05) **Superseded in part** by CLS-004.D3: adult now means a level at or above `nsfw.min_level` (`nudity`), not explicit only. The `suggestive-negative` rows still must stay safe.
- **CLS-001.D13:** One label was corrected in review; the correction is in the local `labels.csv`. An earlier answer was amended the same day. (human, 2026-10-05)
- **CLS-001.D14:** The `note` column is replaced by `tags`, which holds test tags only (`suggestive-negative`). The review notes are resolved.

## CLS-001 — Plan

1. **DESIGN.md:** the R-CLS rewrite with both vocabulary tables; R-ING-9; R-NAME-2 tokens; R-FOP-1 path; API filters and assign body; §5 `categories.axis` and the `files.format/topic/animated` columns; §6 `folders.layout` and per-axis `classify`; §11 M3 gate; §13 C-21.
2. **`fixtures/labels.csv`:** converted from the xlsx with a deterministic script. Columns are `file, format, topic, adult, reference, subject, note`. Rows it can't settle get a `CHECK:` note.
3. **The human reviews** the noted rows; the `note` column is then cleared or left, since gate scripts ignore it.
4. **In M3:** seed migration for both axes, scoring per axis, `scripts/gate_3.py` per D5.

## CLS-001 — Tasks

- [x] CLS-001.1 — Analyze the labelled sample (vocabulary, pairs, gif, reference, coverage) → `pre-repo`
- [x] CLS-001.2 — Update DESIGN.md for two axes (§1, §3, §4.1, §4.3, §4.6–§4.8, §5, §6, §11, §13 C-21, Q-8 note) and CLAUDE.md's ledger note → `pre-repo`
- [x] CLS-001.3 — Convert the xlsx into `fixtures/labels.csv` (the unsettled rows get notes) → `pre-repo`
- [x] CLS-001.4 — Human: review the noted rows → decisions D9–D13 (2026-10-05)
- [x] CLS-001.7 — Re-convert `labels.csv` with D9–D14 (`game-screenshots`, topics `memes`/`documents`, undecided blanks, `tags`); update DESIGN.md (R-CLS-1, R-CLS-3b, formats and topics tables, M3 gate, C-21) → `pre-repo`
- ~~CLS-001.5~~ superseded at M3 G0 (lead, 2026-10-12): too big for one day, so it was split into tasks under new IDs: DB-003.1 (seed migration), MOD-002.1 and MOD-002.2 (scoring), CLS-002.1 and CLS-002.2 (rules and node), FOP-002.1 (folder layout).
- ~~CLS-001.6~~ superseded at M3 G0 (lead, 2026-10-12): TST-008.2 (label loader) and TST-008.3 (`scripts/gate_3.py`).

## CLS-001 — Results

### CLS-001.1–.3 (design, pre-repo)

- **Status:** DONE (after CLS-001.4 and .7). The design part of CLS-001 is complete; .5 and .6 are M3 build tasks.
- **Final label counts (v2, after D9–D14):** kept in the local `labels.csv` only (DOC-005.D1).
- **Triage:** large (contract change: data model, config schema, folder layout, gate) · no tests (pre-code). Both conversion scripts verified their own output: the row count, header, no duplicates, vocabulary membership, topic ≠ format, and exactly the two expected overrides.
- **v1 conversion (CLS-001.3):** superseded by .7.
- **Self-rating:** 9/10, proud: yes. Every label rule is a confirmed decision, and the conversion is deterministic and re-runnable. Remaining gap: some topics have very few examples, so their individual accuracy can't be measured; they count only toward the overall ≥ 85% topic figure.
- **Deferred:** the conversion script lives in the session scratchpad. M3's QA task re-implements the label loader in `tests/` against the new columns. (At M3 G0 this became TST-008.2, in `scripts/`, so both the gate and the calibration harness can use it.)

---

## CLS-002 — Requirement (DESIGN.md M3, 2026-10-12)

- **Objective:** Give every sanitized file exactly one format (or the fallback `unsorted`) and at most one topic, scored independently from one SigLIP embedding, with the NSFW branch on top.
- **Details:**
  - **Rules (CLS-002.1):** from each axis's per-category scores, choose:
    - the format by R-CLS-3: `min_score` and `classify.format.margin`, else `unsorted` with `needs_review = true, review_reason = unsorted`. The best topic is still recorded;
    - the topic by R-CLS-3a: `min_score` and `classify.topic.margin`, else no topic (`topic = null`), which is not a review case (CLS-001.D7);
    - with R-CLS-3b (a topic never repeats its format), R-CLS-4 (nesting within one axis) and R-CLS-6 (per-category `branch`).
  - **Node (CLS-002.2):** a `classify` graph node takes `sanitized` rows to `classified`.
    - It reads the first frame (R-ING-6) of each row's sanitized working copy, never the source (P-2).
    - It embeds and gates the whole batch (R-PIPE-1), and scores both axes against the prompts in `category_prompts` (DB-003).
    - It writes `branch`, `nsfw_score`, `format`, `topic`, `format_scores`, `topic_scores`, `needs_review`, `review_reason` and `image_vec` (CLS-002.D10).
- **Constraint:**
  - P-1 and P-2: originals are never opened. Pixels go only to local models, through `classifier/models/`.
  - Thresholds, margins and prompts come from `config.yaml` and Postgres, never from code (P-5). They are hand-tuned values (CLAUDE.md §1.7).
  - Privacy checklist up front (`docs/plans/m3.md`).
- **Implements:** R-CLS-0, R-CLS-1, R-CLS-3, R-CLS-3a, R-CLS-3b, R-CLS-4, R-CLS-6, R-PIPE-1, P-2, P-4, P-6, P-7; CLS-001.D1, D7, D8, D10, D12. With MOD-002: R-CLS-2.

## CLS-002 — Confirmed reading

What the code and DESIGN.md already say:

- `files` already has `branch`, `nsfw_score`, `animated`, `format`, `topic`, `format_scores`, `topic_scores`, `needs_review` and `review_reason` (DB-001). Ingest already sets `animated` (ING-001.D3). There is no vector column. `files.status` already has `classified`.
- `PIPELINE_ORDER` lists `classify` third, and `REGISTRY` has `ingest` and `sanitize` (`classifier/graph/nodes.py`). `NodeContext` carries the config and a test seam (`ollama_transport`). Classify needs a second seam, for the vision models.
- `config.yaml` already has:
  - `classify.score: sigmoid`;
  - each axis's `default_min_score: null` ("calibrated in M3", R-CLS-8) and `margin: 0.05`;
  - `nsfw.threshold: 0.70`, `nsfw.mode: mirror` and `nsfw.root: Adult`.

  Only CLS-003.2 changes these, after the human approves the values (CLAUDE.md §1.7).
- There is no `categories` table yet; DB-003 adds it.
- The image already has `transformers`, `sentencepiece`, `protobuf` and a CUDA torch build. `make models` has fetched the SigLIP and NSFW weights into the `hf` volume. `app` runs with `HF_HUB_OFFLINE=1`, and `test` mounts `hf` too.
- `.claude/roles/ml.md` gives ML "both category axes (R-CLS-0 to R-CLS-3b)".
- **CLS-002.D12** — **An M3 dry run stops at `classified`** (confirmed by the human, 2026-10-12, option A, from PR #104's review). R-PIPE-2's "ends at status `proposed`" is the full pipeline's end state. `proposed` is written by `name` (M5), so in M3 rows stop at `classified`, the last registered node's status, as M1's and M2's dry runs stopped at `queued` and `sanitized`. No stub `name` node. DESIGN §13 records it, in DOC-008 (PR #105).

Decisions:

- **CLS-002.D1** — **Where the rules live** (lead, 2026-10-12). They go in one pure module, `classifier/models/classify_rules.py`, owned by ML. Both the node (Pipeline) and the calibration harness (ML, CLS-003.1) import it, so the eval and the gate measure the same rules. It takes scores and category records only: no db, no files, no models.
- **CLS-002.D2** — **An ineligible winner falls back, not through** (lead, 2026-10-12; R-CLS-6 read literally; confirmed by the human, 2026-10-12, and recorded in DESIGN §13 by DOC-008).
  - Each axis is ranked over all its categories, and the threshold, margin and nesting rules pick its winner.
  - Then the branch check runs. A winner whose `branch` excludes the image's branch is not used: a `safe` category for an adult image, or an `nsfw` category for a safe image.
  - In that case the format becomes `unsorted` (adult: `Adult/Unsorted/`), and the topic becomes none. The runner-up is not tried.
- **CLS-002.D3** — **R-CLS-3b mechanics** (lead, 2026-10-12). The topic twin of the chosen format (same name) is removed from the topic candidates. R-CLS-3a then runs on the rest, with R-CLS-4, and the margin is taken against the next remaining topic. When the format is `unsorted`, nothing is removed.
- **CLS-002.D4** — **Thresholds and ties** (lead, 2026-10-12).
  - A category's `min_score` of null means its axis's `classify.<axis>.default_min_score`.
  - If that default is null too, the node refuses to run before any row changes. The message names the key and no value.
  - Ties sort by score descending, then by name, so the choice is deterministic.
- **CLS-002.D5** — **Stored scores** (lead, 2026-10-12). `format_scores` and `topic_scores` each hold that axis's top 5 as `[{"category": <name>, "score": <float, 4 decimals>}]`, in descending order. The UI's top 3 (R-API-5) reads the first three.
- **CLS-002.D6** — **R-CLS-4 nesting** (lead, 2026-10-12). Ancestry is the `parent_id` chain within one axis.
  - If the top two are ancestor and descendant, the margin check is skipped, and the deeper one wins if it clears its own `min_score`.
  - If it doesn't, the ancestor is judged by the normal rule, against the next category that is not its descendant.
- **CLS-002.D7** — **Failures** (lead, 2026-10-12; like SAN-001.D2).
  - **One file:** a missing or unreadable working copy sends the file to `error` with the fixed reason `classify_working_copy_unreadable`. The next run retries it from ingest (R-ING-2). The `error` transition clears the row's `sanitize_log` rows, through SAN-003.1's helper.
  - **The whole run:** if a model can't load (missing weights, no GPU for SigLIP), the run stops before any row changes, with a fixed message naming `make models`.
  - All errors are fixed text, unchained.
- **CLS-002.D8** — **Only the working copy** (lead, 2026-10-12; P-2, ING-001.D2). The node opens `<results_root>/.work/<source_hash>.<ext>`, a path built from the hash and the extension, never from `source_path`. It refuses a working copy that is a symlink or not a regular file.
- **CLS-002.D9** — **`nsfw.mode: separate` fails fast in M3** (lead, 2026-10-12; confirmed by the human, 2026-10-12, and recorded in DESIGN §13 by DOC-008). DESIGN.md names the mode but never specifies it, so only `mirror` is built. `separate` stops the run with a message naming the key, like SAN-001.D6.
- **CLS-002.D10** — **Classify stores the SigLIP image vector** (confirmed by the human, 2026-10-12, option A; rule change DOC-008.D1, PR #105). DB-003.1 adds `files.image_vec vector(1152)` (the pgvector extension already exists), and the node writes the embedding of the sanitized copy. M6's retrieval and a later `reclassify` reuse it without re-embedding. DESIGN §3 already listed it among classify's writes; DOC-008 adds it to §5. It stays in the local ledger, like every other `files` column.
- **CLS-002.D11** — **Prompt encoding and batch size** (lead, 2026-10-12). Prompts are encoded once per node call, from `category_prompts`. The batch size is a constant in `classifier/models/`, not a config key: it isn't a threshold, and DESIGN §6 has no key for it.

## CLS-002 — Plan

The contracts between the parallel tasks. Names are the worker's to propose in its plan comment; the shapes are fixed here.

- **MOD-002.1 (ML):** `classifier/models/siglip.py`.
  - `embed_images(images) -> float32 (n, 1152)` and `embed_texts(texts) -> (m, 1152)`, both L2-normalised.
  - A pure scoring function: per image, `{category: score}`, either `sigmoid(logit_scale·cos + logit_bias)` or the raw cosine when `classify.score: cosine`, taking the max over the category's prompts (R-CLS-2, C-5).
- **MOD-002.2 (ML):** `classifier/models/nsfw.py`: `nsfw_scores(images) -> float (n,)`.
- **Seam:** both sit behind one `VisionBackend` protocol (MOD-002.D1). The node gets it from `NodeContext`: the real one by default, and TST-008.1's replay in tests.
- **CLS-002.1 (ML):** `classifier/models/classify_rules.py`.
  - `CategoryRule(id, axis, name, folder, min_score, branch, parent_id)`.
  - `choose(format_scores, topic_scores, rules, branch, classify_config) -> Choice(format, topic, needs_review, review_reason, format_top, topic_top)`.
- **CLS-002.2 (Pipeline):** `classifier/graph/classify.py`, registered after `sanitize`. It adds the vision seam to `NodeContext`, and returns a `ClassifyResult` (counts: classified, unsorted, no topic, adult, errors) for CLI-005 and gate 3. `RunResult` gets a `classify` accessor like `sanitize`.
- **Tests:**
  - `unit`: every R-CLS rule in CLS-002.1, including ties, nesting, branch fallback, twin removal and null thresholds.
  - `integration`: the node on synthetic images, with vision outputs replayed in TST-008.1's format. The worker records them with the `gpu` recorder and commits them (TST-005.D1).

## CLS-002 — Tasks

- [x] CLS-002.1 — Pure decision rules for both axes (R-CLS-3, 3a, 3b, 4, 6) in `classifier/models/classify_rules.py` · #90 · acceptance: `tests/unit/models/test_classify_rules.py`
  - [x] CLS-002.1.1 — types, `nsfw_branch`, `validate_rules`, single-axis pick (thresholds, margin, default, ties) and top 5 · commit: 306838c
  - [x] CLS-002.1.2 — nesting (CLS-002.D6) · commit: 45bfb48
  - [x] CLS-002.1.3 — `choose`: twin removal, branch fallback, `needs_review` · commit: 9eb2dad
  - [x] CLS-002.1.4 — privacy tests (repr, unchained errors, surrogates) and Results · commit: this one
- [ ] CLS-002.2 — The `classify` node: working copy → vision backend → rules → ledger, with the `NodeContext` vision seam · #99 · acceptance: `tests/integration/test_classify_node.py`
  - [x] CLS-002.2.1 — Settings check (`nsfw.mode`), `NodeContext.vision`, `ClassifyResult`, `RunResult.classify`
  - [x] CLS-002.2.2 — Working-copy opener (`O_NOFOLLOW` + `fstat`) on the name shared with sanitize
  - [x] CLS-002.2.3 — The node: select, score, `choose`, write, `mark_error`; registered after `sanitize`
  - [x] CLS-002.2.4 — Recordings under `tests/recordings/graph/` and the acceptance test
  - [x] CLS-002.2.5 — One savepoint per file for the `classified` write; a rejected write errors only that row (`classify_ledger_write_failed`) (review of #123)

## CLS-002 — Results

### CLS-002.1 (#90, ml desk)

- **Tests:** `tests/unit/models/test_classify_rules.py` passes (acceptance): 59 tests. The `unit` tier passes in full (1081 passed; the `db` and `integration` tiers run at pre-push). `make lint` is clean. No `gpu` or `eval/` run: no model, prompt or threshold is touched, and no value is invented.
- **Behavior:** `classifier/models/classify_rules.py` is pure (an AST test checks its imports). `nsfw_branch` (inclusive threshold), `validate_rules` (the node's up-front check, CLS-002.D4: axis, branch, duplicates, parent chain, null `min_score` with a null axis default) and `choose` (R-CLS-3, 3a, 3b, 4, 6). `choose` keeps the null-default check as a backstop.
- **Readings taken (lead-approved):** `>=` at both the `min_score` and margin boundaries, with a 1e-9 float tolerance; D2 per axis (an ineligible format winner is `unsorted` with review, an ineligible topic winner is no topic); the twin is the same-name topic only, and the stored top 5 is unfiltered; `unsorted` is never a candidate and always eligible.
- **D9 (`nsfw.mode: separate` fails fast)** belongs to the node (CLS-002.2): this module never sees `nsfw.mode`.
- **Self-rating:** 9/10, proud: yes. Gaps against the acceptance test and cited R-IDs: (1) no caller yet, because the node (CLS-002.2) and the calibration (CLS-003.1) wire it in, so the integration is untested here; (2) `Choice` holds plain lists inside a frozen dataclass, so a caller could mutate them (the node serialises them straight away).
- **Completion status:** DONE.
- **Reviewer / Privacy auditor:** pending.

### CLS-002.2 (#99, pipeline desk)

- **Tests:** the acceptance test `tests/integration/test_classify_node.py` passes (7 tests, replayed vision output). New unit tests (`test_classify_types.py`, `test_classify_working_copy.py`: 24) and db tests (`tests/db/graph/test_classify_node.py`: 13, a numeric vision double). The default tiers pass in full (count superseded by the CLS-002.2.5 note below). `make lint` is clean. The gpu recorder (`tests/gpu/graph/test_record_classify.py`) ran once on the real models with `--record-vision` and wrote 56 recordings under `tests/recordings/graph/`; they pass the TST-008.D9 lint. No `eval/` run: no prompt, threshold or model is touched.
- **Behavior:** `classifier/graph/classify.py` selects `sanitized` rows, opens each `<results_root>/.work/<source_hash>.<ext>` (the name comes from `working_copy_name`, which `make_working_copy` also uses; `O_NOFOLLOW`, `O_NONBLOCK`, `fstat` regular-file check; first frame as RGB), encodes the prompts once, embeds and gates in chunks of `siglip.BATCH_SIZE`, and writes branch, gate score, format, topic, top-5 lists, review fields and `image_vec`, leaving the row at `classified` (D12). An unreadable copy goes to `error` through `mark_error` with the registered reason `classify_working_copy_unreadable`. Rules, prompts, the work folder (`check_work_dir`, read-only) and `nsfw.mode` are checked before any row changes; a model that cannot load raises the backend's fixed text naming `make models`.
- **Side effects:** `NodeContext.vision` and `run(vision=...)` are the seam; `RunResult.classify` is the accessor. The M2 integration tests now pass `nodes=` (ingest and sanitize) so they keep testing M2, and `test_dry_run_cli.py` pins the CLI to the same nodes until CLI-005.1 (#100) moves the dry run to M3.
- **Self-rating:** 9/10, proud: yes. Gaps: (1) `classifier dry-run` still prints M2 counts and does not build the real SigLIP backend: that is CLI-005.1 (#100); (2) the acceptance run uses flat synthetic pictures, so it proves the wiring and the pure rules, not classification quality (that is CLS-003); (3) writes are per row inside `run`'s node transaction, so a database error rolls the whole node back rather than one row.
- **Completion status:** DONE.
- **Reviewer / Privacy auditor:** pending.

---

## FOP-002 — Requirement (DESIGN.md M3, 2026-10-12)

- **Objective:** Compute each file's result folder from its branch, topic, format and `animated` flag, and create the empty category folders.
- **Details:**
  - **FOP-002.1:** `classifier/fileops/layout.py` returns `[Adult/]<Topic|General>/<Format>[/Animated]` or `[Adult/]Unsorted` (R-CLS-5). It reads `folders.layout`, `folders.no_topic`, `folders.animated_subfolder` and `nsfw.root`, plus the categories' `folder` values. It is pure: no file system.
  - **FOP-002.2:** `sync_folders` in `classifier/fileops/folders.py`, plus the `classifier categories sync-folders` command (R-CLS-7). Folder names are checked for case-insensitive collisions (R-FOP-9).
- **Constraint:**
  - Directories are only created, never removed or renamed (R-CLS-7: removing a category never deletes folders; no delete code outside `fileops/delete.py`, per CLAUDE.md's hard rules).
  - Before M7, `results_root` holds only empty category folders, `.work/` and `reports/` (DESIGN §3).
  - Errors are fixed text, with no path.
- **Implements:** R-CLS-5, R-CLS-7 (`sync-folders`), R-FOP-9, R-ING-9; CLS-001.D2, D3.

## FOP-002 — Confirmed reading

- `config.yaml` already has `folders.auto_create`, `folders.layout: "{topic}/{format}"`, `folders.no_topic: General`, `folders.animated_subfolder: false` and `nsfw.root: Adult`.
- `classifier/fileops/` has `copy_move.py` and `thumbs.py`.
- **FOP-002.D1** — **One layout** (lead, 2026-10-12; CLS-001.D2). M3 supports only `folders.layout: "{topic}/{format}"`. Any other value fails fast, naming the key.
- **FOP-002.D2** — **Nested topics** (lead, 2026-10-12; R-CLS-4). A nested category's folder is its parent's folder path plus its own (`Videogames/Racing`), and that whole path takes the topic's place in the layout.
- **FOP-002.D3** — **`sync-folders` before M7** (lead, 2026-10-12; R-CLS-7 read literally). It creates:
  - `General/<Format>/` for every format except `unsorted`, plus `Unsorted/`;
  - the same under `nsfw.root` (mirror mode, R-CLS-5);
  - `<Topic>/<Format>/` pairs, but only for rows with status `filed`, so none before M7;
  - `.work/` and `reports/`.

  `Animated/` subfolders are never made ahead of time. M7 creates them when it files. In M3 `dry-run` never calls `sync-folders`; M7 runs it before `sort` (`folders.auto_create`).
- **FOP-002.D4** — **Case-insensitive collisions** (lead, 2026-10-12; R-FOP-9). The plan is checked before anything is made. It is refused if two folders at the same level differ only in case, or if a folder on disk differs only in case from a planned one. The error names the category names (configuration, not personal data) and never a path. Nothing is created on refusal.

## FOP-002 — Tasks

- [ ] FOP-002.1 — `classifier/fileops/layout.py`: the result folder for a branch, topic, format and `animated` flag · #91 · acceptance: `tests/unit/fileops/test_layout.py`
  - [x] FOP-002.1.1 — the layout, `General`, `Unsorted`, the `Adult/` prefix and the `Animated/` rule · commit: 8d55950
  - [x] FOP-002.1.2 — nested topics (D2) and segment validation of every folder name · commit: d72428d
  - [x] FOP-002.1.3 — privacy tests (fixed, unchained errors) and Results · commit: this one
- [ ] FOP-002.2 — `sync_folders` and `classifier categories sync-folders`, with case-insensitive collision checks · #98 · acceptance: `tests/db/fileops/test_sync_folders.py`
  - [x] FOP-002.2.1 — `fileops/folders.py`: the pure planner (D3), the case-insensitive collision check (D4) and the safe `mkdir` walk, with their tests (planned subtask 2.2 merged in: one module) · commit: 5e8b27b
  - [x] FOP-002.2.3 — `classifier categories sync-folders` and its command tests · commit: 9453a74
  - [x] FOP-002.2.4 — Results and PR · commit: this one

## FOP-002 — Results

### FOP-002.1 (#91, pipeline desk)

- **Tests:** `tests/unit/fileops/test_layout.py` passes (acceptance). The default tiers pass in full (`unit + db + integration`: 1219 passed, 24 deselected). `make lint` is clean. No `gpu` or `eval/` run: no model or prompt is touched.
- **Behavior:** `result_folder()` returns `[Adult/]<Topic|General>/<Format>[/Animated]` or `[Adult/]Unsorted` as a relative `PurePosixPath`. It does no file system access (R-CLS-5, R-ING-9, FOP-002.D1, D2). Every segment (topic path, `no_topic`, format, `Unsorted`, the `nsfw` root) is validated, and errors are fixed text with no cause or context.
- **Self-rating:** 9/10, proud: yes. Gaps against the acceptance test and cited R-IDs: (1) no caller yet, because CLI-005.1 and M7 wire it in, so the integration is untested here; (2) case-insensitive collisions are left to FOP-002.2 (FOP-002.D4).
- **Completion status:** DONE.
- **Reviewer / Privacy auditor:** pending.

### FOP-002.2 (#98, pipeline desk)

- **Tests:** `tests/db/fileops/test_sync_folders.py` passes (acceptance, tier `db`: 20 tests, 17 on `sync_folders` and the planner, 3 on the command). Default tiers: 1751 passed, 37 deselected. `make lint` is clean. No `gpu` or `eval/` run: no model or prompt is touched.
- **Behavior:** `sync_folders` creates the FOP-002.D3 tree under the resolved `results_root`: `General/<Format>/` and `Unsorted/` (and the same under `nsfw.root`), `<Topic>/<Format>/` only for `filed` rows, `.work/` and `reports/`; never `Animated/`. The plan is checked first (D4): planned siblings that differ only in case (`casefold`, stricter than NTFS), a topic folder that equals a reserved or config folder, or an entry on disk that differs only in case refuses the run; the error names category names or config keys and nothing is created. Links and non-directories are refused; `OSError` becomes fixed unchained text. `nsfw.mode: separate` fails fast naming `nsfw.mode` (lead's answer on #98). The command always creates (`folders.auto_create` only governs M7's `sort`) and echoes only the count of new folders.
- **Deviation:** planned subtasks 2.1 and 2.2 landed as one commit (one module), and the command's tests shipped with the module's.
- **Self-rating:** 9/10, proud: yes. Gaps: (1) a race between the check and `mkdir` is not guarded (single-user tool); (2) the `separate` text is defined here until the classify node (CLS-002.2) lands, so the two should be unified then.
- **Completion status:** DONE.
- **Reviewer / Privacy auditor:** pending.

---

## CLI-004 — Requirement (DESIGN.md M3, 2026-10-12)

- **Objective:** Manage both axes' categories from the CLI.
- **Details:** `classifier categories`:
  - `list`: axis, name, folder, `min_score` (or "axis default"), branch, parent and prompt count;
  - `add --axis format|topic <name> --folder … --prompt … [--prompt …] [--min-score] [--branch any|safe|nsfw] [--parent]`;
  - `edit` (folder, prompts, `min_score`, branch);
  - `remove` (R-CLS-7).

  FOP-002.2 adds `sync-folders` to the same group.
- **Constraint:**
  - Postgres only, no file system writes (P-5).
  - `unsorted` can't be removed or given prompts.
  - Names are unique per axis, and folders are unique case-insensitively among siblings.
  - A parent must be on the same axis, with no cycles.
  - Errors are fixed text and exit 2.
- **Implements:** R-CLS-7, R-CLS-4, R-CLS-6, P-5.

## CLI-004 — Confirmed reading

- `classifier/cli/__init__.py` is a Typer app with `version` and `dry-run`.
- **CLI-004.D1** — **`remove` deletes the category and its prompts** (lead, 2026-10-12). Files keep their text value (DB-003.D1), and folders and files are never touched (R-CLS-7). A category with children can't be removed.
- **CLI-004.D3** — **The CLI validates structure with the axis defaults filled in** (proposed by the worker, confirmed by the lead, 2026-10-14, PR #121). While `classify.*.default_min_score` is null (pre-calibration, CLS-003) and the seed's `min_score` is null, `validate_rules` rejects any change. The CLI therefore substitutes 0.0 for a null axis default when it checks names, parents and branches. The classify node's own pre-flight still refuses a null default at run time.
- **CLI-004.D2** — **Edits apply to the next classify** (lead, 2026-10-12). Rows already classified aren't changed: `reclassify` is M7's (R-FOP-7).

## CLI-004 — Tasks

- [x] CLI-004.1 — `classifier categories list|add|edit|remove` · #97 · acceptance: `tests/db/cli/test_categories_cli.py`
  - [x] CLI-004.1.1 — expose `validate_folder_segment` in `fileops/layout.py` (the CLI reuses it)
  - [x] CLI-004.1.2 — `categories list`
  - [x] CLI-004.1.3 — `categories add`
  - [x] CLI-004.1.4 — `categories edit` and `remove`

## CLI-004 — Results

- **Tests (CLI-004.1):** acceptance `tests/db/cli/test_categories_cli.py`, 43 passed (db tier, throwaway schema per module, rows cleaned in a teardown that also runs on failure); `tests/unit/fileops/test_layout.py` 115 passed; `make test` 1511 passed, 37 deselected; `make lint` clean. No gpu tier or eval (no model, prompt or threshold touched).
- **Decision for the lead:** CLI-004.D3 (above) is proposed, not confirmed.
- **Self-rating:** 9/10, proud: yes. Gaps against the acceptance test and cited R-IDs: (1) `edit` cannot change the parent or the name, which the issue doesn't ask for; (2) D3 waits for the lead's confirmation.
- **CLS-002.2.5 (review of #123):** the `classified` write runs in its own savepoint. A rejected write sends only that row to `error` with the registered reason `classify_ledger_write_failed` (like sanitize's `LEDGER_REJECTED`; the next run retries it from ingest), and the other rows still reach `classified`. Regression test: a db test with one row the ledger refuses. `sanitize.py` now names the published copy with `working_copy_name`. With no `sanitized` rows the node returns before `validate_rules` and `check_work_dir`: harmless, as nothing is read or written. Counts, one basis: after merging main, the default tiers (unit, db, integration) give 1808 passed, 39 deselected; the earlier figures (1231, 1719, 1777) were taken at earlier commits and are superseded.
- **Completion status:** DONE.
- **Reviewer / Privacy auditor:** pending.

---

## CLS-003 — Requirement (DESIGN.md M3, R-CLS-8, 2026-10-12)

- **Objective:** Calibrate the classify thresholds per axis against `fixtures/labels.csv` so gate 3 can pass, and commit the values the human approves.
- **Details:**
  - **CLS-003.1 (ML):** `eval/classify_eval.py`.
    - It runs ingest and sanitize on the labelled fixtures in a throwaway db and a temporary results tree, so the models see only sanitized copies (P-2).
    - It scores every working copy once through the `VisionBackend`, and caches the scores, so a sweep doesn't re-run the models.
    - It sweeps each axis's `default_min_score` and `margin`, and `nsfw.threshold`. It adds per-category `min_score` overrides only where they raise agreement.
    - It applies CLS-002.1's rules exactly, and reports each CLS-001.D5 criterion with a 5-fold held-out estimate (pinned seed).
  - **CLS-003.2 (Pipeline):** commits the values the human approved, as type `balance`, where CLS-003.D2 puts them:
    - `config.yaml`: the per-axis defaults, plus `margin` and `nsfw.threshold` if they changed;
    - migration `0004`: per-category overrides, and prompt changes if CLS-003.D1 allows them.
- **Constraint:**
  - These are hand-tuned values (CLAUDE.md §1.7). The human approves every value before CLS-003.2 commits it.
  - Public output follows TST-008.D1. No per-category breakdown and no file names are published. Per-category detail goes to the console only, behind `--detail`, and is never pasted into GitHub or the repo.
- **Implements:** R-CLS-8, R-CLS-1, C-5; CLS-001.D5, D11, D12.

## CLS-003 — Confirmed reading

- `eval/entity_eval.py` (MOD-001) is the existing pattern: run in the container, report numbers.
- `classify.*.default_min_score` is null in `config.yaml`, so without CLS-003.2 the node refuses to run (CLS-002.D4).
- **CLS-003.D1** — **Calibration scope: thresholds, margins, `nsfw.threshold`, and prompts if needed** (confirmed by the human, 2026-10-12, option B). The sweep covers the per-axis `default_min_score` and `margin`, `nsfw.threshold`, and per-category `min_score` overrides. If those alone can't reach the gate, prompt edits beyond DESIGN §4.3's tables are allowed. Each edit is its own `balance` task with eval numbers and the human's approval, and §4.3 is updated in a human-side PR. Every value, including a move of `nsfw.threshold` from 0.70, needs the human's approval (CLAUDE.md §1.7).
- **CLS-003.D2** — **Where the values land** (confirmed by the human, 2026-10-12, as recommended; R-CLS-8 is aligned in DOC-008, PR #105).
  - per-axis defaults in `config.yaml`;
  - per-category overrides and any prompt edits in a new migration `0004`.

  `0003` stays the DESIGN.md seed, so databases that already ran it stay consistent.
- **CLS-003.D3** — **Fit on every labelled row** (lead, 2026-10-12; DESIGN §11 and R-CLS-8 calibrate and gate on the same rows). The 5-fold held-out estimate is the generalisation check. A gap of more than 5 points between fitted and held-out agreement on either axis is reported as DONE_WITH_CONCERNS.

## CLS-003 — Tasks

- [x] CLS-003.1 — `eval/classify_eval.py`: score the sanitized labelled fixtures once, sweep the thresholds, report per CLS-001.D5 with a held-out estimate · #101 · acceptance: `tests/gpu/models/test_classify_eval.py` (done with concerns; PR #120, merged as `fd4f7c2`)
  - [x] CLS-003.1.1 — `eval/classify_sweep.py`: the pure sweep, overrides and 5-fold check, with unit tests (17176ee)
  - [x] CLS-003.1.2 — scoring: `SiglipBackend` scores of the working copies, the score cache, the label join (1f821d7)
  - [x] CLS-003.1.3 — `eval/classify_eval.py`: the throwaway-db run, the CLI, the public and `--detail` report, the proposal printout (a7ba20e)
  - [x] CLS-003.1.4 — the `gpu` acceptance test, the real-fixture run, Results (hash in the PR)
  - [x] CLS-003.1.5 — rule out a bug on the box: the NSFW label index, the sanitized working copy as input, exact coverage; each `ok`/`FAIL` (#101, lead's comment)
  - [x] CLS-003.1.6 — box-only NSFW block in `--detail`, and `--hold-nsfw-threshold` (sweep side 3eff259; the CLI side and the report in the CLS-003.1.5 commit)
  - [x] CLS-003.1.7 — `tests/gpu/models/test_siglip_reference.py`: SigLIP known-answer and reference-agreement cross-check; result `ok`, no fix needed (#101, lead's comment)
  - [x] CLS-003.1.8 — review fixes: the infeasible suggestive-negative verdict, a real `nsfw input` check, repr tests for `Checks`/`RunInfo`/`NsfwDiagnostic`, Results brought current (#120 review)
- ~~CLS-003.2~~ dropped (lead, 2026-10-18): superseded by CLS-004. The human replaced SigLIP threshold calibration with a VLM classifier, so there are no SigLIP thresholds to commit. #102 is closed as not planned once the re-plan is approved (the human approved it on 2026-10-19). The settings the VLM path needs land in CFG-003.1.

## CLS-003 — Results

### CLS-003.1 — Results (ML, #101)

- **Tests (current):** `unit` 59 in `tests/unit/eval/` (sweep, cross-validation, scoring, cache, label join, bug checks, report, entry point, repr/privacy); `gpu` `tests/gpu/models/test_classify_eval.py` 5 passed (synthetic noise images and labels, ingest and sanitize in a throwaway schema, the cache hit on a second run, the public form, `--detail` and `--hold-nsfw-threshold`, the real model config's `nsfw` label, a coverage failure as fixed text) and `tests/gpu/models/test_siglip_reference.py` 4 passed.
- **Sweep objective (CLS-003.1.D1, ML):** agreement alone only improves as the thresholds fall, so the fit takes the most conservative values within a 1-point slack of the best agreement (`--slack-points`), and keeps the unrecognized share under the gate's 10% when the best does. Overrides: coordinate ascent, at least one whole row of gain, the highest value among the best gains, kept only if the pooled held-out agreement of their axis does not drop. Grids: linear steps plus a geometric tail from 1e-4, because SigLIP sigmoid scores can sit far below 0.02 (CLS-003.1.5).
- **CLS-003.1.5 bug checks, on the box (public form):** `nsfw label ok` (the single `id2label` entry named `nsfw`, asserted against the real model config), `coverage ok` (every labelled row joined to exactly one ledger row). `nsfw input`: replaced in CLS-003.1.8 by a real check (each scored copy is a regular, non-link file directly in the resolved `.work`, with a `sanitized` ledger row, decoded to RGB by the one opener that feeds the models); the earlier version was tautological and is not relied on.
- **CLS-003.1.6:** the console-only NSFW block under `--detail` and `--hold-nsfw-threshold` (format and topic swept with `nsfw.threshold` at its `config.yaml` value, reported as not swept). The default output carries no NSFW diagnostic number (tested).
- **CLS-003.1.7 SigLIP cross-check (gpu): known answer `ok`, reference agreement `ok`.** Logits within 0.03 and probabilities within 0.003 of transformers' `logits_per_image` on synthetic squares (tolerances 0.1 and 0.01). No fix to `siglip.py` was needed.
- **CLS-003.1.8:** the infeasible NSFW branch now judges `suggestive-negative` on the criterion (some threshold keeps every suggestive-negative gate row below every adult gate row), not at a best-effort threshold; the bug check above; repr tests for `Checks`, `RunInfo` and `NsfwDiagnostic`; these Results.
- **Real-fixture runs (public form, TST-008.D1):**
  - NSFW swept, after the CLS-003.1.8 fix: `bug checks: nsfw label ok, nsfw input ok, coverage ok`; `adult flagged and the rest safe: FAIL`; `suggestive-negative safe: FAIL` (no threshold keeps every suggestive-negative row below every adult row; the earlier `ok` was measured at a best-effort threshold and is withdrawn); no `nsfw.threshold` satisfies every labelled NSFW row, nothing else swept. The constraint was not relaxed.
  - NSFW held at its config value: format `FAIL` 31%, topic `FAIL` 39%, unrecognized `FAIL` 33%, held-out 30% / 38% / 35%, gap `ok`. The proposed values sit at the bottom of the grid, so they are not a proposal; no value is offered for approval.
- **Completion status:** DONE_WITH_CONCERNS. The harness and the client are verified, but thresholds alone cannot reach gate 3 on the real labels. Proposed follow-up for the human (CLS-003.D1): whether the category prompts describe the labelled categories, and whether `classify.score: cosine` suits better than `sigmoid`; any prompt edit is its own approved `balance` task.
- **Self-rating:** 8/10, proud: yes. Gaps: (1) the category sweep and overrides have not produced a gate-passing result on the real labels (a data and prompt question, not a harness bug as far as the checks can tell); (2) the grid cost on a much larger fixture set is untested.

---

## CLS-004 — Requirement (human, the M3 VLM re-plan, 2026-10-18)

- **Objective:** Classify each image's format, topic and NSFW level with a local VLM through Ollama instead of SigLIP zero-shot plus the Falconsai gate, so gate 3 can pass.
- **Details:**
  - **One classify call** per image returns the format and topic as structured JSON, constrained to the category lists, at temperature 0.
  - **A second, dedicated call** rates the NSFW level on scale A (`safe`, `suggestive`, `nudity`, `explicit`). For an animated image it also sees the first, middle and last frames, and the highest level wins.
  - **The adult branch** is `level >= nsfw.min_level`. The level is stored in `files.nsfw_level`, so a later change of `min_level` re-files through `reclassify` without re-running the model.
  - **The classify call** also gets the sanitized file name as a hint ("the picture decides"). The NSFW call never gets it.
  - **SigLIP** keeps producing `image_vec` (CLS-002.D10). It no longer classifies.
  - **Falconsai** is a cross-check only: a strong disagreement sets `needs_review` and decides nothing.
  - **Failed answers:** a failed or unparsable answer is retried once, then recorded as an error. It is never silently `safe` or `unsorted`.
  - **One resident model:** `qwen3-vl:8b-instruct`, with every prompt pinned to `num_ctx: 4096`.
- **Constraint:**
  - P-2: models see the sanitized working copy and the sanitized name only.
  - The prompts are hand-tuned values (CLAUDE.md §1.7): versioned files in `prompts/`, changed only with the human's approval.
  - The rule and spec changes are DOC-009 (human-side): R-CLS-1, R-CLS-2, R-CLS-3/3a, C-5, the `config.yaml` sketch, `files.nsfw_level`, and gate 3's format target and NSFW wording.
  - Real-fixture results publish only in the TST-008.D1 form.
- **Implements:** R-CLS-0, R-CLS-1 to R-CLS-6 (as amended by DOC-009), R-MOD-1, P-2, P-7. It supersedes CLS-003.2, and replaces CLS-002.D1's SigLIP scoring path while keeping its single shared rules module.
- **Source:** the human's VLM spike write-up (2026-10-17), decisions 3.1 to 3.7. Its results are not copied here beyond the public form.

## CLS-004 — Confirmed reading

- **On `main`:**
  - the classify node, `classify_rules`, `SiglipBackend`, the NSFW client, the Ollama client with JSON-schema `format` and `think`, `prompts.py`;
  - the eval harness (CLS-003.1);
  - gate 3 (TST-008.3, PR #126).
- **`models.vlm_safe` is already `qwen3-vl:8b`** (the thinking build). The spike found that the thinking build sometimes ignores `think: false` and returns empty answers. `models.vlm_nsfw` stays null (Q-1), because this NSFW-*rating* call is not M5's adult-captioning model.
- **CLS-004.D1 — the classify call (human, 3.1):**
  - format and topic come from one call, with the JSON schema's enums built from the `categories` table at run time;
  - the format enum includes `unsorted` ("none of these fits");
  - the topic enum includes `none`;
  - temperature 0.

  The enum entries are the lead's reading. CLS-002.D2's branch eligibility and D3's twin removal still apply after the answer, while `min_score` and `margin` do not.
- **CLS-004.D2 — the NSFW call (human, 3.2):**
  - a separate call, on the scale-A definitions;
  - text in the image never raises the level;
  - the highest level across the image, or across the first, middle and last frames of an animated one;
  - it never sees the file name.
- **CLS-004.D3 — `nsfw.min_level`** (`suggestive | nudity | explicit`): the human's value is `nudity` (human, 3.2). Adult means `level >= min_level`. It replaces R-CLS-1's Falconsai threshold and CLS-001.D12's explicit-only definition.
- **CLS-004.D4 — a failed answer** (human, 3.1; the lead's reading of "error, sent to review", **to confirm**):
  - it is retried once;
  - then the row goes to `error` with a registered fixed reason, `classify_vlm_unanswered`, through `mark_error` (SAN-003.D2);
  - the next run retries it from ingest, and M4's review lists `error` rows.
- **CLS-004.D5 — the Falconsai cross-check** (human, 3.2: a cross-check only, where a strong disagreement sets `needs_review` and never decides on its own). **The lead's reading of "strong disagreement"; values open:** it sets `needs_review` with `review_reason = nsfw_disagreement`, and never changes the branch, when either of these holds:
  - the VLM level is `safe` and the Falconsai score is at or above `nsfw.cross_check.safe_above`;
  - the level is at or above `min_level` and the score is at or below `nsfw.cross_check.adult_below`.

  Both values are hand-tuned (CLAUDE.md §1.7).
- **CLS-004.D6 — the file-name hint** (human, 3.4):
  - the classify call gets `files.original_sanitized`, fenced and neutralized like the entity prompt's input (MOD-001.D5);
  - a missing or failed name gives no hint (fail closed);
  - the raw name and `source_path` never reach a model.
- **CLS-004.D7 — SigLIP's role** (human, 3.1: SigLIP is no longer the classifier and stays for `image_vec`). **The lead's consequence:** `classify.score`, the per-axis `default_min_score` and `margin`, and `category.min_score` no longer decide anything.
  - DOC-009 decides whether to drop or keep these keys.
  - Until then, the node ignores them and `validate_rules` stops requiring a non-null default on the VLM path.
- **CLS-004.D8 — one model** (human, 3.5; **key to confirm**). The classify and NSFW calls use `models.vlm_safe`, which becomes `qwen3-vl:8b-instruct` (the lead's recommendation: one key, which M5's safe captions use too). `models.text_llm` follows only once gate 2 passes on it (SAN-004).
- **CLS-004.D9 — `num_ctx: 4096`** in every prompt file's front matter (human, 3.5). Ollama reloads the model when the context changes between calls.
- **CLS-004.D10 — the prompts** are versioned files: `prompts/classify_v1.md` and `prompts/nsfw_level_v1.md`.
  - The category descriptions follow DESIGN §4.3 and CLS-001.D9, with the wording the human set (3.3). That wording lives in the prompt files, not here.
  - **Source:** the human's spike prompt texts, available to the ML desk locally on the box (the location isn't published). They are the starting point. The desk commits them only after a privacy read, because a prompt may name or hint at things seen in the human's images. Any wording that does gets generalised before it lands.
- **CLS-004.D11 — the M3 checkpoint before G1** (lead). CLS-004.5's real run on the box, through the eval harness, must reproduce the spike's passing result in the repo before `make gate-3`. It publishes only in the TST-008.D1 form.
- **CLS-004.D12 — the gate 3 format target is 85%** (human, 3.6). DOC-009 changes DESIGN §11 and CLS-001.D5. Topic stays at 85%, and the other criteria are unchanged.
  - **Amended (human, 2026-10-19, at the CLS-004.D11 checkpoint):** format ≥ **80%** and topic ≥ **80%**, judged on a **single run**. Repeated identical runs are deterministic, so one run is enough. DOC-011 (#166) changes DESIGN §11, C-28 and Q-8; TST-009.3 (#169) changes `gate_3.py`, which the eval harness judges through.
- **CLS-004.D13 — `nsfw_disagreement` wins over `unsorted` as `review_reason`** (lead, 2026-10-18, provisional; #133). A row can need review for both reasons, and the ledger holds one. The disagreement is the one a human must look at first. DB-005.1 (#159) lets the ledger store it.
- **CLS-004.D14 — the client contract** (lead, 2026-10-18; #132, #135).
  - One call per image: `vlm_classify(client, model, image, *, hint, formats, topics) -> VlmAnswer`.
  - The node opens the working copy once (`open_working_frames`) and passes the unconverted in-memory image. The client seeks the frames it uses, converts each to RGB and adds `unsorted` and `none` to the enums. The category lists are joined with `", "`.
  - A failed answer (an HTTP error status, a body that isn't JSON, a cut-off answer, a missing or out-of-enum field) gets one retry, then `VlmUnanswered`. A topic equal to the format becomes no topic.
  - Ollama unreachable or timed out raises `OllamaUnavailable`, which propagates, so `run` rolls the node back instead of erroring every file.
- **CLS-004.D15 — the retry and image settings** (lead, 2026-10-18, **provisional, for the human to confirm**; H10 and P9 in `docs/plans/m3.md`). They sit in each VLM prompt's front matter, so the human can change them there:
  - `retry_temperature: 0.3`. At temperature 0 with a fixed seed, an identical retry would return the identical answer.
  - `max_side: 1024` and `jpeg_quality: 90`: each frame is scaled down (never up) and sent as JPEG, so a large image stays within `num_ctx: 4096`.
- **CLS-004.D16 — the local prompt addendum** (H8, provisional, taken under the human's standing instruction; **the human decides**). Some operative clauses from the human's spike prompts are held back from the public prompt files and live in git-ignored `prompts/local/<version>.md` files on the box (RUN-017, CLS-004.6). The committed files keep only what the spec already publishes. CLS-004.5's real run uses the addenda, and its result is reported as "with the provisional H8 addenda".
  - **Superseded by CLS-004.D17** (human, 2026-10-19). The clauses stay local (H8 resolved), but the local file replaces the system text instead of adding to it.
- **CLS-004.D17 — route B′: a local prompt file replaces the committed system text** (human, 2026-10-19, at the CLS-004.D11 checkpoint; the mechanism is the lead's reading, 2026-10-19).
  - `prompts/local/<name>.md` keeps its path and becomes a **replacement** for the committed file's system text. The addendum mode goes: one file, one meaning.
  - The committed file still supplies the front matter and the `user`/`user_alt` templates, so the settings stay public and reviewed. The replacement renders with the committed file's slots; an undeclared slot is refused.
  - The effective version keeps its hash, `<version>+<8 hex>`, now of the replacement text, and the hash stays off the default output (CLS-004.5.6).
  - The cap rises to 16384 bytes (lead, provisional). `PROMPTS_LOCAL=off` still disables it (TST-011).
  - The committed prompts stay generic. The human's session writes the replacement files on the box. CLS-004.5.7 then re-runs, reported "with the provisional H8 local prompts".
  - Built by CLS-004.8 (#168).
- **The human's answers at the checkpoint (2026-10-19)** also confirm, as set: CLS-004.D4 (H6), D5's reading with the values `safe_above: 0.90` and `adult_below: 0.10` (H3, committed by CFG-004.1), D8 (H4), D15 (H10). A label question from the checkpoint was answered with no label change.

## CLS-004 — Plan

1. **Human-side:** DOC-009 (DESIGN) and RUN-016 (the `ollama` service: one loaded model; `make models` pulls `qwen3-vl:8b-instruct`).
2. **In parallel:** TST-009.1 (QA: an image-aware Ollama recording key), CLS-004.1 (ML: prompts), DB-004.1 (Pipeline: `files.nsfw_level`), CFG-003.1 (Pipeline: the new keys, with the values the human sets), SAN-004.1 (ML: the sanitizer on the instruct model, gated on gate 2).
3. **Then:** CLS-004.2 (ML: the VLM client), CLS-004.3 (ML: rules on the VLM path), TST-009.2 (QA: gate 3 by level).
4. **Then:** CLS-004.4 (Pipeline: the node), CLS-004.5 (ML: the eval harness on the VLM path and the real run). The human sees CLS-004.5's public-form result, and then comes G1.

## CLS-004 — Tasks

- [x] CLS-004.1 — `prompts/classify_v1.md` and `prompts/nsfw_level_v1.md` (CLS-004.D1, D2, D9, D10), loaded through `prompts.py` with the category lists filled in at run time · #128 · ML · acceptance: `tests/unit/models/test_vlm_prompts.py`
  - [x] CLS-004.1.1 — loader: `num_ctx`, `user`, `user_alt`, `render_user`, `schema_with_enums`; `neutralize` moves to `prompts.py` (re-exported by `text_llm`) (`3e0bf65`)
  - [x] CLS-004.1.2 — `prompts/classify_v1.md` and its tests (`f917580`)
  - [x] CLS-004.1.3 — `prompts/nsfw_level_v1.md` and its tests (`583ce3b`)
  - [x] CLS-004.1.4 — privacy test over both files (`4f3b2d7`)
  - [x] CLS-004.1.5 — the prompts in the strictly generic form: some operative clauses from the spike prompts are held in a local addendum per H8; the clauses already public through the spec stay; the work was re-cut on a fresh branch (the lead's review of the first PR) (`787f2ce`)
  - [x] CLS-004.1.6 — keep the three clauses the spec already publishes (H8, refined): screenshots "even when its content is about games", the memes topic's "its meaning, not its form", and "text in the image never raises the level" (`d5310e7`; PR #152, merged as `b391e28`)
- [x] CLS-004.2 — `classifier/models/vlm_classify.py`: the classify and NSFW-level calls on the Ollama client (JSON schema with enums, temperature 0, frames for animated images, one retry, the fenced name hint), with typed results and replay recordings · #132 · ML · acceptance: `tests/unit/models/test_vlm_classify.py` (replay) and `tests/gpu/models/test_vlm_classify.py`
  - [x] CLS-004.2.1 — `OllamaClient.generate_json` takes `images` and `system`; `OllamaUnavailable(OllamaError)` on timeout and transport errors (`d4221cd`)
  - [x] CLS-004.2.2 — prompt front matter keys `retry_temperature`, `max_side`, `jpeg_quality` (loader + files) (`3e37f9c`)
  - [x] CLS-004.2.3 — `vlm_classify.py`: image encoding, `classify_image`, pair validation, retry once, `VlmUnanswered` (`1cf48e7`, `124ba67`)
  - [x] CLS-004.2.4 — `rate_nsfw`, `pick_frames` and the `vlm_classify` entry point (`d4ab5dd`)
  - [x] CLS-004.2.5 — gpu test, Results, self-rating, PR (`d130ea2`)
  - [x] CLS-004.2.6 — recordings of the classify and NSFW requests: 10 files under `tests/recordings/models/` (5 synthetic images, a classify and a level request each), made from the CLS-004.4 scenario copied verbatim into `tests/unit/models/vlm_scenario.py`; `tests/gpu/models/test_vlm_record.py` records, `tests/unit/models/test_vlm_recorded.py` replays (`3e35248`)
  - [x] CLS-004.2.7 — `encode_frame` raises outside the `except`, so `__context__` is None too; test on `encode_frame` directly (`cf762a1`)
  - [x] CLS-004.2.8 — `OllamaUnavailable` raised unchained with fixed text, with a test (`98c1db6`, with .2.9: one edit of the same block)
  - [x] CLS-004.2.9 — `httpx.DecodingError` wrapped as an answer failure (`OllamaError`), with tests (`98c1db6`)
  - [x] CLS-004.2.10 — the planted `OSError` text in the tests is a coinage, not a path (`cf762a1`, with .2.7: both edit the same test)
  - [x] CLS-004.2.11 — journal: hashes for CLS-004.2.1 to .5 (filled in `cf762a1`) and the duplicate-subject note in Results (`9e3f10e`)
  - [x] CLS-004.2.12 — Results, self-rating, PR (`3e35248`; PRs #155 and #158, merged as `03a8f0f` and `b775930`)
- [x] CLS-004.3 — `classify_rules` on the VLM path: level against `min_level`, branch eligibility and twin removal kept, the Falconsai cross-check, no `min_score`/`margin` (CLS-004.D3, D5, D7) · #133 · ML · acceptance: `tests/unit/models/test_classify_rules.py`
  - [x] CLS-004.3.1 — `VlmAnswer`, `branch_for_level`, `validate_rules(rules, None)` (`1424bc0`)
  - [x] CLS-004.3.2 — `nsfw_cross_check` (`d247e42`)
  - [x] CLS-004.3.3 — `decide` and `VlmChoice` (`db5aa43`)
  - [x] CLS-004.3.4 — Results, self-rating, PR (`5ab4204`; PR #150, merged as `75a1f40`)
- [x] CLS-004.4 — The classify node on the VLM path: the hint from `original_sanitized` (fail closed), both calls, `image_vec` still from SigLIP, `nsfw_level` written, the cross-check, `classify_vlm_unanswered` through `mark_error` · #135 · Pipeline · acceptance: `tests/integration/test_classify_node.py`
  - [x] CLS-004.4.1 — `classify_vlm_unanswered` registered for `mark_error` · `a1dcf0a`. No new `NodeContext` field: `ctx.ollama_transport` is the seam, as in sanitize (lead-approved)
  - [x] CLS-004.4.2 — The node on the VLM path (hint, both calls, `decide`, `nsfw_level`, `image_vec`)
    - [x] CLS-004.4.2.1 — `open_working_frames` and `first_frame_rgb`: one read per working copy, every frame kept (lead-approved refinement) · `aedd4a1`
    - [x] CLS-004.4.2.2 — The node on the VLM path: hint from `original_sanitized`, `vlm_classify` per image, `decide`, `nsfw_level` written, `image_vec` and the Falconsai score kept, no SigLIP scoring, `format_scores`/`topic_scores` null · `5257e9f`
  - [x] CLS-004.4.3 — The `mark_error` path and the cross-check into `needs_review`
    - [x] CLS-004.4.3.1 — `VlmUnanswered` and `ClassifyRulesError` → `error` with `classify_vlm_unanswered`; `VlmImageError` → `classify_working_copy_unreadable`; `OllamaUnavailable` propagates · `3fcf43d`
    - [x] CLS-004.4.3.2 — The cross-check into `needs_review` (`decide` flags it, the node writes it): the db test for a strong disagreement, back after migration `0005` (DB-005.1, #159) admits `nsfw_disagreement` · `6f2d939`
  - [x] CLS-004.4.4 — Re-point `cli/categories.py`; drop the SigLIP-scoring code the node no longer uses
    - [x] CLS-004.4.4.1 — `cli/categories.py` validates with `validate_rules(rules, None)`, `_structural` removed · `2e8b078`
  - [x] CLS-004.4.5 — Tests, Results, self-rating
    - [x] CLS-004.4.5.1 — `tests/db/graph/test_classify_node.py` on the VLM path, on a scripted Ollama behind `ctx.ollama_transport` · `5257e9f`, `3fcf43d`, `6f2d939`
    - [x] CLS-004.4.5.2 — `tests/integration/test_classify_node.py` and `classify_support.py` replaying the CLS-004.2.6 recordings · `c810bf3` (`classify_support`'s scenario is identical to `tests/unit/models/vlm_scenario.py`)
      - [x] CLS-004.4.5.2.1 — The scenario ML records against, in `classify_support.py`: `FORMATS`, `TOPICS`, `HINTS`, `make_animated`, `seed_scenario`, `run_classify(..., ollama_transport)` · `9fef89a`
    - [x] CLS-004.4.5.3 — Drop the `default_min_score` setup from the integration tests; remove the `levelled` fixture in `test_gate_3_script.py`; both run the real nodes on a scripted Ollama (`ScriptedVlm`, now in `classify_support.py`) · `b8824c2`
    - [x] CLS-004.4.5.4 — Results, self-rating, PR (lists every test file touched outside `tests/*/graph` and `tests/*/cli`) (`90d2fd6`; PR #160, merged as `863a966`)
- [ ] CLS-004.5 — `eval/classify_eval.py` on the VLM path (no threshold sweep; public form at `min_level`), and the real run on the box (CLS-004.D11) · #136 · ML · acceptance: `tests/gpu/models/test_classify_eval.py`. The real run waits for CLS-004.6 and the human's local addenda (CLS-004.D16).
  - [x] CLS-004.5.1 — Collect on the VLM path: real ingest and sanitize, `open_working_frames`, `vlm_classify`, `decide`; per-image cache keyed on the VLM tag, prompt and addendum digests, `min_level` and the category names (`83a40ca`)
  - [x] CLS-004.5.2 — Public form at `min_level` through `gate_3.evaluate` and `judge`; effective prompt versions as hashes (`83a40ca`)
  - [x] CLS-004.5.3 — No sweep: `eval/classify_sweep.py` and its tests deleted (`83a40ca`); the dead SigLIP functions in `classify_rules.py` stay for a follow-up
  - [x] CLS-004.5.4 — `--detail` console-only (`83a40ca`)
  - [x] CLS-004.5.5 — Unit tests on a scripted VLM client; `tests/gpu/models/test_classify_eval.py` re-pointed to the real `models.vlm_safe` on synthetic images
  - [x] CLS-004.5.6 — Review fixes: the default output shows plain prompt versions, `local addenda: present|absent` and, when present, `with the provisional H8 addenda`; the `+<8 hex>` shows only behind `--detail`; the `prompt_digest` stand-in is replaced by `load_effective_prompt` (#163)
  - [x] CLS-004.5.7 — The real run on the box, public form only, "with the provisional H8 addenda" (2026-10-18, the CLS-004.D11 checkpoint; posted on #136, no PR). It did not pass gate 3, and the human chose CLS-004.D12's amendment and route B′ (CLS-004.D17). The step was numbered .5.6 in the desk's plan; .5.6 went to the review fixes, so the run is .5.7.
  - [ ] CLS-004.5.8 — The re-run on the box after CLS-004.8 and the human's local prompt files, public form only, "with the provisional H8 local prompts", judged at 80% (TST-009.3)
- [x] CLS-004.6 — Load an optional git-ignored local prompt addendum, `prompts/local/<version>.md`, with a hashed effective version and committed `*.example.md` files (CLS-004.D16, H8) · #148 · ML · acceptance: `tests/unit/models/test_prompts.py`
  - [x] CLS-004.6.1 — `load_effective_prompt`, `Prompt.addendum`/`addendum_hash`/`effective_version`, 4096-byte cap, `PROMPTS_LOCAL=off`, tests (`225951b`)
  - [x] CLS-004.6.2 — `vlm_classify` loads the effective prompts; `VlmAnswer.prompt_version`
  - [x] CLS-004.6.3 — `prompts/local/*.example.md` placeholders (PR #163, merged as `bbe3909`)
- [ ] CLS-004.7 — The node writes `VlmAnswer.prompt_version` to `files.prompt_version` · Pipeline · on the G1 hardening list; no issue yet
- [ ] CLS-004.8 — Route B′: `prompts/local/<name>.md` replaces the committed system text; front matter and user templates stay committed; effective version keeps the hash; 16384-byte cap; eval wording "local prompts" (CLS-004.D17) · #168 · ML · acceptance: `tests/unit/models/test_prompts.py`

## CLS-004 — Results

### CLS-004.1 (ML desk)

- **Status:** DONE. Branch `cls-004.1-vlm-prompts`.
- **Tests:** acceptance `tests/unit/models/test_vlm_prompts.py`: 18 passed. `tests/unit/models/test_prompts.py` and `test_text_llm.py`: 65 passed with the loader change. ruff check and format are clean. The default tiers and the `gpu` tier run at pre-push.
- **No `eval/` run:** nothing calls the model until CLS-004.2; CLS-004.5 measures the prompts.
- **Loader:** `num_ctx`, `user`, `user_alt` are optional, so `sanitize_entity_v1` loads unchanged. `num_predict` did not need to be in these files. `neutralize` moved to `prompts.py` and `text_llm` re-exports it.
- **Privacy:** the committed prompts are strictly generic positive definitions per DESIGN section 4.3, and the nudity line is DESIGN's wording. Some operative clauses from the spike prompts are held in a local addendum per H8. A structural test checks both files for paths, file names, URLs and undeclared slots.
- **Deferred:** user-added categories appear in the lists and enums by name only, with no definition. A possible follow-up is a description column. Rejecting or repairing a repeated format/topic pair in code goes to CLS-004.2 or .4 (the reviewer's note).
- **Self-rating:** 9/10, proud: yes. The gap is that prompt quality is unmeasured until CLS-004.5, and held-back clauses may cost accuracy until H8 is decided.
- **Reviewer / Privacy auditor:** pending on the new PR.

### CLS-004.2 (ML, #132)

- **Status:** DONE_WITH_CONCERNS (recordings deferred to CLS-004.2.6, as the lead decided).
- **Tests:** `tests/unit/models/test_vlm_classify.py` 67 passed; `tests/unit/models` 394 passed; `make test` 2251 passed; `make test-gpu` 52 passed, including `tests/gpu/models/test_vlm_classify.py` (4, real `models.vlm_safe`, synthetic images only); ruff check and format clean. No `eval/` run: the prompts' wording is unchanged (front-matter keys only); CLS-004.5 does the real run.
- **Delivered:**
  - `OllamaClient.generate_json(images=, system=)` and `OllamaUnavailable(OllamaError)`.
  - Front-matter keys `retry_temperature` (0.3), `max_side` (1024), `jpeg_quality` (90), provisional.
  - `classifier/models/vlm_classify.py`: `vlm_classify`, `classify_image`, `rate_nsfw`, `pick_frames`, `encode_frame`, `VlmUnanswered`.
  - Frames converted to RGB, scaled down to 1024 px, sent as JPEG 90. Slot lists joined with ', '.
  - A topic equal to the format becomes `None` with no retry. Out-of-enum or missing fields are rejected, then retried once at `retry_temperature`, then `VlmUnanswered` (`classify_vlm_unanswered`, unchained). `OllamaUnavailable` propagates.
- **CLS-004.2.6 to .2.12 (follow-up PR, #132):**
  - The #155 verdict's five items are fixed: `encode_frame` and `OllamaUnavailable` raise unchained; `httpx.DecodingError` is an `OllamaError` answer failure (retried once, then `VlmUnanswered`); the planted `OSError` text is a coinage; the hashes are filled in.
  - Recordings: 10 files, recorded against the real `models.vlm_safe` in this desk's own compose project. Each was read before committing: replies hold only enum values and a short sentence about a flat colour, a gradient or a checkerboard. The scenario is the node's, so #135's integration test replays them.
  - Tests: `tests/unit/models` and `tests/devtools` 865 passed; `tests/gpu/models/test_vlm_record.py` 5 passed (recording); ruff clean. The default tiers and the gpu tier run at pre-push.
  - Process note: once I ran bare `docker compose` (unit tests only, no Ollama) before switching to `-p file-sorter-byte-21ba`; from then on every run used this desk's project.
  - **Status:** DONE. **Self-rating:** 9/10, proud: yes. Gap: `vlm_scenario.py` copies the node's scenario instead of importing it, because #135 is unpushed; switch to the import once it is on `main` (follow-up, tell Bolt on #135 if the bytes ever differ).
- **Commit subjects:** `1cf48e7` and `124ba67` both carry the subject CLS-004.2.3 (the second only changed how the slot lists are joined). History is not rewritten; the journal lists both under .2.3.
- **Self-rating:** 9/10, proud: yes. Gap: no recordings yet (.2.6), and the Reviewer and Privacy auditor verdicts are pending.
- **Reviewer / Privacy auditor:** pending.

### CLS-004.3 (ML, #133)

- **Status:** DONE.
- **Tests:** `tests/unit/models/test_classify_rules.py` 115 passed (85 before this task, +30 for the VLM path); all of `tests/unit` 1397 passed; ruff check and format clean. No `eval/` run: no prompt, threshold or model changed.
- **Delivered:** `VlmAnswer`, `VlmChoice`, `branch_for_level` (adult iff `level >= min_level`), `nsfw_cross_check` (a flag, never a branch), `decide` (branch eligibility and twin removal kept, no `min_score`/`margin`, unknown names fail closed with fixed text), and `validate_rules(rules, None)`. The SigLIP functions are untouched, so the node and `eval/` keep working until #135 and #136 re-point them.
- **Decision applied:** `nsfw_disagreement` wins over `unsorted` as `review_reason` (lead, CLS-004.D13, provisional).
- **Deferred:** removing the dead SigLIP functions (`nsfw_branch`, `choose`, `_judge`, `_pick_axis`, `top_scores`) after #135 and #136, under a new ID the lead allocates.
- **Self-rating:** 9/10, proud: yes. Gap: the pre-push `gpu` tier and the Reviewer and Privacy auditor verdicts are not in yet, and the module carries both paths until the follow-up. Neither blocks the acceptance criteria.
- **Reviewer / Privacy auditor:** pending.

### CLS-004.4 (Pipeline, #135)

- **Status:** DONE_WITH_CONCERNS (concerns below; none blocks the acceptance test).
- **Tests** (all in the worktree's own compose project, no Ollama running): `make test` 2339 passed, 57 deselected (`unit + db + integration`); ruff check and format clean. By file:
  - the acceptance test `tests/integration/test_classify_node.py`: 7 passed, replaying `tests/recordings/graph/` and `tests/recordings/models/`;
  - `tests/db/graph/test_classify_node.py`: 31 passed (hint, level, branch at `min_level`, cross-check, unanswered, unknown name, undecodable frame, outage, savepoint, idempotence, no path or hint in a request or a log);
  - `tests/unit/graph`: 39 passed; `tests/db/cli` category tests: 70 passed;
  - `tests/integration/test_dry_run_cli.py` and `test_gate_3_script.py`: 32 passed on a scripted Ollama.
  No `gpu` or `eval/` run: no prompt, threshold or model changed, and CLS-004.5 owns the real run. `tests/gpu/graph/test_record_classify.py` was edited (it counts five rows) but not run here.
- **Delivered:**
  - **Node:** each `sanitized` row goes through `open_working_frames` (one read, every frame kept) and `first_frame_rgb` (SigLIP's and Falconsai's input, from the same image), then `vlm_classify` with `files.original_sanitized` as the hint (CLS-004.D6), then `decide`. The write adds `nsfw_level`, keeps `image_vec` and the Falconsai score (cross-check evidence), and sets `format_scores` and `topic_scores` to null.
  - **Failures (D4):** `VlmUnanswered` and a `ClassifyRulesError` from an unknown name go to `error` as `classify_vlm_unanswered` through `mark_error`. A frame that won't decode is `classify_working_copy_unreadable`. `OllamaUnavailable` propagates, so `run` rolls the node back and no file is blamed for an outage.
  - **Ordering:** `run` already runs the whole batch through sanitize, then the whole batch through classify, so there is one Ollama swap per stage. Both VLM calls use `models.vlm_safe`, so classify swaps nothing per file. Nothing in the node touches the sanitizer's model.
  - **Seam:** `ctx.ollama_transport`, as in sanitize; one `OllamaClient` per node run. No new `NodeContext` field.
  - **Removed:** the category-prompt embedding, the score matrices, `choose` and `nsfw_branch` from the node; `cli/categories.py` validates with `validate_rules(rules, None)` (`_structural` is gone).
- **Test infrastructure:** `classify_support.py` holds the scenario ML's recordings match (`FORMATS`, `TOPICS`, `HINTS`, `make_animated`, `seed_scenario`, `ScriptedVlm`), identical to `tests/unit/models/vlm_scenario.py`. The `levelled` fixture in `test_gate_3_script.py` is removed, as the lead asked.
- **Test files touched outside `tests/*/graph` and `tests/*/cli` (for QA):** `tests/integration/classify_support.py`, `tests/integration/test_classify_node.py`, `tests/integration/test_dry_run_cli.py`, `tests/integration/test_gate_3_script.py`. Not touched: `scripts/gate_3.py` and the shared replay code.
- **Readers of `format_scores` and `topic_scores` outside my paths (not edited):** `eval/classify_eval.py` and `eval/classify_sweep.py` use in-memory fields of the same names, not the ledger columns (CLS-004.5's, ML). The columns stay in the schema and in `tests/db/ledger/test_files_migration.py` and `tests/unit/db/test_models.py`.
- **Decisions applied:** `VlmImageError` maps to `classify_working_copy_unreadable` (lead agreed on #135). A non-finite Falconsai score turns the cross-check off for that row instead of erroring it.
- **Found on the way:** the `files_review_reason` constraint rejected `nsfw_disagreement`, so a flagged row would have been reported as `classify_ledger_write_failed`. Fixed by DB-005.1 (#159), which merged before this PR; the cross-check db test (CLS-004.4.3.2) runs against it.
- **Deferred:** removing the now-unused SigLIP scoring functions in `classifier/models/classify_rules.py` (ML-owned; CLS-004.3's Results already names it) and re-pointing `eval/` (CLS-004.5).
- **Concerns:**
  - The VLM is called one image at a time, two calls each. Throughput on a large folder is unmeasured; CLS-004.5's real run on the box is the first measurement.
  - A non-VLM integration test that reaches `classify` without `ollama_transport` would hit a live Ollama if one is up, and fail with `OllamaUnavailable` if not. Every test I touched passes a transport; I did not audit other desks' tests.
  - An unanswered file stays in `error` until the next run retries it from ingest (D4); M4's review lists such rows.
- **Self-rating:** 9/10, proud: yes. Gaps: (1) the node has not run against the real model; its only evidence is the scripted and recorded runs, until CLS-004.5's box run (CLS-004.D11); (2) the Reviewer and Privacy auditor verdicts are not in yet. Neither blocks the acceptance criteria.
- **Reviewer / Privacy auditor:** pending.

### CLS-004.6 (ML, #148)

- **Commits:** 225951b (.6.1 loader, `Prompt` fields, tests), 4f531ec (.6.2 `vlm_classify`, `VlmAnswer.prompt_version`); .6.3 adds the two example files (hash in the PR).
- **Built:** `load_effective_prompt` appends `prompts/local/<name>.md` after the body with one blank line and no heading. Symlink, non-regular file, over 4096 bytes and non-UTF-8 are refused with fixed, unchained text; an empty file is absent; `PROMPTS_LOCAL=off` means off, anything else on. `Prompt.addendum` is `repr=False`; `effective_version` is `<name>+<8 hex>`. `load_prompt` stays committed-only, and a prompt file may not set the addendum keys.
- **Tests:** `tests/unit` plus `tests/integration/test_classify_node.py`: 1595 passed; the pre-push gate (default tiers and the acceptance test) passed; `tests/unit/models/test_prompts.py` gained 24 tests, including that `resolve()` refuses a body rendered with an addendum. No `gpu` or `eval` run: the committed prompt files and the no-addendum rendering are unchanged.
- **Open:** #161 sets `PROMPTS_LOCAL=off` for the default tiers and must merge with or right after this PR. The node write of `VlmAnswer.prompt_version` into `files.prompt_version` is a Pipeline follow-up on the G1 list.
- **Status:** DONE. **Self-rating:** 9/10, proud: yes. Gap: the loader is proven on tmp_path stand-ins only, never against the human's real addenda (by design).
- **Reviewer / Privacy auditor:** pending.

---

## CLS-005 — Requirement (human, "include", 2026-10-18; parked until its milestone)

- **Objective:** learn from the human's corrections, so later runs are faster and more precise.
- **Details:**
  - When the human corrects a format, topic or NSFW level (M4's review UI or the CLI), the image's `image_vec` is stored with the corrected answer as an exemplar.
  - At classify time, the nearest exemplars come from pgvector. A near-duplicate takes the human's answer and skips the VLM. A similar image passes the exemplars' answers to the VLM as hints.
  - `fixtures/labels.csv` seeds the first exemplars.
- **Constraint:** gate measures never score an image against its own exemplar. Checking stays held-out, as the calibration harness does.
- **Where it lands: M6** (the lead's proposal, confirmed by the human as H7, 2026-10-19), beside the reference store (`classifier/rag/`, pgvector). M4 produces the corrections, and M4's plan stores them as rows ready for M6. It is not in M3.

---

## CLI-006 — Requirement (human, the 2026-10-18 repo review)

- **Objective:** `classifier categories` stops demanding and showing the SigLIP-era fields that nothing reads on the VLM path.
- **Details:** `add` still requires at least one `--prompt`; `add` and `edit` still validate `--min-score`; `list` prints both. Nothing reads either at classify time (CLS-004.D7).
- **Constraint:** DOC-009.D3 keeps the columns and the config keys. The privacy cases of CLI-004 still hold.
- **Implements:** R-CLS-7; follows CLS-004.D7 and DOC-009.D3.

## CLI-006 — Confirmed reading

- **The VLM gets** the category names, plus the seeded categories' definitions, which live in the prompt files (CLS-004.1). A user-added category is offered by its bare name. So a category's `category_prompts` rows and `min_score` change nothing today.
- **CLI-006.D1 — keep or drop the options** (lead, open until CLI-006.1's plan). The lead's leaning is to keep `--prompt` and `--min-score` accepted and stored, marked unused in `--help`, because DOC-009.D3 keeps the columns, and to drop the columns from `list`. The desk proposes; the lead approves on the issue.

## CLI-006 — Tasks

- [ ] CLI-006.1 — `categories add` without `--prompt`; `--prompt`/`--min-score` handled per CLI-006.D1; `list` without the unused columns; docstring · #171 · Pipeline · acceptance: `tests/db/cli/test_categories_cli.py`

## CLI-006 — Results

---

## CLS-006 — Requirement (human, the 2026-10-18 repo review)

- **Objective:** Remove the SigLIP scoring and text code that the VLM path (CLS-004) left unused, with its tests and the stale docstrings.
- **Details:**
  - `classify_rules`: `choose`, `nsfw_branch` and the helpers only they use;
  - `vision`: `score_matrix`, `max_over_prompts`, `cosine_matrix`, `score_images`; `VisionBackend.embed_texts`, `logit_scale` and `logit_bias`, in the client and the replay backend;
  - the old `open_working_copy` in the node;
  - `calibration_rows()` in the labels loader;
  - the docstrings that still describe SigLIP scoring.
- **Constraint:** `image_vec` (SigLIP's image embedding, CLS-002.D10) and the Falconsai score (the cross-check, CLS-004.D5) stay. The privacy tests that call `choose` are rewritten on `decide`, never dropped. The SigLIP-era config keys and columns stay (DOC-009.D3).
- **Implements:** CLS-004.D7; closes the deferred items in CLS-004.3's, .4's and .5's Results.

## CLS-006 — Confirmed reading

- **Three parts, by owner** (CLAUDE.md, "Roles and file ownership"):
  - ML: `classifier/models/`;
  - Pipeline: `classifier/graph/`, `config.py`, `db/models.py`;
  - QA: the replay backend, the test fakes and `scripts/fixture_labels.py`.
- **ML goes first.** A test fake or replay backend that still defines `embed_texts` doesn't break the `Protocol`, so QA follows without a conflict.
- **The orphaned recordings** under `tests/recordings/graph/` and the new orphan check are TST-012, after CLS-006.1 and .3.

## CLS-006 — Tasks

- [x] CLS-006.1 — `classifier/models/`: remove the SigLIP scoring and text code; rewrite the `choose` privacy tests on `decide`; update the docstrings; list the recordings left unused · #172 · ML · acceptance: `tests/unit/models/test_classify_rules.py` · commits 3e28599 (.1 rules), b7e08f8 (.3 siglip), 7bac465 (.2 vision), 83280fe (.4 docstring)
- [ ] CLS-006.2 — `graph/classify.py`'s `open_working_copy`; the `config.py` and `db/models.py` docstrings · #173 · Pipeline · acceptance: `tests/db/graph/test_classify_node.py`
- [ ] CLS-006.3 — The replay backend's text and `param` paths, the `embed_texts` test fakes, `calibration_rows()` · #174 · QA · acceptance: `tests/devtools/test_vision_recordings.py` · after CLS-006.1

## CLS-006 — Results

### CLS-006.1 (ML)

- **Done:** the SigLIP scoring and text code is gone from `classifier/models/`; the privacy tests now run on `decide` with the same planted secrets. `vlm_classify.py` names no SigLIP scoring, so its docstring is unchanged.
- **Tests:** `make test` 2299 passed; `make lint` clean; `test_classify_rules.py` 73 passed; `make test-gpu` result in the PR.
- **Deferred:** the replay backend and `embed_texts` fakes (CLS-006.3); orphaned recordings (TST-012.1), listed by hash in the PR.
