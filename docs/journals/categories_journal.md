# Categories — journal

**ID:** CLS-001 · **Systems:** CLS (+ NAME, FOP, DB, API, TST) · **Type:** feature · **Status:** proposed ·
**Milestone:** m3 (design now; built in M3) · **Issues:** — (pre-repo) · **Branch:** pre-repo, committed at bootstrap

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
- [ ] CLS-001.5 — M3: seed migration with both axes and their prompts; per-axis scoring and folder layout (issue at M3 G0)
- [ ] CLS-001.6 — M3: `scripts/gate_3.py` measures format, topic and NSFW per D5 (issue at M3 G0)

## CLS-001 — Results

### CLS-001.1–.3 (design, pre-repo)

- **Status:** DONE (after CLS-001.4 and .7). The design part of CLS-001 is complete; .5 and .6 are M3 build tasks.
- **Final label counts (v2, after D9–D14):** kept in the local `labels.csv` only (DOC-005.D1).
- **Triage:** large (contract change: data model, config schema, folder layout, gate) · no tests (pre-code). Both conversion scripts verified their own output: the row count, header, no duplicates, vocabulary membership, topic ≠ format, and exactly the two expected overrides.
- **v1 conversion (CLS-001.3):** superseded by .7.
- **Self-rating:** 9/10, proud: yes. Every label rule is a confirmed decision, and the conversion is deterministic and re-runnable. Remaining gap: some topics have very few examples, so their individual accuracy can't be measured; they count only toward the overall ≥ 85% topic figure.
- **Deferred:** the conversion script lives in the session scratchpad. M3's QA task re-implements the label loader in `tests/` against the new columns.
