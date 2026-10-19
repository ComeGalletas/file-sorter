"""MOD-002.1: the real SigLIP on synthetic images (MOD-002.D5), tier `gpu`.

Prerequisites, named on failure by `conftest.py` (never skipped): an NVIDIA GPU and
`models.classifier` fetched into the hf volume (`make models`).

Synthetic images only, generated in code with a pinned seed. No threshold is tuned here
(CLS-003 owns that). fp16 makes results differ in the last bits between batch shapes, so the
equality checks use the stated tolerances below instead of bitwise equality.
"""

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from classifier.models.siglip import BATCH_SIZE, SiglipBackend

DIM = 1152
# fp16 embeddings from the same input, run twice or in a different batch shape.
EMBED_ATOL = 2e-3
SEED = 20261012


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


def test_shapes_dtype_and_normalisation(siglip_backend: SiglipBackend, images) -> None:
    image_vectors = siglip_backend.embed_images(images)
    assert image_vectors.shape == (len(images), DIM)
    assert image_vectors.dtype == np.float32
    assert np.isfinite(image_vectors).all()
    assert np.allclose(np.linalg.norm(image_vectors, axis=1), 1.0, atol=1e-5)


def test_embeddings_are_deterministic_across_two_runs(
    siglip_backend: SiglipBackend, images
) -> None:
    first = siglip_backend.embed_images(images)
    second = siglip_backend.embed_images(images)
    assert np.allclose(first, second, atol=EMBED_ATOL)


def test_batching_does_not_change_the_embeddings(siglip_backend: SiglipBackend) -> None:
    many = [noise_image(SEED + 100 + i, size=64) for i in range(BATCH_SIZE + 3)]
    together = siglip_backend.embed_images(many)
    alone = np.concatenate([siglip_backend.embed_images([image]) for image in many])
    assert together.shape == (BATCH_SIZE + 3, DIM)
    assert np.allclose(together, alone, atol=EMBED_ATOL)
