"""Milestone 3 gate: Classify (DESIGN.md §11).

Criterion: On every real image labelled in fixtures/labels.csv: format agreement >= 90% on rows
with a format; topic agreement >= 85% on rows with a topic (blank = undecided, not scored); every
adult image flagged and every suggestive-negative row safe; unrecognized format < 10%.
(CLS-001.D5, D11, D12)

Runs inside the `test` container (`make gate-3`): ingest -> sanitize -> classify as a dry run on
fixtures/images/, in a fresh schema of the throwaway Postgres and a temp results tree that is
removed afterwards (TST-008.D4, TST-005.D6). Each ledger row is matched to its label by the file's
path relative to the images folder, in memory only (TST-008.D4).

The vocabularies the labels are checked against are the names in the `categories` table of the
gate's own fresh schema after `alembic upgrade head`: the committed configuration (the seed plus
the approved overrides of the later migrations). Categories the human adds to the local database
through the category CLI are not measured.

Measures (TST-008.D4; the figures come from exact integer ratios, only the printed one is rounded):
  - format: rows with a format whose ledger format equals it; `unsorted` or none is a miss;
  - topic: rows with a topic whose ledger topic equals it; none is a miss;
  - nsfw: every `adult = yes` row is `nsfw`, every `adult = no` row is `safe`; the
    `suggestive-negative` rows are their own line, all `safe`. Neither set may be empty;
  - unrecognized: the share of rows whose format is `unsorted`, strictly below 10%;
  - any ledger row in `error`, or labels and images that do not match one to one, fail.
Rows tagged `calibration-only` are left out of every measure (TST-008.D2).

QA owns this file. The default output is the public form (TST-008.D1, D6) and nothing else:
  - format, topic and unrecognized: ok or FAIL, and the percentage rounded down to a whole percent;
  - the adult line, the suggestive-negative line, errors and coverage: ok or FAIL only.
Never a count, a denominator, a split, a file name or a label value. `--detail` adds one-decimal
figures and per-category detail for the box console; it is never pasted anywhere (TST-008.D6).
Every error is fixed text; label values and ledger values are repr=False.
"""

import sys
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
IMAGES = REPO / "fixtures" / "images"
LABELS = REPO / "fixtures" / "labels.csv"
CONFIG = REPO / "config.yaml"

