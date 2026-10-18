"""The synthetic scenario the VLM recordings are made from (CLS-004.2.6).

Copied verbatim from the CLS-004.4 integration scenario (`classify_support.py`, #135) so the
recorded requests are the ones the classify node sends. Everything here is synthetic: flat
colours, a gradient and a checkerboard, coined category names and hints. Once the node's module
is on `main`, import these from it instead; both must produce identical bytes.
"""

import hashlib
import io

from PIL import Image

SIZE = 48
LABELS = ("img-a", "img-b", "img-c", "img-d")  # the four stills (gate 3's scenario uses these)
ANIMATED = "img-e"  # three frames: img-a, img-b, img-c, in that order (an animated PNG)
SCENARIO_LABELS = (*LABELS, ANIMATED)
# What the node passes the client, in `categories` id order (CLS-004.4.5.2).
FORMATS = ("qorvex", "zhyndel")
TOPICS = ("vrelk", "xandoz")
# `files.original_sanitized` per image, as stored; a missing label has no name.
HINTS = {
    "img-a": "xandoz notes",
    "img-c": "qorvex sketch, draft 2",
    ANIMATED: "zhyndel loop",
}


def source_hash(label: str) -> str:
    return hashlib.sha256(f"classify-scenario-{label}".encode()).hexdigest()


def make_image(label: str) -> Image.Image:
    """Four benign synthetic pictures: two flat colours, a gradient and a checkerboard."""
    image = Image.new("RGB", (SIZE, SIZE))
    pixels = image.load()
    for x in range(SIZE):
        for y in range(SIZE):
            if label == "img-a":
                pixels[x, y] = (200, 30, 30)
            elif label == "img-b":
                pixels[x, y] = (30, 30, 200)
            elif label == "img-c":
                pixels[x, y] = (x * 255 // (SIZE - 1), y * 255 // (SIZE - 1), 90)
            else:
                pixels[x, y] = (255, 255, 255) if (x // 8 + y // 8) % 2 else (0, 0, 0)
    return image


def make_animated() -> bytes:
    """The animated picture as animated-PNG bytes: lossless, so frame digests are stable."""
    frames = [make_image(label) for label in ("img-a", "img-b", "img-c")]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="PNG", save_all=True, append_images=frames[1:])
    return buffer.getvalue()


def open_scenario_image(label: str) -> Image.Image:
    """The image as the node opens it: a seekable PNG, unconverted (stills RGB)."""
    if label == ANIMATED:
        data = make_animated()
    else:
        buffer = io.BytesIO()
        make_image(label).save(buffer, format="PNG")
        data = buffer.getvalue()
    return Image.open(io.BytesIO(data))
