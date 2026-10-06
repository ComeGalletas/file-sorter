# DESIGN.md — Image Classification Bot (MVP)

Status: **confirmed** — every §13 change reviewed by the human on 2026-10-05; §14 open questions remain · Oct 5, 2026 · @JP
Source: `docs/PLAN.md`, a copy of `Design Plan — Image Classification Bot (MVP).md`. The original is archived at the workspace root, `file-sorter-full\`.

**How to use this file.** `docs/PLAN.md` is the narrative and rationale. This file is the normative spec: what to build, in what order, and how it is tested. Requirement IDs (`R-SAN-3`) are cited in issues, plans and acceptance tests. Where this file and the plan disagree, this file wins **once its status line says `confirmed`**; every deviation is listed in §13.

---

## 1. Goal and scope

A local bot on the RTX 5080 box watches one images folder. For each image it:

1. sanitizes sensitive values;
2. classifies the image into a **format** (required) and a **topic** (optional) from configurable lists, with adult content mirrored under `Adult/`;
3. names the file from its content and, where possible, a resolved reference;
4. copies the result into a `<Topic>/<Format>/` folder.

The source folder is **read-only**: the bot never moves, modifies or deletes an original. Everything it produces goes to a separate **results** folder.

**In scope (MVP):** jpg, jpeg, png, webp, gif, bmp, heic, tiff; the CLI; a local status UI; Postgres ledger; pgvector reference store; Docker Compose runtime.
**Target folder profile (Oct 2026).**

- About 150 images in one flat folder (mostly png, then jpg/jpeg and gif, one webp), plus a few non-image files (audio, `desktop.ini`).
- Many of the images are screenshots or Snipping Tool captures.
- Fewer than 5 are adult images.
- Source and results are sibling folders on the same Windows drive, bind-mounted into Docker Desktop containers.
- Real paths live only in the git-ignored `.env`.

**Out of scope (MVP):** other file types (separate plan after M6 is stable on the real folder), pixel blurring, reverse image search, UI auth, UI deletion, network exposure beyond `127.0.0.1`.

## 2. Principles (non-negotiable)

| ID | Principle |
| --- | --- |
| P-1 | **Non-destructive, read-only source.** No sorting step ever writes to, moves, modifies or deletes anything in `source_root`; it is mounted read-only. Sorted copies are written to `results_root`. Deletion exists only as `purge-sources` and `delete`, which are separate, explicit CLI commands, **disabled by default** (`deletion.enabled: false`). |
| P-2 | **Sanitize first.** No classification, captioning or naming model sees unredacted metadata or filenames. |
| P-3 | **Local first.** No egress by default except SearXNG (outbound search) and model pulls. Every remote backend is opt-in by config. |
| P-4 | **Idempotent and resumable.** The ledger is the checkpoint. A known hash is skipped, and a crash resumes from the last recorded status. |
| P-5 | **Config over code.** Categories, prompts, templates and rules are editable from the CLI or YAML without a code change. |
| P-6 | **Unrecognized is an outcome, not a guess.** A format below threshold → `Unsorted/`, flagged for review. A topic below threshold → no topic (`General/<Format>/`). |
| P-7 | **Adult content is first-class.** It uses the same formats and topics, mirrored under `Adult/`, with models that do not refuse. |

## 3. Pipeline — execution order

The plan numbers stages by topic. **Execution order differs:** naming consumes `{reference}`, so retrieval runs before naming.

```
ingest → sanitize → classify (embed + NSFW gate + score) → caption → retrieve → name → fileops
```

| Node | Plan stage | Writes |
| --- | --- | --- |
| `ingest` | — | hash, source path, mtime, ext, `animated` flag, thumbnail; skip known hashes and non-images |
| `sanitize` | 1 | sanitized working copy, sanitized original name, `sanitize_log` |
| `classify` | 2 | SigLIP vector, NSFW score, branch, format and topic scores, chosen format (or unsorted) and topic (or none) |
| `caption` | 3 (input) | subject, detail, caption, tags (safe or adult VLM by branch) |
| `retrieve` | 4 | reference id / name, verdict, `retrieval_log` |
| `name` | 3 | rendered filename |
| `fileops` | 5 | result file in `results_root`, final status |

**Batching (R-PIPE-1).** Nodes run as **per-stage batches**, not per-file: embed and gate the whole batch, then caption the safe batch with the safe VLM, then the adult batch with the adult VLM, then judge with the text LLM. The ledger `status` after each node is the checkpoint, and a resumed run selects files by status. Only `fileops` is a per-file transaction.

**Dry run (R-PIPE-2).** `dry-run` runs every node except `fileops`. It ends at status `proposed` and writes `source → proposed output` to CSV and to the ledger, so the UI can review it. **Milestones M3–M6 operate in dry-run only. Before M7, `results_root` holds only empty category folders from `sync-folders`, plus `.work/` and `reports/`; no image is written there.**

## 4. Functional requirements

### 4.1 Ingest

- **R-ING-1** Hash: SHA-256 of the source bytes. This `source_hash` is the dedup key. `short_hash` = its first 8 hex chars.
- **R-ING-2** A `source_hash` already in the ledger (any status except `error`) is skipped with no side effects.
- **R-ING-3** A non-image or unreadable file → status `skipped` with a reason. It stays untouched in the source folder.
- **R-ING-8** OS metadata files (`desktop.ini`, `Thumbs.db`, `.DS_Store`) are ignored silently: no ledger row, no log line.
- **R-ING-7** The same `source_hash` at a second path is not re-processed; the extra path is appended to `files.duplicate_paths`.
- **R-ING-4** Capture source mtime at ingest. It is the fallback for `{date}` and `{time}`.
- **R-ING-5** Generate a 256 px thumbnail from the **sanitized** copy into `.work/thumbs/<short_hash>.webp`. The UI never reads originals.
- **R-ING-6** GIF: use the first frame. TIFF: use the first page. HEIC: decode via `pillow-heif`.
- **R-ING-9** `animated` is **derived, never classified** (CLS-001.D3). It is `true` when the file has more than one frame (GIF, WebP, APNG; Pillow `is_animated`). It feeds the `{animated}` token and the optional `Animated/` subfolder.

### 4.2 Sanitize (`sanitize.yaml`)

- **R-SAN-1** Runs on the working copy in `.work/`, never on the source.
- **R-SAN-2** EXIF/XMP/IPTC: `strip_all` by default except an allow-list (default `Orientation`, `DateTimeOriginal`).
- **R-SAN-3** Rule types are `literal`, `regex`, `entity` (`PERSON`/`ORG`/`LOCATION` via LLM) and `exif_field`. Rules apply to the original filename and path segments before they are used as a naming hint or stored.
- **R-SAN-4** Order: `literal` → `regex` → `entity`. The Claude backend only ever receives text that has already passed literal and regex rules, and **never pixels**.
- **R-SAN-5** OCR of visible text is optional and off by default. Matches set `has_sensitive_text`, and naming never copies OCR text into a name.
- **R-SAN-6** Every redaction writes `sanitize_log(source_hash, rule_id, field, before_hash, after_value)`. Original values are never stored in plain text.
- **R-SAN-7** The rendered final filename is re-run through all rules (see R-NAME-5).
- **R-SAN-8** Results are metadata-stripped. The full metadata survives in the original in the read-only source folder (P-1). It is lost only if the human enables deletion and runs `purge-sources`.

### 4.3 Classify

- **R-CLS-0** **Two axes (CLS-001).** Every image gets exactly one **format** (what kind of image it is) and at most one **topic** (what it is about). The two axes are scored independently. The adult flag (R-CLS-1) and the reference (R-RAG) sit on top of both.
- **R-CLS-1** NSFW gate (`Falconsai/nsfw_image_detection`): `branch = nsfw` if score ≥ `nsfw.threshold` (0.70), else `safe`. **Adult means explicit sexual imagery** (CLS-001.D12). Suggestive images without explicit content (covered bodies, innuendo, joke ads) are `safe`, and must not be flagged.
- **R-CLS-2** SigLIP zero-shot: each prompt is scored as a **sigmoid probability** (`sigmoid(logit_scale·cos + logit_bias)`), and a category's score is the **max** over its prompts (see §13 C-5). One image embedding is scored against both axes' prompts.
- **R-CLS-3** **Format** is required. The top format wins only if its score ≥ its `min_score` **and** it beats the runner-up by `classify.format.margin`. Otherwise the image goes to `Unsorted/` with `needs_review = true, review_reason = unsorted`. The best topic is still recorded.
- **R-CLS-3a** **Topic** is optional. The top topic wins only if it clears its `min_score` and `classify.topic.margin`. Otherwise the image has **no topic**: it goes to `General/<Format>/`, and this is *not* a review case.
- **R-CLS-3b** **A topic never repeats its format** (CLS-001.D10). `memes` and `documents` exist on both axes. As a topic they mean the image's meaning (a real photo with a joke meaning → `Memes/Photos/`; a screenshot showing a document → `Documents/Screenshots/`). If the top topic equals the chosen format, the next topic that clears its threshold is used, or no topic.
- **R-CLS-4** **Nested categories:** within one axis, if the top two are ancestor and descendant by folder (e.g. a user-added `videogames/racing` under `videogames`), the margin check is skipped and the deeper one wins if it clears its own `min_score`.
- **R-CLS-5** **Folder layout `<Topic>/<Format>/` (CLS-001.D2):** e.g. `Videogames/Screenshots/`, `Anime/Memes/`. With no topic, the image goes to `General/<Format>/`. With no format, it goes to `Unsorted/`.
  - Mirror mode: the branch changes only the root (`Adult/<Topic>/<Format>/`, `Adult/Unsorted/`) and the VLM used. Prompts, thresholds and templates are identical.
  - With `folders.animated_subfolder: true`, animated images (R-ING-9) go one level deeper (`…/<Format>/Animated/`). The default is `false`.
- **R-CLS-6** Per-category `branch`, on both axes: `any` (default, mirrored), `safe` (adult images fall through: a format to `Adult/Unsorted/`, a topic to no topic), or `nsfw` (adult-only).
- **R-CLS-7** Category CLI: `list`, `add --axis format|topic`, `edit`, `remove`, `sync-folders`. Removing a category never deletes folders or files. `sync-folders` creates the `<Topic>/<Format>` grid lazily (only for pairs that are actually filed) plus `General/<Format>/`. It runs before every sort unless `folders.auto_create: false`.
- **R-CLS-8** Defaults: thresholds are **provisional until calibrated in M3** against `fixtures/labels.csv`, per axis. The calibrated values are committed to the seed migration.

**Default formats** (required; folder = second level). `game-screenshots` is a capture taken **inside** a game, on PC, console or any source. `screenshots` is a computer or phone capture of an app, website or chat, even when its content is about games (CLS-001.D9):

| Format | Folder | Default prompts (SigLIP) |
| --- | --- | --- |
| photos | `Photos/` | a photo taken with a camera, a portrait, a photo of an object |
| game-screenshots | `Game Screenshots/` | a screenshot taken inside a video game, a video game scene with a game HUD, a video game character in a 3D game world |
| screenshots | `Screenshots/` | a screenshot of a phone, a screenshot of a desktop app or website, a cropped screen capture of part of a window, a snippet of a webpage, chat or app |
| memes | `Memes/` | a meme with text, a reaction image |
| artwork | `Artwork/` | a digital illustration, a drawing, concept art, an animated abstract graphic |
| documents | `Documents/` | a scanned document, a receipt, a form |

**Default topics** (optional; folder = first level). The vocabulary comes from the human's labels (DOC-002 Q-8 sample):

| Topic | Folder | Default prompts (SigLIP) |
| --- | --- | --- |
| videogames | `Videogames/` | a video game screenshot, a video game character, a game user interface |
| anime | `Anime/` | an anime character, manga style art |
| cartoons | `Cartoons/` | a western cartoon character, a comic drawing |
| pc-equipment | `PC Equipment/` | a computer case, PC hardware components |
| animals | `Animals/` | a photo of a cat, a photo of a dog, an animal |
| people | `People/` | a photo of people, a person's face |
| landscapes | `Landscapes/` | a landscape, a beach, a cityscape, a view from a high floor |
| music | `Music/` | a list of song names, a music player |
| tv-shows | `TV Shows/` | a still from a TV show |
| software | `Software/` | a code editor, a mobile app screen |
| memes | `Memes/` | a joke or humorous image, an image with an ironic meaning |
| documents | `Documents/` | a document, a receipt, a form, a list of text |

`unsorted` is the fallback format (`Unsorted/`, no prompts). The plan's `products` and `landscapes` formats are gone: `landscapes` is now a topic, and `products` had no examples in the real folder (it can be re-added with the CLI). The original filename (after sanitization) is passed to the caption step as a hint, since snips are typically named `Screenshot <date>`.

### 4.4 Caption

- **R-CAP-1** Safe branch → `models.vlm_safe`. Adult branch → `models.vlm_nsfw`. Both produce `{subject}` (1–3 words), `{detail}`, `{caption}` and `{tags}`.
- **R-CAP-2** The adult caption prompt requires **neutral, non-graphic** descriptors and includes a character or franchise if recognizable.
- **R-CAP-3** Prompts live in `prompts/` as versioned files. The prompt version is recorded on the ledger row.

### 4.5 Retrieve (RAG before web)

- **R-RAG-1** Query local pgvector first: the image vector (SigLIP) plus a text vector (caption + tags, `bge-m3`), top-k=5 each, union, rerank.
- **R-RAG-2** The judge (text LLM) returns `MATCH <id>`, `NO_MATCH` or `AMBIGUOUS`, plus a one-line reason. A `MATCH` below `rag.min_similarity` (image 0.80, text 0.75) is downgraded to `AMBIGUOUS`.
- **R-RAG-3** `MATCH` → fill `{reference}` and increment `hit_count`. `AMBIGUOUS` → fill it and set `needs_review = true, review_reason = ambiguous_reference`. `NO_MATCH` → web branch.
- **R-RAG-4** The web branch is a text query only. Backends: `searxng` (default), `brave`, or `claude` (only valid when `sanitizer.backend: claude`). The judge re-reads the results, and only a `MATCH` is ingested.
- **R-RAG-5** Adult branch: `rag.web_for_nsfw: text_only` (default) or `false` (strictly local). Reverse image search is never used (phase 2, safe branch only).
- **R-RAG-6** Write-back: a web `MATCH` creates a `references` row (`created_from: web`, 2–3-sentence summary, source URL, both embeddings, the current image as first exemplar). A later RAG `MATCH` adds an exemplar (max 10).
- **R-RAG-7** Embedding rows record their model id and version. On a model change, embeddings are recomputed on start.
- **R-RAG-8** Gate property: a franchise resolved via the web once is resolved locally on the next image with `web_called = false`.

### 4.6 Name

- **R-NAME-1** Built-in templates: `descriptive` (default), `reference`, `dated`, `category-seq`, `keep-original`, `hash`. User templates come from the CLI, assignable globally or per category, with `preview --sample N`.
- **R-NAME-2** Tokens: `{subject} {detail} {caption} {tags} {reference} {date} {time} {year} {format} {topic} {category} {animated} {branch} {ext} {original_sanitized} {short_hash} {seq[:width]}`.
  - `{category}` = `{topic}_{format}`, or `{format}` when there is no topic.
  - `{animated}` renders `animated` or nothing.
  - Filters: `|title`, `|max=N`, `|or=<fallback>`.
- **R-NAME-3** `{date}`/`{time}`/`{year}` come from EXIF `DateTimeOriginal` if kept, else the source mtime captured at ingest.
- **R-NAME-4** Adult files use **the category's own template**, the same as safe files. `naming.nsfw_template` is an optional override and is **unset by default**.
- **R-NAME-5** Normalize: lowercase, ASCII-fold, replace non-`[a-z0-9]` with `_`, collapse repeats, cap the stem at 120 chars. Then re-run the sanitize rules on the result.
- **R-NAME-6** Collisions in the target folder: increment `{seq}`. If the template has no `{seq}`, append `_NNN`. Never overwrite.
- **R-NAME-8** Adult files get `naming.nsfw_prefix` (default `nsfw_`) prepended to the rendered stem, e.g. `nsfw_zelda_link_horseback_003.png`. It is configurable, and an empty string disables it. It is applied before the 120-char cap and counts toward it.
- **R-NAME-7** Until M6 lands, `{reference}` is empty. Built-in templates that use it must declare an `|or=` fallback.

### 4.7 File operations

- **R-FOP-1** Sequence per file:
  1. Read the source, without modifying it, and copy it to `<results_root>/.work/<source_hash>.<ext>`.
  2. Sanitize, classify and name the copy.
  3. Atomically rename it into `<results_root>/[Adult/]<Topic|General>/<Format>[/Animated]/<name>`, or `[Adult/]Unsorted/<name>` (R-CLS-5).
  4. Verify size and `output_hash` (SHA-256 of the sanitized copy).
  5. Set the ledger status to `filed`.

  The source is never touched.
- **R-FOP-2** If verification fails, the temp copy is discarded, the status becomes `error`, and the next run retries. A partially written result is never left in a category folder.
- **R-FOP-9** On start, the bot refuses to run if `results_root` is inside `source_root` or vice versa, because `watch` would re-ingest its own results. Category folders are created with case-insensitive collision checks, since the results drive is NTFS.
- **R-FOP-8** `source_root` is bind-mounted **read-only** (`:ro`) into `app`, so any accidental write fails at the OS level. A test asserts that the mount is read-only.
- **R-FOP-3** `.work/` is cleaned on start (except `thumbs/`).
- **R-FOP-0** Deletion is disabled unless `deletion.enabled: true`. While it is disabled, `purge-sources` and `delete` exit non-zero with a message naming the config key, and `--dry-run` still works for listing.
- **R-FOP-4** `purge-sources --older-than 30d [--dry-run]`: deletes an original in `source_root` only if re-hashing it matches the ledger `source_hash` **and** its result exists with a matching `output_hash`. It requires `deletion.enabled: true` **and** the override `docker-compose.purge.yml`, which remounts the source read-write for that one command. It lists the files, asks for confirmation, writes to `deletions`, and refuses while a run holds the run lock (R-API-6).
- **R-FOP-5** `delete <hash|path> [--with-source]`: removes one result and marks the ledger row `deleted`. `--with-source` has the same preconditions as R-FOP-4.
- **R-FOP-6** `sort`, `watch`, `dry-run` and `reclassify` contain no delete code path. This is enforced by the Reviewer and a test that greps for unlink/remove calls outside `fileops/delete.py`. Cleanup of `.work/` temp files is the only exception, in `fileops/copy_move.py`.
- **R-FOP-7** `watch` uses watchdog on `source_root` (recursive), debounced 2 s. File-change events from Windows bind mounts don't reach Linux containers, so `watch.polling: auto` uses the polling observer whenever `source_root` is a Windows bind mount (always, on this host). `reclassify --from <format|topic>` re-runs classify → fileops on existing **results** and moves them between result folders. Sources are untouched.

### 4.8 Status UI and API

- **R-API-1** FastAPI is served by `classifier serve` on `127.0.0.1:8000` only. No auth in the MVP.
- **R-API-2** Read: `GET /api/status` (run state, counts per status and category, imgs/min, VRAM, loaded model, last error), `GET /api/events` (SSE), and `GET /api/files?status=&format=&topic=&needs_review=&page=`.
- **R-API-3** Write (M8): `POST /api/files/{hash}/assign` (body: `format`, `topic`; either may be omitted), `POST /api/files/{hash}/rerun`, `POST /api/run/{action}` with `action ∈ {sort, pause, resume}`.
- **R-API-4** Every write calls the same graph nodes as the CLI. The UI never calls models.
- **R-API-5** UI: one `ui/index.html` (htmx or Alpine, no build step). The dashboard shows a run banner, a topic × format count grid (safe vs adult), the last 20 filed files, and errors with retry. The review queue shows unsorted and `needs_review` files with the top-3 scores and the judge's reason, with **adult thumbnails blurred by default**.
- **R-API-6** Run state lives in a `runs` table, plus a Postgres advisory lock held by `sort`, `watch` and `reclassify`.
- **R-API-7** `classifier report [--out report.html]` produces self-contained HTML from the same JSON as the API.
- **R-API-8** No deletion in the UI.

## 5. Data model (Postgres 16 + pgvector)

**Tables:** `categories` (with `axis ∈ {format, topic}`, `folder`, `min_score`, `branch`, `parent_id`), `category_prompts`, `naming_templates`, `template_assignments`, `files` (ledger), `sanitize_log`, `references`, `reference_embeddings`, `retrieval_log`, `deletions`, `runs`, `schema_version` (Alembic).

**`files` key columns:** `source_hash` (PK), `short_hash`, `source_path`, `duplicate_paths[]`, `source_mtime`, `ext`, `status`, `branch`, `nsfw_score`, `animated`, `format`, `topic`, `format_scores`, `topic_scores` (jsonb, top-k each), `caption` (jsonb), `prompt_version`, `reference_id`, `template`, `proposed_path`, `output_path`, `output_hash`, `needs_review`, `review_reason`, `has_sensitive_text`, `error`, timestamps.

**`files.status` enum:** `queued → sanitized → classified → captioned → resolved → named → proposed | filed`, plus `skipped`, `error` and `deleted`. "Unsorted" is the fallback **format**, not a status. A missing topic is `topic = null`. Review is the `needs_review` flag with a `review_reason ∈ {unsorted, ambiguous_reference}`.

**`references`:** `id, name, kind ∈ {character, franchise, product, artwork, place, person-public}, aliases[], summary, source_url, confidence, created_from ∈ {seed, web, manual}, hit_count`.

**`reference_embeddings`:** `reference_id, image_vec vector(1152)` (SigLIP so400m), `text_vec vector(1024)` (bge-m3), `exemplar_hash, model_id, model_version`.

## 6. Configuration (`config.yaml`, corrected)

```yaml
paths:                               # container paths; host paths come from .env (SOURCE_ROOT, RESULTS_ROOT)
  source_root: /source               # READ-ONLY bind mount; watched; never written to
  results_root: /results             # category tree, Adult/, .work/, reports/
