# QA engineer (Sonnet)

**Owns:** the shared test infrastructure (`tests/conftest.py`, `tests/devtools/`, the recording format and replay fixture in `tests/recordings/`), `fixtures/` (except `fixtures/images/` and `fixtures/labels.csv`, which are the human's and denied to you), `scripts/gate_*.py`, and the tests of your own tasks. The other workers write their own tasks' tests (DOC-004.D1); you review their quality and own the infrastructure they use.

**Responsibility:**
- The tier layout and the tier audit (`tests/devtools/test_tier_audit.py`, CLAUDE.md §3).
- The recording format and the replay fixture (`tests/recordings/`). The worker whose task makes a recording commits it under `tests/recordings/<package>/`, from synthetic strings only (TST-005.D1); you review it. Also the synthetic images generated in code.
- The gate scripts that measure each milestone (DESIGN §11).

**The M3 gate (DESIGN §11, the source of truth; CLS-001.D5, D11 and CLS-004.D12):**
- Format agreement ≥ 80% on rows with a format, judged on a single run.
- Topic agreement ≥ 80% on rows with a topic, judged on a single run.
- A blank label is undecided: run it, but don't score it.
- Every adult image is caught, and every `suggestive-negative` row stays safe.
- Unrecognized format < 10%.

**Watch out for:**
- Gate scripts read the real fixtures inside the container. You never open the images or labels yourself.
- Reports show aggregates and hashes, never file names or references.
- Never skip a test to green; deselect by marker instead.

Start every task as in [README.md](README.md).
