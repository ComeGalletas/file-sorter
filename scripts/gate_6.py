"""Milestone 6 gate: RAG + web (DESIGN.md §11).

Criterion: A franchise searched once resolves locally on the second image (web_called = false).

STUB (RUN-002.4): exits 1 until milestone 6 implements the measurement.
QA owns this file. Report aggregates and hashes only, never file names or references.
"""

import sys

CRITERION = "A franchise searched once resolves locally on the second image (web_called = false)."


def main() -> int:
    print(f"gate 6 NOT IMPLEMENTED: {CRITERION}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
