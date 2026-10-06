"""Milestone 1 gate: Skeleton + ledger (DESIGN.md §11).

Criterion: Re-running on the same folder skips 100% of files, with no new ledger rows.

STUB (RUN-002.4): exits 1 until milestone 1 implements the measurement.
QA owns this file. Report aggregates and hashes only, never file names or references.
"""

import sys

CRITERION = "Re-running on the same folder skips 100% of files, with no new ledger rows."


def main() -> int:
    print(f"gate 1 NOT IMPLEMENTED: {CRITERION}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
