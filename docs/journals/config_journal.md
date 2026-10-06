# Config loading — journal

**ID:** CFG-001 · **Systems:** CFG (+ FOP) · **Type:** feature · **Status:** proposed · **Milestone:** m1 ·
**Issues:** #13 · **Branch:** per task, named by agent-office (`office/*`)

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
- **Review:**
- **Deferred:** symlink resolution in `check_roots` (the lead asked for a pure comparison; containment through a bind-mount alias is not detectable without touching the filesystem).
