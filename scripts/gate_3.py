"""Milestone 3 gate: Classify (DESIGN.md §11).

Criterion: On all ~150 labelled real images: format agreement >= 90% on rows with a format; topic
agreement >= 85% on rows with a topic (blank = undecided, not scored); every adult image flagged and
every suggestive-negative row safe; unrecognized format < 10%. (CLS-001.D5, D11, D12)

STUB (RUN-002.4): exits 1 until milestone 3 implements the measurement.
QA owns this file. Report aggregates and hashes only, never file names or references.
"""

import sys

CRITERION = (
    "On all ~150 labelled real images: format agreement >= 90% on rows with a format; "
    "topic agreement >= 85% on rows with a topic (blank = undecided, not scored); every "
    "adult image flagged and every suggestive-negative row safe; unrecognized format < "
    "10%. (CLS-001.D5, D11, D12)"
)


def main() -> int:
    print(f"gate 3 NOT IMPLEMENTED: {CRITERION}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