# `python scripts/gate_3.py` puts scripts/ on sys.path; the lazy imports of `classifier` and
# `tests` need the repo, and the labels loader is a sibling module.
for _path in (str(REPO), str(SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import fixture_labels  # noqa: E402  (needs SCRIPTS on sys.path)

CRITERION = (
    "On every real image labelled in fixtures/labels.csv: format agreement >= 90% on rows "
    "with a format; topic agreement >= 85% on rows with a topic (blank = undecided, not "
    "scored); every adult image flagged and every suggestive-negative row safe; "
    "unrecognized format < 10%. (CLS-001.D5, D11, D12)"
)

FORMAT_MIN = 90  # percent, inclusive (CLS-001.D5)
TOPIC_MIN = 85  # percent, inclusive
UNRECOGNIZED_BELOW = 10  # percent, strict

UNSORTED = "unsorted"
NSFW = "nsfw"
SAFE = "safe"
ERROR = "error"
SKIPPED = "skipped"
NODES = ("ingest", "sanitize", "classify")


class GateSetupError(Exception):
    """A prerequisite is missing; the gate fails and names it. Fixed text, never a value."""


class GateRunError(Exception):
    """A step failed while measuring; fixed text only."""


# --- The measures (pure; TST-008.D4) -----------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    """One ledger row, as the gate reads it. Every field can identify a human file."""

    names: tuple[str, ...] = field(repr=False)  # relative paths: the source and its duplicates
    status: str = field(repr=False)
    format: str | None = field(repr=False)
    topic: str | None = field(repr=False)
    branch: str | None = field(repr=False)


@dataclass(frozen=True)
class Tally:
    """Hits over a total, as integers; every share is derived from these, never a float."""

    hit: int = field(repr=False)
    total: int = field(repr=False)

    def floor_pct(self) -> int:
        return 100 * self.hit // self.total if self.total else 0

    def floor_tenths(self) -> str:
        tenths = 1000 * self.hit // self.total if self.total else 0
        return f"{tenths // 10}.{tenths % 10}"

    def at_least(self, percent: int) -> bool:
        """hit/total >= percent/100, exactly, and false when nothing was measured."""
        return self.total > 0 and 100 * self.hit >= percent * self.total

    def below(self, percent: int) -> bool:
        """hit/total < percent/100, exactly, and false when nothing was measured."""
        return self.total > 0 and 100 * self.hit < percent * self.total


@dataclass(frozen=True)
class Measures:
    format: Tally = field(repr=False)
    topic: Tally = field(repr=False)
    unrecognized: Tally = field(repr=False)
    adult: Tally = field(repr=False)  # adult = yes rows that are nsfw
    safe: Tally = field(repr=False)  # adult = no rows that are safe
    suggestive: Tally = field(repr=False)  # suggestive-negative rows that are safe
    errors: int = field(repr=False)
    coverage_ok: bool = field(repr=False)
    by_format: tuple[tuple[str, Tally], ...] = field(repr=False)  # detail only
    by_topic: tuple[tuple[str, Tally], ...] = field(repr=False)  # detail only


@dataclass(frozen=True)
class Verdict:
    passed: bool
    lines: tuple[str, ...] = field(repr=False)
    detail: tuple[str, ...] = field(default=(), repr=False)  # TST-008.3.7: label names, counts


def _index(outcomes: Sequence[Outcome]) -> tuple[dict[str, Outcome], bool]:
    """Outcomes by name, and whether no name belongs to two ledger rows."""
    index: dict[str, Outcome] = {}
    unique = True
    for outcome in outcomes:
        for name in outcome.names:
            if name in index:
                unique = False
            index[name] = outcome
    return index, unique


def _coverage(labels: Collection[Any], outcomes: Sequence[Outcome], unique: bool) -> bool:
    """Labels and images match one to one: every label has a ledger row, and every readable
    image has a label (a `skipped` row is an unreadable non-image and needs none)."""
    index, _ = _index(outcomes)
    if not unique or any(row.file not in index for row in labels):
        return False
    labelled = {row.file for row in labels}
    return all(
        outcome.status == SKIPPED or any(name in labelled for name in outcome.names)
        for outcome in outcomes
    )


def _by_category(
    pairs: Sequence[tuple[str, bool]],
) -> tuple[tuple[str, Tally], ...]:
    names = sorted({name for name, _ in pairs})
    return tuple(
        (
            name,
            Tally(
                sum(hit for n, hit in pairs if n == name),
                sum(1 for n, _ in pairs if n == name),
            ),
        )
        for name in names
    )


def evaluate(labels: "fixture_labels.LabelSet", outcomes: Sequence[Outcome]) -> Measures:
    """Match the labels to the ledger rows and tally every measure (TST-008.D4)."""
    index, unique = _index(outcomes)
    coverage_ok = _coverage(labels.rows, outcomes, unique)
    gate_rows = labels.gate_rows()
    suggestive = {id(row) for row in labels.suggestive_negatives()}
    fmt_pairs: list[tuple[str, bool]] = []
    topic_pairs: list[tuple[str, bool]] = []
    adult = [0, 0]
    safe = [0, 0]
    sugg = [0, 0]
    unsorted = [0, 0]
    for row in gate_rows:
        outcome = index.get(row.file)
        branch = outcome.branch if outcome else None
        got_format = outcome.format if outcome else None
        unsorted[1] += 1
        unsorted[0] += got_format == UNSORTED
        if row.format:
            fmt_pairs.append((row.format, got_format == row.format))
        if row.topic:
            topic_pairs.append((row.topic, bool(outcome) and outcome.topic == row.topic))
        side = adult if row.adult else safe
        side[1] += 1
        side[0] += branch == (NSFW if row.adult else SAFE)
        if id(row) in suggestive:
            sugg[1] += 1
            sugg[0] += branch == SAFE
    return Measures(
        format=Tally(sum(hit for _, hit in fmt_pairs), len(fmt_pairs)),
        topic=Tally(sum(hit for _, hit in topic_pairs), len(topic_pairs)),
        unrecognized=Tally(*unsorted),
        adult=Tally(*adult),
        safe=Tally(*safe),
        suggestive=Tally(*sugg),
        errors=sum(1 for outcome in outcomes if outcome.status == ERROR),
        coverage_ok=coverage_ok,
        by_format=_by_category(fmt_pairs),
        by_topic=_by_category(topic_pairs),
    )


def _all_hit(tally: Tally) -> bool:
    """Every row hit, and at least one row measured (an empty set is unmeasured, not ok)."""
    return tally.total > 0 and tally.hit == tally.total


def _word(ok: bool) -> str:
    return "ok" if ok else "FAIL"


def judge(measures: Measures, detail: bool = False) -> Verdict:
    """Verdicts come from the exact ratios; the printed percentage is rounded down (D6)."""
    fmt_ok = measures.format.at_least(FORMAT_MIN)
    topic_ok = measures.topic.at_least(TOPIC_MIN)
    unrec_ok = measures.unrecognized.below(UNRECOGNIZED_BELOW)
    nsfw_ok = _all_hit(measures.adult) and _all_hit(measures.safe)
    sugg_ok = _all_hit(measures.suggestive)
    errors_ok = measures.errors == 0
    checks = (fmt_ok, topic_ok, unrec_ok, nsfw_ok, sugg_ok, errors_ok, measures.coverage_ok)
    passed = all(checks)
    lines = (
        f"format agreement: {measures.format.floor_pct()}% "
        f"(required >= {FORMAT_MIN}%): {_word(fmt_ok)}",
        f"topic agreement: {measures.topic.floor_pct()}% "
        f"(required >= {TOPIC_MIN}%): {_word(topic_ok)}",
        f"unrecognized format: {measures.unrecognized.floor_pct()}% "
        f"(required < {UNRECOGNIZED_BELOW}%): {_word(unrec_ok)}",
        f"nsfw gate (adult flagged, safe not flagged): {_word(nsfw_ok)}",
        f"suggestive-negative rows safe: {_word(sugg_ok)}",
        f"node errors: {_word(errors_ok)}",
        f"labels and images match: {_word(measures.coverage_ok)}",
        f"gate 3 {'PASS' if passed else 'FAIL'}",
    )
    return Verdict(passed, lines, _detail(measures) if detail else ())


def _detail(measures: Measures) -> tuple[str, ...]:
    """One-decimal figures and per-category detail: the box console only (TST-008.D6)."""
    rows = [
        "--- DETAIL: box console only, never paste it into an issue, PR, journal or log ---",
        f"format {measures.format.floor_tenths()}%  topic {measures.topic.floor_tenths()}%  "
        f"unrecognized {measures.unrecognized.floor_tenths()}%",
        f"adult flagged {measures.adult.hit}/{measures.adult.total}  "
        f"safe kept {measures.safe.hit}/{measures.safe.total}  "
        f"suggestive-negative safe {measures.suggestive.hit}/{measures.suggestive.total}",
        f"node errors {measures.errors}",
    ]
    rows += [
        f"format {name}: {t.floor_tenths()}% ({t.hit}/{t.total})" for name, t in measures.by_format
    ]
    rows += [
        f"topic {name}: {t.floor_tenths()}% ({t.hit}/{t.total})" for name, t in measures.by_topic
    ]
    return tuple(rows)


# --- The runner (TST-008.3.3) ---------------------------------------------------------------
# Every error below is raised after its `except` block, from fixed text: an exception from the
# filesystem, the database or the pipeline may quote a path, a name or the DSN.


def gate_nodes(registry: Sequence[Any]) -> tuple[Any, ...]:
    """The ingest, sanitize and classify nodes, in that order: never a later node."""
    picked = tuple(node for name in NODES for node in registry if node.name == name)
    if tuple(node.name for node in picked) != NODES:
        raise GateSetupError(
            "the node registry must hold exactly one `ingest`, `sanitize` and `classify` node "
            "(CLS-002.2)"
        )
    return picked


def check_prerequisites(dsn: str | None, images: Path) -> str:
    """Return the DSN, or raise naming what is missing."""
    if not dsn:
        raise GateSetupError(
            "DB_DSN is not set: gate 3 needs the throwaway Postgres of the `test` compose "
            "profile. Run it with `make gate-3`."
        )
    if not images.is_dir() or not any(images.iterdir()):
        raise GateSetupError(
            "fixtures/images/ is missing or empty: gate 3 classifies the human's real "
            "fixtures, mounted read-only into the `test` container (RUN-009). Run it with "
            "`make gate-3`."
        )
    return dsn


def relative_name(path: str, images: Path) -> str | None:
    """A ledger path as the labels name it: relative to the images folder, in memory only."""
    try:
        return PurePosixPath(path).relative_to(PurePosixPath(images.as_posix())).as_posix()
    except ValueError:
        return None


def to_outcomes(rows: Sequence[Sequence[Any]], images: Path) -> list[Outcome]:
    """Ledger rows `(source_path, duplicate_paths, status, format, topic, branch)`."""
    outcomes: list[Outcome] = []
    for path, duplicates, status, fmt, topic, branch in rows:
        names = [relative_name(p, images) for p in (path, *(duplicates or ()))]
        if None in names:
            raise GateRunError("a ledger path is outside the images folder (source_root mismatch)")
        outcomes.append(Outcome(tuple(n for n in names if n), status, fmt, topic, branch))
    return outcomes


def load_config(source: Path, results: str, dsn: str, rules_path: Path | None = None) -> Any:
    """config.yaml with the gate's roots and schema (as gate 2). With `rules_path`, the
    sanitize node reads that rules file instead of the local sanitize.yaml (a test seam)."""
    import yaml

    from classifier.config import Config, check_roots

    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    data["paths"] = {"source_root": str(source), "results_root": results}
    data["db"] = {"dsn": dsn}
    if rules_path is not None:
        data["sanitizer"] = {**data.get("sanitizer", {}), "rules_file": str(rules_path)}
    config = Config.model_validate(data)
    check_roots(config)  # R-FOP-9
    return config


def read_vocabularies(dsn: str) -> tuple[frozenset[str], frozenset[str]]:
    """Format and topic names from the gate's own migrated schema: the committed configuration."""
    import psycopg

    with psycopg.connect(dsn) as conn:
        rows = conn.execute("select axis, name from categories").fetchall()
    formats = frozenset(name for axis, name in rows if axis == "format")
    topics = frozenset(name for axis, name in rows if axis == "topic")
    return formats, topics


def run_pipeline(
    dsn: str,
    images: Path,
    labels_path: Path,
    nodes: Sequence[Any],
    rules_path: Path | None = None,
    vision: Any = None,
) -> Measures:
    """Ingest -> sanitize -> classify into a fresh schema and a removed temp results tree
    (TST-005.D6), then tally the labels against the ledger (TST-008.D4)."""
    import tempfile

    import psycopg

    from classifier.graph.run import run
    from tests.integration.schema_support import migrated_schema

    with migrated_schema(dsn) as schema, tempfile.TemporaryDirectory() as results:
        formats, topics = read_vocabularies(schema)
        labels = fixture_labels.load_labels(labels_path, formats=formats, topics=topics)
        run(
            load_config(images, results, schema, rules_path),
            dry_run=True,
            nodes=tuple(nodes),
            vision=vision,
        )
        with psycopg.connect(schema) as conn:
            rows = conn.execute(
                "select source_path, duplicate_paths, status::text, format, topic, branch "
                "from files"
            ).fetchall()
    return evaluate(labels, to_outcomes(rows, images))


def main(
    argv: Sequence[str] | None = None,
    images: Path = IMAGES,
    labels_path: Path = LABELS,
    registry: Sequence[Any] | None = None,
    rules_path: Path | None = None,
    vision: Any = None,
) -> int:
    """`images`, `labels_path`, `registry`, `rules_path` and `vision` are test seams: with
    `vision=None` the classify node builds the real SigLIP and NSFW backends (CLS-002.2)."""
    import os

    detail = "--detail" in (sys.argv[1:] if argv is None else argv)
    try:
        dsn = check_prerequisites(os.environ.get("DB_DSN"), images)
        if registry is None:
            from classifier.graph import nodes as graph_nodes

            registry = graph_nodes.REGISTRY
        measures = run_pipeline(dsn, images, labels_path, gate_nodes(registry), rules_path, vision)
    except (GateSetupError, GateRunError, fixture_labels.LabelsError) as exc:  # fixed text
        print(f"gate 3 FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # the type only: a message can carry a value, a path or the DSN
        print(f"gate 3 FAIL: run errored ({type(exc).__name__})", file=sys.stderr)
        return 1
    verdict = judge(measures, detail)
    print("\n".join((*verdict.lines, *verdict.detail)))
    return 0 if verdict.passed else 1


if __name__ == "__main__":
    sys.exit(main())
