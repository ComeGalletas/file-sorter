# Design Plan — Image Classification Bot (MVP)

Oct 5, 2026 · @JP

## Brief for the implementing agent

You are the lead Claude Code session for this project. This document is the full specification; read it top to bottom once, then work only from the Setup runbook at the end and the milestone list under Tech stack. Decisions below are final unless the human changes this file.

- **Decided:** images-only MVP; non-destructive copy/rename/move with `done/`; deletion only via `purge-done` and `delete`; NSFW in mirror mode under `Adult/`; sanitization before any model sees a file; RAG before web; everything in Docker Compose; Claude Code sessions hired through agent-office with GitHub issues as the task queue and pull requests as the review step; one human gate per milestone (G0 plan, G1 demo).
- **Open, ask the human:** the exact Ollama tag for the uncensored VLM; whether the git remote is GitHub (default) or a local Gitea; the output root path on the box.
- **Your first action:** runbook step 3 (repo bootstrap). Steps 1 and 2 are the human's. Do not start milestone 1 before `docs/plans/m1.md` carries `status: approved`.
- **Never:** read `source_root/` originals in tests, commit images, add a network route beyond localhost services, or call a model other than through the Ollama and Anthropic clients in `models/` and `sanitize/`.
- **Working style:** tasks of at most one day each with an acceptance test named up front; one worktree per task; every completion gated by the compose `test` profile; append one JSON line per lifecycle event to `.claude/events.jsonl`; write `docs/tasks/<id>.md` on merge.

## Scope and principles

The MVP is a local bot that watches one images folder, sanitizes sensitive values, classifies each picture into a configurable category, names it from its content, and copies the result into a category folder. Everything runs on the RTX 5080 box; Claude is an optional backend for the sanitization step only.

- **Images only.** Accepted: jpg, jpeg, png, webp, gif, bmp, heic, tiff. Any other file is logged and skipped; no other type is enabled until image classification is validated end to end.
- **Non-destructive by default.** Sources are never modified in place. Each image is copied, the copy is renamed and moved into its category folder, and only then is the original moved to `done/`. The only destructive action is an explicit, separate `delete` command.
- **NSFW and unrecognized are first-class.** Adult (legal) content goes through the same categories as everything else, filed under an Adult/ parent folder, and is handled by models that do not refuse; images that match no category above the confidence threshold go to `unsorted/` for review instead of being guessed.
- **Config over code.** Categories, naming templates and sanitization rules live in a YAML config and a small Postgres schema, editable from the CLI without touching code.
- **Local-first retrieval.** Image references (characters, products, places, artwork) are looked up in a local Postgres/pgvector RAG before any web search; whatever the web search finds is written back so the next run does not search again.
- **Idempotent and resumable.** Every file is hashed; a hash already in the ledger is skipped, so re-runs and crashes are safe.

## Pipeline overview

Each image passes through five stages in order, and every stage reads and writes one Postgres database so a crash can resume where it stopped.

&#91;embedded content: image pipeline · 5 stages, 2 shared services\]

The stages are LangGraph nodes; Classify is the MVP gate and the only stage with a hard accuracy target before anything else is enabled. Sanitize runs before Classify so no model other than the sanitizer ever sees unredacted metadata.

## Stage 1 — Sanitization of sensitive values

Sanitization runs on the working copy, never the source, and is driven entirely by `sanitize.yaml`. Its job is to remove or replace values you have declared sensitive before any classification or naming model, local or remote, sees the file.

**What is sanitized in the image MVP**

- **Metadata:** EXIF/XMP/IPTC fields (GPS, camera serial, owner name, software, timestamps if configured). Default is strip-all except orientation, with an allow-list you can extend.
- **Filename and path:** the original name is matched against the rule set (regex, literal, entity type) and offending segments are replaced with the rule's token (`[REDACTED]`, `[PERSON]`, `[EMAIL]`) before it is used as a naming hint or stored in the ledger.
- **Visible text (optional, off by default):** OCR via the VLM; matches against the rules are logged, and the image is tagged `has_sensitive_text` so the naming stage never copies that text into the filename. Pixel-level blurring is out of scope for the MVP.

**Rule types in `sanitize.yaml`**

| Type | Example | Backend needed |
| --- | --- | --- |
| `literal` | your name, your handle, a client name | none (string match) |
| `regex` | emails, phone numbers, IDs, card-like numbers | none |
| `entity` | `PERSON`, `ORG`, `LOCATION` on free text | LLM (local or Claude) |
| `exif_field` | `GPSLatitude`, `SerialNumber` | none (exiftool / piexif) |

**Backend choice (one flag: `sanitizer.backend: local | claude`)**

- `local` (default): a small text LLM through Ollama does entity detection on filenames and OCR text. Nothing leaves the machine, which is the right default when the folder includes adult content.
- `claude`: higher-quality entity detection via the Anthropic API, text-only. The image itself is never sent; only the extracted filename and OCR strings are, and only after `literal`/`regex` rules have already run. Recommended only for folders you are comfortable sending text snippets from.

Every redaction is recorded in `ledger.sanitize_log` (file hash, rule id, field, before-hash, after-value) so you can audit what was removed without storing the original value in plain text.

## Stage 2 — Image classification

Classification is a two-step vote: an NSFW classifier decides whether the image is adult, then a SigLIP zero-shot embedding scores it against every enabled category's prompts. The top category wins only if its score clears the category's threshold and beats the runner-up by the configured margin; otherwise the image goes to `unsorted`. The adult flag does not change the category set, only the destination root: an adult image lands in `Adult/<category folder>/` instead of `<category folder>/`.