folders:
  auto_create: true
  layout: "{topic}/{format}"         # CLS-001.D2; topic folder first
  no_topic: General                  # folder used when no topic clears its threshold
  animated_subfolder: false          # true → …/<Format>/Animated/ (R-ING-9)
models:
  classifier: google/siglip-so400m-patch14-384
  nsfw: Falconsai/nsfw_image_detection
  vlm_safe: qwen3-vl:8b
  vlm_nsfw: <OPEN Q-1>
  text_llm: qwen3-vl:8b              # MVP shortcut: one model for caption + judge + sanitizer
  text_embed: bge-m3
classify:
  score: sigmoid                     # sigmoid | cosine
  format:                            # required axis (R-CLS-3)
    default_min_score: <calibrated in M3>
    margin: 0.05
  topic:                             # optional axis (R-CLS-3a)
    default_min_score: <calibrated in M3>
    margin: 0.05
nsfw:
  threshold: 0.70
  mode: mirror                       # mirror | separate
  root: Adult
naming:
  default_template: descriptive
  nsfw_template: null                # optional override; null = same as category
  nsfw_prefix: "nsfw_"                # prepended to every adult name; "" disables
  max_len: 120
rag:
  top_k: 5
  min_similarity: { image: 0.80, text: 0.75 }
  max_exemplars: 10
  web_backend: searxng               # searxng | brave | claude
  web_for_nsfw: text_only            # text_only | false
