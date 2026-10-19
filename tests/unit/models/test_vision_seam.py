"""MOD-002.1.1: the pure scoring maths and the `VisionBackend` seam, on fake vectors only.

No model, no image decode: arrays in, arrays out (MOD-002.D2).
"""

import math
from collections.abc import Sequence

import numpy as np
import pytest
from PIL import Image

from classifier.models.vision import (
    VisionBackend,
    VisionError,
    cosine_matrix,
    l2_normalize,
    max_over_prompts,
    score_images,
    score_matrix,
)


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def test_sigmoid_matches_the_formula() -> None:
    cos = np.array([[0.1, -0.2, 0.0], [0.3, 0.05, -0.4]], dtype=np.float32)
    out = score_matrix(cos, mode="sigmoid", logit_scale=117.0, logit_bias=-12.0)
    expected = [[sigmoid(117.0 * float(c) - 12.0) for c in row] for row in cos]
    assert out.dtype == np.float32
    assert out.shape == cos.shape
    assert np.allclose(out, np.array(expected), atol=1e-6)


def test_cosine_mode_returns_the_raw_cosine() -> None:
    cos = np.array([[0.25, -0.5]], dtype=np.float32)
    out = score_matrix(cos, mode="cosine", logit_scale=117.0, logit_bias=-12.0)
    assert np.array_equal(out, cos)


def test_sigmoid_stays_in_range_and_finite_at_extremes() -> None:
    cos = np.array([[1.0, -1.0, 0.0]], dtype=np.float32)
    out = score_matrix(cos, mode="sigmoid", logit_scale=1e6, logit_bias=0.0)
    assert np.all(np.isfinite(out))
    assert out.min() >= 0.0 and out.max() <= 1.0
    assert out[0, 0] == 1.0 and out[0, 1] == 0.0 and out[0, 2] == 0.5


def test_sigmoid_is_monotonic_in_the_cosine() -> None:
    cos = np.linspace(-1, 1, 21, dtype=np.float32)[None, :]
    out = score_matrix(cos, mode="sigmoid", logit_scale=10.0, logit_bias=-1.0)[0]
    assert np.all(np.diff(out) >= 0)


@pytest.mark.parametrize("scale, bias", [(float("nan"), 0.0), (1.0, float("inf"))])
def test_non_finite_parameters_are_refused(scale: float, bias: float) -> None:
    with pytest.raises(VisionError):
        score_matrix(np.zeros((1, 1)), mode="sigmoid", logit_scale=scale, logit_bias=bias)


def test_non_finite_parameters_do_not_matter_for_cosine() -> None:
    out = score_matrix(
        np.ones((1, 2)), mode="cosine", logit_scale=float("nan"), logit_bias=float("nan")
    )
    assert out.shape == (1, 2)


def test_unknown_mode_and_bad_rank_are_refused_with_fixed_text() -> None:
    with pytest.raises(VisionError, match="unknown score mode"):
        score_matrix(np.zeros((1, 1)), mode="softmax", logit_scale=1.0, logit_bias=0.0)
    with pytest.raises(VisionError, match="2-D"):
        score_matrix(np.zeros(3), mode="sigmoid", logit_scale=1.0, logit_bias=0.0)


def test_max_over_prompts_takes_the_best_prompt_per_category() -> None:
    scores = np.array([[0.1, 0.9, 0.4, 0.2], [0.7, 0.3, 0.1, 0.8]], dtype=np.float32)
    out = max_over_prompts(scores, ["qorvex", "qorvex", "zhyndel", "zhyndel"])
    assert out[0] == {"qorvex": pytest.approx(0.9), "zhyndel": pytest.approx(0.4)}
    assert out[1] == {"qorvex": pytest.approx(0.7), "zhyndel": pytest.approx(0.8)}


def test_max_over_prompts_handles_interleaved_columns_and_keeps_first_seen_order() -> None:
    scores = np.array([[0.2, 0.6, 0.5, 0.1]], dtype=np.float32)
    out = max_over_prompts(scores, ["zhyndel", "qorvex", "zhyndel", "qorvex"])
    assert list(out[0]) == ["zhyndel", "qorvex"]
    assert out[0]["zhyndel"] == pytest.approx(0.5)
    assert out[0]["qorvex"] == pytest.approx(0.6)


