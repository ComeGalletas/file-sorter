"""MOD-002.3: the synthetic inputs behind `tests/recordings/models/` (MOD-002.D6, TST-008.D9).

Shared by the gpu recording test and the unit replay tests, so the two cannot drift apart: a
recording is keyed by the digest of these exact pixels and by these exact prompt strings.

Images are generated in code from seeded PCG64 noise, flat colours and drawn rectangles. No font
is rendered: Pillow is not pinned, and a rasterisation change would silently change a digest and
orphan the recordings. The prompts are artificial and meet the recordings lint (ASCII letters and
single spaces). Nothing here describes or depicts adult content.
"""

import numpy as np
from PIL import Image, ImageDraw

SEED = 20261015
SIZE = 64

PROMPTS = [
    "a photo of a page of printed text",
    "a photo of a mountain landscape",
    "a screenshot of a user interface",
]
CATEGORIES = ["document", "landscape", "document"]


def noise_image(seed: int, size: int = SIZE) -> Image.Image:
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, size=(size, size, 3), dtype=np.uint8), "RGB")


def flat_image(colour: str, size: int = SIZE) -> Image.Image:
    return Image.new("RGB", (size, size), colour)


def bars_image(size: int = SIZE) -> Image.Image:
    """Dark horizontal bars on white: a text-like layout with no font involved."""
    image = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(image)
    for row in range(6):
        top = 4 + row * 10
        draw.rectangle((4, top, size - 4 - (row % 3) * 12, top + 4), fill="black")
    return image


def scoring_images() -> list[Image.Image]:
    """The images the embedding and scoring tests use."""
    return [noise_image(SEED + i) for i in range(3)] + [bars_image(), flat_image("white")]


def nsfw_images() -> list[Image.Image]:
    """Benign synthetic images for the gate's range and shape checks."""
    return [noise_image(SEED + 10 + i) for i in range(2)] + [
        bars_image(),
        flat_image("white"),
        flat_image("black"),
        flat_image("gray"),
    ]
