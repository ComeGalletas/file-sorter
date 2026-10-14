"""Calibrate the classify thresholds on the labelled fixtures (CLS-003.1; R-CLS-8, CLS-003.D1-D3).

Run in the `test` container, which has the throwaway Postgres and the read-only fixtures mount:

    docker compose --profile test run --rm test python eval/classify_eval.py

It runs the real ingest and sanitize nodes over the images in a throwaway schema and a temporary
results tree, scores each sanitized working copy once through `SiglipBackend` (P-2: the models
never see a source path or a raw name), sweeps the thresholds with `eval/classify_sweep.py` and
prints the proposed values. It edits no config, migration or prompt (CLAUDE.md §1.7): the human
approves the values, and CLS-003.2 commits them.

Privacy (TST-008.D1, D6): the default output is the public form, safe to paste. `--detail` adds
one-decimal figures and per-category detail for the box console, and is never pasted. Labels are
matched to ledger rows by file name in memory only; the cache holds scores keyed by source hash.
Every error is fixed text.
"""

import hashlib
import json
import os
import stat
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _path in (REPO, REPO / "eval", REPO / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import numpy as np  # noqa: E402
from classify_sweep import Item  # noqa: E402
from fixture_labels import TAG_CALIBRATION_ONLY, TAG_SUGGESTIVE_NEGATIVE, LabelSet  # noqa: E402
from PIL import Image  # noqa: E402

from classifier.models.vision import (  # noqa: E402
    VisionBackend,
    cosine_matrix,
    max_over_prompts,
    score_matrix,
)

CONFIG = REPO / "config.yaml"
IMAGES = REPO / "fixtures" / "images"
LABELS = REPO / "fixtures" / "labels.csv"
CACHE_DIR = REPO / "eval" / ".cache"
BATCH = 16


class EvalError(Exception):
    """A step failed. The message is fixed text: no path, name, label or rule value."""


_ERR_COVERAGE = "the labels and the images do not match exactly"
_ERR_AMBIGUOUS = "two images share a file name, so the labels cannot be matched"
_ERR_NOT_SANITIZED = "an image did not reach the sanitized status: check Ollama and the rules"
_ERR_COPY = "a working copy is missing or is not a regular file"
_ERR_DECODE = "a working copy could not be decoded"
_ERR_NO_PROMPTS = "the categories carry no prompts"


# --- Scores ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scores:
    """One image's scores; keyed by source hash, never by a name."""

    format: Mapping[str, float] = field(repr=False)
    topic: Mapping[str, float] = field(repr=False)
    nsfw: float = field(repr=False)


@dataclass(frozen=True)
class PromptSet:
    """Every category prompt of both axes, in the order the scores are built (R-CLS-2)."""

    texts: Mapping[str, tuple[str, ...]] = field(repr=False)  # axis -> prompts
    categories: Mapping[str, tuple[str, ...]] = field(repr=False)  # axis -> a category per prompt

    def digest(self) -> str:
        return _digest({"texts": self.texts, "categories": self.categories})


def _digest(value: object) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def cache_key(backend: VisionBackend, mode: str, prompts: PromptSet) -> str:
    """The cache file's name: the models, the score mode and the prompt set (no label in it)."""
    return _digest([backend.classifier_id, backend.nsfw_id, mode, prompts.digest()])


def load_cache(folder: Path, key: str) -> dict[str, Scores]:
    """The cached scores, or {} for anything unreadable: a cache is only a speed-up."""
    out: dict[str, Scores] = {}
    try:
        path = folder / f"{key}.json"
        if stat.S_ISREG(path.lstat().st_mode):
            data = json.loads(path.read_bytes().decode("utf-8", errors="surrogatepass"))
            for digest, row in data["scores"].items():
                out[str(digest)] = Scores(
                    {str(k): float(v) for k, v in row["format"].items()},
                    {str(k): float(v) for k, v in row["topic"].items()},
                    float(row["nsfw"]),
                )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}
    return out


