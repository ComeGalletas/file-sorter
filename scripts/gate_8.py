"""Milestone 8 gate: UI write actions (DESIGN.md §11).

Criterion: Every unsorted file from the real folder can be filed from the browser, and ledger ==
disk.

STUB (RUN-002.4): exits 1 until milestone 8 implements the measurement.
QA owns this file. Report aggregates and hashes only, never file names or references.
"""

import sys

CRITERION = (
    "Every unsorted file from the real folder can be filed from the browser, and ledger == disk."
)


def main() -> int:
    print(f"gate 8 NOT IMPLEMENTED: {CRITERION}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
