# Categories — journal

**ID:** CLS-001 (+ CLS-002, CLS-003, FOP-002, CLI-004) · **Systems:** CLS (+ NAME, FOP, DB, API, TST, MOD, CLI) · **Type:** feature · **Status:** CLS-001 design done; its build (CLS-002, CLS-003, FOP-002, CLI-004) proposed for M3 ·
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
  
  (human, 2026-10-05)
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
- **CLS-001.D12:** **Adult means explicit sexual imagery.** Suggestive images without it stay `adult = no`. Such rows are deliberate negative tests, tagged `suggestive-negative`, and none may be flagged (R-CLS-1). (human, 2026-10-05)
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

- [ ] CLS-003.1 — `eval/classify_eval.py`: score the sanitized labelled fixtures once, sweep the thresholds, report per CLS-001.D5 with a held-out estimate · #101 · acceptance: `tests/gpu/models/test_classify_eval.py`
  - [x] CLS-003.1.1 — `eval/classify_sweep.py`: the pure sweep, overrides and 5-fold check, with unit tests (17176ee)
  - [x] CLS-003.1.2 — scoring: `SiglipBackend` scores of the working copies, the score cache, the label join (1f821d7)
  - [x] CLS-003.1.3 — `eval/classify_eval.py`: the throwaway-db run, the CLI, the public and `--detail` report, the proposal printout (a7ba20e)
  - [x] CLS-003.1.4 — the `gpu` acceptance test, the real-fixture run, Results (hash in the PR)
  - [x] CLS-003.1.5 — rule out a bug on the box: the NSFW label index, the sanitized working copy as input, exact coverage; each `ok`/`FAIL` (#101, lead's comment)
  - [x] CLS-003.1.6 — box-only NSFW block in `--detail`, and `--hold-nsfw-threshold` (sweep side 3eff259; the CLI side and the report in the CLS-003.1.5 commit)
  - [x] CLS-003.1.7 — `tests/gpu/models/test_siglip_reference.py`: SigLIP known-answer and reference-agreement cross-check; result `ok`, no fix needed (#101, lead's comment)
  - [x] CLS-003.1.8 — review fixes: the infeasible suggestive-negative verdict, a real `nsfw input` check, repr tests for `Checks`/`RunInfo`/`NsfwDiagnostic`, Results brought current (#120 review)
- ~~CLS-003.2~~ dropped (lead, 2026-10-18): superseded by CLS-004. The human replaced SigLIP threshold calibration with a VLM classifier, so there are no SigLIP thresholds to commit. #102 is closed as not planned once the re-plan is approved. The settings the VLM path needs land in CFG-003.1.

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

## CLS-004 — Plan

1. **Human-side:** DOC-009 (DESIGN) and RUN-016 (the `ollama` service: one loaded model; `make models` pulls `qwen3-vl:8b-instruct`).
2. **In parallel:** TST-009.1 (QA: an image-aware Ollama recording key), CLS-004.1 (ML: prompts), DB-004.1 (Pipeline: `files.nsfw_level`), CFG-003.1 (Pipeline: the new keys, with the values the human sets), SAN-004.1 (ML: the sanitizer on the instruct model, gated on gate 2).
3. **Then:** CLS-004.2 (ML: the VLM client), CLS-004.3 (ML: rules on the VLM path), TST-009.2 (QA: gate 3 by level).
4. **Then:** CLS-004.4 (Pipeline: the node), CLS-004.5 (ML: the eval harness on the VLM path and the real run). The human sees CLS-004.5's public-form result, and then comes G1.

## CLS-004 — Tasks

- [ ] CLS-004.1 — `prompts/classify_v1.md` and `prompts/nsfw_level_v1.md` (CLS-004.D1, D2, D9, D10), loaded through `prompts.py` with the category lists filled in at run time · #128 · ML · acceptance: `tests/unit/models/test_vlm_prompts.py`
- [ ] CLS-004.2 — `classifier/models/vlm_classify.py`: the classify and NSFW-level calls on the Ollama client (JSON schema with enums, temperature 0, frames for animated images, one retry, the fenced name hint), with typed results and replay recordings · #132 · ML · acceptance: `tests/unit/models/test_vlm_classify.py` (replay) and `tests/gpu/models/test_vlm_classify.py`
- [ ] CLS-004.3 — `classify_rules` on the VLM path: level against `min_level`, branch eligibility and twin removal kept, the Falconsai cross-check, no `min_score`/`margin` (CLS-004.D3, D5, D7) · #133 · ML · acceptance: `tests/unit/models/test_classify_rules.py`
  - [x] CLS-004.3.1 — `VlmAnswer`, `branch_for_level`, `validate_rules(rules, None)` (this commit)
  - [ ] CLS-004.3.2 — `nsfw_cross_check`
  - [ ] CLS-004.3.3 — `decide` and `VlmChoice`
  - [ ] CLS-004.3.4 — Results, self-rating, PR
- [ ] CLS-004.4 — The classify node on the VLM path: the hint from `original_sanitized` (fail closed), both calls, `image_vec` still from SigLIP, `nsfw_level` written, the cross-check, `classify_vlm_unanswered` through `mark_error` · #135 · Pipeline · acceptance: `tests/integration/test_classify_node.py`
- [ ] CLS-004.5 — `eval/classify_eval.py` on the VLM path (no threshold sweep; public form at `min_level`), and the real run on the box (CLS-004.D11) · #136 · ML · acceptance: `tests/gpu/models/test_classify_eval.py`

## CLS-004 — Results

---

## CLS-005 — Requirement (human, "include", 2026-10-18; parked until its milestone)

- **Objective:** learn from the human's corrections, so later runs are faster and more precise.
- **Details:**
  - When the human corrects a format, topic or NSFW level (M4's review UI or the CLI), the image's `image_vec` is stored with the corrected answer as an exemplar.
  - At classify time, the nearest exemplars come from pgvector. A near-duplicate takes the human's answer and skips the VLM. A similar image passes the exemplars' answers to the VLM as hints.
  - `fixtures/labels.csv` seeds the first exemplars.
- **Constraint:** gate measures never score an image against its own exemplar. Checking stays held-out, as the calibration harness does.
- **Lead's proposal for where it lands (to confirm):** M6, beside the reference store (`classifier/rag/`, pgvector). M4 produces the corrections, and M4's plan stores them as rows ready for M6. It is not in M3.