def save_cache(folder: Path, key: str, scores: Mapping[str, Scores]) -> bool:
    """Write the cache atomically. False when it cannot be written (never fatal)."""
    payload = {
        "scores": {
            digest: {"format": dict(s.format), "topic": dict(s.topic), "nsfw": s.nsfw}
            for digest, s in sorted(scores.items())
        }
    }
    data = json.dumps(payload, sort_keys=True).encode("utf-8", errors="surrogatepass")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{key}.json"
        temp = folder / f"{key}.json.tmp"
        temp.write_bytes(data)
        temp.replace(target)
    except OSError:
        return False
    return True


def open_rgb(path: Path, short_hash: str) -> Image.Image:
    """Decode one working copy to RGB. Refuses links and non-files; errors carry the hash."""
    problem = ""
    image = None
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            problem = _ERR_COPY
        else:
            with Image.open(path) as opened:
                image = opened.convert("RGB")
    except OSError:
        problem = _ERR_DECODE
    except Exception:  # Pillow raises many types; none of their messages is shown
        problem = _ERR_DECODE
    if problem or image is None:
        raise EvalError(f"{problem or _ERR_DECODE} ({short_hash})")
    return image


def score_copies(
    backend: VisionBackend,
    copies: Mapping[str, Path],
    prompts: PromptSet,
    mode: str,
    cache_folder: Path | None,
) -> dict[str, Scores]:
    """Score every working copy once; a hash already in the cache is not scored again."""
    if not any(prompts.texts.values()):
        raise EvalError(_ERR_NO_PROMPTS)
    key = cache_key(backend, mode, prompts)
    scores = load_cache(cache_folder, key) if cache_folder is not None else {}
    todo = [digest for digest in sorted(copies) if digest not in scores]
    if todo:
        text_embeddings = {
            axis: backend.embed_texts(list(texts)) for axis, texts in prompts.texts.items()
        }
        for start in range(0, len(todo), BATCH):
            batch = todo[start : start + BATCH]
            images = [open_rgb(copies[d], d[:8]) for d in batch]
            embedded = backend.embed_images(images)
            nsfw = np.asarray(backend.nsfw_scores(images), dtype=np.float64)
            per_axis = {}
            for axis, texts in text_embeddings.items():
                cosines = cosine_matrix(embedded, texts)
                matrix = score_matrix(
                    cosines,
                    mode=mode,
                    logit_scale=backend.logit_scale,
                    logit_bias=backend.logit_bias,
                )
                per_axis[axis] = max_over_prompts(matrix, prompts.categories[axis])
            for index, digest in enumerate(batch):
                scores[digest] = Scores(
                    per_axis["format"][index], per_axis["topic"][index], float(nsfw[index])
                )
            for image in images:
                image.close()
        if cache_folder is not None:
            save_cache(cache_folder, key, scores)
    return {digest: scores[digest] for digest in copies}


# --- Matching the labels to the ledger (in memory only) -----------------------------------


def match_labels(
    ledger: Sequence[tuple[str, str, Sequence[str]]],
    source_root: str,
    labels: LabelSet,
) -> list[tuple[object, str]]:
    """Pair each label row with a source hash. Coverage must be exact, in both directions.

    `ledger` rows are (source_hash, source_path, duplicate_paths). A label's `file` is a path
    relative to `source_root`, or a bare file name that is unique among the images. Nothing
    here is printed, logged or cached (TST-008.D4).
    """
    root = source_root.rstrip("/") + "/"
    by_path: dict[str, str] = {}
    by_name: dict[str, str | None] = {}
    for digest, path, duplicates in ledger:
        for one in (path, *duplicates):
            relative = one[len(root) :] if one.startswith(root) else one
            by_path[relative] = digest
            name = relative.rsplit("/", 1)[-1]
            by_name[name] = digest if by_name.get(name, digest) == digest else None
    paired: list[tuple[object, str]] = []
    failed = ""
    for row in labels.rows:
        digest = by_path.get(row.file)
        if digest is None and row.file in by_name:
            digest = by_name[row.file]
            if digest is None:
                failed = failed or _ERR_AMBIGUOUS
        if digest is None:
            failed = failed or _ERR_COVERAGE
        else:
            paired.append((row, digest))
    if failed:
        raise EvalError(failed)
    if {digest for _, digest in paired} != {digest for digest, _, _ in ledger}:
        raise EvalError(_ERR_COVERAGE)
    return paired


