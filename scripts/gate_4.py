"""Milestone 4 gate: Status UI, read-only (DESIGN.md §11).

Criterion: A dry run of the whole real folder is reviewable end to end without a terminal.

STUB (RUN-002.4): exits 1 until milestone 4 implements the measurement.
QA owns this file. Report aggregates and hashes only, never file names or references.
"""

import sys

CRITERION = "A dry run of the whole real folder is reviewable end to end without a terminal."


def main() -> int:
    print(f"gate 4 NOT IMPLEMENTED: {CRITERION}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
