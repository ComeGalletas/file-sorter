"""Milestone 2 gate: Sanitize (DESIGN.md §11).

Criterion: 50 seeded names come out with 0 residual sensitive values; EXIF on outputs contains only
the allow-list.

STUB (RUN-002.4): exits 1 until milestone 2 implements the measurement.
QA owns this file. Report aggregates and hashes only, never file names or references.
"""

import sys

CRITERION = (
    "50 seeded names come out with 0 residual sensitive values; EXIF on outputs contains "
    "only the allow-list."
)


def main() -> int:
    print(f"gate 2 NOT IMPLEMENTED: {CRITERION}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