def build_items(paired: Sequence[tuple[object, str]], scores: Mapping[str, Scores]) -> list[Item]:
    """The sweep's items: each labelled row with its image's scores."""
    items = []
    for row, digest in paired:
        s = scores[digest]
        items.append(
            Item(
                format_scores=s.format,
                topic_scores=s.topic,
                nsfw=s.nsfw,
                format=row.format,  # type: ignore[attr-defined]
                topic=row.topic,  # type: ignore[attr-defined]
                adult=row.adult,  # type: ignore[attr-defined]
                suggestive_negative=TAG_SUGGESTIVE_NEGATIVE in row.tags,  # type: ignore[attr-defined]
                calibration_only=TAG_CALIBRATION_ONLY in row.tags,  # type: ignore[attr-defined]
            )
        )
    return items


# --- The run: ledger, categories, scoring ---------------------------------------------------

NODES = ("ingest", "sanitize")
FORMAT_GATE = 90  # DESIGN.md §11, gate 3
TOPIC_GATE = 85
UNRECOGNIZED_LIMIT = 10


def load_config(source: Path, results: str, dsn: str):
    """config.yaml with the harness's roots and schema (as gate 2 does)."""
    import yaml

    from classifier.config import Config, check_roots

    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    data["paths"] = {"source_root": str(source), "results_root": results}
    data["db"] = {"dsn": dsn}
    config = Config.model_validate(data)
    check_roots(config)  # R-FOP-9
    return config


def harness_nodes():
    """The ingest and sanitize nodes, in that order: scoring never runs a later node."""
    from classifier.graph import nodes as graph_nodes

    picked = tuple(n for name in NODES for n in graph_nodes.REGISTRY if n.name == name)
    if tuple(n.name for n in picked) != NODES:
        raise EvalError("the node registry must hold one ingest and one sanitize node")
    return picked


def read_categories(conn) -> tuple[list, PromptSet]:
    """The category rules and the prompt set of the migrated schema (DB-003, R-CLS-0)."""
    from classifier.models.classify_rules import CategoryRule

    rules = [
        CategoryRule(
            id=int(i),
            axis=axis,
            name=name,
            folder=folder,
            min_score=None if min_score is None else float(min_score),
            branch=branch,
            parent_id=None if parent is None else int(parent),
        )
        for i, axis, name, folder, min_score, branch, parent in conn.execute(
            "select id, axis, name, folder, min_score, branch, parent_id "
            "from categories order by id"
        ).fetchall()
    ]
    texts: dict[str, list[str]] = {"format": [], "topic": []}
    names: dict[str, list[str]] = {"format": [], "topic": []}
    for axis, name, prompt in conn.execute(
        "select c.axis, c.name, p.prompt from category_prompts p "
        "join categories c on c.id = p.category_id order by c.id, p.position"
    ).fetchall():
        texts[axis].append(prompt)
        names[axis].append(name)
    prompts = PromptSet(
        {axis: tuple(v) for axis, v in texts.items()},
        {axis: tuple(v) for axis, v in names.items()},
    )
    return rules, prompts


def find_copy(work: Path, digest: str) -> Path:
    """The one working copy of `digest` under `.work/`, or a fixed error with the hash."""
    found = []
    try:
        found = sorted(work.glob(f"{digest}.*"))
    except OSError:
        found = []
    if len(found) != 1:
        raise EvalError(f"{_ERR_COPY} ({digest[:8]})")
    return found[0]


