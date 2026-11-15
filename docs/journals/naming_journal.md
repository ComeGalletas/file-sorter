# Naming — journal

**ID:** NAME-001 (+ NAME-002, CLI-010) · **Systems:** NAME (+ PIPE, CLI, SAN, FOP, DB) · **Type:** feature ·
**Status:** proposed (M5 G0) · **Milestone:** m5 ·
**Issues:** see each Tasks section · **Branch:** per task (`office/*`)

<!--
Rules: CLAUDE.md §1 (DOC-001). Public repo: never write image file names, real proposed names, captions or host paths here. Use hashes.
-->

---

## NAME-001 — Requirement (DESIGN.md m5, 2026-11-15)

- **Objective:** Render a safe, readable file name from a template and a row's tokens.
- **Details:**
  - R-NAME-2's tokens and filters (`|title`, `|max=N`, `|or=<fallback>`);
  - R-NAME-1's six built-ins;
  - R-NAME-3's dates;
  - R-NAME-5's normalization, then the sanitize rules re-run (R-SAN-7);
  - R-NAME-8's `nsfw_` prefix inside the 120-character cap;
  - R-NAME-6's collisions;
  - R-NAME-7's `{reference}`, empty until M6.
- **Constraint:** pure functions (the sanitize re-run is injected). The text token fields are `repr=False`, and no real name is ever logged.
- **Implements:** R-NAME-1 to R-NAME-8, R-SAN-7.

## NAME-001 — Confirmed reading

- `classifier/naming/` is empty. `config.yaml` has `naming.default_template`, `nsfw_template` (null, R-NAME-4), `nsfw_prefix` and `max_len`.
- **NAME-001.D1 — the `descriptive` template** (lead, 2026-11-15, provisional; answer 9): `{subject}_{detail|max=40}_{seq:3}`.
- **NAME-001.D2 — the other built-ins** (lead, provisional): `reference` = `{reference|or={subject}}_{seq:3}` (`|or=` takes a token as its fallback; the tests pin it), `dated` = `{date}_{subject}_{seq:3}`, `category-seq` = `{category}_{seq:4}`, `keep-original` = `{original_sanitized}`, `hash` = `{short_hash}`.
- **NAME-001.D3 — collisions** (lead, provisional; answer 13): casefolded, across the run's proposed set plus the existing names under the target folder in `results/`. In a dry run nothing is written.

## NAME-001 — Tasks

- [ ] NAME-001.1 — `render()`: tokens, filters, built-ins, dates, normalization, the injected sanitize re-run, the prefix and the cap · #258 · Pipeline · a test pins the `|or=` token fallback (NAME-001.D2) · acceptance: `tests/unit/naming/test_templates.py`
  - [x] NAME-001.1.1 — the parser, `Tokens` (`repr=False` text and date fields) and the six built-ins
- [ ] NAME-001.2 — `unique()`: R-NAME-6 collisions, casefolded · #259 · Pipeline · acceptance: `tests/unit/naming/test_collisions.py`

## NAME-001 — Results

---

## NAME-002 — Requirement (DESIGN.md m5, 2026-11-15)

- **Objective:** Give every captioned row a proposed name and path, so the dry run ends at `proposed`.
- **Details:**
  - the `name` node picks each row's template: its category's assignment, else the global one, else `naming.default_template`; adult rows use the same template, or the `naming.nsfw_template` override (R-NAME-4);
  - it renders, re-runs the sanitize rules, and makes the name unique;
  - it writes `template`, `proposed_path` and status `proposed`;
  - the dry-run CSV carries the proposed name.
- **Constraint:** no file is written to `results/` (dry run, M3–M6). No log line carries a name.
- **Implements:** R-NAME-1, R-NAME-4, R-PIPE-2; closes C-22.

## NAME-002 — Confirmed reading

- **NAME-002.D1 — the input status** (lead, 2026-11-15, provisional): `captioned`. M6 inserts `resolved` between them.
- **NAME-002.D2 — `proposed_path`** (lead, provisional): relative to `results_root`, `[Adult/]<Topic|General>/<Format>[/Animated]/<name>` or `[Adult/]Unsorted/<name>`, with nested topics, built by FOP-002's `result_folder`.

## NAME-002 — Tasks

- [ ] NAME-002.1 — The name node, the template resolution, `proposed`, and the dry-run CSV's proposed name · #260 · Pipeline · acceptance: `tests/db/graph/test_name_node.py`

## NAME-002 — Results

---

## CLI-010 — Requirement (DESIGN.md m5, 2026-11-15)

- **Objective:** Manage templates from the CLI: `classifier templates list|add|set-default|assign|preview --sample N` (`list` extends DESIGN §7's set).
- **Constraint:**
  - a template is validated by NAME-001's parser before it's stored;
  - errors are fixed text, unchained;
  - preview prints synthetic names only (CLI-010.D1).
- **Implements:** §7, R-NAME-1.

## CLI-010 — Confirmed reading

- **CLI-010.D1 — the preview's rows** (lead, 2026-11-15, provisional): synthetic sample rows with a pinned seed, so the console never prints a real image's name (privacy item 2). Real names are reviewed in the dashboard (API-002).

## CLI-010 — Tasks

- [ ] CLI-010.1 — `templates list|add|set-default|assign|preview` (`list` extends DESIGN §7) · #261 · Pipeline · acceptance: `tests/db/cli/test_templates_cli.py`

## CLI-010 — Results
