"""Evaluate the VLM classify path on the labelled fixtures (CLS-004.5; R-CLS-8, CLS-004.D11).

Run in the `test` container, which has the throwaway Postgres, ollama and the read-only fixtures
mount:

    docker compose --profile test run --rm test python eval/classify_eval.py

It runs the real ingest and sanitize nodes over the images in a throwaway schema and a temporary
results tree. Then, for each sanitized working copy, it does what the classify node does: opens the
copy with `open_working_frames`, calls `vlm_classify` with the sanitized name as the hint and the
category names (P-2: the model never sees a source path or a raw name), takes the Falconsai score,
and applies `decide` with `nsfw.min_level`. There is nothing to sweep: the thresholds are
configuration, and this reports what the committed configuration achieves. It edits no config,
migration or prompt (CLAUDE.md §1.7).

The measures are `scripts/gate_3.py`'s own (`evaluate` and `judge`), so the eval and the gate count
the same thing. Nothing is copied from them.

Privacy (TST-008.D1, D6): the default output is the public form, safe to paste: format, topic and
unrecognized as a verdict and a whole percent, adult and suggestive-negative as ok or FAIL, and
whether each prompt has a local prompt (present or absent, never its hash: the hash fingerprints
private text). `--detail` adds one-decimal figures, per-category detail, the effective prompt
versions with their local-prompt hashes and the Falconsai cross-check count for the box console,
and is never pasted or committed. Labels are matched to ledger rows by file name in memory only; the
cache holds answers keyed by source hash.
Every error is fixed text.

Categories (CLS-007.3). The throwaway schema holds only the seeded, generic descriptions. With
`--categories-from-app-db` the run first reads the local app database's categories (the DSN comes
from `APP_DB_DSN`, passed with `-e`; the connection is read-only) and applies them to the
throwaway schema: descriptions for categories that exist on the same axis, and the categories only
the app database has. The descriptions are kept per axis (a name can exist on both) and reach
`vlm_classify` as `format_definitions` and `topic_definitions`. The DSN, the descriptions and the
category names are never printed; the report says only where the descriptions came from.
"""

