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
- **MOD-001.D4** — **Client timeout** (lead, 2026-10-07, on #50). `OllamaClient` takes `timeout` as a constructor parameter, defaulting to the module constant `DEFAULT_TIMEOUT = 300.0` s, because the first call after a model swap loads a 6–9 GB model (R-MOD-1). No config key now; if tuning ever needs one, it becomes a Pipeline issue.

## MOD-001 — Plan

1. **MOD-001.1, the client:** `OllamaClient(host, transport=None)` with `generate_json(model, prompt, schema, options, keep_alive)`. The host check, the timeout, and `OllamaError` for connection errors, HTTP errors and invalid JSON. Unit tests through `httpx.MockTransport`: request shape, options passed through, each error mapped, a non-compose host refused.
2. **MOD-001.2, entity detection:** `prompts/sanitize_entity_v1.md` (front matter per D1) and `detect_entities`. A `gpu` test on synthetic strings with real Ollama: known people, organisations and places found, plain dates and counters left alone, the same output on two calls. It also produces the replay recordings for SAN-001.3 and SAN-001.4 (the ML worker commits them itself, under `tests/recordings/<package>/`, synthetic strings only: TST-005.D1, DOC-007.D5). The eval per D3.

## MOD-001 — Tasks

- [x] MOD-001.1 — The Ollama text client with a transport seam · #50 · acceptance: `tests/unit/models/test_ollama_client.py`
  - [x] MOD-001.1.1 — `classifier/models/ollama.py` and its unit tests · 6852fac
  - [x] MOD-001.1.2 — A `gpu` round trip against the real `ollama` service (discovered: the `gpu` tier was empty, so pre-push failed with "no tests collected") (hash in Results)
- [ ] MOD-001.2 — The entity-detection prompt and `detect_entities`, with its eval and recordings · #51 · acceptance: `tests/gpu/models/test_entity_detection.py`

## MOD-001 — Results

### MOD-001.1 (worker: ml)

- **Built:** `OllamaClient(host, transport=None, timeout=DEFAULT_TIMEOUT)`, `from_env()` (reads `OLLAMA_HOST`, no default URL), `generate_json(model, prompt, schema, options, keep_alive, think=None)` → `POST /api/generate` with `model`, `prompt`, `format`, `options`, `keep_alive`, `stream: false`, and `think` only when set. One `OllamaError` for a refused host, connection error, timeout, HTTP error, a non-JSON body, a body without a text `response`, and an answer that isn't a JSON object. Errors carry the model tag and an 8-hex prompt hash, never the prompt or the answer. The host allow-list is exactly `ollama`, `localhost`, `127.0.0.1`, `::1` and is checked even when a transport is passed. Text only: no `images` field.
- **Transport seam (for TST-005.1):** the `transport` parameter, a plain `httpx.BaseTransport` handed to `httpx.Client(transport=...)`.
- **Tests:** `tests/unit/models/test_ollama_client.py`, 41 unit tests through `httpx.MockTransport`. `make test` (unit + db + integration): 483 passed. `make lint`: clean. Tier audit: clean (no Ollama port literal in the unit test). `tests/gpu/models/test_ollama_roundtrip.py`: 2 passed against the real service (`models.text_llm`, temperature 0, seed 7, `keep_alive: 0`; one schema-constrained answer, and an unknown tag mapped to `OllamaError`).
- **Status:** DONE_WITH_CONCERNS.
  - Concern (medium): the `test` service doesn't start `ollama` (no `depends_on`), so in a worktree's compose project the `gpu` tier reaches Ollama only after `docker compose -p file-sorter-<worktree> up -d ollama` by hand. Before this task the `gpu` tier was empty and pre-push failed on pytest's "no tests collected" exit code. Follow-up: an issue for the RUN owner.
- **Self-rating:** 9/10, proud: yes. Gap: whether the pinned Ollama accepts `think: false` for the tag is still unchecked; MOD-001.2 records it (D2).

### MOD-001.2 (worker: ml)

- **Status:**