**Default category set** (editable; each row is a record in `categories`)

| Category | Folder (safe) | Folder (adult, mirrored) | Default prompts (SigLIP) |
| --- | --- | --- | --- |
| photos | `Photos/` | `Adult/Photos/` | a photo of people, a portrait, a family photo |
| screenshots | `Screenshots/` | `Adult/Screenshots/` | a screenshot of a phone, a screenshot of a desktop app |
| memes | `Memes/` | `Adult/Memes/` | a meme with text, a reaction image |
| artwork | `Artwork/` | `Adult/Artwork/` | a digital illustration, a drawing, concept art |
| anime | `Artwork/Anime/` | `Adult/Artwork/Anime/` | an anime character, manga style art |
| landscapes | `Landscapes/` | `Adult/Landscapes/` | a landscape, a cityscape, nature photography |
| documents | `Documents/` | `Adult/Documents/` | a scanned document, a receipt, a form |
| products | `Products/` | `Adult/Products/` | a product photo, packaging, a device |
| unsorted | `Unsorted/` | `Adult/Unsorted/` | (no prompts; fallback) |

**Rules**

- **Mirror mode (default, `nsfw.mode: mirror`).** The NSFW classifier sets `branch = nsfw` when its score passes `nsfw.threshold` (default 0.7). Scoring, thresholds, prompts and naming templates are then exactly the same as for safe images; the only difference is that the category folder is created under `nsfw.root` (default `Adult/`), and the adult VLM is used for the caption. An explicit anime image of a known character therefore lands in `Adult/Artwork/Anime/` with the character's name in the filename, the same way a safe one lands in `Artwork/Anime/`.
- **Per-category override.** A category can opt out of mirroring with `branch: safe` (never receives adult images; they fall through to `Adult/Unsorted/`) or `branch: nsfw` (an adult-only category with its own prompts, e.g. a specific genre folder). `any` is the default and means mirrored.
- Thresholds are per category (`min_score`, default 0.25 cosine) plus a global `margin` (default 0.05) between first and second place. Both are tunable from the CLI while you watch a dry run.
- Nested folders are supported by the `folder` field; the mirror reproduces the nesting under `Adult/`.
- `unrecognized` is not a guess: it is the explicit outcome when no category clears its threshold. Images in `Unsorted/` or `Adult/Unsorted/` keep their sanitized name and a `review` flag in the ledger so a later `reclassify` command can pick them up after you add or tune categories.

**Category management (CLI)**

```
classifier categories list
classifier categories add receipts --folder Documents/Receipts --prompt "a photo of a receipt" --branch safe
classifier categories edit memes --add-prompt "a screenshot of a tweet" --min-score 0.3
classifier categories remove products        # images already filed stay where they are
classifier categories sync-folders            # creates any missing category folders under the output root
```

`sync-folders` runs automatically before each sort unless `folders.auto_create: false`. Removing a category never deletes its folder or its files.

## Stage 3 — Naming engine

Filenames are rendered from a template of tokens; the content tokens come from the VLM caption and from the reference lookup in Stage 4, so a name can say *what* is in the picture and, when known, *who* or *which* it is.

**Built-in templates** (`naming_templates`, each selectable per category or globally)

| Template id | Pattern | Example output |
| --- | --- | --- |
| `descriptive` (default) | `{subject}_{detail}_{date}_{seq}` | `golden_retriever_beach_2026-10-05_001.jpg` |
| `reference` | `{reference}_{subject}_{seq}` | `zelda_tears_of_the_kingdom_link_horseback_003.png` |
| `dated` | `{date}_{time}_{subject}` | `2026-10-05_1432_city_skyline.jpg` |
| `category-seq` | `{category}_{seq:04}` | `screenshots_0042.png` |
| `keep-original` | `{original_sanitized}` | whatever survived sanitization |
| `hash` | `{short_hash}` | `a93f1c2e.webp` |

**Tokens available in any template**

- Content: `{subject}` (1–3 word main subject), `{detail}` (setting or action), `{caption}` (full slug, capped at `naming.max_len`), `{tags}` (top-N SigLIP tags), `{reference}` (resolved name from RAG/web: character, franchise, product, artwork, place).
- Metadata: `{date}`, `{time}`, `{year}` (from EXIF if kept, else file mtime), `{category}`, `{branch}`, `{ext}`, `{original_sanitized}`, `{short_hash}`, `{seq}` with optional width `{seq:04}`.
- Filters: `{subject|title}`, `{caption|max=40}`, `{reference|or=unknown}` for a fallback when a token is empty.

**User-defined templates**

```
classifier templates add my-art "{reference|or=original}_{subject}_{year}_{seq:03}"
classifier templates set-default my-art            # global
classifier templates assign anime my-art           # per category
classifier templates preview my-art --sample 10    # dry-run names for 10 files, no moves
```

**Sanitization of the rendered name:** lowercase, ASCII-fold, replace non-`[a-z0-9]` with `_`, collapse repeats, cap at 120 characters, and run the Stage 1 rules once more on the final string so a caption cannot reintroduce a redacted value. Collisions inside the target folder increment `{seq}` rather than overwrite.

**Adult branch:** names are built from the same template as the category's safe images, so `{reference}` and `{subject}` are filled the same way: the adult VLM captions the image (subject count, setting, style, and the character or franchise if recognizable), the retrieval judge resolves `{reference}` against the RAG store, and an explicit picture of a known fictional character gets that character's name exactly as a safe one would. The caption prompt asks for neutral, non-graphic descriptors so names stay usable in a file browser. `naming.nsfw_template` remains available as an optional override (e.g. `category-seq`) if you prefer generic names there.

