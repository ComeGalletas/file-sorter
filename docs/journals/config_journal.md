# Config loading — journal

**ID:** CFG-001 (+ CFG-002) · **Systems:** CFG (+ FOP) · **Type:** feature · **Status:** CFG-001 done; CFG-002 proposed · **Milestone:** m1 (CFG-002: m2, proposed) ·
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
  - [x] CFG-002.1.5 — Results and post-rebase hashes

## CFG-002 — Results

### CFG-002.1 (worker: pipeline)

- **Status:** DONE
- **Triage:** medium; `unit` (config, cli) plus lint, with the default tiers through the pre-push gate; solo; branch `office/byte-3ea0`.
- **Tests:**
  - `unit` 47 passed in `tests/unit/config/test_config.py` (the acceptance test).
  - `unit` 5 passed in the new `tests/unit/cli/test_dry_run_config_errors.py`.
  - `integration` 10 passed in `tests/integration/test_dry_run_cli.py`.
  - `make test` on the rebased branch: 783 passed, 2 deselected. `make lint` clean.
- **Privacy:**
  - Every `ConfigError` from `load_config` is raised after its `except` block, from the file path, the YAML line, or the key location and pydantic error type. Unknown keys show as `<unknown key>`.
  - The tests plant a secret in a value, an unknown key, the YAML text, raw bytes and a DSN. They assert it is absent from `str` and `repr`, and that `__cause__` and `__context__` are `None`.
  - `DbConfig.dsn` is `repr=False`. The CLI never prints the config or a dump of it.
- **Found along the way:** `tests/integration/test_dry_run_cli.py` (CLI-002's test) wrote its DSN into the config file, which CFG-001.D2 now refuses. It now passes `DB_DSN` per invocation, folded into CFG-002.1.3 so that every commit is green. `test_dry_run_graph.py` and `scripts/gate_1.py` build `Config` directly and are unaffected.
- **Self-rating:** pass 1: 9/10, proud: yes. The 1 point: `_where` shows any location part that isn't a config key as `<unknown key>`, including a pydantic union tag. No current field has a tagged union, so nothing is affected today. A future `str | int` field would get a vaguer location, though still value-free.
- **Review:** pending.
