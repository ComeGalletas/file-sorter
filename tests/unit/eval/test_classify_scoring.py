"""Scoring, the cache and the label join of the calibration harness (CLS-003.1.2).

A fake `VisionBackend` over tiny synthetic images; synthetic labels with coinage names.
"""

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

EVAL = Path(__file__).resolve().parents[3] / "eval"
SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
for folder in (EVAL, SCRIPTS):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import classify_eval as ev  # noqa: E402
from fixture_labels import parse_labels  # noqa: E402

PROMPTS = ev.PromptSet(
    texts={"format": ("a qorvex", "a zhyndel"), "topic": ("a blip", "a quarn")},
    categories={"format": ("Qorvex", "Zhyndel"), "topic": ("Blip", "Quarn")},
)


def _unit(matrix):
    return (matrix / np.linalg.norm(matrix, axis=1, keepdims=True)).astype(np.float32)


class FakeBackend:
    """Embeddings from the image's mean colour; counts its calls."""

    classifier_id = "fake-classifier"
    nsfw_id = "fake-nsfw"
    logit_scale = 10.0
    logit_bias = -2.0

    def __init__(self) -> None:
        self.image_calls = 0

    def embed_images(self, images):
        self.image_calls += len(images)
        rows = [np.array(im).reshape(-1, 3).mean(axis=0)[:2] + 1.0 for im in images]
        return _unit(np.array(rows, dtype=np.float32))

    def embed_texts(self, texts):
        rows = [[1.0 + len(t) % 3, 1.0 + len(t) % 2] for t in texts]
        return _unit(np.array(rows, dtype=np.float32))

    def nsfw_scores(self, images):
        return np.array([0.1 for _ in images], dtype=np.float32)


def make_copies(folder: Path, n: int = 3) -> dict[str, Path]:
    copies = {}
    for i in range(n):
        digest = f"{i:02d}" + "ab" * 31
        path = folder / f"{digest}.png"
        Image.new("RGB", (8, 8), (30 * i, 90, 200 - 40 * i)).save(path)
        copies[digest] = path
    return copies


def test_every_copy_is_scored_per_axis_and_nsfw(tmp_path):
    copies = make_copies(tmp_path)
    scores = ev.score_copies(FakeBackend(), copies, PROMPTS, "sigmoid", None)
    assert set(scores) == set(copies)
    one = next(iter(scores.values()))
    assert set(one.format) == {"Qorvex", "Zhyndel"}
    assert set(one.topic) == {"Blip", "Quarn"}
    assert one.nsfw == pytest.approx(0.1)


def test_a_second_run_reads_the_cache_and_does_not_score(tmp_path):
    copies = make_copies(tmp_path)
    cache = tmp_path / "cache"
    first, second = FakeBackend(), FakeBackend()
    a = ev.score_copies(first, copies, PROMPTS, "sigmoid", cache)
    b = ev.score_copies(second, copies, PROMPTS, "sigmoid", cache)
    assert first.image_calls == 3 and second.image_calls == 0
    assert a == b


def test_only_the_missing_hashes_are_scored(tmp_path):
    copies = make_copies(tmp_path, 4)
    cache = tmp_path / "cache"
    ev.score_copies(FakeBackend(), dict(list(copies.items())[:2]), PROMPTS, "sigmoid", cache)
    backend = FakeBackend()
    ev.score_copies(backend, copies, PROMPTS, "sigmoid", cache)
    assert backend.image_calls == 2


def test_the_cache_key_changes_with_the_prompts_the_mode_and_the_models():
    base = ev.cache_key(FakeBackend(), "sigmoid", PROMPTS)
    other = ev.PromptSet(dict(PROMPTS.texts, topic=("a blip", "another")), PROMPTS.categories)
    assert ev.cache_key(FakeBackend(), "cosine", PROMPTS) != base
    assert ev.cache_key(FakeBackend(), "sigmoid", other) != base
    renamed = FakeBackend()
    renamed.nsfw_id = "other"
    assert ev.cache_key(renamed, "sigmoid", PROMPTS) != base


def test_the_cache_holds_scores_by_hash_and_nothing_else(tmp_path):
    copies = make_copies(tmp_path)
    ev.score_copies(FakeBackend(), copies, PROMPTS, "sigmoid", tmp_path / "cache")
    text = next((tmp_path / "cache").glob("*.json")).read_text(encoding="utf-8")
    assert all(digest in text for digest in copies)
    assert "png" not in text and str(tmp_path) not in text