## Stage 4 — Reference retrieval (RAG before web)

The `{reference}` token is filled by a retrieval judge that always queries the local Postgres/pgvector store first and only calls a web search when the judge rejects the local candidates. Whatever the web returns is written back, so each franchise, character, product or place is searched at most once.

&#91;embedded content: reference retrieval · RAG first, web on miss, write-back\]

**Store (Postgres 16 + pgvector)**

| Table | Purpose | Key columns |
| --- | --- | --- |
| `references` | one row per known entity | `id`, `name`, `kind` (character, franchise, product, artwork, place, person-public), `aliases[]`, `summary`, `source_url`, `confidence`, `created_from` (seed, web, manual) |
| `reference_embeddings` | vectors for matching | `reference_id`, `image_vec` (SigLIP, 768-d), `text_vec` (bge-m3 or nomic-embed, 1024-d), `exemplar_hash` |
| `retrieval_log` | every lookup and its verdict | `file_hash`, `candidates`, `verdict`, `web_called`, `latency_ms` |

**Retrieval judge (one LangGraph node, local text LLM)**

1. Build two queries: the SigLIP image vector, and the VLM caption plus top tags as text.
2. Pull top-k (default 5) by cosine from both vectors, union, and rerank.
3. Judge prompt: given the caption, the tags and the candidates with their summaries, answer `MATCH <id>`, `NO_MATCH`, or `AMBIGUOUS` with a one-line reason. A `MATCH` under `rag.min_similarity` (default 0.80 image or 0.75 text) is downgraded to `AMBIGUOUS`.
4. `MATCH` → fill `{reference}` and bump that row's `hit_count`. `AMBIGUOUS` → fill with the candidate name but mark the ledger row `needs_review`. `NO_MATCH` → web branch.

**Web branch**

- Query is text-first (caption + tags, e.g. `"blue-haired anime girl with a scythe" character`); reverse image search is a phase-2 option since it means uploading the image to a third party. For `nsfw` branch files the web branch is **off by default** for reverse-image search, which is never used there. The text query still runs by default (`rag.web_for_nsfw: text_only`): it carries no pixels and the caption is neutral, so an unknown character can still be resolved and ingested. Set it to `false` to keep adult lookups strictly local to the RAG store.
- Search backend is pluggable: SearXNG self-hosted (default, keeps queries local), Brave Search API, or the Claude API with the web search tool when `sanitizer.backend: claude` is already on.
- The judge re-reads the top results and must return the same `MATCH/NO_MATCH` verdict; only a `MATCH` is ingested.

**Ingestion (write-back)**

- A `MATCH` from the web creates a `references` row with `created_from: web`, its summary (2–3 sentences, local LLM), the source URL, and embeddings from both the current image and the summary text. The current image's hash becomes the first exemplar.
- A later `MATCH` from RAG on a different image adds that image vector as another exemplar (max 10 per reference), so matching improves with use.
- Manual commands: `classifier refs add`, `refs merge`, `refs list --needs-review`, `refs forget <id>`.

The store is self-managed: migrations run on start, embeddings are recomputed if the embedding model version changes, and the judge never needs you to curate anything for the pipeline to keep running.

## Stage 5 — File operations

The sort is a copy-then-move transaction per file; the source is only touched once the renamed copy is verified in place, and nothing is ever deleted by the sort.

**Per-file sequence**

1. Copy source to `work/<hash>.<ext>` (temp, same volume as output to allow atomic rename).
2. Sanitize the copy (Stage 1), classify and name it (Stages 2–4).
3. Atomic rename `work/<hash>` → `<output_root>/<category folder>/<new name>`; verify size and hash of the result.
4. Write `ledger.files` row: `hash, source_path, output_path, category, template, scores, status=filed`.
5. Move the untouched source to `<source_root>/done/` keeping its original name and relative subfolder; status becomes `done`. If the move fails (locked file, permissions), the output copy stays and status is `filed_source_pending` for a retry.

**Folder layout**

```
source_root/
  inbox/            # watched; anything dropped here is processed
  done/             # originals, untouched, after a successful sort
output_root/
  Photos/ Screenshots/ Artwork/Anime/ ... Unsorted/
  Adult/            # same tree, mirrored: Adult/Photos/ Adult/Artwork/Anime/ ... Adult/Unsorted/
  .work/            # temp copies; cleaned on start
```

**Deletion is a separate command, never a side effect**

- `classifier purge-done --older-than 30d [--dry-run]` deletes originals in `done/` that have a `filed` output with a matching hash. It prints the list, asks for confirmation, and writes every deletion to `ledger.deletions`.
- `classifier delete <hash|path>` removes one output file and marks the ledger row `deleted`; the original in `done/` is left alone unless `--with-source` is passed.
- There is no delete inside the sort, watch or reclassify commands, and `purge-done` refuses to run while a sort is in progress.

**Modes:** `classifier sort` (one pass), `classifier watch` (watchdog on `inbox/`, debounced 2 s so half-written files are not picked up), `classifier dry-run` (full pipeline, writes a CSV of `source → proposed output`, moves nothing), `classifier reclassify --from Unsorted` (re-runs Stages 2–5 on already-filed files after a config change, moving outputs between category folders).

## Stage 6 — Status UI

The MVP gets a small local web UI served by the bot itself: a status dashboard that refreshes while a sort runs, plus the few actions you need to unblock a run (review `Unsorted/`, reassign a category, re-run a file). A static HTML report is kept as an export of the same data, not as the thing the UI reads from.

**Why the statement changes slightly**

