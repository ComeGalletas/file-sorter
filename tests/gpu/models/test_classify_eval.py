"""CLS-003.1: the calibration harness end to end, tier `gpu`.

Real ingest and sanitize nodes in a throwaway schema, real SigLIP and NSFW gate, on synthetic
images with synthetic labels. The image content is benign abstract noise, so the labels carry
no meaning: this checks the plumbing and the output form, not the calibrated values. It never
reads `fixtures/`.

Prerequisites, named on failure (never skipped): an NVIDIA GPU, `models.classifier` and
`models.nsfw` in the hf volume (`make models`), the throwaway Postgres (`DB_DSN`, the `test`
compose profile), ollama (`make test-gpu` starts it) and a local `sanitize.yaml` (`make init`).
"""

import os
import random
import re
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
for folder in (REPO / "eval", REPO / "scripts"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import classify_eval as ev  # noqa: E402

pytestmark = pytest.mark.gpu

N_IMAGES = 24
SEED = 20261014
PREREQS = "DB_DSN (the throwaway Postgres of the test profile), ollama, sanitize.yaml (make init)"


def synthetic_folder(folder: Path) -> list[str]:
    """`N_IMAGES` distinct abstract noise images, named like nothing real."""
    names = []
    for i in range(N_IMAGES):
        rng = np.random.default_rng(SEED + i)
        size = 64 + 16 * (i % 4)
        pixels = rng.integers(0, 256, size=(size, size, 3), dtype=np.uint8)
        name = f"qorvex_{i:03d}.png"
        Image.fromarray(pixels, "RGB").save(folder / name)
        names.append(name)
    return names


def write_labels(path: Path, names: list[str], formats: list[str], topics: list[str]) -> None:
    rng = random.Random(SEED)
    rows = ["file,format,topic,adult,reference,subject,tags"]
    for i, name in enumerate(names):
        fmt = rng.choice(formats)
        topic = rng.choice([t for t in topics if t != fmt] + [""])
        tags = "suggestive-negative" if i == 1 else "calibration-only" if i == 2 else ""
        rows.append(f"{name},{fmt},{topic},no,,,{tags}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


@pytest.fixture
def dsn() -> str:
    value = os.environ.get("DB_DSN")
    if not value:
        pytest.fail(f"DB_DSN is not set; prerequisites: {PREREQS}")
    return value


@pytest.fixture
def workspace(tmp_path: Path, dsn: str):
    from tests.integration.schema_support import migrated_schema

    images = tmp_path / "images"
    images.mkdir()
    names = synthetic_folder(images)
    with migrated_schema(dsn) as schema:
        import psycopg

        with psycopg.connect(schema) as conn:
            rules, _ = ev.read_categories(conn)
    formats = [r.name for r in rules if r.axis == "format" and r.name != "unsorted"]
    topics = [r.name for r in rules if r.axis == "topic"]
    labels = tmp_path / "labels.csv"
    write_labels(labels, names, formats, topics)
    return images, labels, tmp_path / "cache", names, formats, topics


class Counting:
    """Wraps the real backend to count the images it embeds."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.images = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def embed_images(self, images):
        self.images += len(images)
        return self.inner.embed_images(images)


def test_the_harness_runs_end_to_end_and_prints_the_public_form(siglip_backend, workspace, capsys):
    images, labels, cache, names, formats, topics = workspace
    args = ["--images", str(images), "--labels", str(labels), "--cache-dir", str(cache)]
    counted = Counting(siglip_backend)

    assert ev.main(args, backend=counted) == 0
    out = capsys.readouterr().out

    # The public form: verdicts, whole percents, config values.
    assert re.search(r"^format agreement: (PASS|FAIL) \d+% \(gate >= 90%\)$", out, re.M)
    assert re.search(r"^topic agreement: (PASS|FAIL) \d+% \(gate >= 85%\)$", out, re.M)
    assert re.search(r"^unrecognized format: (PASS|FAIL) \d+% \(gate < 10%\)$", out, re.M)
    assert "adult flagged and the rest safe: ok" in out
    assert "suggestive-negative safe: ok" in out
    assert re.search(r"^held-out \(5-fold, seed 20261014\): ", out, re.M)
    assert "gap <= 5 points:" in out
    assert re.search(r"^  nsfw\.threshold: [0-9.e-]+$", out, re.M)
    assert re.search(r"^  classify\.format\.default_min_score: [0-9.]+$", out, re.M)
    assert "DETAIL" not in out and not re.search(r"\d+\.\d+%", out)

    # No file name, path or label leaks into the output.
    assert not any(name in out for name in names)
    assert str(images) not in out and str(labels) not in out
    assert "qorvex_" not in out

    # Every image was embedded once; a second run reads the cache and embeds nothing.
    assert counted.images == N_IMAGES
    assert list(cache.glob("*.json"))
    again = Counting(siglip_backend)
    assert ev.main(args, backend=again) == 0
    assert again.images == 0
    assert capsys.readouterr().out == out  # the pinned seed makes the report repeatable


def test_detail_stays_behind_the_flag(siglip_backend, workspace, capsys):
    images, labels, cache, *_ = workspace
    args = ["--images", str(images), "--labels", str(labels), "--cache-dir", str(cache)]
    assert ev.main([*args, "--detail"], backend=siglip_backend) == 0
    out = capsys.readouterr().out
    assert "DETAIL (box console only: never paste, commit or post)" in out
    assert re.search(r"fitted: format \d+\.\d%", out)


def test_a_missing_label_fails_with_fixed_text(siglip_backend, workspace, capsys):
    images, labels, cache, names, *_ = workspace
    lines = labels.read_text(encoding="utf-8").splitlines()
    labels.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    args = ["--images", str(images), "--labels", str(labels), "--cache-dir", str(cache)]
    assert ev.main(args, backend=siglip_backend) == 1
    err = capsys.readouterr().err
    assert err.strip() == "classify_eval FAIL: the labels and the images do not match exactly"
    assert not any(name in err for name in names)
