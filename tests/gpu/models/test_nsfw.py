"""MOD-002.2: the real NSFW gate on benign synthetic images (MOD-002.D3, D4, D5), tier `gpu`.

Prerequisites, named on failure (never skipped): `models.nsfw` fetched into the hf volume
(`make models`). The GPU path needs an NVIDIA GPU visible to the test container.

Benign synthetic images only (seeded noise, flat colours, code-rendered invented words). Nothing
here says what a score should be for any content, and no threshold is tuned: the checks are the
shape, the range, determinism, the batch shape and the two device paths (CLS-003 owns the rest).
fp16 on CUDA differs from fp32 on CPU in the last bits, so comparisons use the stated tolerances.
"""

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from classifier.models import nsfw
from classifier.models.nsfw import NSFW_BATCH_SIZE, load_nsfw, score_nsfw
from classifier.models.siglip import SiglipBackend
from classifier.models.vision import VisionError

SEED = 20261014
# Softmax probabilities from the same input: run twice or in another batch shape (fp16).
SCORE_ATOL = 2e-3
# fp16 on the GPU against fp32 on the CPU.
DEVICE_ATOL = 2e-2

PREREQS = (
    "models.nsfw fetched into the hf volume (make models), and an NVIDIA GPU visible to the "
    "test container"
)


def noise_image(seed: int, size: int = 256) -> Image.Image:
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, size=(size, size, 3), dtype=np.uint8), "RGB")


def text_image() -> Image.Image:
    image = Image.new("RGB", (384, 384), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=56)
    for row, line in enumerate(["QORVEX", "ZHYNDEL"]):
        draw.text((24, 20 + row * 88), line, fill="black", font=font)
    return image


@pytest.fixture(scope="module")
def images() -> list[Image.Image]:
    flat = [Image.new("RGB", (128, 128), colour) for colour in ("white", "black", "gray")]
    return [noise_image(SEED + i) for i in range(3)] + [text_image()] + flat


@pytest.fixture(scope="module")
def scorer(nsfw_model_id: str):
    try:
        return load_nsfw(nsfw_model_id)
    except VisionError as error:
        pytest.fail(f"the NSFW gate did not load ({error}); prerequisites: {PREREQS}")


def test_scores_have_the_right_shape_dtype_and_range(scorer, images) -> None:
    out = score_nsfw(scorer, images)
    assert out.shape == (len(images),)
    assert out.dtype == np.float32
    assert np.isfinite(out).all()
    assert out.min() >= 0.0 and out.max() <= 1.0


def test_empty_input_gives_an_empty_array(scorer) -> None:
    assert score_nsfw(scorer, []).shape == (0,)


def test_scores_are_deterministic_across_two_runs(scorer, images) -> None:
    assert np.allclose(score_nsfw(scorer, images), score_nsfw(scorer, images), atol=SCORE_ATOL)


def test_batching_does_not_change_the_scores(scorer) -> None:
    many = [noise_image(SEED + 100 + i, size=64) for i in range(NSFW_BATCH_SIZE + 3)]
    together = score_nsfw(scorer, many)
    alone = np.concatenate([score_nsfw(scorer, [image]) for image in many])
    assert together.shape == (NSFW_BATCH_SIZE + 3,)
    assert np.allclose(together, alone, atol=SCORE_ATOL)


def test_the_backend_scores_through_the_same_gate(
    siglip_backend: SiglipBackend, scorer, images
) -> None:
    assert np.allclose(
        siglip_backend.nsfw_scores(images), score_nsfw(scorer, images), atol=SCORE_ATOL
    )


def test_the_cpu_path_agrees_with_the_gpu_path(nsfw_model_id: str, scorer, images) -> None:
    try:
        cpu = nsfw._TorchNsfw(nsfw_model_id, use_cuda=False)
    except VisionError as error:
        pytest.fail(f"the NSFW gate did not load on CPU ({error}); prerequisites: {PREREQS}")
    on_cpu = score_nsfw(cpu, images)
    assert on_cpu.min() >= 0.0 and on_cpu.max() <= 1.0
    assert np.allclose(on_cpu, score_nsfw(scorer, images), atol=DEVICE_ATOL)
