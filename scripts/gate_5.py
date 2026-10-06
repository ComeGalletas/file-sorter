"""Milestone 5 gate: Name (DESIGN.md §11).

Criterion: 0 sensitive values in 500 generated names (the M5 plan settles how 500 names come from
the real images); names readable without opening the file (human review at G1).

STUB (RUN-002.4): exits 1 until milestone 5 implements the measurement.
QA owns this file. Report aggregates and hashes only, never file names or references.
"""

import sys

CRITERION = (
    "0 sensitive values in 500 generated names (the M5 plan settles how 500 names come "
    "from the real images); names readable without opening the file (human review at G1)."
)


def main() -> int:
    print(f"gate 5 NOT IMPLEMENTED: {CRITERION}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