def collect(
    dsn: str,
    images: Path,
    labels_path: Path,
    backend: VisionBackend,
    cache_folder: Path | None,
    nodes=None,
):
    """Ingest, sanitize and score `images`; return (rules, classify config, items).

    The schema and the results tree are removed when this returns (CLS-003.1: throwaway).
    """
    import tempfile

    import psycopg
    from fixture_labels import load_labels

    from classifier.graph.run import run
    from classifier.models.classify_rules import validate_rules
    from tests.integration.schema_support import migrated_schema

    with migrated_schema(dsn) as schema, tempfile.TemporaryDirectory() as results:
        config = load_config(images, results, schema)
        run(config, dry_run=True, nodes=tuple(nodes or harness_nodes()))
        with psycopg.connect(schema) as conn:
            ledger = conn.execute(
                "select source_hash, source_path, duplicate_paths, status::text from files"
            ).fetchall()
            rules, prompts = read_categories(conn)
        if any(status not in ("sanitized", "skipped") for *_, status in ledger):
            raise EvalError(_ERR_NOT_SANITIZED)
        kept = [(d, p, list(dup or [])) for d, p, dup, status in ledger if status == "sanitized"]
        base = config.classify
        defaults = {"default_min_score": 0.5}
        validate_rules(
            rules,
            base.model_copy(
                update=dict(
                    format=base.format.model_copy(update=defaults),
                    topic=base.topic.model_copy(update=defaults),
                )
            ),
        )
        formats = {r.name for r in rules if r.axis == "format"}
        topics = {r.name for r in rules if r.axis == "topic"}
        labels = load_labels(labels_path, formats=formats, topics=topics)
        paired = match_labels(kept, str(images), labels)
        work = Path(results) / ".work"
        copies = {d: find_copy(work, d) for d, _, _ in kept}
        scores = score_copies(backend, copies, prompts, base.score, cache_folder)
    return rules, base, build_items(paired, scores)


# --- The report -----------------------------------------------------------------------------


def _floor(part: int, whole: int) -> str:
    return f"{100 * part // whole}%" if whole else "n/a"


def _tenth(part: int, whole: int) -> str:
    return f"{100.0 * part / whole:.1f}%" if whole else "n/a"