The original idea was an HTML report generated at runtime, with a frontend page that reads and updates from it. Reading from a generated HTML file works for a one-way status view, but a page cannot *update* through another HTML file: any write action (reassign, approve, re-run) needs an endpoint, and parsing the status back out of rendered HTML is fragile. The cleaner split that keeps the same goal is: the ledger in Postgres is the single source of truth, a tiny FastAPI app exposes it as JSON and accepts the write actions, the frontend reads and updates through that API, and `classifier report` renders the HTML report from the same JSON whenever you want a shareable, offline snapshot.

**Components**

| Piece | What it is | MVP scope |
| --- | --- | --- |
| `GET /api/status` | run state (idle, sorting, watching, paused), counts per status and per category, throughput, last error | read-only, polled every 2 s or pushed over SSE at `/api/events` |
| `GET /api/files?status=unsorted&page=` | ledger rows with thumbnail, scores, caption, proposed name, category | read-only, paged |
| `POST /api/files/{hash}/assign` | set category (creates folder if needed), re-render name, move the output | write |
| `POST /api/files/{hash}/rerun` | re-run Stages 2–5 on one file | write |
| \`POST /api/run/{sort | pause | resume}\` |
| `classifier report [--out report.html]` | self-contained HTML (inline CSS, thumbnails as data URIs or links) built from the same JSON | static export |
| `ui/` | one `index.html` with htmx or Alpine.js, no build step, served by FastAPI at `/` | dashboard, Unsorted review queue, category and template tables (read-only in MVP) |

**Dashboard content (first screen)**

- Run banner: mode, files queued / processing / filed / done / unsorted / needs\_review, images per minute, VRAM in use, current model loaded.
- Category bar chart from `GET /api/status` (count per folder, safe and adult side by side).
- Last 20 filed files with thumbnail, old name → new name, category, confidence.
- Error list from the ledger (`filed_source_pending`, sanitize failures) with a retry button.

**Review queue (second screen)**

- Grid of `Unsorted/` and `needs_review` files with the top-3 category scores and the judge's reason; one click assigns a category or confirms the reference. Adult thumbnails are blurred by default with a toggle.

**Rules**

- Bound to `127.0.0.1` only; no auth in the MVP because it never leaves the machine. A `--host 0.0.0.0` flag can be added later with a token.
- The UI never calls the models directly; every write goes through the same LangGraph nodes the CLI uses, so behaviour is identical.
- Thumbnails are generated once at ingest (256 px, stored under `.work/thumbs/`) so the UI does not read original files.
- Deletion stays out of the UI in the MVP, consistent with Stage 5; `purge-done` and `delete` remain CLI-only.

## Configuration schema

One `config.yaml` holds paths, model choices and thresholds; categories, templates and references live in Postgres so the CLI can edit them without a restart. `sanitize.yaml` is kept separate so it can be reviewed and version-controlled on its own.

```yaml
# config.yaml
paths:
  source_root: /data/images/inbox
  done: /data/images/done
  output_root: /data/sorted
folders:
  auto_create: true
models:
  classifier: google/siglip-so400m-patch14-384
  nsfw: Falconsai/nsfw_image_detection
  vlm_safe: qwen2.5-vl:7b                 # Ollama tag
  vlm_nsfw: <uncensored vlm tag>          # see Models section
  text_llm: qwen2.5:7b-instruct           # judge, sanitizer (local), summaries
  text_embed: bge-m3
classify:
  margin: 0.05
nsfw:
  threshold: 0.70
  mode: mirror                       # mirror | separate (own categories only)
  root: Adult
naming:
  default_template: descriptive
  nsfw_template: reference
  max_len: 120
rag:
  top_k: 5
  min_similarity: { image: 0.80, text: 0.75 }
  web_backend: searxng               # searxng | brave | claude
  web_for_nsfw: text_only            # text_only | false
sanitizer:
  backend: local                     # local | claude
  rules_file: sanitize.yaml
  ocr: false
db:
  dsn: postgresql://classifier@localhost/classifier
```

```yaml
# sanitize.yaml
exif:
  mode: strip_all
  keep: [Orientation, DateTimeOriginal]
rules:
  - id: my-name
    type: literal
    values: ["<your name>", "<your handle>"]
    replace: "[PERSON]"
  - id: email
    type: regex
    pattern: "[\\w.+-]+@[\\w-]+\\.[\\w.]+"
    replace: "[EMAIL]"
  - id: entities
    type: entity
    labels: [PERSON, ORG]
    replace: "[{label}]"