sanitizer:
  backend: local                     # local | claude
  rules_file: sanitize.yaml
  ocr: false
watch:
  debounce_s: 2
  polling: auto                      # auto = poll on Windows bind mounts (always on this host)
thumbs:
  size: 256
deletion:
  enabled: false                     # purge-sources / delete refuse unless true
api:
  host: 127.0.0.1
  port: 8000
db:
  dsn: postgresql://classifier@db/classifier
```

**Public-repo split (R-CFG-1).**

- `sanitize.example.yaml` is committed with placeholder values. It has the plan's structure: EXIF `strip_all` plus the keep list, and `literal`, `regex` and `entity` rules.
- The real `sanitize.yaml` is **git-ignored**. `make init` creates it from the example when it is missing.
- The same pattern applies to `.env.example` → `.env`, which holds `SOURCE_ROOT`, `RESULTS_ROOT` and API keys.
- `config.yaml` is committed. It contains only container paths and no personal values.

## 7. CLI (Typer: `classifier …`)

`sort` · `watch` · `dry-run [--csv]` · `reclassify --from <cat>` · `categories {list,add,edit,remove,sync-folders}` · `templates {add,set-default,assign,preview}` · `refs {add,merge,list --needs-review,forget}` · `purge-sources` · `delete` · `serve` · `report`.

## 8. Models and VRAM (RTX 5080, 16 GB)

| Role | Model | VRAM | Residency |
| --- | --- | --- | --- |
| Category scoring + image vectors | SigLIP so400m-patch14-384 | ~1.5 GB | resident (PyTorch, app container) |
| NSFW gate | Falconsai/nsfw_image_detection | ~0.4 GB | resident (CPU fallback) |
| Safe VLM, judge, local sanitizer (MVP) | `qwen3-vl:8b` (fallbacks `minicpm-v:4.5`, `llama3.2-vision:11b`) | 6–8 GB | Ollama, one at a time |
| Adult VLM | candidate `huihui_ai/qwen3-vl-abliterated:8b-instruct` (Q-1, final at M5) | ~6.1 GB weights + KV cache | Ollama, one at a time |
| Text embeddings | `bge-m3` | <1 GB | Ollama |
| Remote sanitizer (opt-in) | Claude API, text-only | 0 | — |

- **R-MOD-1** Ollama `keep_alive` is set per stage so that only one 6–9 GB model is loaded at a time.
- **R-MOD-2** `make models` pulls **both** the Ollama tags and the Hugging Face weights (SigLIP, NSFW) into volumes. At runtime the app sets `HF_HUB_OFFLINE=1`.
- **R-MOD-3** A dedicated text LLM (`qwen3:14b`) is a later split, made only if the M6 judge quality is weak.
- **Throughput target:** gate and score at 20–40 img/s. Captioning (1–3 s/img) is the bottleneck.

## 9. Runtime (Docker Compose)

| Service | Image | Network |
| --- | --- | --- |
| `db` | `pgvector/pgvector:pg16`, volume `pgdata` | internal only |
| `ollama` | `ollama/ollama`, `gpus: all`, volume `ollama` | egress for pulls only |
| `searxng` | `searxng/searxng`, JSON enabled | egress (it forwards queries to public engines) |
| `app` | `Dockerfile` (py3.12, torch CUDA, `gpus: all`) | internal only by default; port `127.0.0.1:8000` |
| `test` | same image, profile `test` | throwaway db, mounts `fixtures/` only |

- **R-RUN-1** All host ports bind to `127.0.0.1`.
- **R-RUN-2** `app` has no internet route by default. The opt-in remote backends (`sanitizer.backend: claude`, `rag.web_backend: brave|claude`) require the override file `docker-compose.egress.yml`. Without that override they fail fast with a clear error.
- **R-RUN-4** `app` mounts `source_root` as `:ro` and `results_root` as read-write. Only `docker-compose.purge.yml` remounts the source read-write, and only for `purge-sources`.
- **R-RUN-3** Images, Postgres data and model weights are volumes and are never baked into images. `fixtures/` is the only image folder mounted into `test`.
- **As built (RUN-001):**
  - **Networks:** `internal` has no internet route (`app`, `db`, `test`). Only `ollama` and `searxng` also join `egress`.
  - **Model downloads:** Hugging Face weights come through a one-off `fetch` service (profile `tools`), the only app-image container with internet.
  - **UI port:** Docker can't publish ports for internal-only containers, so the UI port waits for M4's localhost-only proxy (RUN-001.D5).
  - **`test`:** has no `/source` or `/results` mount at all (RUN-001.D6).
  - **Pins:** see the RUN-001 journal.
- **R-RUN-5** The RTX 5080 is Blackwell (sm_120). The `app` image must use PyTorch wheels built for **CUDA 12.8 or newer** (`cu128`+); `cu124` builds don't support the card. The `ollama/ollama` image is pinned to a version with qwen3vl support.

### 9a. Host and workspace (Windows-native)

**Host software:**

- Windows 11, with the NVIDIA driver and **Docker Desktop**, set to use its WSL2 backend with GPU support enabled.
- WSL2 is only Docker Desktop's internal engine. There is no Linux distro to manage, and no code lives in WSL.
- Natively on Windows: git, Git Bash (ahead of `WindowsApps` on `PATH`), the GitHub CLI, Node 20+ (agent-office minimum), Claude Code, and `make` (`winget install ezwinports.make`).
- Check: `docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi` shows the 5080.

**Workspace layout (everything together):**

```
<workspace>\file-sorter-full\     workspace root (not a git repo)
├─ Design Plan — Image Classification Bot (MVP).md   original plan (archive)
├─ agent-office\                  clone of ComeGalletas/agent-office, built from source
├─ agent-logs\<role>\             per-agent logs (C-18), local only
└─ file-sorter\                   THE project repo → public GitHub repo
```

**Workspace rules:**

- **The repo path is fixed** at `file-sorter-full\file-sorter`. agent-office normally clones projects to `<code folder>\<owner>\<repo>`. At setup step 5, add the existing clone as a floor. If agent-office can't adopt an existing clone, create a directory junction from its expected path to the fixed repo (`mklink /J <code folder>\<owner>\file-sorter <workspace>\file-sorter-full\file-sorter`). Never let it make a second clone.
- Where agent-office creates worker worktrees is verified at setup step 5 and recorded in `docs/`. Worktrees must stay on the same drive as the repo.
- No `CLAUDE.md` sits at the workspace root. The project rules live only in `file-sorter\CLAUDE.md`, so agent-office's own sessions don't inherit them.

**Windows specifics:**

- **Line endings.** `.gitattributes` holds `* text=auto eol=lf` (binary types marked `binary`). Otherwise CRLF breaks shell hooks and container entrypoints.
- **Make.** The `Makefile` sets `SHELL := bash` and requires Git Bash on `PATH`.
- **Hooks.** Claude Code hooks and git hooks are POSIX shell scripts run by Git Bash, calling `docker compose`. No hook assumes Linux-only tools.
- **Paths.** `.env` holds forward-slash Windows paths (`D:/…`), quoted because they contain spaces.
- **Docker data.** Volumes (Postgres, Ollama ~13 GB, HF weights, the CUDA image ~10 GB) live in Docker Desktop's disk image, on C: by default. To move it, change Docker Desktop → Settings → Resources → Disk image location.
- **Auto-reload.** Dev auto-reload inside containers uses polling, because bind-mount file events don't propagate.

## 10. Repository layout

```
classifier/
  cli/ graph/ models/ sanitize/ rag/ naming/ fileops/ api/ ui/ db/
