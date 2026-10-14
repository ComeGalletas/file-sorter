"""MOD-002.1: the real SigLIP on synthetic images (MOD-002.D5), tier `gpu`.

Prerequisites, named on failure by `conftest.py` (never skipped): an NVIDIA GPU and
`models.classifier` fetched into the hf volume (`make models`).

Synthetic images only, generated in code with a pinned seed. No threshold is tuned here
(CLS-003 owns that). fp16 makes results differ in the last bits between batch shapes, so the
equality checks use the stated tolerances below instead of bitwise equality.
"""

import math

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from classifier.models.siglip import BATCH_SIZE, SiglipBackend
from classifier.models.vision import (
    cosine_matrix,
    max_over_prompts,
    score_images,
    score_matrix,
)

DIM = 1152
# fp16 embeddings from the same input, run twice or in a different batch shape.
EMBED_ATOL = 2e-3
SCORE_ATOL = 2e-3
# Smallest cosine gap for which the prompt ordering is compared (see the ordering check).
ORDER_GAP = 1e-3
SEED = 20261012

PROMPTS = [
    "a photo of a page of printed text",
    "a photo of a mountain landscape",
    "a screenshot of a user interface",
]
CATEGORIES = ["document", "landscape", "document"]


def noise_image(seed: int, size: int = 256) -> Image.Image:
    rng = np.random.default_rng(seed)
    pixels = rng.integers(0, 256, size=(size, size, 3), dtype=np.uint8)
    return Image.fromarray(pixels, "RGB")


def text_image() -> Image.Image:
    image = Image.new("RGB", (384, 384), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=56)
    for row, line in enumerate(["QORVEX", "ZHYNDEL", "BRAKMOOR", "VELKARRA"]):
        draw.text((24, 20 + row * 88), line, fill="black", font=font)
    return image


@pytest.fixture(scope="module")
def images() -> list[Image.Image]:
    return [noise_image(SEED + i) for i in range(3)] + [text_image()]


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def test_shapes_dtype_and_normalisation(siglip_backend: SiglipBackend, images) -> None:
    image_vectors = siglip_backend.embed_images(images)
    text_vectors = siglip_backend.embed_texts(PROMPTS)
    assert image_vectors.shape == (len(images), DIM)
    assert text_vectors.shape == (len(PROMPTS), DIM)
    for vectors in (image_vectors, text_vectors):
        assert vectors.dtype == np.float32
        assert np.isfinite(vectors).all()
        assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


def test_scoring_parameters_are_usable(siglip_backend: SiglipBackend) -> None:
    assert math.isfinite(siglip_backend.logit_scale) and siglip_backend.logit_scale > 0
    assert math.isfinite(siglip_backend.logit_bias)


def test_embeddings_are_deterministic_across_two_runs(
    siglip_backend: SiglipBackend, images
) -> None:
    first = siglip_backend.embed_images(images)
    second = siglip_backend.embed_images(images)
    assert np.allclose(first, second, atol=EMBED_ATOL)
    texts_a = siglip_backend.embed_texts(PROMPTS)
    texts_b = siglip_backend.embed_texts(PROMPTS)
    assert np.allclose(texts_a, texts_b, atol=EMBED_ATOL)


def test_batching_does_not_change_the_embeddings(siglip_backend: SiglipBackend) -> None:
    many = [noise_image(SEED + 100 + i, size=64) for i in range(BATCH_SIZE + 3)]
    together = siglip_backend.embed_images(many)
    alone = np.concatenate([siglip_backend.embed_images([image]) for image in many])
    assert together.shape == (BATCH_SIZE + 3, DIM)
    assert np.allclose(together, alone, atol=EMBED_ATOL)


def test_modes_range_and_sigmoid_against_cosine(siglip_backend: SiglipBackend, images) -> None:
    cos = cosine_matrix(siglip_backend.embed_images(images), siglip_backend.embed_texts(PROMPTS))
    assert cos.min() >= -1.0 - 1e-5 and cos.max() <= 1.0 + 1e-5
    scale, bias = siglip_backend.logit_scale, siglip_backend.logit_bias
    sig = score_matrix(cos, mode="sigmoid", logit_scale=scale, logit_bias=bias)
    raw = score_matrix(cos, mode="cosine", logit_scale=scale, logit_bias=bias)
    assert np.array_equal(raw, cos)
    assert sig.min() >= 0.0 and sig.max() <= 1.0
    expected = np.array([[sigmoid(scale * float(c) + bias) for c in row] for row in cos])
    assert np.allclose(sig, expected, atol=1e-5)
    # The sigmoid is monotonic in the cosine, so it never reorders prompts within an image.
    # Only rows with a strict gap between neighbouring cosines are compared: a near-tie may
    # round either way in float32 (MOD-002.2 carried finding b).
    gaps = np.diff(np.sort(cos, axis=1), axis=1).min(axis=1)
    strict = gaps > ORDER_GAP
    assert strict.any()
    assert (np.argsort(sig, axis=1)[strict] == np.argsort(cos, axis=1)[strict]).all()


def test_max_over_prompts_is_the_best_single_prompt(siglip_backend: SiglipBackend, images) -> None:
    for mode in ("sigmoid", "cosine"):
        together = score_images(siglip_backend, images, PROMPTS, CATEGORIES, mode=mode)
        singles = [
            score_images(siglip_backend, images, [prompt], [category], mode=mode)
            for prompt, category in zip(PROMPTS, CATEGORIES, strict=True)
        ]
        for row, scores in enumerate(together):
            document = max(singles[0][row]["document"], singles[2][row]["document"])
            assert scores["document"] == pytest.approx(document, abs=SCORE_ATOL)
            assert scores["landscape"] == pytest.approx(
                singles[1][row]["landscape"], abs=SCORE_ATOL
            )
        # And it is a real max: never below any one of the category's prompt columns.
        cos = cosine_matrix(
            siglip_backend.embed_images(images), siglip_backend.embed_texts(PROMPTS)
        )
        columns = score_matrix(
            cos,
            mode=mode,
            logit_scale=siglip_backend.logit_scale,
            logit_bias=siglip_backend.logit_bias,
        )
        assert max_over_prompts(columns, CATEGORIES) == pytest.approx(together, abs=1e-6)


def test_a_rendered_text_image_scores_text_above_landscape(
    siglip_backend: SiglipBackend,
) -> None:
    (scores,) = score_images(
        siglip_backend,
        [text_image()],
        ["a photo of a page of printed text", "a photo of a mountain landscape"],
        ["document", "landscape"],
        mode="cosine",
    )
    assert scores["document"] > scores["landscape"]
