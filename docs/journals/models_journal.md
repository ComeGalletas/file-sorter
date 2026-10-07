# Models — journal

**ID:** MOD-001 · **Systems:** MOD (+ SAN, TST) · **Type:** feature · **Status:** proposed · **Milestone:** m2 ·
**Issues:** MOD-001.1 #50, MOD-001.2 #51 · **Branch:** per task (`office/*`)

<!--
Rules: CLAUDE.md §1 (DOC-001). Public repo: never write image file names, captions,
references, host paths or the human's sanitize.yaml values here. Use hashes.
-->

---

## MOD-001 — Requirement (DESIGN.md M2, C-13, 2026-10-07)

- **Objective:** Give the app one Ollama client, and use it for the sanitizer's entity detection.
- **Details:**
  - `classifier/models/ollama.py`: a text client over `httpx` to `OLLAMA_HOST` (compose sets `http://ollama:11434`). Structured JSON output, per-call sampling options, `keep_alive` per stage (R-MOD-1), a timeout, and one typed error for every failure.
  - A transport seam, so tests replay recorded responses instead of calling Ollama (CLAUDE.md §3; TST-005.1).
  - `detect_entities(text, labels) -> list[Entity]` in `classifier/models/text_llm.py`, with its prompt versioned in `prompts/` (R-CAP-3's rule applies to every prompt).
  - The model tag comes from `models.text_llm` (`qwen3-vl:8b`, C-1). No tag is hard-coded.
- **Constraint:**
  - Every model call goes through `classifier/models/` (CLAUDE.md hard rule). Text only; no pixels.
  - The client refuses any host other than the compose `ollama` service or localhost (CLAUDE.md network rule).
  - `models.vlm_nsfw` stays unset (Q-1).
  - Recordings are made only from synthetic strings (SAN-001.D10).
- **Implements:** R-SAN-3 (`entity`), R-SAN-4, R-MOD-1, P-2, P-3, C-1, C-13.

## MOD-001 — Confirmed reading

- `classifier/models/` and `prompts/` are empty. `httpx>=0.27` is already a dependency. `make models` already pulls `qwen3-vl:8b`.
- The `ollama/ollama:0.35.1` image has qwen3vl support (R-RUN-5).
- The `gpu` tier runs at pre-push when `classifier/models/` or `prompts/` change. It calls Ollama with temperature 0 and a fixed seed (CLAUDE.md §3).
- **MOD-001.D1** — **Sampling and `keep_alive` live in the prompt file** (lead, 2026-10-07). Each prompt in `prompts/` carries front matter: `version`, `temperature`, `seed`, `keep_alive`, and the output JSON schema. The client reads them from there, so no value is hard-coded and no config key is added. The prompt's `version` is what a later stage records on the ledger (R-CAP-3).
- **MOD-001.D2** — **Entity output** (lead, 2026-10-07). The model answers through Ollama's `format` JSON schema: `{"entities": [{"text": ..., "label": ...}]}`. `detect_entities` drops a span that isn't literally in the input, and a label outside the requested ones. Thinking output is turned off for this call (`think: false`), if the pinned Ollama accepts it for the tag; the worker checks and records which.
- **MOD-001.D3** — **Eval for the entity prompt** (lead, 2026-10-07). §3 asks for an `eval/` run when a prompt changes. For this prompt, the eval is gate 2's seeded-name measure (TST-005.2), run on synthetic names only in `eval/`, with the numbers in this journal: recall on seeded entities, and false redactions on a set of names with no entity.

## MOD-001 — Plan

1. **MOD-001.1, the client:** `OllamaClient(host, transport=None)` with `generate_json(model, prompt, schema, options, keep_alive)`. The host check, the timeout, and `OllamaError` for connection errors, HTTP errors and invalid JSON. Unit tests through `httpx.MockTransport`: request shape, options passed through, each error mapped, a non-compose host refused.
2. **MOD-001.2, entity detection:** `prompts/sanitize_entity_v1.md` (front matter per D1) and `detect_entities`. A `gpu` test on synthetic strings with real Ollama: known people, organisations and places found, plain dates and counters left alone, the same output on two calls. It also produces the replay recordings for SAN-001.3 and SAN-001.4 (the ML worker commits them itself, under `tests/recordings/<package>/`, synthetic strings only: TST-005.D1, DOC-007.D5). The eval per D3.

## MOD-001 — Tasks

- [ ] MOD-001.1 — The Ollama text client with a transport seam · #50 · acceptance: `tests/unit/models/test_ollama_client.py`
- [ ] MOD-001.2 — The entity-detection prompt and `detect_entities`, with its eval and recordings · #51 · acceptance: `tests/gpu/models/test_entity_detection.py`

## MOD-001 — Results

### MOD-001.1 (worker: ml)

- **Status:**

### MOD-001.2 (worker: ml)

- **Status:**