prompts/            # versioned VLM / judge / sanitizer prompts
eval/               # labelled-sample evaluation harness
scripts/gate_1.py … gate_8.py
tests/{unit,db,integration,gpu,devtools}/  tests/recordings/  tests/conftest.py   # tiers by path (CLAUDE.md §3)
fixtures/           # fixtures/images/ is git-ignored, box-only
docs/PLAN.md  docs/plans/{TEMPLATE,mN}.md
docs/journals/{INDEX,TEMPLATE}.md  docs/journals/<feature>_journal.md   # work IDs (CLAUDE.md §1)
config.yaml  sanitize.example.yaml  .env.example        # sanitize.yaml and .env are git-ignored
docker-compose.yml  docker-compose.egress.yml  docker-compose.purge.yml  Dockerfile  Makefile  pyproject.toml  .gitattributes  .gitignore
fixtures/labels.example.csv                           # labels.csv and images/ are git-ignored
.claude/agents/{reviewer,privacy-auditor,test-runner}.md   # read-only subagents only (RUN-002.D1)
.claude/roles/{README,lead,pipeline,ml,rag,api-ui,qa}.md    # desk briefs
.claude/settings.json  .claude/settings.{lead,worker}.json   # shared + per-desk layers (RUN-002.D6)
.claude/hooks/   .githooks/pre-push                         # lint, stop tests, logs; the push gate
docker/searxng/settings.yml  scripts/{fetch_models.py,init_local_files.sh,gate_1..8.py}
.github/ISSUE_TEMPLATE/task.md  .github/pull_request_template.md
.task                                                       # git-ignored per worktree: role, issue, acceptance
```

## 11. Milestones and gates

Each gate is measured by `scripts/gate_N.py` via `make gate-N`. Nothing from N+1 starts before the `mN-approved` tag exists.

| M | Scope | Gate (acceptance) |
| --- | --- | --- |
| 1 | Skeleton + ledger: compose, `files`, hashing, ingest, `dry-run` CSV | Re-running on the same folder skips 100% of files, with no new ledger rows. |
| 2 | Sanitize: EXIF strip, literal/regex, `sanitize_log`, entity rule via local LLM | 50 seeded names come out with 0 residual sensitive values. EXIF on outputs contains only the allow-list. |
| 3 | Classify: SigLIP + NSFW, default formats and topics, `<Topic>/<Format>` folders, mirror, thresholds per axis, unsorted, category CLI; **threshold calibration** | Measured on **all ~150 real images**, labelled in `fixtures/labels.csv`. A blank format or topic means the human was **undecided**: the row still runs, but isn't scored on that axis (CLS-001.D11). Targets: ≥ 90% **format** agreement on rows with a format; ≥ 85% **topic** agreement on rows with a topic (CLS-001.D5); every row tagged `suggestive-negative` must stay `safe`; the NSFW gate flags **every** labelled adult image and **0** safe ones; unrecognized < 10%. Extra box-only adult samples in `fixtures/` may be used for threshold calibration but don't count toward the gate. |
| 4 | Status UI read-only: `/api/status`, `/api/files`, dashboard, `report` | A dry run of the whole real folder (~150 images) is reviewable end to end without a terminal. |
| 5 | Name: built-in and user templates, captions from both VLMs, collisions | 0 sensitive values in 500 names. A readability spot-check of names passes human review at G1. |
| 6 | RAG + web: pgvector, judge, SearXNG, write-back, `refs` CLI | A franchise searched once resolves locally on the second image (`web_called = false`). |
| 7 | File ops + watch: copy → results transaction, `watch`, `purge-sources` and `delete` (disabled by default) | Kill mid-run and restart: 0 duplicates, 0 lost files, ledger == results on disk. The source tree's checksum manifest is **byte-identical before and after** the run. With the default config, `purge-sources` and `delete` refuse. |
| 8 | UI write actions: assign, rerun, pause/resume | Every unsorted file from the real folder is fileable from the browser, and ledger == disk. |

## 12. Development process (summary — operating rules are in `CLAUDE.md`)

- **Team surface.**
  - agent-office desks (one Claude Code session per desk), GitHub issues as the task queue, PRs as review. The native agent-teams fallback is dropped, because it needs tmux (DOC-003.D9).
  - **Install from the fork `https://github.com/ComeGalletas/agent-office`, cloned into `file-sorter-full\agent-office` and built from source per its README.** Do not use the plan's `curl … install.sh | bash`: the fork's `install.sh` hard-codes `REPO="AgentSystemLabs/agent-office"` and downloads upstream release tarballs, and the fork publishes no releases. As of 2026-10-05 the fork is identical to upstream `main`. Once it diverges, only a source build runs the fork's code.
  - **As built (RUN-003):** `npm install -g .` links the fork globally. `agent-office <repo>` adopts this checkout as the floor, with no second clone, and keeps its data and worker worktrees in the git-ignored `.agent-office/`. Its desks run with agent-office's own `--settings`, so the roles are enforced by the location-aware guard hook (RUN-002.D8).