def _verdict(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def _ok(passed: bool) -> str:
    return "ok" if passed else "FAIL"


def _survive(value: bool | None) -> str:
    if value is None:
        return "none proposed"
    return "ok" if value else "dropped (held-out agreement fell)"


def render(result, slack_points: float, detail: Sequence[str] | None = None) -> list[str]:
    """The public form (TST-008.D6), plus `detail` lines when given (console only)."""
    import classify_sweep as sweep

    fit, held = result.fitted, result.held_out
    lines = [f"classify calibration (CLS-003.1; slack {slack_points:g} points)"]
    if not result.feasible:
        lines += [
            f"adult flagged and the rest safe: {_ok(fit.adult_ok)}",
            f"suggestive-negative safe: {_ok(fit.suggestive_ok)}",
            "no nsfw.threshold satisfies every labelled NSFW row: nothing else was swept",
        ]
        return lines
    f_ok = fit.format_correct * 100 >= FORMAT_GATE * fit.format_total
    t_ok = fit.topic_correct * 100 >= TOPIC_GATE * fit.topic_total
    u_ok = fit.unsorted * 100 < UNRECOGNIZED_LIMIT * fit.rows
    concerns = sweep.has_concerns(fit, held)
    lines += [
        f"format agreement: {_verdict(f_ok)} {_floor(fit.format_correct, fit.format_total)}"
        f" (gate >= {FORMAT_GATE}%)",
        f"topic agreement: {_verdict(t_ok)} {_floor(fit.topic_correct, fit.topic_total)}"
        f" (gate >= {TOPIC_GATE}%)",
        f"unrecognized format: {_verdict(u_ok)} {_floor(fit.unsorted, fit.rows)}"
        f" (gate < {UNRECOGNIZED_LIMIT}%)",
        f"adult flagged and the rest safe: {_ok(fit.adult_ok)}",
        f"suggestive-negative safe: {_ok(fit.suggestive_ok)}",
        f"held-out ({sweep.FOLDS}-fold, seed {sweep.SEED}): "
        f"format {_floor(held.format_correct, held.format_total)}, "
        f"topic {_floor(held.topic_correct, held.topic_total)}, "
        f"unrecognized {_floor(held.unsorted, held.rows)}, "
        f"adult {_ok(held.adult_ok)}, suggestive-negative {_ok(held.suggestive_ok)}",
        f"fitted vs held-out gap <= {sweep.GAP_POINTS:g} points: "
        f"{'CONCERNS' if concerns else 'ok'}",
        "overrides vs the held-out check: "
        f"format {_survive(result.format_overrides_survive)}, "
        f"topic {_survive(result.topic_overrides_survive)}",
        "proposed values (not applied; the human approves them first):",
        f"  classify.format.default_min_score: {result.format.default_min_score:g}",
        f"  classify.format.margin: {result.format.margin:g}",
        f"  classify.topic.default_min_score: {result.topic.default_min_score:g}",
        f"  classify.topic.margin: {result.topic.margin:g}",
        f"  nsfw.threshold: {result.nsfw_threshold:g}",
    ]
    pairs = [("format", n, v) for n, v in result.format.overrides] + [
        ("topic", n, v) for n, v in result.topic.overrides
    ]
    lines.append("  min_score overrides (migration 0004): " + ("none" if not pairs else ""))
    lines += [f"    {axis} {name}: {value:g}" for axis, name, value in sorted(pairs)]
    if detail is not None:
        gaps = sweep.gap_points(fit, held)
        lines += ["", "DETAIL (box console only: never paste, commit or post)"]
        lines += [
            f"  fitted: format {_tenth(fit.format_correct, fit.format_total)}, "
            f"topic {_tenth(fit.topic_correct, fit.topic_total)}, "
            f"unrecognized {_tenth(fit.unsorted, fit.rows)}",
            f"  held-out: format {_tenth(held.format_correct, held.format_total)}, "
            f"topic {_tenth(held.topic_correct, held.topic_total)}, "
            f"unrecognized {_tenth(held.unsorted, held.rows)}",
            f"  gap (points): format {gaps[0]:.1f}, topic {gaps[1]:.1f}",
            *detail,
        ]
    return lines


def detail_lines(items, rules, base, result) -> list[str]:
    """Per-category agreement of the proposed values, one decimal. Console only."""
    import classify_sweep as sweep

    applied, config = sweep.materialize(rules, base, result.format, result.topic)
    table = sweep.per_category(items, applied, config, result.nsfw_threshold)
    out = []
    for axis in ("format", "topic"):
        for label, (right, total) in sorted(table[axis].items()):
            out.append(f"  {axis} {label}: {_tenth(right, total)} ({right}/{total})")
    return out


# --- Entry point ----------------------------------------------------------------------------


def run_eval(
    dsn: str,
    images: Path,
    labels_path: Path,
    cache_folder: Path | None,
    detail: bool,
    slack_points: float,
    backend: VisionBackend | None = None,
) -> list[str]:
    import classify_sweep as sweep

    from classifier.config import load_config as load_app_config
    from classifier.models.siglip import SiglipBackend

    if backend is None:
        models = load_app_config().models
        backend = SiglipBackend(models.classifier, models.nsfw)
    rules, base, items = collect(dsn, images, labels_path, backend, cache_folder)
    result = sweep.calibrate(items, rules, base, slack_points=slack_points)
    extra = detail_lines(items, rules, base, result) if detail and result.feasible else None
    return render(result, slack_points, extra if detail else None)


def main(argv: Sequence[str] | None = None, backend: VisionBackend | None = None) -> int:
    import argparse

    import classify_sweep as sweep

    parser = argparse.ArgumentParser(description="Calibrate the classify thresholds (CLS-003.1)")
    parser.add_argument("--images", type=Path, default=IMAGES)
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--slack-points", type=float, default=sweep.SLACK_POINTS)
    parser.add_argument("--detail", action="store_true", help="box console only; never paste")
    args = parser.parse_args(argv)
    dsn = os.environ.get("DB_DSN")
    if not dsn:
        print(
            "classify_eval FAIL: DB_DSN is not set: run it in the test container", file=sys.stderr
        )
        return 1
    try:
        lines = run_eval(
            dsn,
            args.images,
            args.labels,
            None if args.no_cache else args.cache_dir,
            args.detail,
            args.slack_points,
            backend,
        )
    except (EvalError, sweep.SweepError) as exc:  # fixed text by construction
        print(f"classify_eval FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # the type only: a message can carry a value, a path or the DSN
        print(f"classify_eval FAIL: run errored ({type(exc).__name__})", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
