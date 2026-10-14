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
