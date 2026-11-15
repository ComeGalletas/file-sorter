# Caption — journal

**ID:** CAP-001 · **Systems:** CAP (+ MOD, PIPE, SAN) · **Type:** feature ·
**Status:** proposed (M5 G0) · **Milestone:** m5 ·
**Issues:** see the Tasks section · **Branch:** per task (`office/*`)

<!--
Rules: CLAUDE.md §1 (DOC-001). Public repo: never write image file names, captions of real images, references or host paths here. Use hashes.
-->

---

## CAP-001 — Requirement (DESIGN.md m5, 2026-11-15)

- **Objective:** Caption every classified image with a subject, a detail, a one-sentence caption and tags, from the branch's VLM, for the name step to use.
- **Details:**
  - the safe branch on `models.vlm_safe` and the adult branch on `models.vlm_nsfw`. Both are `qwen3-vl:8b-instruct` (Q-1 answered b), so one model stays resident;
  - versioned prompts `prompts/caption_safe_v1.md` and `prompts/caption_nsfw_v1.md`, with local replacements on the box (answer 5);
  - per-stage batches; the caption sanitized on write (answer 6); status `captioned`.
- **Constraint:**
  - the adult prompt asks for neutral, non-graphic descriptors (R-CAP-2);
  - no real person is named (answer 7);
  - visible text is not transcribed (answer 8);
  - only the sanitized name is used as a hint (P-2).
- **Implements:** R-CAP-1, R-CAP-2, R-CAP-3, R-MOD-1, P-2; the human's answers 1 and 5–8.

## CAP-001 — Confirmed reading

- **What exists:**
  - `classifier/models/vlm_classify.py` gives the client pattern (prompts with front matter, a JSON schema, one retry, `pick_frames`, image encoding, `VlmUnanswered`, `OllamaUnavailable`);
  - `prompts/` holds the classify and NSFW prompts, with local B′ replacements (CLS-004.8, CLS-008);
  - `files.caption` is jsonb, and `captioned` is in the status enum;
  - the sanitize rules live in `classifier/sanitize/` (Pipeline).
- **From the human's spike** (public form): the visible-text prompt rule alone isn't enough, so sanitize-on-write is a needed net. And more frames than `pick_frames` gives can overflow `num_ctx` 4096 on an animated image.
- **CAP-001.D1 — sanitizing on write** (lead, 2026-11-15, provisional): the same rules as names (literal, regex, entity), run as a batch after the caption batch inside the same node, so the text model loads once per run. Raw answers are held in memory only, never in the graph state, the ledger or a log.
- **CAP-001.D2 — the answer** (lead, provisional):
  - JSON with `subject` (1–3 words), `detail`, `caption` (one sentence) and `tags` (at most 8);
  - validated, with one retry;
  - low temperature, `num_ctx` 4096, and classify's image settings.
- **CAP-001.D3 — the caption prompt's version** (lead, provisional): stored inside `files.caption` (a `prompt_version` key). `files.prompt_version` keeps classify's version (CLS-004.7).
- **CAP-001.D4 — the hint** (lead, provisional): the sanitized name only, as classify does.

## CAP-001 — Plan

- **ML (CAP-001.1):**
  - `classifier/models/vlm_caption.py` with `vlm_caption(client, model, image, *, hint, branch) -> CaptionAnswer`;
  - `CaptionAnswer` is frozen, with every text field `repr=False`;
  - both committed prompts, generic, plus their `prompts/local/*.example.md`;
  - recordings from synthetic images only;
  - a `gpu` test on synthetic images, including one with printed coined text, to measure the visible-text rule.
- **Pipeline (CAP-001.2):**
  - the `caption` node runs per-stage batches by branch, then the sanitize batch, then writes `files.caption` and status `captioned`;
  - an unanswered call takes the fixed error code, as classify does.
- **Tests:** unit for the client (replay); db and integration for the node; plants in a recorded caption proved held raw, then absent from the stored row, the logs and the reprs (checklist item 17).

## CAP-001 — Tasks

- [ ] CAP-001.1 — The caption client and both prompts (safe and adult), the local examples, recordings · ML · acceptance: `tests/unit/models/test_vlm_caption.py`
- [ ] CAP-001.2 — The caption node: batches by branch, sanitize on write, `captioned` · Pipeline · acceptance: `tests/db/graph/test_caption_node.py`

## CAP-001 — Results