import hashlib
import json
import math
import os
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _path in (REPO, REPO / "eval", REPO / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import fixture_labels  # noqa: E402
import gate_3 as gate  # noqa: E402

from classifier.config import NsfwLevel  # noqa: E402
from classifier.models.classify_rules import (  # noqa: E402
    CategoryRule,
    ClassifyRulesError,
    VlmAnswer,
    decide,
    validate_rules,
)
from classifier.models.prompts import PROMPTS_DIR, Prompt, load_effective_prompt  # noqa: E402
from classifier.models.vlm_classify import (  # noqa: E402
    CLASSIFY_PROMPT,
    NSFW_PROMPT,
    VlmImageError,
    VlmUnanswered,
    vlm_classify,
)

CONFIG = REPO / "config.yaml"
IMAGES = REPO / "fixtures" / "images"
LABELS = REPO / "fixtures" / "labels.csv"
CACHE_DIR = REPO / "eval" / ".cache"  # git-ignored by eval/.gitignore
NODES = ("ingest", "sanitize")
PROMPT_NAMES = (CLASSIFY_PROMPT, NSFW_PROMPT)
DISAGREEMENT = "nsfw_disagreement"  # classify_rules.decide's review reason for the cross-check


class EvalError(Exception):
    """A step failed. The message is fixed text: no path, name, label or rule value."""


_ERR_NOT_SANITIZED = "an image did not reach the sanitized status: check Ollama and the rules"
_ERR_PROMPT = "a prompt file cannot be read"
_ERR_NO_CLIENT = "OLLAMA_HOST is not set: run it in the test container"
_ERR_NO_APP_DSN = "APP_DB_DSN is not set: pass it with -e at run time"
_ERR_APP_DB = "the app database cannot be read"
_APP_DB_OPTIONS = "-c default_transaction_read_only=on"


# --- Prompt versions ------------------------------------------------------------------------


def prompt_file_digest(name: str, prompts_dir: Path = PROMPTS_DIR) -> str:
    """SHA-256 of the committed prompt file: part of the cache key, never printed."""
    data = None
    try:
        path = prompts_dir / f"{name}.md"
        if stat.S_ISREG(path.lstat().st_mode):
            data = path.read_bytes()
    except OSError:
        data = None
    if data is None:  # raised outside the `except`, so it is unchained
        raise EvalError(_ERR_PROMPT)
    return hashlib.sha256(data).hexdigest()


def effective_prompts(prompts_dir: Path = PROMPTS_DIR) -> tuple[Prompt, ...]:
    """The prompts the VLM path uses, with their local replacements when present (CLS-004.8)."""
    return tuple(load_effective_prompt(name, prompts_dir) for name in PROMPT_NAMES)


def local_prompt_lines(prompts: Sequence[Prompt]) -> list[str]:
    """The publishable fact about the local prompts: present or absent per prompt, never a hash.

    When any is present the report says so (CLS-004.D17: provisional, the human decides).
    """
    lines = [
        "local prompts: "
        + ", ".join(f"{p.version} {'present' if p.replacement_hash else 'absent'}" for p in prompts)
    ]
    if any(p.replacement_hash for p in prompts):
        lines.append("with the provisional H8 local prompts")
    return lines


def versions_line(prompts: Sequence[Prompt]) -> str:
    """Effective versions with their local-prompt hashes: the local console only (CLS-004.D17)."""
    return "effective prompts (console only): " + ", ".join(p.effective_version for p in prompts)


def _digest(value: object) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


# --- The per-image cache --------------------------------------------------------------------


@dataclass(frozen=True)
class Answer:
    """One image's VLM answer and Falconsai score; keyed by source hash, never by a name."""

    format: str = field(repr=False)
    topic: str | None = field(repr=False)
    level: str = field(repr=False)  # an `NsfwLevel` name
    nsfw: float | None = field(repr=False)
    traces: bool = field(default=False, repr=False)  # CLS-007.D2: the model's raw flag

    def vlm(self) -> VlmAnswer:
        return VlmAnswer(self.format, self.topic, NsfwLevel[self.level], nsfw_traces=self.traces)


def cache_key(
    model: str,
    prompt_hashes: Sequence[str],
    min_level: NsfwLevel,
    formats: Sequence[str],
    topics: Sequence[str],
    format_definitions: Mapping[str, str | None] | None = None,
    topic_definitions: Mapping[str, str | None] | None = None,
    conservative_traces: bool = False,
) -> str:
    """The cache file's name: the VLM tag, the prompt and local-prompt digests, `min_level`, the
    category names, each axis's descriptions and the traces flag, all reduced to one digest. No
    label, path, file name or description is readable from it."""
    return _digest(
        [
            model,
            list(prompt_hashes),
            min_level.name,
            list(formats),
            list(topics),
            sorted((format_definitions or {}).items()),
            sorted((topic_definitions or {}).items()),
            bool(conservative_traces),
        ]
    )


def load_cache(folder: Path, key: str) -> dict[str, Answer]:
    """The cached answers, or {} for anything unreadable: a cache is only a speed-up."""
    out: dict[str, Answer] = {}
    try:
        path = folder / f"{key}.json"
        if stat.S_ISREG(path.lstat().st_mode):
            data = json.loads(path.read_bytes().decode("utf-8", errors="surrogatepass"))
            for digest, row in data["answers"].items():
                topic, score = row["topic"], row["nsfw"]
                traces = row.get("traces", False)
                if not isinstance(traces, bool):
                    raise TypeError  # drops the whole cache
                level = str(row["level"])
                NsfwLevel[level]  # an unknown name drops the whole cache
                out[str(digest)] = Answer(
                    str(row["format"]),
                    None if topic is None else str(topic),
                    level,
                    None if score is None else float(score),
                    traces,
                )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}
    return out


