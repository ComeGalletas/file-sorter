# Design review — journal

**ID:** DOC-002 · **Systems:** DOC (+ all) · **Type:** process · **Status:** done · **Milestone:** — ·
**Issues:** — (pre-repo) · **Branch:** pre-repo, committed at bootstrap

---

## DOC-002 — Requirement (human, 2026-10-05)

- **Objective:** Review the MVP design plan and turn it into a CLAUDE.md and a normative DESIGN.md, confirming every change with the human.
- **Details:** Find the plan's contradictions, factual errors and gaps. Propose a fix for each. Answer the plan's open questions.
- **Constraint:** The plan's decisions are final unless the human changes them, so every deviation is confirmed individually.
- **Implements:** DESIGN.md as a whole; §13 lists the deviations and §14 the questions.

and then: the human gave the source and results folders and described the folder's contents (a mix of mostly images, a few adult ones, many screenshots and snips).

and then: the human confirmed the M3 gate for the real folder, named the agent-office fork, and asked to check a candidate adult VLM.

## DOC-002 — Confirmed reading

The decisions below are the outcomes of DESIGN.md §13 (C-1 to C-20, each confirmed by the human) and of the §14 answers. DESIGN.md holds the full text; this list is the citable record.

- **DOC-002.D1 (C-1):** `qwen3-vl:8b` for the safe VLM, judge and local sanitizer in the MVP. Accepted; the model choice was the human's call delegated to Claude.
- **DOC-002.D2 (C-2):** Adult files use their category's template, plus a configurable `nsfw_` prefix (R-NAME-8). Changed by the human.
- **DOC-002.D3 (C-3):** The source folder is read-only and mounted `:ro`. Results go to a separate `results_root`; there is no `inbox/` or `done/`. `purge-done` becomes `purge-sources`, disabled by default. Changed by the human.
- **DOC-002.D4 (C-4):** Vectors are 1152-d (SigLIP so400m) and 1024-d (bge-m3 only). Accepted.
- **DOC-002.D5 (C-5):** Scores use the SigLIP sigmoid probability, max over prompts, with thresholds calibrated in M3. Accepted.
- **DOC-002.D6 (C-6):** Between a parent and child category, the child wins without the margin check (R-CLS-4). Accepted.
- **DOC-002.D7 (C-7):** Execution order is caption → retrieve → name. Accepted.
- **DOC-002.D8 (C-8):** Each stage processes a whole batch, with the ledger status as the checkpoint; file ops are per file. Accepted.
- **DOC-002.D9 (C-9):** One `needs_review` flag plus a reason; Unsorted is a category, not a status. Accepted.
- **DOC-002.D10 (C-10):** FastAPI is part of the MVP. Accepted.
- **DOC-002.D11 (C-11):** Add `hit_count`, a `runs` table and an advisory lock. Accepted.
- **DOC-002.D12 (C-12):** Pipeline owns `sanitize/`, and the missing folders are added to the tree. Accepted.
- **DOC-002.D13 (C-13):** The ML desk joins M2 for the Ollama client task. Accepted.
- **DOC-002.D14 (C-14):** Egress only through `docker-compose.egress.yml`; SearXNG is documented as outbound. Accepted.
- **DOC-002.D15 (C-15):** `make models` also fetches the HF weights, and the app runs offline. Accepted.
- **DOC-002.D16 (C-16):** The lead runs in default mode with `gh` and `git merge` allow-listed and edits on source folders denied. Accepted.
- **DOC-002.D17 (C-17):** Ruff after each edit, touched tests on `Stop`, and the full suite plus the acceptance test at pre-push. Accepted.
- **DOC-002.D18 (C-18):** Per-agent log subfolders, local only, never committed. Changed by the human; the folder location was later set by DOC-003.D2.
- **DOC-002.D19 (C-19):** `sanitize.example.yaml` is committed, and the real `sanitize.yaml` is git-ignored. Changed by the human.
- **DOC-002.D20 (C-20):** The malformed `/api/run` row and the lost diagrams are restated as text. Accepted.
- **DOC-002.D21 (Q-6):** Originals are never deleted after sorting. Deletion is a separate function, disabled by default (P-1, R-FOP-0, R-FOP-8).
- **DOC-002.D22 (Q-2):** The repo is on GitHub and **public**. The public-repo rules follow from that: no image names, host paths or real names in anything committed.
- **DOC-002.D23 (Q-7):** `fixtures/labels.csv` is git-ignored, and a 5-row synthetic `labels.example.csv` is committed.
- **DOC-002.D24 (Q-8):** The M3 gate is measured on the whole real folder (~150 images): at least 90% category agreement overall, every adult image caught, and no safe image flagged as adult.
- **DOC-002.D25 (Q-1):** The adult VLM stays open until M5 planning. The candidate `huihui_ai/qwen3-vl-abliterated:8b-instruct` was checked against the registry: qwen3vl family, 8.8B parameters, Q4_K_M, 6.1 GB, stock qwen3-vl-instruct renderer, default temperature 1.0.
- **DOC-002.D26:** The folder profile added three requirements:
  - R-ING-8: OS metadata files are ignored silently.
  - R-FOP-9: the bot refuses to start if source and results are nested.
  - Snip prompts for the Screenshots category, plus the original filename as a caption hint.
- **DOC-002.D27:** The M4 and M8 gates are sized to the real folder, replacing the plan's "300-image sample", as a consequence of D24. Made during DOC-001 (task DOC-002.4).

## DOC-002 — Plan

1. Review the plan.
2. Write CLAUDE.md and DESIGN.md.
3. Confirm the deviations in groups of four.
4. Apply the human's changes.
5. Record the open questions.

## DOC-002 — Tasks

- [x] DOC-002.1 — Review the plan; draft CLAUDE.md and DESIGN.md with C-1 to C-20 → `pre-repo`
- [x] DOC-002.2 — Confirm C-1 to C-20 with the human and apply the changes (C-2, C-3, C-18, C-19) → `pre-repo`
- [x] DOC-002.3 — Apply the folder profile, the Q-8 gate, the fork, and the VLM candidate check → `pre-repo`
- [x] DOC-002.4 — Size the M4 and M8 gates to the real folder (D27) → `pre-repo`

## DOC-002 — Results

- **Status:** DONE_WITH_CONCERNS.
  - Q-1 (adult VLM tag) is open by design until M5.
  - The M5 gate still says "500 names". The real folder has ~150 images, so the 500 names must come from several templates per image or from seeded synthetic names. M5 G0 must settle how (proposed decision for the M5 plan).
- **Triage:** large (contract: the whole spec) · no tests (pre-code) · solo.
- **Self-rating:** 8/10, proud: yes. Gaps:
  - The M5 sample size is above.
  - Nothing is enforced until the bootstrap hooks exist.
