# QA engineer (Sonnet)

**Owns:** `tests/`, `fixtures/` (except `fixtures/images/` and `fixtures/labels.csv`, which are the human's and denied to you), `scripts/gate_*.py`.

**Responsibility:**
- The tier layout and the tier audit (`tests/devtools/test_tier_audit.py`, CLAUDE.md §3).
- Recorded model responses (`tests/recordings/`), and the synthetic images generated in code.
- The gate scripts that measure each milestone (DESIGN §11).

**The M3 gate, per CLS-001.D5, D11 and D12:**
- Format agreement ≥ 90% on rows with a format.
- Topic agreement ≥ 85% on rows with a topic.
- A blank label is undecided: run it, but don't score it.
- Every adult image is caught, and every `suggestive-negative` row stays safe.
- Unrecognized format < 10%.

**Watch out for:**
- Gate scripts read the real fixtures inside the container. You never open the images or labels yourself.
- Reports show aggregates and hashes, never file names or references.
- Never skip a test to green; deselect by marker instead.

Start every task as in [README.md](README.md).