- **Process standard (DOC-001, full rules in CLAUDE.md §1–§3).**
  - Work IDs `<SYS>-<NNN>` per requirement, using the system codes of this spec's R-prefixes.
  - Task `.n` = one issue = one PR. Subtask `.n.n` = one commit. Decision `.Dn`.
  - One journal per feature in `docs/journals/` (Requirement → Confirmed reading → Plan → Tasks → Results), indexed in `docs/journals/INDEX.md`.
  - Commit subjects start with the ID. Every task opens with a triage block and ends with a completion status and a self-rating.
  - Test tiers: `unit`, `db`, `integration`, `gpu`, `gate`.
- **Roles and file ownership.**
  - Lead (Opus): `docs/` only, no code.
  - Pipeline: `graph/ naming/ fileops/ db/ cli/ sanitize/`.
  - ML: `models/ prompts/ eval/`.
  - Data/RAG: `rag/` plus `references*` migrations.
  - API/UI: `api/ ui/`.
  - QA: `tests/ fixtures/ scripts/`.
  - Reviewer (Sonnet), Privacy auditor (Haiku) and Test runner (Sonnet) are read-only subagents in `.claude/agents/`. The six desk roles are briefs in `.claude/roles/`, never subagents (RUN-002.D1).
- **Human gates.**
  - G0: you set `status: approved` in `docs/plans/mN.md`.
  - G1: you review `make gate-N` and the UI, then create the tag `mN-approved`.
  - G2: ad hoc review at any time.
