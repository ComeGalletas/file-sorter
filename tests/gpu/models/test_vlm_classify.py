"""CLS-004.2: the VLM classify client against the real `models.vlm_safe`, synthetic images only.

Structure only: the answer lies inside the enums and the level is a valid level. What the model
says about a flat colour or a gradient is not asserted. No fixture image is read.

Prerequisites, named on failure (CLAUDE.md §3, never skipped): the compose `ollama` service is
running in this compose project, and `models.vlm_safe` is pulled (`make models`).
"""

import io

import pytest
from PIL import Image

from classifier.config import NsfwLevel, load_config
from classifier.models.classify_rules import VlmAnswer
from classifier.models.ollama import OllamaClient, OllamaError
from classifier.models.vlm_classify import VlmUnanswered, rate_nsfw, vlm_classify

FORMATS = ["photos", "screenshots", "artwork"]
TOPICS = ["landscapes", "software"]
PREREQS = (
    "start the compose `ollama` service for this project "
    "(docker compose -p <project> up -d ollama) and pull models.vlm_safe (make models)"
)


@pytest.fixture(scope="module")
def client():
    with OllamaClient.from_env() as c:
        yield c


@pytest.fixture(scope="module")
def model() -> str:
    return load_config().models.vlm_safe


def gradient(size: tuple[int, int]) -> Image.Image:
    ramp = Image.linear_gradient("L")
    bands = (ramp.resize(size), ramp.rotate(90).resize(size), Image.new("L", size, 128))
    return Image.merge("RGB", bands)


def animated() -> Image.Image:
    frames = [Image.new("RGB", (96, 96), c) for c in [(240, 20, 20), (20, 240, 20), (20, 20, 240)]]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=50)
    buffer.seek(0)
    return Image.open(buffer)


def run(client: OllamaClient, model: str, image: Image.Image, hint: str | None) -> VlmAnswer:
    try:
        return vlm_classify(client, model, image, hint=hint, formats=FORMATS, topics=TOPICS)
    except (OllamaError, VlmUnanswered) as exc:
        pytest.fail(f"{type(exc).__name__}: {exc}; prerequisites: {PREREQS}")


def check(answer: VlmAnswer) -> None:
    assert answer.format in {*FORMATS, "unsorted"}
    assert answer.topic is None or answer.topic in TOPICS
    assert isinstance(answer.level, NsfwLevel)


def test_a_small_image_is_answered_inside_the_enums(client: OllamaClient, model: str) -> None:
    check(run(client, model, gradient((128, 96)), hint=None))


def test_a_hint_does_not_break_the_answer(client: OllamaClient, model: str) -> None:
    check(run(client, model, gradient((128, 96)), hint="Qorvex_Zhyndel"))


def test_a_large_image_fits_the_context(client: OllamaClient, model: str) -> None:
    # 4000 px wide is sent as a 1024-px JPEG, so it fits num_ctx 4096 (CLS-004.2.2).
    check(run(client, model, gradient((4000, 2500)), hint=None))


def test_an_animated_image_is_rated(client: OllamaClient, model: str) -> None:
    try:
        level = rate_nsfw(client, model, animated())
    except (OllamaError, VlmUnanswered) as exc:
        pytest.fail(f"{type(exc).__name__}: {exc}; prerequisites: {PREREQS}")
    assert isinstance(level, NsfwLevel)