```

**Postgres tables (MVP):** `categories`, `category_prompts`, `naming_templates`, `template_assignments`, `files` (ledger), `sanitize_log`, `references`, `reference_embeddings`, `retrieval_log`, `deletions`, `schema_version`.

## Model recommendations — RTX 5080 (16 GB VRAM)

The 16 GB budget does not hold every model at once, so the plan keeps the two small classifiers resident in PyTorch and lets Ollama swap one larger model at a time (VLM or text LLM). Sizes below are approximate Q4 figures as of October 2026; verify the exact tags on ollama.com and Hugging Face before pulling.

| Role | Model | Approx. VRAM | Why |
| --- | --- | --- | --- |
| Category scoring | `google/siglip-so400m-patch14-384` (open\_clip / transformers) | \~1.5 GB | Best zero-shot image-text matching at this size; no refusals; same vector reused for RAG |
| NSFW gate | `Falconsai/nsfw_image_detection` (ViT) | \~0.4 GB | Fast binary adult/safe classifier; runs on CPU if VRAM is tight |
| VLM, safe branch | `qwen3-vl:8b` (Ollama), fallback `minicpm-v:4.5` or `llama3.2-vision:11b` | 6–8 GB | Strong captions and OCR; [Qwen3-VL and Llama 3.2 Vision are the current 8–16 GB picks](https://www.promptquorum.com/power-local-llm/local-vision-models-llava-ollama-2026) |
| VLM, adult branch | an abliterated/uncensored Qwen-VL fine-tune (community GGUF on Hugging Face, e.g. the `huihui_ai` abliterated series; pull with `ollama pull hf.co/<repo>`) | 6–8 GB | Stock VLMs describe adult content inconsistently or refuse; an abliterated variant returns neutral descriptors reliably |
| Text LLM (judge, sanitizer, summaries) | `qwen3:14b` Q4 (\~9 GB), or reuse `qwen3-vl:8b` text-only to avoid a swap | 6–9 GB | [Qwen3 14B is the 16 GB sweet spot with context to spare](https://localaimaster.com/vram/best-llm-16gb-vram); Gemma 3 12B is the multilingual alternative |
| Text embeddings | `bge-m3` (Ollama) or `nomic-embed-text` | <1 GB | Multilingual (names in Spanish/English/Japanese romaji), 1024-d for pgvector |
| Sanitizer, remote option | Claude API, text-only | 0 | Only when `sanitizer.backend: claude`; the image never leaves the machine |

**Loading plan**

- Resident: SigLIP + NSFW classifier (\~2 GB) in one PyTorch process with CUDA.
- Batch per stage, not per file: embed and gate every image in the batch first, then load the safe VLM for the safe batch, then the adult VLM for the adult batch, then the text LLM for judging and sanitization. Ollama `keep_alive` is set per stage so only one 6–9 GB model is loaded at a time.
- MVP shortcut: use `qwen3-vl:8b` for captions, judging and local sanitization. One swap fewer, and quality is enough to validate the pipeline; split into a dedicated text LLM later if the judge's verdicts are weak.
- Phase 2 if you want more headroom: `qwen3-vl:30b-a3b` (MoE, \~3B active) [runs partially offloaded on a 16 GB card at usable speed](https://www.glukhov.org/post/2026/01/choosing-best-llm-for-ollama-on-16gb-vram-gpu/), or Gemma 3 27B at Q3.

**Throughput target:** on this card, SigLIP + NSFW gate should clear roughly 20–40 images/s; the VLM caption is the bottleneck at about 1–3 s per image, so a 5,000-image backlog is a few hours of unattended run, which is why captioning is batched after classification rather than inline.

## Tech stack, project structure and milestones

Python 3.12 with LangGraph for the pipeline graph, Ollama for the swappable models, PyTorch for the resident classifiers, and Postgres 16 + pgvector in Docker. Playwright is not needed; the CLI is Typer, and a small FastAPI status endpoint is optional for a later UI.

```
classifier/
  cli/            # typer commands: sort, watch, dry-run, reclassify, categories, templates, refs, purge-done, delete, serve, report
  graph/          # langgraph nodes: ingest, sanitize, classify, caption, retrieve, name, fileops
  models/         # siglip.py, nsfw.py, vlm.py (ollama client), text_llm.py, embed.py
  sanitize/       # rules.py (literal/regex/entity/exif), log.py
  rag/            # store.py (pgvector), judge.py, web.py (searxng/brave/claude backends), ingest.py
  naming/         # templates.py, tokens.py, render.py
  fileops/        # copy_move.py, ledger.py, delete.py, thumbs.py
  api/            # fastapi app: status, files, actions, sse; report.py (html export)
  ui/             # index.html + htmx/alpine, no build step
  db/             # alembic migrations, models.py
  config.yaml  sanitize.yaml  docker-compose.yml  tests/