def save_cache(folder: Path, key: str, answers: Mapping[str, Answer]) -> bool:
    """Write the cache atomically. False when it cannot be written (never fatal)."""
    payload = {
        "answers": {
            digest: {
                "format": a.format,
                "topic": a.topic,
                "level": a.level,
                "nsfw": a.nsfw,
                "traces": a.traces,
            }
            for digest, a in sorted(answers.items())
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


# --- The app database's categories (CLS-007.D4) --------------------------------------------


@dataclass(frozen=True)
class AppCategory:
    """One category of the app database; every field can hold the human's private wording."""

    axis: str = field(repr=False)
    name: str = field(repr=False)
    folder: str = field(repr=False)
    branch: str = field(repr=False)
    description: str | None = field(repr=False)
    parent: str | None = field(repr=False)  # the parent's name on the same axis


def read_app_categories(dsn: str | None, connect: Callable | None = None) -> list[AppCategory]:
    """The app database's categories, read-only. Any failure is one fixed text, unchained."""
    if not dsn:
        raise EvalError(_ERR_NO_APP_DSN)
    found = None
    try:
        if connect is None:
            import psycopg

            connect = psycopg.connect
        with connect(dsn, options=_APP_DB_OPTIONS) as conn:
            rows = conn.execute(
                "select c.axis, c.name, c.folder, c.branch, c.description, p.name "
                "from categories c left join categories p on p.id = c.parent_id "
                "order by c.id"
            ).fetchall()
        found = [
            AppCategory(
                str(a),
                str(n),
                str(f),
                str(b),
                None if d is None else str(d),
                None if p is None else str(p),
            )
            for a, n, f, b, d, p in rows
        ]
    except Exception:  # fixed text only: a driver message can carry the DSN
        found = None
    if found is None:
        raise EvalError(_ERR_APP_DB)
    return found


def apply_app_categories(conn, app: Sequence[AppCategory]) -> int:
    """Copy `app` into the throwaway schema; return how many categories could not be applied.

    A category that exists on its axis takes the app's description. One that only the app has is
    inserted, parents first. One whose parent is in neither place, or that the schema's own
    constraints refuse, is skipped and only counted.
    """
    import psycopg

    ids = {
        (str(axis), str(name)): int(i)
        for i, axis, name in conn.execute("select id, axis, name from categories").fetchall()
    }
    pending = []
    for cat in app:
        if (cat.axis, cat.name) in ids:
            conn.execute(
                "update categories set description = %s where axis = %s and name = %s",
                (cat.description, cat.axis, cat.name),
            )
        else:
            pending.append(cat)
    progress = True
    while pending and progress:
        progress, waiting = False, []
        for cat in pending:
            if cat.parent is not None and (cat.axis, cat.parent) not in ids:
                waiting.append(cat)
                continue
            parent = None if cat.parent is None else ids[(cat.axis, cat.parent)]
            try:
                with conn.transaction():
                    new = conn.execute(
                        "insert into categories (axis, name, folder, branch, parent_id, "
                        "description) values (%s, %s, %s, %s, %s, %s) returning id",
                        (cat.axis, cat.name, cat.folder, cat.branch, parent, cat.description),
                    ).fetchone()
                ids[(cat.axis, cat.name)] = int(new[0])
                progress = True
            except psycopg.Error:
                waiting.append(cat)  # counted as skipped below; the driver text is dropped
        pending = waiting
    return len(pending)


def read_definitions(conn) -> tuple[dict[str, str | None], dict[str, str | None]]:
    """One name -> description map per axis, as the classify node reads them."""
    out: dict[str, dict[str, str | None]] = {"format": {}, "topic": {}}
    for axis, name, description in conn.execute(
        "select axis, name, description from categories order by id"
    ).fetchall():
        out[str(axis)][str(name)] = None if description is None else str(description)
    return out["format"], out["topic"]


# --- The run: ledger, categories, the VLM ---------------------------------------------------


@dataclass(frozen=True)
class Checks:
    """The CLS-003.1.5 bug checks that still apply: public (ok or FAIL only)."""

    nsfw_label: bool = field(repr=False)  # the scorer reads the `nsfw` id2label entry
    nsfw_input: bool = field(repr=False)  # each copy is a regular, sanitized file that decodes
    coverage: bool = field(repr=False)  # labels and images match one to one


@dataclass(frozen=True)
class Collected:
    measures: gate.Measures = field(repr=False)
    checks: Checks = field(repr=False)
    prompts: tuple[Prompt, ...] = field(repr=False)  # their hashes are console-only
    min_level: str = field(repr=False)
    cross_checked: int = field(repr=False)  # rows the Falconsai cross-check flags: detail only
    descriptions: str = field(default="seeded", repr=False)  # `app database` or `seeded`
    conservative_traces: bool = field(default=False, repr=False)
    skipped: int | None = field(default=None, repr=False)  # app categories not applied


@dataclass(frozen=True)
class _Row:
    source_hash: str = field(repr=False)
    ext: str = field(repr=False)
    hint: str | None = field(repr=False)  # `original_sanitized`: the only name a model may see


def nsfw_label_ok(model_id: str) -> bool:
    """Whether the model's own config has exactly one `nsfw` label, and the scorer picks it."""
    from transformers import AutoConfig

    from classifier.models.nsfw import NSFW_LABEL, nsfw_class_index

    ok = False
    try:
        labels = AutoConfig.from_pretrained(model_id, local_files_only=True).id2label
        index = nsfw_class_index(labels)
        ok = index is not None and str(labels[index]).strip().lower() == NSFW_LABEL
    except Exception:  # fixed verdict only: a library message can carry a path
        ok = False
    return ok


def harness_nodes():
    """The ingest and sanitize nodes, in that order: the eval never runs a later node."""
    from classifier.graph import nodes as graph_nodes

    picked = tuple(n for name in NODES for n in graph_nodes.REGISTRY if n.name == name)
    if tuple(n.name for n in picked) != NODES:
        raise EvalError("the node registry must hold one ingest and one sanitize node")
    return picked


def read_rules(conn) -> list[CategoryRule]:
    """The category rules of the migrated schema, as the classify node reads them."""
    return [
        CategoryRule(
            id=int(i),
            axis=str(axis),
            name=str(name),
            folder=str(folder),
            min_score=None if min_score is None else float(min_score),
            branch=str(branch),
            parent_id=None if parent is None else int(parent),
        )
        for i, axis, name, folder, min_score, branch, parent in conn.execute(
            "select id, axis, name, folder, min_score, branch, parent_id "
            "from categories order by id"
        ).fetchall()
    ]


def verify_copies(rows: Sequence[_Row], work: Path) -> bool:
    """CLS-003.1.8: every classified copy is a real input of the sanitize node.

    Each one is a regular file (a link is refused) directly in the resolved `.work`, and opens
    through `open_working_frames` and decodes to RGB, the way the node feeds the models.
    """
    from classifier.fileops.copy_move import working_copy_name
    from classifier.graph.classify import WorkingCopyUnreadable, first_frame_rgb
    from classifier.graph.classify import open_working_frames as open_frames

    try:
        root = work.resolve(strict=True)
        for row in rows:
            path = work / working_copy_name(row.source_hash, row.ext)
            if not stat.S_ISREG(path.lstat().st_mode) or path.resolve(strict=True).parent != root:
                return False
            with open_frames(work, row.source_hash, row.ext) as image:
                if first_frame_rgb(image).mode != "RGB":
                    return False
    except (OSError, WorkingCopyUnreadable):
        return False
    return True


def judge_image(
    client,
    model: str,
    backend,
    work: Path,
    row: _Row,
    formats: Sequence[str],
    topics: Sequence[str],
    format_definitions: Mapping[str, str | None] | None = None,
    topic_definitions: Mapping[str, str | None] | None = None,
) -> Answer | None:
    """One image's answer the way the classify node asks for it, or None when it has none.

    `OllamaUnavailable` is not caught: it says nothing about this file, so it stops the run.
    """
    from classifier.graph.classify import (
        WorkingCopyUnreadable,
        first_frame_rgb,
    )
    from classifier.graph.classify import open_working_frames as open_frames

    answer: Answer | None = None
    try:
        with open_frames(work, row.source_hash, row.ext) as frames:
            rgb = first_frame_rgb(frames)
            score = float(backend.nsfw_scores([rgb])[0])
            rgb.close()
            said = vlm_classify(
                client,
                model,
                frames,
                hint=row.hint,
                formats=formats,
                topics=topics,
                format_definitions=format_definitions,
                topic_definitions=topic_definitions,
            )
        answer = Answer(
            said.format,
            said.topic,
            said.level.name,
            score if math.isfinite(score) else None,
            said.nsfw_traces,
        )
    except (VlmUnanswered, VlmImageError, WorkingCopyUnreadable):
        answer = None
    return answer


def collect(
    dsn: str,
    images: Path,
    labels_path: Path,
    client,
    backend,
    cache_folder: Path | None,
    nodes=None,
    label_check=nsfw_label_ok,
    prompts_dir: Path = PROMPTS_DIR,
    app_categories: Sequence[AppCategory] | None = None,
) -> Collected:
    """Ingest, sanitize and classify `images` on the VLM path; tally the labels against it.

    The schema and the results tree are removed when this returns (CLS-003.1: throwaway).
    """
    import tempfile

    import psycopg

    from classifier.graph.run import run
    from tests.integration.schema_support import migrated_schema

    with migrated_schema(dsn) as schema, tempfile.TemporaryDirectory() as results:
        config = gate.load_config(images, results, schema)
        run(config, dry_run=True, nodes=tuple(nodes or harness_nodes()))
        skipped = None
        with psycopg.connect(schema) as conn:
            if app_categories is not None:
                skipped = apply_app_categories(conn, app_categories)
            ledger = conn.execute(
                "select source_hash, ext, original_sanitized, source_path, duplicate_paths, "
                "status::text from files order by created_at, source_hash"
            ).fetchall()
            rules = read_rules(conn)
            format_defs, topic_defs = read_definitions(conn)
        if any(status not in ("sanitized", "skipped") for *_, status in ledger):
            raise EvalError(_ERR_NOT_SANITIZED)
        validate_rules(rules, None)  # as the node does, before any row is judged
        formats = [r.name for r in rules if r.axis == "format"]
        topics = [r.name for r in rules if r.axis == "topic"]
        labels = fixture_labels.load_labels(labels_path, formats=set(formats), topics=set(topics))
        model = config.models.vlm_safe
        min_level = config.nsfw.min_level
        prompts = effective_prompts(prompts_dir)
        hashes = [prompt_file_digest(name, prompts_dir) for name in PROMPT_NAMES]
        hashes += [p.effective_version for p in prompts]
        conservative = bool(config.nsfw.conservative_traces)  # CLS-007.2's key
        key = cache_key(
            model, hashes, min_level, formats, topics, format_defs, topic_defs, conservative
        )
        answers = load_cache(cache_folder, key) if cache_folder is not None else {}
        cached = len(answers)
        work = Path(results) / ".work"
        kept = [
            _Row(str(h), str(ext), None if hint is None else str(hint))
            for h, ext, hint, _, _, status in ledger
            if status == "sanitized"
        ]
        for row in kept:
            if row.source_hash in answers:
                continue
            found = judge_image(
                client, model, backend, work, row, formats, topics, format_defs, topic_defs
            )
            if found is not None:  # an unanswered image is not cached: the next run asks again
                answers[row.source_hash] = found
        if cache_folder is not None and len(answers) != cached:
            save_cache(cache_folder, key, answers)
        outcomes, cross_checked = [], 0
        for h, _, _, path, duplicates, status in ledger:
            decided = None
            if status == "sanitized":
                decided = _decide(answers.get(h), rules, config.nsfw, conservative)
                status = "classified" if decided is not None else "error"
            if decided is None:
                outcomes.append((path, duplicates, status, None, None, None, None))
                continue
            choice, level = decided
            cross_checked += choice.review_reason == DISAGREEMENT
            outcomes.append(
                (path, duplicates, status, choice.format, choice.topic, choice.branch, level)
            )
        measures = gate.evaluate(
            labels, gate.to_outcomes(outcomes, images), int(config.nsfw.min_level)
        )
        checks = Checks(
            nsfw_label=label_check(backend.nsfw_id),
            nsfw_input=verify_copies(kept, work),
            coverage=measures.coverage_ok,
        )
    return Collected(
        measures,
        checks,
        prompts,
        min_level.name,
        cross_checked,
        "app database" if app_categories is not None else "seeded",
        conservative,
        skipped,
    )


def _decide(
    answer: Answer | None,
    rules: Sequence[CategoryRule],
    nsfw_config,
    conservative_traces: bool = False,
):
    """`(choice, level name)`, or None when the image has no usable answer (a ledger `error`)."""
    if answer is None:
        return None
    choice = None
    try:
        choice = decide(answer.vlm(), rules, answer.nsfw, nsfw_config, conservative_traces)
    except ClassifyRulesError:
        choice = None
    return None if choice is None else (choice, answer.level)


# --- The report -----------------------------------------------------------------------------


def _ok(passed: bool) -> str:
    return "ok" if passed else "FAIL"


def render(collected: Collected, detail: bool = False) -> list[str]:
    """The public form (TST-008.D6): gate 3's own verdict lines, then the prompt hashes.

    `detail` adds the console-only block. The gate's final pass/fail line is dropped: this is a
    report, not a gate.
    """
    checks = collected.checks
    verdict = gate.judge(collected.measures, detail)
    lines = [
        f"classify eval, VLM path (CLS-004.5; judged at nsfw.min_level = {collected.min_level})",
        *local_prompt_lines(collected.prompts),
        f"category descriptions: {collected.descriptions}",
        f"conservative traces: {'on' if collected.conservative_traces else 'off'}",
        *([f"categories skipped: {collected.skipped}"] if collected.skipped is not None else []),
        f"bug checks: nsfw label {_ok(checks.nsfw_label)}, nsfw input {_ok(checks.nsfw_input)}, "
        f"coverage {_ok(checks.coverage)}",
        *verdict.lines[:-1],
    ]
    if detail:
        lines += [
            versions_line(collected.prompts),
            *verdict.detail,
            f"Falconsai cross-check flags {collected.cross_checked} rows (needs_review)",
        ]
    return lines


# --- Entry point ----------------------------------------------------------------------------


def run_eval(
    dsn: str,
    images: Path,
    labels_path: Path,
    cache_folder: Path | None,
    detail: bool,
    client=None,
    backend=None,
    from_app_db: bool = False,
    app_source: Callable[[str | None], Sequence[AppCategory]] = read_app_categories,
) -> list[str]:
    from classifier.config import load_config as load_app_config
    from classifier.models.ollama import OllamaClient
    from classifier.models.siglip import SiglipBackend

    app = app_source(os.environ.get("APP_DB_DSN")) if from_app_db else None
    if backend is None:
        models = load_app_config().models
        backend = SiglipBackend(models.classifier, models.nsfw)  # only the NSFW gate is used
    if client is not None:
        collected = collect(
            dsn, images, labels_path, client, backend, cache_folder, app_categories=app
        )
    else:
        if not os.environ.get("OLLAMA_HOST"):
            raise EvalError(_ERR_NO_CLIENT)
        with OllamaClient.from_env() as own:
            collected = collect(
                dsn, images, labels_path, own, backend, cache_folder, app_categories=app
            )
    return render(collected, detail)


def main(argv: Sequence[str] | None = None, client=None, backend=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate the VLM classify path (CLS-004.5)")
    parser.add_argument("--images", type=Path, default=IMAGES)
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument(
        "--categories-from-app-db",
        action="store_true",
        help="use the categories and descriptions of the app database (APP_DB_DSN, read-only)",
    )
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
            client,
            backend,
            from_app_db=args.categories_from_app_db,
        )
    except (EvalError, gate.GateRunError, gate.GateSetupError, fixture_labels.LabelsError) as exc:
        print(f"classify_eval FAIL: {exc}", file=sys.stderr)  # fixed text by construction
        return 1
    except Exception as exc:  # the type only: a message can carry a value, a path or the DSN
        print(f"classify_eval FAIL: run errored ({type(exc).__name__})", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
