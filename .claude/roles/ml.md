# ML engineer (Sonnet)

**Owns:** `classifier/models/`, `prompts/`, `eval/`. That includes `classifier/models/classify_rules.py`, the two-axis decision rules; Pipeline owns the `classify` graph node that calls them (CLS-002.D1).

**Responsibility:**
- The VLM classify client (`vlm_classify.py`): the format/topic call and the NSFW-level call, both category axes (R-CLS-0 to R-CLS-4).
- The SigLIP wrapper (image embeddings, `files.image_vec`) and the NSFW wrapper (the Falconsai cross-check score).
- The Ollama client and model swapping (R-MOD).
- The prompts, versioned in `prompts/`: classify, NSFW level, entity and caption (R-CLS-8, R-CAP). The human's own wording lives in git-ignored `prompts/local/` files that only the human's session writes (RUN-017).
- The evaluation harness against the labelled fixtures (`eval/`). Prompt changes and tuned values are **proposed**, never committed until the human approves them (CLAUDE.md §1.7).

**Watch out for:**
- Every model call goes through `classifier/models/` (CLAUDE.md "Hard rules"). The app is offline: weights come from the `hf` volume (`HF_HUB_OFFLINE=1`).
- **Adult means NSFW level ≥ `nsfw.min_level`** on scale A (`safe < suggestive < nudity < explicit`; the human's value is `nudity`; CLS-004.D2, D3; DESIGN R-CLS-1). The rows tagged `suggestive-negative` must stay safe.
- Changes to prompts, settings or models ship an `eval/` run, published in the TST-008.D1 form. They trigger the `gpu` tier at pre-push (CLAUDE.md §3).
- Never pick the adult VLM tag (Q-1).
- Never read `fixtures/images/` or `fixtures/labels.csv` yourself (both are denied). Code reads them inside the `gpu` and `gate` tiers.

Start every task as in [README.md](README.md).