```

**Milestones (each gated; nothing from the next starts until the gate passes)**

1. **Skeleton + ledger** — Postgres up, `files` table, hashing, `dry-run` producing a CSV. Gate: re-running on the same folder skips every file.
2. **Sanitize** — EXIF strip, literal/regex rules, `sanitize_log`, local LLM entity rule. Gate: a test set of 50 names with seeded sensitive values comes out fully redacted.
3. **Classify** — SigLIP + NSFW gate, default categories, mirror mode, thresholds, `Unsorted`, folder creation, category CLI. Gate: ≥ 90% agreement with your manual labels on a 300-image sample across safe and adult; unrecognized rate under 10%.
4. **Status UI, read-only** — FastAPI `/api/status` and `/api/files`, dashboard page, `classifier report`. Built right after Classify so the next gates are checked in the browser instead of a CSV. Gate: a 300-image dry run can be reviewed end to end without opening a terminal.
5. **Name** — built-in templates, user templates, caption tokens from the two VLMs, collision handling. Gate: zero sensitive values in 500 generated names; names readable without opening the file.
6. **RAG + web** — pgvector store, judge node, SearXNG backend, write-back, `refs` CLI. Gate: a franchise searched once is resolved locally on the second image without a web call.
7. **File ops + watch** — copy/rename/move transaction, `done/`, `watch`, `purge-done` and `delete` as separate commands. Gate: kill the process mid-run and restart with no duplicates, no lost files.
8. **UI write actions** — review queue with assign, rerun, pause/resume. Gate: every `Unsorted/` file from the 300-image sample can be filed from the browser and the ledger matches the disk.

Other file types (PDF, video, audio, archives) are a separate plan written only after milestone 6 is stable on your real folder.

## Development by a Claude Code agent team

The plan is built milestone by milestone by a team of Claude Code sessions hired at desks in [agent-office](https://github.com/AgentSystemLabs/agent-office) on your machine, with GitHub issues as the task list, pull requests as the review step, one human review gate per milestone, and the office floor as the view you open whenever you want to see who is doing what. Claude Code's [agent teams](https://code.claude.com/docs/en/agent-teams) (experimental, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) remain a fallback; [subagents](https://code.claude.com/docs/en/subagents-and-plugins.md) cover the short review jobs; [git worktrees](https://code.claude.com/docs/en/worktrees.md) keep workers from editing the same files.

One thing to be clear about: "local" here means the repo, Postgres, Ollama, tests and the board run on the RTX box and nothing about your images leaves it. The agents themselves are Claude models served by Anthropic, so a team consumes your Claude Code subscription or API usage; it is not free of cloud credits. The levers that keep that bill small are below (team size, model per role, scoped tasks). A fully local alternative would be a harness driving an Ollama model (for example OpenCode or Aider with Qwen3-Coder), at a real cost in autonomy and code quality; the recommendation is Claude Code with cost controls.

**Roles** (files in `.claude/agents/`; a teammate owns its folders and does not edit others')

| Role | Type | Model | Owns | Responsibility |
| --- | --- | --- | --- | --- |
| Lead | lead desk in agent-office; coordinates only | Opus | nothing (no code edits) | reads this doc, turns one milestone into tasks with dependencies, assigns, approves plans, merges to `main`, writes the milestone report |
| Pipeline engineer | teammate | Sonnet | `graph/`, `naming/`, `fileops/`, `db/`, `cli/` | LangGraph nodes, ledger, templates, copy/move transaction, CLI commands |
| ML engineer | teammate | Sonnet | `models/`, `prompts/`, `eval/` | SigLIP/NSFW/VLM wrappers, Ollama swapping, caption prompts, the labelled-sample evaluation harness |
| Data/RAG engineer | teammate | Sonnet | `rag/`, migrations for `references*` | pgvector store, judge node, SearXNG backend, write-back |
| API/UI engineer | teammate | Sonnet | `api/`, `ui/`, `report.py` | FastAPI, SSE, htmx dashboard, HTML export |
| QA engineer | teammate | Sonnet | `tests/`, `fixtures/`, `scripts/gate_*.py` | fixtures, integration tests, the scripts that measure each milestone gate |
| Reviewer | subagent, read-only tools | Sonnet | — | reviews every task's diff for correctness, test coverage and the privacy rule (nothing leaves the machine); runs before merge |
| Privacy auditor | subagent, read-only | Haiku | — | greps each diff for outbound HTTP, image uploads, logged filenames or EXIF values |

Run three or four teammates at a time, never all six: milestone 1 is Lead + Pipeline + QA; milestone 3 adds ML; milestone 4 swaps in API/UI; milestones 5–6 bring in RAG. A smaller team keeps the lead coordinating less and the token bill lower.

**Per-task workflow (enforced by hooks, not by asking)**

1. Lead opens a GitHub issue per task with the acceptance test named (`scripts/gate_3.py` or a pytest path), labels it with the milestone and the owning role, and assigns it to the worker's desk in agent-office.
2. Worker starts in its own worktree (`claude --worktree <issue>`), writes a short plan as the first issue comment; lead approves or redirects before any code is written.
3. Worker implements; `PostToolUse` hook runs `ruff` and the touched tests on every edit.
4. Worker pushes and opens a pull request; the `Stop` hook (and the pre-push hook) runs the full compose `test` profile and the task's acceptance test and fails the push if either fails.
5. Lead spawns the Reviewer and Privacy auditor subagents on the PR diff; findings go back as PR comments or a new issue if blocking.
6. Lead merges the PR to `main` and closes the issue; the `SessionStart`/`Stop`/`SubagentStop`/`PostToolUse` hooks have appended one JSON line each to `.claude/events.jsonl` along the way, and agent-office shows the issue and PR moving on the floor.

**Human review gates**

| Gate | When | What you review | How the next step is unblocked |
| --- | --- | --- | --- |
| G0 plan | before milestone N starts | the lead's task breakdown in `docs/plans/mN.md` and the issues it opened | you set `status: approved` in that file; the lead's `CLAUDE.md` forbids assigning issues for milestone N before that |
| G1 demo | milestone N issues all closed | `make gate-N` output and, from milestone 4 on, the status UI on a dry run of your real folder | you create the git tag `mN-approved`; the lead may not plan milestone N+1 without that tag |
| G2 ad hoc | any time | agent-office (desks, live terminals, open issues and PRs), `git log --graph --all` | you talk to a desk directly in agent-office or comment on the issue |

Each milestone is one lead session; shut the team down after G1 and start the next session fresh so context stays small and a bad run cannot leak into the next milestone.

**Visual tracking on demand**

- agent-office is the tracking surface: each desk is one Claude Code session with a live terminal you can open at any moment, and the floor shows the repo's open issues and pull requests, so the state of a milestone is visible without asking any model.
- Event trail: hooks append one JSON line per lifecycle event to `.claude/events.jsonl` (session, role, issue, tool, files touched, test result) for audit and for the cost summary per milestone.
- Review trail: every merged task leaves `docs/tasks/<id>.md` (plan, diff summary, reviewer verdict) written by the lead, so a milestone can be audited from files alone.
- Future side feature: agent-orchestrator (see the runbook) as a Kanban over the same issues and worktrees if agent-office's issue/PR view turns out too coarse.

**Cost and safety controls**

- `CLAUDE.md` rules: no network calls except Ollama, Postgres and SearXNG on localhost; never read `source_root/` originals in tests (use `fixtures/`); never commit images.
- `--permission-mode` per role: teammates in `acceptEdits` inside their worktree; the lead in `plan` mode outside gates; subagents read-only.
- Scoped tasks of a few files each; the lead never assigns "implement milestone 3" as one task.
- The fixture set (300 labelled images, safe and adult) is prepared by you once; it is the only image data agents ever see.

**Docker for all development and runtime services**

Everything the agents build, test and run lives in `docker-compose.yml`, so a teammate's environment is the same as yours and the gate scripts run the same way at review time.

| Service | Image | Notes |
| --- | --- | --- |
| `db` | `pgvector/pgvector:pg16` | ledger, config tables, reference store; volume `pgdata`; migrations run by the `app` entrypoint |
| `ollama` | `ollama/ollama` with the NVIDIA Container Toolkit (`gpus: all`) | models volume `ollama`; the VLM and text LLM tags are pulled once by `make models` |
| `searxng` | `searxng/searxng` | local search backend for the RAG web branch; JSON format enabled |
| `app` | built from `Dockerfile` (python 3.12, torch CUDA, `gpus: all`) | runs the pipeline, the FastAPI UI on `127.0.0.1:8000`, SigLIP and the NSFW classifier; mounts `source_root`, `output_root` and `fixtures/` |
| `test` | same image, profile `test` | `pytest` against a throwaway `db` and `fixtures/`; this is what the pre-push and `Stop` hooks call (`docker compose --profile test run --rm test`) |

agent-office itself is a Node service on the host, not a compose service, because it owns the Claude Code sessions and your GitHub login.

- Claude Code itself runs on the host (it needs your login and the worktrees), and every build, test and run command in `CLAUDE.md` is spelled as a `docker compose` invocation, so no teammate installs Python packages or touches the host GPU directly. An optional `.devcontainer/` lets you open the repo in VS Code inside the `app` image with Claude Code preinstalled.
- Images, Postgres data and Ollama weights are volumes, not part of any image; `fixtures/` is the only image folder mounted into `test`.
- Ports bind to `127.0.0.1` only, and the compose network has no route to the internet except `searxng` (and `ollama` for pulls); the Privacy auditor checks that this stays true in every change to the compose file.

**Harness options around the agent team**

| Option | What it adds | Fit for this project |
| --- | --- | --- |
| Claude Code agent teams + hooks + a project plugin (`.claude-plugin/`) | the team, the task list and the gates above, packaged so the roles, hooks and skills install in one step | the role, hook and gate layer that agent-office's desks run on |
| [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview) (Python/TypeScript) | your own orchestrator script: spawn one fresh agent per task from a queue, enforce gates in code, write the board events yourself | the upgrade if agent teams' experimental limits (one team per session, no resume) get in the way; keeps the same `.claude/agents/` role files |
| Issue-queue orchestrators on the Agent SDK (e.g. [mala](https://pypi.org/project/mala-agent/) with the Beads issue tracker) | a queue of small issues, one fresh agent each, file locks, validation triggers, a devcontainer | worth a look for milestones 5–8 once tasks are many and small; verify maintenance before adopting |
| Local-model harnesses (OpenCode, Aider, OpenHands with an Ollama model) | zero Claude usage | not integrable as teammates; only as a full replacement, at a quality cost |

Start with the baseline and revisit the SDK route at the milestone-4 review if coordination overhead or session limits are hurting.

## Setup runbook — from empty machine to an autonomous team

The team is "autonomous enough" when a whole milestone runs from G0 to G1 with no human message in between, every bad completion is blocked by a hook rather than by you noticing, and the board shows the state without asking a model. The steps below get there in order; each has a check you can verify before the next.

**Review notes on the plan before executing it**

- The 300-image labelled fixture set is the only piece an agent cannot produce; without it milestone 3 has no gate. It is step 2 below, before any agent runs.
- Agent teams are experimental (one team per session, no resume). The runbook therefore uses agent-office, where each desk is a full Claude Code session, GitHub issues are the task queue and pull requests are the review step; that matches the human gates better than a chat lead. Native agent teams stay as the fallback (step 5B).
- agent-office replaces the home-built `tools/board.py` and the `board` compose service; the product's own Stage 6 UI is unaffected.
- Docker with GPU on Windows means WSL2 + NVIDIA Container Toolkit; the whole repo should live inside the WSL filesystem for I/O speed.
- agent-office needs a GitHub repo for issues and PRs. The private repo holds code only (images are git-ignored). A local Gitea is possible later but is not what agent-office signs in to, so GitHub is the default.

**Candidate repos found for the orchestration and tracking layer**

| Repo | What it does | Agents | Fit here |
| --- | --- | --- | --- |
| [AgentSystemLabs/agent-office](https://github.com/AgentSystemLabs/agent-office) | 3D office: workers at desks are Claude Code sessions with live shared terminals, voice, GitHub issues and PRs per repo; runs locally or self-hosted | claude, codex, opencode, cursor-agent and others, chosen with `--agent` | the most visual option and the closest to "watch the team"; needs GitHub sign-in and a Node 22 host service |
| [Untrivial-ai/agent-orchestrator](https://github.com/Untrivial-ai/agent-orchestrator) | live Kanban where each card is a worker with its worktree, PR, CI and review state; an orchestrator plans and delegates larger outcomes; Apache-2.0 | Claude Code, Codex and 25+ harnesses | strongest operational fit: PR-based gates, worktrees, CI reflected on the card |
| [Vibe Kanban](https://github.com/BloopAI/vibe-kanban) (community-maintained) | web Kanban with worktree per task and MCP-driven task decomposition | 10+ incl. Claude Code, Codex, OpenCode, Qwen Code | good, lighter alternative to the above |
| [mraza007/baton](https://github.com/mraza007/baton) | polls GitHub Issues, runs Claude Code in a worktree per issue, reconciles; CLI | Claude Code (command configurable) | minimal queue runner if you want issues as the only source of truth |
| [hongbietcode/claude-team](https://github.com/hongbietcode/claude-team) | CONDUCTOR / ENGINEER / TESTER roles on a shared Kanban with a web dashboard streaming terminals | Claude Code | closest to the roles model, smaller community |
| [alessiocol/claude-kanban](https://github.com/alessiocol/claude-kanban) | hook-enforced state machine (UNCLAIMED → IN\_PROGRESS → IN\_REVIEW → COMPLETED) in `ACTIVE.md`, WIP limit per agent | Claude Code | no UI; a good template for the hook logic even if you use another board |
| [langwatch/kanban-code](https://github.com/langwatch/kanban-code) | desktop Kanban over `~/.claude/projects/` sessions with worktrees and PR tracking | Claude Code | macOS-only, listed for completeness |

Decision: **agent-office** is the team surface for this project (desks, live terminals, issues and PRs). **agent-orchestrator** is recorded as a future side feature: a Kanban over the same issues, worktrees and PRs with CI and review state on each card, to add after milestone 8 if the issue/PR view in agent-office proves too coarse. Both can coexist because the roles, hooks and gates live in the repo, not in the tool.

**Step-by-step**

1. **Host prerequisites (you, \~1 h).** WSL2 Ubuntu 24.04 (or native Linux), NVIDIA driver, Docker Engine + NVIDIA Container Toolkit, git, GitHub CLI signed in, Node 22, tmux, Claude Code (`npm i -g @anthropic-ai/claude-code && claude login`). Check: `docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi` shows the 5080.
2. **Fixture set (you, the longest chore).** Pick 300 images across the default categories, safe and adult; put them in `fixtures/images/` and label them in `fixtures/labels.csv` (`file, category, adult, reference`). Git-ignore `fixtures/images/`; keep it only on the box. Check: `wc -l fixtures/labels.csv` = 301.
3. **Repo bootstrap (lead session, you review).** Create the private GitHub repo and run one Claude Code session on the host with this plan as `docs/PLAN.md`, asking it to generate: `docker-compose.yml` (services from the Docker clause), `Dockerfile`, `Makefile` (`up`, `models`, `test`, `gate-N`, `lint`), `config.yaml`, `sanitize.yaml`, `pyproject.toml`, `.gitignore`, and empty package folders from the project structure. Check: `make up && make test` runs an empty pytest suite inside the `test` profile and `make models` pulls the Ollama tags.
4. **Agent configuration (same session).** Generate `CLAUDE.md` (rules from the Cost and safety list, all commands as `docker compose`, the gate rules from the Human review gates table), `.claude/agents/*.md` for the eight roles with their owned folders, `.claude/settings.json` hooks: `PostToolUse` → ruff + touched tests; `Stop` and a git pre-push hook → `docker compose --profile test run --rm test` plus the issue's `scripts/gate_N.py`, non-zero blocks the push; every event → append to `.claude/events.jsonl`. Add `docs/plans/TEMPLATE.md`, `docs/tasks/`, issue and PR templates under `.github/`, and `scripts/gate_1.py` through `gate_8.py` as stubs that fail. Commit. Check: edit a file by hand in a `claude` session and see the lint hook run; push a branch with a failing test and see it rejected.
5. **Team surface.** 5A (chosen): install agent-office (`curl -fsSL https://raw.githubusercontent.com/AgentSystemLabs/agent-office/main/install.sh | bash`), start it, sign in with GitHub, add the repo as a floor, hire one desk per active role (lead + 2–3 workers) with `--agent claude`. In each worker desk the session starts with `claude --worktree --permission-mode acceptEdits`; the lead desk runs plain `claude`. 5B (native fallback): `export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, `claude --teammate-mode tmux`. Check: the floor shows the repo with zero open issues and the desks idle.
6. **Harness dry run (half a day).** Open one trivial issue ("add `make lint` and a passing test") and let it flow: lead assigns it, worker creates its worktree, writes the plan comment, you approve, implementation, hooks run tests, PR opened, Reviewer and Privacy auditor subagents comment, lead merges. Then open an issue designed to fail its test and confirm the push is rejected. Fix the hooks until both behave. Check: one closed issue with a merged PR, one open issue whose PR could not be pushed, both visible on the floor.
7. **Milestone 1 for real.** Send the lead desk the G0 request: "plan milestone 1 from docs/PLAN.md into issues ≤ 1 day each with their acceptance test". Review `docs/plans/m1.md`, set `status: approved`, start the run with Pipeline + QA desks. Do not intervene. At the end run `make gate-1`, review the output, tag `m1-approved`. Check: `.claude/events.jsonl` and the issues show no human message between approval and gate.
8. **Autonomy from milestone 2.** Give the lead a standing instruction in `CLAUDE.md`: on start, find the highest `mN-approved` tag, plan milestone N+1 into issues, wait for approval, assign and run, stop at the gate. Your only actions become: approve a plan, review a gate, tag. Open agent-office when you want to look. Record cost per milestone from the desks' token usage in `docs/tasks/mN-summary.md`.
9. **Exit criteria for "set up".** Milestone 2 completes with zero human messages between G0 and G1, every issue has a PR with reviewer comments, every push was gated by the test hook, agent-office reflected the state without any prompt to a model, and no process in compose ever reached the internet except SearXNG and Ollama pulls (`docker network inspect` plus the Privacy auditor's log).
10. **Later side feature.** Add agent-orchestrator as a Kanban over the same issues and PRs once milestone 8 is done, if a per-card CI/review view is wanted; no change to hooks or roles is required.