- **Team per milestone.**

  | Milestone | Team |
  | --- | --- |
  | M1 | Lead + Pipeline + QA |
  | M2 | Lead + Pipeline + QA, plus ML for the Ollama client task |
  | M3 | adds ML |
  | M4 | API/UI replaces ML |
  | M5–M6 | add RAG |

  Run 3–4 teammates at a time at most.

## 13. Reconciliations vs the plan (confirm each)

| # | Plan says | This spec says | Why | Status |
| --- | --- | --- | --- | --- |
| C-1 | `config.yaml`: `vlm_safe: qwen2.5-vl:7b`, `text_llm: qwen2.5:7b-instruct` | `qwen3-vl:8b` for both (MVP shortcut) | Matches the plan's own Models section and loading plan. | **accepted** |
| C-2 | `naming.nsfw_template: reference` | `nsfw_template: null` (category template) **plus** `nsfw_prefix: "nsfw_"` on every adult name, configurable (R-NAME-8) | Human decision, 2026-10-05. | **changed** |
| C-3 | Sources moved to `done/`; `source_root/inbox` | Source folder is **read-only** (mounted `:ro`, never moved or modified); outputs go to a separate `results_root`; no `inbox/` or `done/`; `purge-done` becomes `purge-sources` (disabled by default) | Human decision, 2026-10-05. | **changed** |
| C-4 | `reference_embeddings.image_vec` is 768-d; text is "bge-m3 or nomic, 1024-d" | 1152-d (SigLIP so400m), 1024-d (bge-m3 only) | so400m outputs 1152-d. nomic-embed is 768-d, so one model must be fixed for the column type. | **accepted** |
| C-5 | `min_score` default 0.25 **cosine** | Sigmoid probability, max over prompts; defaults calibrated in M3 | Raw SigLIP image–text cosines for true matches sit well below 0.25, so the plan's default would send almost everything to Unsorted. | **accepted** |
| C-6 | (unspecified) | Nested-category rule R-CLS-4 | `anime` and `artwork` prompts overlap. Without the rule, the 0.05 margin pushes most anime images to Unsorted. | **accepted** |
| C-7 | Stage order Name (3) then Retrieve (4) | Execution order caption → retrieve → name | Naming consumes `{reference}`. | **accepted** |
| C-8 | Per-file LangGraph flow plus per-stage batching | Batch nodes with the ledger status as checkpoint; fileops per file | The two models conflict. Batching is what makes VRAM swapping work. | **accepted** |
| C-9 | Separate `review` and `needs_review` flags; `status=unsorted` | One `needs_review` + `review_reason`; unsorted is a category | One status model for the UI and API. | **accepted** |
| C-10 | Tech stack: "FastAPI optional for a later UI" | FastAPI is MVP (M4, M8) | Stage 6 and the milestones require it. | **accepted** |
| C-11 | `references` has no `hit_count`; no run-state table | Add `hit_count` and a `runs` table + advisory lock | R-RAG-3 and `/api/status` need them; `purge-sources` must detect a running sort. | **accepted** |
| C-12 | `sanitize/` has no owner; `prompts/`, `eval/`, `scripts/`, `fixtures/` missing from the tree | Pipeline owns `sanitize/`; dirs added (§10) | Every folder needs exactly one owner. | **accepted** |
| C-13 | M2 needs the local-LLM entity rule but ML joins at M3 | ML desk joins M2 for one task (the Ollama client in `models/`) | Keeps ownership intact. | **accepted** |
| C-14 | "No network except localhost" vs opt-in Claude/Brave backends; SearXNG "keeps queries local" | Egress only via `docker-compose.egress.yml`; SearXNG documented as outbound | SearXNG forwards query text to public engines. Adult caption text leaves the box under `text_only`. | **accepted** |
| C-15 | `make models` pulls Ollama tags | It also pulls HF weights, and the app runs offline | Otherwise the app needs internet on first run. | **accepted** |
| C-16 | Lead runs in `plan` mode outside gates but must open issues and merge PRs | Lead runs in `default` mode with allow-listed `gh`/`git merge` and Edit/Write denied on source dirs | Plan mode cannot run `gh` or merge. | **accepted** |
| C-17 | `PostToolUse` runs ruff + tests on every edit; `Stop` runs the full compose suite | `PostToolUse` runs ruff on the edited file only. `Stop` runs touched tests in worker worktrees only; **pre-push** runs the full suite + gate and is the hard block | `Stop` fires every turn. A full Docker suite per turn is slow and costly. | **accepted** |
| C-18 | `.claude/events.jsonl` in the repo | **Per-agent log subfolders, local only:** `$AGENT_LOG_ROOT/<role>/events.jsonl` (one line per lifecycle event) and `$AGENT_LOG_ROOT/<role>/<issue>.md` (job log: plan, steps, test results). The default root is `file-sorter-full\agent-logs\`, next to the repo but outside it, and never committed | Human decision, 2026-10-05. Avoids worktree conflicts and keeps agent activity out of the public repo. | **changed** |
| C-19 | (unspecified) | `sanitize.example.yaml` committed with placeholders; the real `sanitize.yaml` is git-ignored and created by `make init` (R-CFG-1) | Human decision, 2026-10-05. Public repo. | **changed** |
| C-20 | API table row for `/api/run` is malformed; two diagrams did not survive export | Fixed in R-API-3 and §3 | Export artifacts. | **accepted** |
| C-21 | One category per image (`category`), formats and subjects mixed; `anime` nested under `Artwork/` | **Two axes:** a required format and an optional topic, scored independently. `<Topic>/<Format>/` folders; new format `game-screenshots` (inside a game) vs `screenshots` (computer capture); `memes`/`documents` also allowed as topics; `gif` becomes a derived `animated` flag; the M3 gate is per axis, with undecided labels not scored (CLS-001) | Human decision, 2026-10-05, from the labelled sample: labels were format + topic pairs typed in either order. | **changed** |

## 14. Open questions (human)

| # | Question | Default if unanswered |
| --- | --- | --- |
| Q-1 | Exact Ollama tag for the adult (uncensored) VLM | **Kept open until M5 planning** (human, 2026-10-05). The M5 G0 plan must ask for it, and no agent picks one. **Candidate checked 2026-10-05:** `huihui_ai/qwen3-vl-abliterated:8b-instruct`.<br>• It is in the Ollama library, so `ollama pull` works with no `hf.co/` path.<br>• It is a qwen3vl family model: 8.8B parameters, Q4_K_M, 6.1 GB of weights.<br>• It uses the stock `qwen3-vl-instruct` renderer and parser, so it is the same architecture and prompt format as `vlm_safe`, and one caption prompt serves both branches.<br>• It is an instruct build (no thinking tokens), so captions are fast.<br>• Its default temperature is 1.0, so caption calls must pass a low temperature.<br>• It needs an Ollama build with qwen3vl support; pin the `ollama/ollama` image version. |
| Q-2 | ~~Git remote~~ | **Answered:** GitHub, **public** repo. agent-office is installed from source from the fork `ComeGalletas/agent-office` (see §12). |
| Q-3 | ~~Results root~~ | **Answered:** a sibling folder on the same Windows drive as the source, set in the local `.env`. `.work/` lives on the same drive, so atomic renames hold. |
| Q-4 | ~~Source root~~ | **Answered:** a Windows-drive folder, set in the local `.env` and bind-mounted `:ro` by Docker Desktop. `watch` uses polling. The path contains a space, so it is quoted in `.env` and compose. |
| Q-5 | ~~Repo location~~ | **Answered (2026-10-05):** Windows-native, no WSL repo. The workspace is `file-sorter-full\` and the repo is fixed at `file-sorter-full\file-sorter` (§9a). |
| Q-6 | ~~Metadata loss~~ | **Answered:** the source is read-only and never deleted by sorting. Deletion stays as a separate function, disabled by default (P-1, R-FOP-0, R-FOP-8). |
| Q-7 | ~~Public fixtures~~ | **Answered:** `fixtures/labels.csv` is git-ignored, and a 5-row synthetic `labels.example.csv` is committed. |
| Q-8 | ~~M3 gate on a small folder~~ | **Answered:** locked in. All ~150 real images are labelled; ≥ 90% category agreement overall (amended by CLS-001: ≥ 90% format, plus ≥ 85% topic on rows with a topic); the NSFW gate catches every adult image with 0 false positives (§11, M3). |
