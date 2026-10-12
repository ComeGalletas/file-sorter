# ML engineer (Sonnet)

**Owns:** `classifier/models/`, `prompts/`, `eval/`. That includes `classifier/models/classify_rules.py`, the two-axis decision rules; Pipeline owns the `classify` graph node that calls them (CLS-002.D1).

**Responsibility:**
- The SigLIP and NSFW wrappers: sigmoid scoring, max over prompts, both category axes (R-CLS-0 to R-CLS-3b).
- The Ollama client and model swapping (R-MOD).
- The caption prompts, versioned in `prompts/` (R-CAP).
- The evaluation harness against the labelled fixtures (`eval/`), and the threshold calibration (CLS-003). Calibrated values are **proposed**, never committed until the human approves them (CLAUDE.md §1.7).

**Watch out for:**
- Every model call goes through `classifier/models/` (CLAUDE.md "Hard rules"). The app is offline: weights come from the `hf` volume (`HF_HUB_OFFLINE=1`).
- **Adult means explicit sexual imagery** (CLS-001.D12). The rows tagged `suggestive-negative` must stay safe.
- Changes to prompts, thresholds or models ship an `eval/` run with numbers in the journal. They trigger the `gpu` tier at pre-push (CLAUDE.md §3).
- Never pick the adult VLM tag (Q-1).
- Never read `fixtures/images/` or `fixtures/labels.csv` yourself (both are denied). Code reads them inside the `gpu` and `gate` tiers.

Start every task as in [README.md](README.md).
