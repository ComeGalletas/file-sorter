"""CLS-004.5: the VLM-path eval harness end to end, tier `gpu`.

Real ingest and sanitize nodes in a throwaway schema, the real `models.vlm_safe` through Ollama
and the real Falconsai gate, on synthetic images with synthetic labels. The image content is
benign abstract noise, so the labels carry no meaning: this checks the plumbing and the output
form, not accuracy. It never reads `fixtures/`.

Prerequisites, named on failure (never skipped): an NVIDIA GPU, `models.nsfw` in the hf volume and
`models.vlm_safe` pulled (`make models`), the throwaway Postgres (`DB_DSN`, the `test` compose
profile), ollama (`make test-gpu` starts it) and a local `sanitize.yaml` (`make init`).
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
            rules = ev.read_rules(conn)
    formats = [r.name for r in rules if r.axis == "format" and r.name != "unsorted"]
    topics = [r.name for r in rules if r.axis == "topic"]
    labels = tmp_path / "labels.csv"
    write_labels(labels, names, formats, topics)
    return images, labels, tmp_path / "cache", names


class Counting:
    """Wraps the real Ollama client to count the generate calls."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.calls = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def generate_json(self, *args, **kwargs):
        self.calls += 1
        return self.inner.generate_json(*args, **kwargs)


@pytest.fixture
def client():
    from classifier.models.ollama import OllamaClient

    if not os.environ.get("OLLAMA_HOST"):
        pytest.fail(f"OLLAMA_HOST is not set; prerequisites: {PREREQS}")
    with OllamaClient.from_env() as own:
        yield Counting(own)


def args_for(images: Path, labels: Path, cache: Path) -> list[str]:
    return ["--images", str(images), "--labels", str(labels), "--cache-dir", str(cache)]


def test_the_harness_runs_end_to_end_and_prints_the_public_form(
    siglip_backend, client, workspace, capsys
):
    images, labels, cache, names = workspace
    args = args_for(images, labels, cache)

    assert ev.main(args, client=client, backend=siglip_backend) == 0
    out = capsys.readouterr().out

    # The public form: verdicts, whole percents, ok or FAIL, and the prompt versions as hashes.
    assert re.search(
        r"^local addenda: classify_v1 (present|absent), nsfw_level_v1 (present|absent)$", out, re.M
    )
    assert not re.search(r"[0-9a-f]{8}", out)  # no addendum hash in anything pasteable
    assert re.search(r"^bug checks: nsfw label ok, nsfw input ok, coverage ok$", out, re.M)
    assert re.search(r"^format agreement: \d+% \(required >= 80%\): (ok|FAIL)$", out, re.M)
    assert re.search(r"^topic agreement: \d+% \(required >= 80%\): (ok|FAIL)$", out, re.M)
    assert re.search(r"^unrecognized format: \d+% \(required < 10%\): (ok|FAIL)$", out, re.M)
    assert re.search(r"^nsfw gate \(adult flagged, safe not flagged\): (ok|FAIL)$", out, re.M)
    assert re.search(r"^suggestive-negative rows safe: (ok|FAIL)$", out, re.M)
    assert not re.search(r"DETAIL|Falconsai|\d+\.\d+%|\d+/\d+", out)
    assert "sweep" not in out and "proposed" not in out

    # No file name, path or label leaks into the output.
    assert not any(name in out for name in names)
    assert str(images) not in out and str(labels) not in out
    assert "qorvex_" not in out

    # Every image was asked once (two VLM calls each); a second run reads the cache and asks none.
    assert client.calls >= 2 * (N_IMAGES - 1), "the VLM was not asked about every image"
    assert list(cache.glob("*.json"))
    again = Counting(client.inner)
    assert ev.main(args, client=again, backend=siglip_backend) == 0
    assert again.calls == 0
    assert capsys.readouterr().out == out  # the cached answers make the report repeatable


def test_detail_stays_behind_the_flag(siglip_backend, client, workspace, capsys):
    images, labels, cache, _ = workspace
    args = args_for(images, labels, cache)
    assert ev.main([*args, "--detail"], client=client, backend=siglip_backend) == 0
    out = capsys.readouterr().out
    assert "DETAIL: box console only" in out
    assert re.search(
        r"^effective prompts \(console only\): classify_v1(\+[0-9a-f]{8})?, ", out, re.M
    )
    assert re.search(r"^Falconsai cross-check flags \d+ rows", out, re.M)


def test_a_missing_label_fails_the_coverage_check_and_names_nothing(
    siglip_backend, client, workspace, capsys
):
    images, labels, cache, names = workspace
    lines = labels.read_text(encoding="utf-8").splitlines()
    labels.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    assert ev.main(args_for(images, labels, cache), client=client, backend=siglip_backend) == 0
    out = capsys.readouterr().out
    assert "coverage FAIL" in out
    assert not any(name in out for name in names)


def test_the_nsfw_scorer_picks_the_class_named_nsfw_in_the_real_models_config(nsfw_model_id):
    """CLS-003.1.5 check 1: the id2label entry named `nsfw`, not its complement."""
    from transformers import AutoConfig

    from classifier.models.nsfw import NSFW_LABEL, nsfw_class_index

    labels = AutoConfig.from_pretrained(nsfw_model_id, local_files_only=True).id2label
    index = nsfw_class_index(labels)
    assert index is not None
    assert str(labels[index]).strip().lower() == NSFW_LABEL
    assert sum(str(v).strip().lower() == NSFW_LABEL for v in labels.values()) == 1
    assert ev.nsfw_label_ok(nsfw_model_id)