def test_a_corrupt_or_unwritable_cache_is_ignored(tmp_path):
    copies = make_copies(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    name = ev.cache_key(FakeBackend(), "sigmoid", PROMPTS)
    (cache / f"{name}.json").write_text("not json")
    assert len(ev.score_copies(FakeBackend(), copies, PROMPTS, "sigmoid", cache)) == 3
    blocked = tmp_path / "file"
    blocked.write_text("x")
    assert len(ev.score_copies(FakeBackend(), copies, PROMPTS, "sigmoid", blocked / "sub")) == 3


def test_a_missing_or_linked_copy_is_refused_with_the_hash_only(tmp_path):
    real = make_copies(tmp_path, 1)
    digest, path = next(iter(real.items()))
    link = tmp_path / "link.png"
    link.symlink_to(path)
    for bad in (tmp_path / "gone.png", link):
        with pytest.raises(ev.EvalError) as caught:
            ev.open_rgb(bad, digest[:8])
        assert digest[:8] in str(caught.value)
        assert str(tmp_path) not in str(caught.value)
        assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_an_undecodable_copy_gives_fixed_text(tmp_path):
    path = tmp_path / "junk.png"
    path.write_bytes(b"not an image")
    with pytest.raises(ev.EvalError) as caught:
        ev.open_rgb(path, "abcd1234")
    assert str(caught.value) == "a working copy could not be decoded (abcd1234)"
    assert caught.value.__cause__ is None and caught.value.__context__ is None


LABELS = (
    "file,format,topic,adult,reference,subject,tags\n"
    "p1.png,Qorvex,Blip,no,,,\n"
    "sub/p2.png,Zhyndel,,no,,,suggestive-negative\n"
    "p3.png,Qorvex,Quarn,yes,,,calibration-only\n"
)
LEDGER = [
    ("h1" * 32, "/img/p1.png", []),
    ("h2" * 32, "/img/sub/p2.png", []),
    ("h3" * 32, "/img/other/x.png", ["/img/p3.png"]),
]


def labels():
    return parse_labels(LABELS, formats={"Qorvex", "Zhyndel"}, topics={"Blip", "Quarn"})


def test_labels_match_by_relative_path_or_unique_name_and_duplicates():
    paired = ev.match_labels(LEDGER, "/img", labels())
    assert [digest for _, digest in paired] == ["h1" * 32, "h2" * 32, "h3" * 32]


def test_an_image_with_no_label_or_a_label_with_no_image_fails_the_coverage():
    for ledger in (LEDGER[:2], [*LEDGER, ("h4" * 32, "/img/p4.png", [])]):
        with pytest.raises(ev.EvalError) as caught:
            ev.match_labels(ledger, "/img", labels())
        assert str(caught.value) == "the labels and the images do not match exactly"
        assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_a_bare_name_shared_by_two_images_is_ambiguous():
    ledger = [
        *LEDGER[:2],
        ("h3" * 32, "/img/a/p3.png", ["/img/b/p3.png"]),
        ("h5" * 32, "/img/c/p3.png", []),
    ]
    with pytest.raises(ev.EvalError, match="share a file name"):
        ev.match_labels(ledger, "/img", labels())


def test_items_carry_the_labels_tags_and_scores():
    paired = ev.match_labels(LEDGER, "/img", labels())
    scores = {digest: ev.Scores({"Qorvex": 0.5}, {"Blip": 0.4}, 0.2) for _, digest in paired}
    items = ev.build_items(paired, scores)
    assert [i.calibration_only for i in items] == [False, False, True]
    assert [i.suggestive_negative for i in items] == [False, True, False]
    assert [i.adult for i in items] == [False, False, True]
    assert items[0].format == "Qorvex" and items[1].topic is None


def test_reprs_hold_no_scores_or_names():
    secret = "Xqzvt-planted"
    scores = ev.Scores({secret: 0.7123}, {secret: 0.7123}, 0.4411)
    prompts = ev.PromptSet({"format": (secret,)}, {"format": (secret,)})
    for obj in (scores, prompts):
        text = repr(obj) + str(obj)
        assert secret not in text and "0.7123" not in text and "0.4411" not in text