def test_max_over_prompts_with_no_images_is_empty() -> None:
    assert max_over_prompts(np.zeros((0, 2), dtype=np.float32), ["a", "b"]) == []


def test_max_over_prompts_refuses_ragged_input() -> None:
    with pytest.raises(VisionError, match="prompt categories"):
        max_over_prompts(np.zeros((1, 3)), ["a", "b"])
    with pytest.raises(VisionError, match="prompt categories"):
        max_over_prompts(np.zeros(3), ["a", "b", "c"])
    with pytest.raises(VisionError, match="at least one prompt"):
        max_over_prompts(np.zeros((2, 0)), [])


def test_l2_normalize_gives_unit_rows_and_keeps_zero_rows_finite() -> None:
    out = l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert out.dtype == np.float32
    assert np.allclose(out[0], [0.6, 0.8])
    assert np.array_equal(out[1], [0.0, 0.0])
    with pytest.raises(VisionError):
        l2_normalize(np.zeros(4))


def test_cosine_matrix_is_the_dot_product_and_checks_widths() -> None:
    images = l2_normalize(np.array([[1.0, 0.0], [1.0, 1.0]]))
    texts = l2_normalize(np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]))
    out = cosine_matrix(images, texts)
    assert out.shape == (2, 3)
    assert out[0, 0] == pytest.approx(1.0)
    assert out[1, 2] == pytest.approx(1.0)
    with pytest.raises(VisionError, match="matching widths"):
        cosine_matrix(np.zeros((1, 2)), np.zeros((1, 3)))


class FakeBackend:
    """A VisionBackend with fixed embeddings: what TST-008.1's replay also implements."""

    classifier_id = "qorvex/fake-classifier"
    nsfw_id = "qorvex/fake-gate"
    logit_scale = 10.0
    logit_bias = -2.0

    def embed_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        return l2_normalize(np.array([[1.0, 0.0], [0.0, 1.0]])[: len(images)])

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        return l2_normalize(np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])[: len(texts)])

    def nsfw_scores(self, images: Sequence[Image.Image]) -> np.ndarray:
        return np.zeros(len(images), dtype=np.float32)


def test_fake_satisfies_the_protocol() -> None:
    assert isinstance(FakeBackend(), VisionBackend)


def test_score_images_runs_embed_score_and_max() -> None:
    images = [Image.new("RGB", (4, 4)), Image.new("RGB", (4, 4))]
    out = score_images(
        FakeBackend(),
        images,
        ["p1", "p2", "p3"],
        ["qorvex", "zhyndel", "qorvex"],
        mode="sigmoid",
    )
    # image 0 = (1, 0): cos 1, 0, 1/sqrt2 ; image 1 = (0, 1): cos 0, 1, 1/sqrt2.
    assert out[0]["qorvex"] == pytest.approx(sigmoid(10.0 * 1.0 - 2.0), abs=1e-5)
    assert out[0]["zhyndel"] == pytest.approx(sigmoid(-2.0), abs=1e-5)
    assert out[1]["zhyndel"] == pytest.approx(sigmoid(10.0 - 2.0), abs=1e-5)
    raw = score_images(FakeBackend(), images, ["p1", "p2"], ["qorvex", "zhyndel"], mode="cosine")
    assert raw[0] == {"qorvex": pytest.approx(1.0), "zhyndel": pytest.approx(0.0)}


def test_score_images_refuses_prompts_and_categories_of_different_length() -> None:
    with pytest.raises(VisionError, match="prompt categories"):
        score_images(FakeBackend(), [], ["p1", "p2"], ["qorvex"], mode="sigmoid")


def test_error_messages_carry_no_input() -> None:
    secret = "Zhyndel-planted-secret"
    with pytest.raises(VisionError) as info:
        max_over_prompts(np.zeros((1, 3)), [secret, secret])
    assert secret not in str(info.value) and secret not in repr(info.value)
    assert info.value.__cause__ is None and info.value.__context__ is None
