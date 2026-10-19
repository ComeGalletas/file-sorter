# Config loading — journal

**ID:** CFG-001 (+ CFG-002) · **Systems:** CFG (+ FOP) · **Type:** feature · **Status:** done (CFG-001; CFG-002 in PR #74, merged as `3033ef4`) · **Milestone:** m1 (CFG-002: m2) ·
**Issues:** #13 (PR #26), #44 (CFG-002.1) · **Branch:** `office/pixel-0686` (CFG-001.1)

<!--
Rules: CLAUDE.md §1 (DOC-001). Public repo: never write image file names, captions,
references or host paths here. Use hashes.
-->

---

## CFG-001 — Requirement (DESIGN.md M1, 2026-10-06)

- **Objective:** Load `config.yaml` once into typed models that every M1 node and command reads.
- **Details:**
  - Pydantic models for the sections M1 reads: `paths`, `db`, `deletion`, plus the rest of §6 as typed but unused fields. Unknown keys are an error.
  - `db.dsn` is `null` in `config.yaml` and comes from the `DB_DSN` environment variable (docker-compose.yml). `CLASSIFIER_CONFIG` names the file.
  - Values marked as not decided yet stay `None` and are allowed: `models.vlm_nsfw` (Q-1) and both `classify.*.default_min_score` (calibrated in M3).
  - Start-up refuses to run if `results_root` is inside `source_root` or the reverse (R-FOP-9).
- **Constraint:** No hard-coded paths, thresholds or model tags in code (CLAUDE.md "Code conventions"). `deletion.enabled` defaults to `false` and nothing here changes that. `vlm_nsfw` is never filled in (Q-1).
- **Implements:** P-5, R-FOP-9, R-CFG-1 (container paths only in `config.yaml`).

## CFG-001 — Confirmed reading

- `config.yaml` already holds the §6 shape with container paths (`/source`, `/results`) and `db.dsn: null`. `docker-compose.yml` sets `CLASSIFIER_CONFIG=/app/config.yaml` and `DB_DSN` for `app` and `test`. No loader exists yet: `classifier/` is empty packages.
- `pydantic>=2.8` and `pydantic-settings>=2.4` are already dependencies.
- R-FOP-9 is a start-up check. M1 is the first milestone where a command reads `paths`, so it lands here rather than in M7.
- **CFG-001.D1** — **The loader is `classifier/config.py`, owned by the Pipeline engineer** (confirmed by the human, 2026-10-06, as recommended). The rule change is DOC-004.D2, merged in PR #24: the roles table now gives Pipeline the package-root `config.py`.
- **CFG-001.D2** — **`DB_DSN` always wins, and a non-null `db.dsn` in `config.yaml` is refused** (lead, 2026-10-06, from PR #26's review). This replaces the worker's "CFG-001.1.D2", where the file won: decisions carry the requirement ID. A DSN carries the database password, and `config.yaml` is committed, so secrets come from the environment only. Not implemented in CFG-001.1, which merged with the file-wins behaviour; it is implemented by **CFG-002**.

## CFG-001 — Plan

1. `classifier/config.py` (D1): `Config` and section models, `load_config(path | None) -> Config`, with the path from `CLASSIFIER_CONFIG` and the DSN from `DB_DSN`.
2. `check_roots(config)`: resolve both paths and refuse, with a clear error, when one contains the other (R-FOP-9).
3. Unit tests with temporary YAML files: the real `config.yaml` loads; unknown keys, a missing DSN and nested roots fail; `deletion.enabled` defaults to `false`.

## CFG-001 — Tasks

- [x] CFG-001.1 — Typed config loader and the R-FOP-9 root check · #13 · acceptance: `tests/unit/config/test_config.py`
  - [x] CFG-001.1.1 — Typed models, unknown keys refused (07cee8e)
  - [x] CFG-001.1.2 — `load_config` with `CLASSIFIER_CONFIG` and `DB_DSN` (8455dc5)
  - [x] CFG-001.1.3 — `check_roots` (R-FOP-9), called by `load_config` (4c63c8a)

## CFG-001 — Results

### CFG-001.1 (worker: pipeline)

- **Status:** DONE
- **Triage:** medium; `unit` tier plus lint; solo; branch `office/pixel-0686`.
- **Tests:** `unit` 26 passed in `tests/unit/config/test_config.py` (the acceptance test). The pre-push gate also ran the default tiers: 154 passed. `make lint` clean.
- **Self-rating:** pass 1: 9/10, proud: yes. The 1 point: **CFG-001.1.D2** (decided by the worker, open for the lead): a non-null `db.dsn` in the file wins over `DB_DSN`. `config.yaml` ships it `null`, so this only matters if someone sets it. Gap named against R-CFG-1; it is a one-line change if the lead wants the environment to win.
- **Review:** PR #26, merged as `4af226f`, closing #13. Reviewer APPROVE (full, 4 minor), Privacy auditor PASS, at `5af6084`; the verdict comment is on the PR. The minors go to CFG-002. The worker's "CFG-001.1.D2" became the lead's CFG-001.D2.
- **Deferred:** symlink resolution in `check_roots` (the lead asked for a pure comparison; containment through a bind-mount alias is not detectable without touching the filesystem).

---

## CFG-002 — Requirement (lead, from PR #26's review, 2026-10-06)

- **Objective:** Harden the config loader along the four lines PR #26's review left open.
- **Details:**
  1. `check_roots`: collapse a leading `//` (which `posixpath.normpath` keeps) and require both roots to be absolute. Mixed relative and absolute roots are refused.
  2. Wrap `yaml.YAMLError` and pydantic's `ValidationError` in `ConfigError`, and keep input values out of the messages, so a mistyped DSN is never echoed.
  3. Implement **CFG-001.D2**: `DB_DSN` always wins, and a non-null `db.dsn` in the file is refused with a clear error.
  4. Tests: a null `db.dsn` falling back to the environment; relative roots; a leading `//`; an error message that carries no input value.
- **Constraint:** `deletion.enabled` and `vlm_nsfw` are untouched. No hard-coded paths.
- **Implements:** R-FOP-9, R-CFG-1, P-5, CFG-001.D2.

## CFG-002 — Confirmed reading

- `classifier/config.py` and `tests/unit/config/test_config.py` are on `main` (PR #26). `config.yaml` ships `db.dsn: null`, so refusing a non-null value breaks nothing that is committed.
- Not in the approved M1 plan. **Proposed for M2** at M2 G0 (lead, 2026-10-07): it is independent of the sanitizer, and item 3 keeps the database password out of the committed file. **Confirmed into M2 by the human, 2026-10-07.**

## CFG-002 — Tasks

- [x] CFG-002.1 — The four hardening items with their unit tests · #44 · acceptance: `tests/unit/config/test_config.py`
  - [x] CFG-002.1.1 — Value-free load errors: YAML, UTF-8 and validation errors become `ConfigError`, rebuilt from location and type, with no exception chain (97aaa5a)
  - [x] CFG-002.1.2 — `check_roots`: absolute roots, a leading `//` collapsed, no path in the message (51b9db6)
  - [x] CFG-002.1.3 — CFG-001.D2: `DB_DSN` always wins, a non-null `db.dsn` in the file is refused, `db.dsn` hidden from `repr` (a83fd6b)
  - [x] CFG-002.1.4 — CLI `dry-run`: drop the dead `except ValidationError` branch, test the value-free exit (8693c49)
  - [x] CFG-002.1.5 — Results and post-rebase hashes (9447512)
  - [x] CFG-002.1.6 — PR #74 round 1: int and bool keys shown as `<unknown key>`, an `OSError` from the read wrapped

## CFG-002 — Results

### CFG-002.1 (worker: pipeline)

- **Status:** DONE
- **Triage:** medium; `unit` (config, cli) plus lint, with the default tiers through the pre-push gate; solo; branch `office/byte-3ea0`.
- **Tests:**
  - `unit` 48 passed in `tests/unit/config/test_config.py` (the acceptance test), after round 1.
  - `unit` 5 passed in the new `tests/unit/cli/test_dry_run_config_errors.py`.
  - `integration` 10 passed in `tests/integration/test_dry_run_cli.py`.
  - `make test` on the rebased branch: 783 passed, 2 deselected. `make lint` clean.
- **Privacy:**
  - Every `ConfigError` from `load_config` is raised after its `except` block, from the file path, the YAML line, or the key location and pydantic error type. Unknown keys show as `<unknown key>`.
  - The tests plant a secret in a value, an unknown key, the YAML text, raw bytes and a DSN. They assert it is absent from `str` and `repr`, and that `__cause__` and `__context__` are `None`.
  - `DbConfig.dsn` is `repr=False`. The CLI never prints the config or a dump of it.
- **Found along the way:** `tests/integration/test_dry_run_cli.py` (CLI-002's test) wrote its DSN into the config file, which CFG-001.D2 now refuses. It now passes `DB_DSN` per invocation, folded into CFG-002.1.3 so that every commit is green. `test_dry_run_graph.py` and `scripts/gate_1.py` build `Config` directly and are unaffected.
- **Self-rating:** pass 1: 9/10, proud: yes. The 1 point: `_where` shows any location part that isn't a config key as `<unknown key>`, including a pydantic union tag. No current field has a tagged union, so nothing is affected today. A future `str | int` field would get a vaguer location, though still value-free.
- **Review:** PR #74 round 1 at `9447512`: Reviewer APPROVE, Privacy auditor FAIL.
  - Privacy: an int or bool YAML key was printed in the location, because pydantic keeps it as an int. `_where` now shows every non-string part as `<unknown key>`. The config has no lists.
  - Reviewer finding 1: an `OSError` from `read_text` now becomes a fixed, unchained `ConfigError` with the file path.
  - Both fixes are in CFG-002.1.6, with regression tests that fail on the old code. The int and bool keys are checked in `str`, `repr` and the CLI's stderr; the read failure is a planted `PermissionError`.

---

## CFG-003 — Requirement (human, the M3 VLM re-plan, 2026-10-18)

- **Objective:** the configuration for the VLM classifier (CLS-004).
- **Details:**
  - **`nsfw.min_level`:** `suggestive | nudity | explicit`, with the human's value `nudity`.
  - **`nsfw.cross_check.safe_above` and `nsfw.cross_check.adult_below`:** the Falconsai disagreement thresholds (CLS-004.D5). The human sets both values.
  - **`models.vlm_safe`:** becomes `qwen3-vl:8b-instruct` (CLS-004.D8, key to confirm).
  - **The obsolete keys:** `nsfw.threshold`, `classify.score` and the per-axis `default_min_score`/`margin` stop deciding anything. Whether DOC-009 drops them or keeps them for compatibility, the loader must not require them on the VLM path.
- **Constraint:** these are hand-tuned values (CLAUDE.md §1.7). The task commits exactly the values the human sets, as type `balance`, with the schema change in its own commit.
- **Implements:** DESIGN §6 (as amended by DOC-009); CLS-004.D3, D5, D7, D8.

## CFG-003 — Tasks

- [x] CFG-003.1 — The schema in `classifier/config.py` (with typed enums for `min_level`, validated cross-check bounds, and fixed-text errors naming the key) and the human's values in `config.yaml` · #130 · Pipeline · acceptance: `tests/unit/config/test_config.py` (the path in the plan was wrong; the lead approved the actual one on #130) · PR #144, merged as `1056ac3`
  - [x] CFG-003.1.1 — The schema: ordered `NsfwLevel`, `nsfw.min_level` (refuses `safe`), `nsfw.cross_check` bounds and order check, the obsolete SigLIP keys optional. `min_level` is optional here so `config.yaml` still loads until .2 sets it · hash: c5e9a2c
  - [x] CFG-003.1.2 — `config.yaml`: the human's values (type `balance`): `nsfw.min_level: nudity`, both cross-check values null, `models.vlm_safe: qwen3-vl:8b-instruct` · hash: e95b8bb
  - [x] CFG-003.1.3 — `min_level` becomes required, now that the file sets it · hash: 3066d47
  - [x] CFG-003.1.4 — Results and the self-rating · hash: ee681b2

## CFG-003 — Results

### CFG-003.1 (Pipeline, PR for #130)

- **Tests:** `tests/unit/config/test_config.py` (the acceptance test; the issue named `tests/unit/test_config.py`, the lead corrected it): 92 tests pass. Default tiers (`make test`): 1968 passed at CFG-003.1.2, and unit + integration passed again at CFG-003.1.3. No `db`-specific change, no `gpu`, no `eval/` run: no model, prompt or threshold is calibrated here. `make lint` clean.
- **Schema:** ordered `NsfwLevel` (`safe < suggestive < nudity < explicit`); `nsfw.min_level` is required and refuses `safe`, numbers and other names; `nsfw.cross_check.safe_above` / `adult_below` are in [0, 1], finite, not bool, and `adult_below` must be below `safe_above`; both null (or the section absent) turns the cross-check off. The obsolete keys (`nsfw.threshold`, `classify.*`) are optional with no defaults and still parse (CLS-004.D7).
- **Values (`config.yaml`, type balance, CFG-003.1.2):** only `nsfw.min_level: nudity`, the two null cross-check keys and `models.vlm_safe: qwen3-vl:8b-instruct`. `vlm_nsfw` stays null (Q-1), `text_llm` unchanged (SAN-004.2).
- **Commit order:** `min_level` landed optional first and became required after the value commit (CFG-003.1.3), so every commit loads the repo's `config.yaml`.
- **Privacy:** errors carry the key location and the pydantic error type only; tests plant a string and a number in the new keys and check `str`, `repr`, `__cause__` and `__context__`. No new field holds a path, name or label, so no `repr=False` is needed.
- **Consumers now seeing `None` (other roles' files, not touched):** `graph/classify.py` (`config.classify.score`, `config.nsfw.threshold`, `validate_rules(... config.classify)`), `models/classify_rules.py` (`default_min_score`, `margin`), `cli/categories.py` (`config.classify`). CLS-004.3 and .4 re-point them.
- **Status:** DONE. **Self-rating:** 9/10, proud: yes. The gap: the old SigLIP path now sees `None` in its keys and would fail at run time rather than at load; CLS-004.4 owns that.
- **Reviewer / Privacy auditor:** pending.

---

## CFG-004 — Requirement (human, at the M3 checkpoint, 2026-10-19)

- **Objective:** Commit the Falconsai cross-check values the human set (H3), and fix the `config.yaml` comments that still describe the SigLIP path.
- **Details:**
  - `nsfw.cross_check.safe_above: 0.90` and `adult_below: 0.10`, from `null` (CFG-003.1 left them off);
  - the comments on `nsfw.threshold` ("adult = explicit…") and `classify.*` ("calibrated in M3") contradict C-26 and DOC-009.D3.
- **Constraint:** the values are hand-tuned (CLAUDE.md §1.7). They land as given, in their own `balance` commit.
- **Implements:** CLS-004.D5, DESIGN §6 (after DOC-011).

## CFG-004 — Confirmed reading

- `nsfw_cross_check` (CLS-004.3) is on when both values are set. A strong disagreement sets `needs_review` with `nsfw_disagreement` and never changes the branch (CLS-004.D5, D13).

## CFG-004 — Tasks

- [x] CFG-004.1 — The two values (CFG-004.1.1 `397a04a`, values only), then the comments and tests (CFG-004.1.2) · #170 · Pipeline · type `balance` · acceptance: `tests/unit/config/test_config.py`

## CFG-004 — Results

### CFG-004.1 (Pipeline)

- Tiers: `make test` 2361 passed (unit + db + integration); `make lint` clean.
- The scenario config in `tests/integration/classify_support.py` keeps the cross-check off, so the integration tests don't depend on the human's tuned values.
- Status: DONE. Self-rating: 9/10, yes (the gap: no `gpu` run, none needed for a config-only change).
