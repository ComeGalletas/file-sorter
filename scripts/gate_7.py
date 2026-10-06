"""Milestone 7 gate: File ops + watch (DESIGN.md §11).

Criterion: Kill mid-run and restart: 0 duplicates, 0 lost files, ledger == results on disk; the
source tree's checksum manifest is byte-identical before and after; purge-sources and delete refuse
by default.

STUB (RUN-002.4): exits 1 until milestone 7 implements the measurement.
QA owns this file. Report aggregates and hashes only, never file names or references.
"""

import sys

CRITERION = (
    "Kill mid-run and restart: 0 duplicates, 0 lost files, ledger == results on disk; the"
    " source tree's checksum manifest is byte-identical before and after; purge-sources "
    "and delete refuse by default."
)


def main() -> int:
    print(f"gate 7 NOT IMPLEMENTED: {CRITERION}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
