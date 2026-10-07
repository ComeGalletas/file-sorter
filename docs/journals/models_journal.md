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
- **MOD-001.D5** — **The entity prompt runs raw, without thinking** (lead, 2026-10-07, on #51). D2's check: on `ollama/ollama:0.35.1`, `qwen3-vl:8b` **accepts `think: false` but ignores it**. Probe on synthetic strings, temperature 0, seed 7:

  | Request | Per filename-like string |
  | --- | --- |
  | default (no `think`) | ~3 000 thinking tokens, ~30 s; once cut off at the length limit with an empty `response` |
  | `think: false` | HTTP 200, but still ~3 000 thinking tokens, ~30 s |
  | `/no_think` in the prompt | ~2 800 thinking tokens, ~28 s |
  | `think: false` + `/no_think` | cut off at the length limit, empty `response` |
  | `raw: true`, ChatML user turn + empty think block | 0.1–0.8 s, 6–60 tokens, no thinking, valid JSON |

  So: `OllamaClient.generate_json` gains `raw: bool = False`, sent only when true. The prompt front matter gains an optional `wrap` with one `{prompt}` slot, which goes with `raw: true`. `sanitize_entity_v1` carries the ChatML wrapper; it is the only model-specific part, and a change of `models.text_llm` family means a new prompt version. Fail closed still holds: `done_reason: length` or an empty `response` is an `OllamaError`, and `num_predict` is bounded in the front matter. The recording key includes `raw` when sent: `{model, prompt, format, options, think?, raw?}`, never `keep_alive` or `stream` (amends TST-005.D5).

## MOD-001 — Plan

1. **MOD-001.1, the client:** `OllamaClient(host, transport=None)` with `generate_json(model, prompt, schema, options, keep_alive)`. The host check, the timeout, and `OllamaError` for connection errors, HTTP errors and invalid JSON. Unit tests through `httpx.MockTransport`: request shape, options passed through, each error mapped, a non-compose host refused.
2. **MOD-001.2, entity detection:** `prompts/sanitize_entity_v1.md` (front matter per D1) and `detect_entities`. A `gpu` test on synthetic strings with real Ollama: known people, organisations and places found, plain dates and counters left alone, the same output on two calls. It also produces the replay recordings for SAN-001.3 and SAN-001.4 (the ML worker commits them itself, under `tests/recordings/<package>/`, synthetic strings only: TST-005.D1, DOC-007.D5). The eval per D3.

## MOD-001 — Tasks

- [x] MOD-001.1 — The Ollama text client with a transport seam · #50 · acceptance: `tests/unit/models/test_ollama_client.py`
  - [x] MOD-001.1.1 — `classifier/models/ollama.py` and its unit tests · 6852fac
  - [x] MOD-001.1.2 — A `gpu` round trip against the real `ollama` service (discovered: the `gpu` tier was empty, so pre-push failed with "no tests collected") (hash in Results)
- [x] MOD-001.2 — The entity-detection prompt and `detect_entities`, with its eval and recordings · #51 · acceptance: `tests/gpu/models/test_entity_detection.py`
  - [x] MOD-001.2.1 — `prompts/sanitize_entity_v1.md` and the prompt loader `classifier/models/prompts.py`, with unit tests · 192f9a5
  - [x] MOD-001.2.2 — `detect_entities` and `Entity` in `classifier/models/text_llm.py`, with the D2 filters and unit tests · b6d0620
  - [x] MOD-001.2.3 — The `gpu` acceptance test on synthetic strings, with the recorder · 27cf267
  - [x] MOD-001.2.4 — The eval (D3) on fictional names in `eval/`, the prompt rules it drove, and the recordings re-made for the new prompt · 24b68cf
  - [x] MOD-001.2.5 — The replay recordings under `tests/recordings/models/`, 18 files. They landed in .2.3's commit (27cf267) because the acceptance test checks every live answer against its recording and is red without them, and were re-made in .2.4's (24b68cf) when the prompt changed.
  - [x] MOD-001.2.6 — Raw mode for the entity prompt (D5, discovered: `think: false` is ignored by the tag): `raw` in the client, `wrap` and `num_predict` in the front matter, a cut-off answer fails closed · e2304f1
  - [x] MOD-001.2.7 — PR #72 round 1: neutralize ChatML control tokens, think tags and fence markers in the text before rendering; spans still matched against the original (hash in Results)
  - [x] MOD-001.2.8 — PR #72 round 1: injection-style synthetic names in the gpu test, with their recordings (3 new; the 18 existing keys are unchanged) (hash in Results)
  - [ ] MOD-001.2.9 — PR #72 round 1: replace real or unconfirmed names in the eval list, re-run the eval

## MOD-001 — Results

### MOD-001.1 (worker: ml)

- **Built:** `OllamaClient(host, transport=None, timeout=DEFAULT_TIMEOUT)`, `from_env()` (reads `OLLAMA_HOST`, no default URL), `generate_json(model, prompt, schema, options, keep_alive, think=None)` → `POST /api/generate` with `model`, `prompt`, `format`, `options`, `keep_alive`, `stream: false`, and `think` only when set. One `OllamaError` for a refused host, connection error, timeout, HTTP error, a non-JSON body, a body without a text `response`, and an answer that isn't a JSON object. Errors carry the model tag and an 8-hex prompt hash, never the prompt or the answer. The host allow-list is exactly `ollama`, `localhost`, `127.0.0.1`, `::1` and is checked even when a transport is passed. Text only: no `images` field.
- **Transport seam (for TST-005.1):** the `transport` parameter, a plain `httpx.BaseTransport` handed to `httpx.Client(transport=...)`.
- **Tests:** `tests/unit/models/test_ollama_client.py`, 41 unit tests through `httpx.MockTransport`. `make test` (unit + db + integration): 483 passed. `make lint`: clean. Tier audit: clean (no Ollama port literal in the unit test). `tests/gpu/models/test_ollama_roundtrip.py`: 2 passed against the real service (`models.text_llm`, temperature 0, seed 7, `keep_alive: 0`; one schema-constrained answer, and an unknown tag mapped to `OllamaError`).
- **Status:** DONE_WITH_CONCERNS.
  - Concern (medium): the `test` service doesn't start `ollama` (no `depends_on`), so in a worktree's compose project the `gpu` tier reaches Ollama only after `docker compose -p file-sorter-<worktree> up -d ollama` by hand. Before this task the `gpu` tier was empty and pre-push failed on pytest's "no tests collected" exit code. Follow-up: an issue for the RUN owner.
- **Self-rating:** 9/10, proud: yes. Gap: whether the pinned Ollama accepts `think: false` for the tag is still unchecked; MOD-001.2 records it (D2).

### MOD-001.2 (worker: ml)

- **Eval (D3):** `python eval/entity_eval.py` in the `test` container, `sanitize_entity_v1`, `qwen3-vl:8b`, temperature 0, seed 7. The cases are filename-shaped strings built from the fictional lists in `eval/data/entity_synthetic.yaml` (12 patterns, 5 separators including CamelCase), plus 30 plain names with no entity. **Recall** is the share of seeded entities with every letter covered by a returned span (nothing would survive redaction). **Exact** means one span with the right label. **Spurious** is the share of returned spans touching no seeded entity. **False redaction** is the share of plain names with any span returned.

  | Run | Recall | Exact | Spurious | False redaction | Errors | Per call |
  | --- | --- | --- | --- | --- | --- | --- |
  | raw, first prompt draft, seed 20311, n 50 | 92.0% | 73.3% | 0.0% | 0.0% | 0.0% | 0.3 s |
  | raw, final prompt, seed 20311, n 50 (tuning draw) | 100.0% | 61.3% | 2.1% | 0.0% | 0.0% | 0.2 s |
  | raw, final prompt, seed 1, n 150 (used for the last rule) | 99.1% | 60.9% | 1.0% | 0.0% | 0.0% | 0.3 s |
  | **raw, final prompt, seed 2, n 150 (held out)** | **98.2%** | 61.8% | 0.3% | **0.0%** | 0.0% | 0.3 s |
  | thinking path (D5's alternative), final prompt, seed 20311, n 12 + 6 plain | 33.3% | 33.3% | 0.0% | 0.0% | 38.9% | 21.1 s |

  - Two prompt rules came from the misses: keep a generic word that belongs to a name ("<Name> Works"), and check every capitalised word, including a lone one before "trip". The examples in the prompt are placeholders, not eval names.
  - The remaining misses share one shape: a one-word place at the start of "<Place> trip <year> - <Person>".
  - "Exact" fell because the model now splits some multi-word names into word spans. Redaction coverage is unchanged by that.
  - In the thinking run, errors are answers cut off at the length limit (they fail closed in the app), and they count as misses. It shared the GPU with a recording run, so its per-call time is high.
- **Built:**
  - `prompts/sanitize_entity_v1.md`: front matter per D1 and D5 (temperature 0, seed 7, `keep_alive: 5m`, `num_predict: 512`, `raw: true`, the ChatML `wrap`, the D2 schema).
  - `classifier/models/prompts.py`: `load_prompt` and `Prompt` (strict front matter; `version` equals the file name; one-pass slot rendering).
  - `classifier/models/text_llm.py`: `detect_entities(text, labels, *, client, model, prompt=None)`, `Entity`, `ENTITY_LABELS`, `entity_prompt()`. It applies the D2 drops, collapses duplicates and keeps first-seen order. A badly shaped answer is an `OllamaError`.
  - `OllamaClient.generate_json` gains `raw`, and `done_reason: length` is now an error (D5).
- **Recordings:** 18 files in `tests/recordings/models/`, keyed per TST-005.D3 and D5 (`{model, prompt, format, options, think?, raw?}`). The response keeps `model`, `response`, `done` and `done_reason`. The gpu test writes them with `RECORD_OLLAMA=1` and otherwise checks every live answer against them. For SAN-001.4: the five `SANITIZE_STRINGS` in the gpu test are recorded with all three labels.
- **Tests:**
  - `make test` (unit + db + integration): 754 passed, after rebasing on 6203400. Unit tests added: `tests/unit/models/test_prompts.py`, `test_text_llm.py`, and 5 new cases in `test_ollama_client.py`.
  - The gpu tier (`tests/gpu/`): 22 passed against the real service, every recording matched.
  - `make lint`: clean.
- **Status:** DONE_WITH_CONCERNS.
  - Concern (medium): held-out recall is 98.2%, not 100%. The remaining misses are one shape (a one-word place leading "<Place> trip <year> - <Person>"). Gate 2 allows 0 surviving seeded values, so its entity share could fail on that shape. Follow-up: if gate 2 (TST-005.2) shows survivors, the next step is a new prompt version (`sanitize_entity_v2`) as an ML issue, not more tuning of v1 against the same draws.
  - Concern (low): the recorder and `recording_key` live in the gpu test until TST-005.1 (#55) lands its replay. Once it does, the test should switch to QA's record mode, and the keys must match (same rule, posted on #55).
- **Self-rating:** 8/10, proud: yes. Gaps against #51 and its R-IDs:
  1. Recall is short of the gate's zero-survivor bar on one filename shape (R-SAN-3; see the concern above).
  2. The recorder duplicates what TST-005.1 will own, until #55 merges.
- **Reviewer / Privacy auditor:** pending (lead).
