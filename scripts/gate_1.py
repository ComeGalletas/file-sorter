"""Milestone 1 gate: Skeleton + ledger (DESIGN.md §11).

Criterion: Re-running on the same folder skips 100% of files, with no new ledger rows.

Runs inside the `test` container (`make gate-1`): a fresh migrated schema in `db-test`, a dry
run twice over `fixtures/images/`, then the measurement on run 2 (TST-002.D2):
  - skipped share = (skipped_known + skipped_unreadable + duplicate) / total, must be 100%;
  - new ledger rows (the `files` count before vs after run 2), must be 0.
QA owns this file. Output is percentages and "0 new ledger rows" only: never a count of the
human's images, never a file name or path (DOC-005.D1).
"""

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMAGES = REPO / "fixtures" / "images"
CONFIG = REPO / "config.yaml"

CRITERION = "Re-running on the same folder skips 100% of files, with no new ledger rows."


class GateSetupError(Exception):
    """A prerequisite is missing; the gate fails and names it. It is never skipped."""


@dataclass(frozen=True)
class Verdict:
    passed: bool
    lines: tuple[str, ...]


def skipped_share(new: int, skipped_known: int, skipped_unreadable: int, duplicate: int) -> float:
    """Share of run 2's files that were not newly ingested, in percent (0.0 for an empty tree)."""
    total = new + skipped_known + skipped_unreadable + duplicate
    if total == 0:
        return 0.0
    return 100.0 * (skipped_known + skipped_unreadable + duplicate) / total


def judge(
    *,
    new: int,
    skipped_known: int,
    skipped_unreadable: int,
    duplicate: int,
    rows_before: int,
    rows_after: int,
    run1_new: int,
) -> Verdict:
    """Decide the gate from run 2's buckets and the ledger count around it. Prints no counts.

    Run 1 must have ingested at least one image (`run1_new`): a tree of non-images leaves
    run 2 skipping everything with no new rows, which would pass without proving anything.
    """
    total = new + skipped_known + skipped_unreadable + duplicate
    if run1_new == 0:
        return Verdict(False, ("gate 1 FAIL: run 1 ingested nothing; the re-run proves nothing",))
    lines: list[str] = []
    ok = True
    if total == 0:
        return Verdict(False, ("gate 1 FAIL: run 2 saw no files; 100% of nothing proves nothing",))

    share = skipped_share(new, skipped_known, skipped_unreadable, duplicate)
    share_ok = new == 0 and share == 100.0
    status = "ok" if share_ok else "FAIL"
    lines.append(f"skipped on re-run: {share:.1f}% (required 100.0%): {status}")
    ok &= share_ok

    rows_ok = rows_after == rows_before
    if rows_ok:
        lines.append("new ledger rows: 0 (required 0): ok")
    else:
        # The ledger only grows by ingest, so a negative delta is as wrong as a positive one.
        lines.append("new ledger rows: not 0 (required 0): FAIL")
    ok &= rows_ok

    lines.append(f"gate 1 {'PASS' if ok else 'FAIL'}: {CRITERION}")
    return Verdict(ok, tuple(lines))


def check_prerequisites(dsn: str | None, images: Path) -> str:
    """Return the DSN, or raise naming what is missing."""
    if not dsn:
        raise GateSetupError(
            "DB_DSN is not set: gate 1 needs the throwaway Postgres of the `test` compose "
            "profile. Run it with `make gate-1`."
        )
    if not images.is_dir():
        raise GateSetupError(
            "fixtures/images/ is missing: gate 1 measures the human's real fixtures, mounted "
            "read-only into the `test` container (RUN-009). Run it with `make gate-1`."
        )
    if not any(images.iterdir()):
        raise GateSetupError("fixtures/images/ is empty: gate 1 has nothing to ingest.")
    return dsn


def measure(db_dsn: str, images: Path) -> Verdict:
    """Dry-run `images` twice against a fresh migrated schema and judge run 2."""
    # Imported here so the pure logic above loads without the app's dependencies.
    import psycopg
    import yaml

    from classifier.config import Config, check_roots
    from classifier.graph import nodes as graph_nodes
    from classifier.graph.run import run
    from tests.integration.schema_support import migrated_schema

    # TST-007.1: gate 1 measures ingest only, so the later nodes (sanitize and on) never run
    # here: no local rules, no entity calls from the integration tier (CLAUDE.md §3).
    ingest_only = tuple(n for n in graph_nodes.REGISTRY if n.name == "ingest")
    if len(ingest_only) != 1:
        raise GateSetupError("the node registry must hold exactly one `ingest` node")

    with migrated_schema(db_dsn) as dsn, tempfile.TemporaryDirectory() as results:
        data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        data["paths"] = {"source_root": str(images), "results_root": results}
        data["db"] = {"dsn": dsn}
        config = Config.model_validate(data)
        check_roots(config)  # R-FOP-9

        first = run(config, dry_run=True, nodes=ingest_only).ingest
        with psycopg.connect(dsn) as conn:
            before = conn.execute("select count(*) from files").fetchone()[0]
        second = run(config, dry_run=True, nodes=ingest_only).ingest
        with psycopg.connect(dsn) as conn:
            after = conn.execute("select count(*) from files").fetchone()[0]

    return judge(
        new=second.new,
        skipped_known=second.skipped_known,
        skipped_unreadable=second.skipped_unreadable,
        duplicate=second.duplicate,
        rows_before=before,
        rows_after=after,
        run1_new=first.new,
    )


def main(images: Path = IMAGES) -> int:
    import os

    try:
        dsn = check_prerequisites(os.environ.get("DB_DSN"), images)
    except GateSetupError as exc:
        print(f"gate 1 FAIL: {exc}", file=sys.stderr)
        return 1
    try:
        verdict = measure(dsn, images)
    except Exception as exc:  # the type only: a message can carry a path or the DSN
        print(f"gate 1 FAIL: run errored ({type(exc).__name__})", file=sys.stderr)
        return 1
    print("\n".join(verdict.lines))
    return 0 if verdict.passed else 1


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    sys.exit(main())
