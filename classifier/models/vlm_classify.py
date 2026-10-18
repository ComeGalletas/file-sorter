"""The VLM classify client (CLS-004.2, CLS-004.D1, D2, D4, D6, D8, D9).

`vlm_classify` is the node's one entry point. It makes two calls on the same model: one for
format and topic (the schema's enums come from the categories) and one for the NSFW level (scale
A, never given a file name). Both go through `OllamaClient.generate_json` with the prompt files
`classify_v1` and `nsfw_level_v1`; nothing about sampling, context or images is hard-coded here.

The node opens the image (`open_working_copy`, P-2) and passes the PIL image in. This module reads
frames from it with `n_frames` and `seek`, converts each frame it uses to RGB itself, scales the
longest side down to `max_side` (never up) and sends it as JPEG, in memory only.

Failure kinds (CLS-004.D4):
- A failed answer is an HTTP error, a body that is not JSON, an answer cut off at the token limit,
  or a missing or out-of-enum field. It is retried once, at `retry_temperature`, and then raises
  `VlmUnanswered`.
- `OllamaUnavailable` (Ollama unreachable or timed out) propagates at once: it says nothing about
  one file, so the caller rolls the node back instead of marking files as failed.

Errors are fixed text, raised outside any `except` block, so they carry no cause or context and
never quote the file name, a category name or the model's answer.
"""

import base64
import io
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from classifier.config import NsfwLevel
from classifier.models.classify_rules import UNSORTED, VlmAnswer
from classifier.models.ollama import OllamaClient, OllamaError, OllamaUnavailable
from classifier.models.prompts import Prompt, load_prompt

CLASSIFY_PROMPT = "classify_v1"
NSFW_PROMPT = "nsfw_level_v1"
NO_TOPIC = "none"  # the topic enum's "no topic clearly applies" (CLS-004.D1)
# CLS-004.D4: the registered `mark_error` reason for a file the VLM never answered.
UNANSWERED_REASON = "classify_vlm_unanswered"
MAX_FRAMES = 3  # first, middle and last (CLS-004.D2)
# Used when a prompt file sets no image keys; the committed files do (CLS-004.2.2).
DEFAULT_MAX_SIDE = 1024
DEFAULT_JPEG_QUALITY = 90

_ERR_IMAGE = "the image cannot be read as a picture"
_ERR_ENUM = "a category list is empty or holds a non-text name"


class VlmUnanswered(Exception):
    """The VLM gave no usable answer after one retry. The text is the registered reason."""


class VlmImageError(Exception):
    """A frame could not be decoded or encoded. Fixed text; the Pillow error is not quoted."""


@dataclass(frozen=True)
class ClassifyAnswer:
    """The format/topic call's result. `topic` is None for the schema's `none`."""

    format: str = field(repr=False)
    topic: str | None = field(repr=False)


def pick_frames(n_frames: int) -> list[int]:
    """The frame indexes the NSFW call looks at: first, middle and last, without repeats."""
    if n_frames <= 1:
        return [0]
    return sorted({0, n_frames // 2, n_frames - 1})


def encode_frame(frame: Image.Image, *, max_side: int, quality: int) -> str:
    """One frame as base64 JPEG: RGB, longest side at most `max_side`, never scaled up."""
    try:
        rgb = frame.convert("RGB")
        rgb.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        rgb.save(buffer, format="JPEG", quality=quality)
    except (OSError, ValueError, EOFError, SyntaxError):
        raise VlmImageError(_ERR_IMAGE) from None
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def encode_frames(
    image: Image.Image, indexes: Iterable[int], *, max_side: int, quality: int
) -> list[str]:
    """The frames at `indexes`, each seeked to and encoded; the image is left on frame 0."""
    encoded: list[str] = []
    ok = True
    try:
        for index in indexes:
            image.seek(index)
            encoded.append(encode_frame(image, max_side=max_side, quality=quality))
        image.seek(0)
    except (OSError, ValueError, EOFError, SyntaxError, VlmImageError):
        ok = False
    if not ok:
        raise VlmImageError(_ERR_IMAGE)
    return encoded


def _names(base: Sequence[str], extra: str) -> list[str]:
    """`base` without repeats, plus `extra` when it is missing (D1: never duplicated)."""
    names = list(dict.fromkeys(base))
    if not all(isinstance(n, str) and n for n in names):
        raise ValueError(_ERR_ENUM)
    if extra not in names:
        names.append(extra)
    return names


def _usable_hint(hint: str | None) -> str | None:
    """The hint if it is non-blank text that encodes cleanly; otherwise None (fail closed)."""
    if not hint or not hint.strip():
        return None
    try:
        hint.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return hint


def _ask[T](
    client: OllamaClient,
    model: str,
    prompt: Prompt,
    *,
    user: str,
    system: str,
    schema: dict[str, Any],
    images: list[str],
    check: Callable[[dict[str, Any]], T | None],
) -> T:
    """Run the call; one retry at `retry_temperature`; `VlmUnanswered` after two failures."""
    for options in (prompt.options, prompt.retry_options):
        result: T | None = None
        try:
            answer = client.generate_json(
                model,
                user,
                schema,
                options,
                prompt.keep_alive,
                think=prompt.think,
                images=images,
                system=system,
            )
            result = check(answer)
        except OllamaUnavailable:
            raise
        except OllamaError:
            result = None
        if result is not None:
            return result
    raise VlmUnanswered(UNANSWERED_REASON)


def _check_classify(
    formats: list[str], topics: list[str]
) -> Callable[[dict[str, Any]], ClassifyAnswer | None]:
    def check(answer: dict[str, Any]) -> ClassifyAnswer | None:
        fmt, topic = answer.get("format"), answer.get("topic")
        # Exact names: the enums come from the table (CLS-004.2 contract, point 6).
        if not isinstance(fmt, str) or fmt not in formats:
            return None
        if not isinstance(topic, str) or topic not in topics:
            return None
        # A topic that repeats the format is the topic twin: dropped, not retried (the same
        # request would repeat it). `decide` removes twins again as the backstop.
        if topic == NO_TOPIC or topic == fmt:
            return ClassifyAnswer(fmt, None)
        return ClassifyAnswer(fmt, topic)

    return check


def classify_image(
    client: OllamaClient,
    model: str,
    image: Image.Image,
    *,
    hint: str | None,
    formats: Sequence[str],
    topics: Sequence[str],
    prompt: Prompt | None = None,
) -> ClassifyAnswer:
    """Format and topic of `image` from frame 0, with the sanitized name as a weak hint."""
    prompt = prompt or load_prompt(CLASSIFY_PROMPT)
    format_names = _names(formats, UNSORTED)
    topic_names = _names(topics, NO_TOPIC)
    system = prompt.render(formats=", ".join(format_names), topics=", ".join(topic_names))
    schema = prompt.schema_with_enums(format=format_names, topic=topic_names)
    name = _usable_hint(hint)
    user = prompt.render_user() if name is None else prompt.render_user(alt=True, name=name)
    images = encode_frames(
        image,
        [0],
        max_side=prompt.max_side or DEFAULT_MAX_SIDE,
        quality=prompt.jpeg_quality or DEFAULT_JPEG_QUALITY,
    )
    return _ask(
        client,
        model,
        prompt,
        user=user,
        system=system,
        schema=schema,
        images=images,
        check=_check_classify(format_names, topic_names),
    )


def _check_level(answer: dict[str, Any]) -> NsfwLevel | None:
    level = answer.get("nsfw_level")
    if not isinstance(level, str) or level not in NsfwLevel.__members__:
        return None
    return NsfwLevel[level]


def rate_nsfw(
    client: OllamaClient,
    model: str,
    image: Image.Image,
    *,
    prompt: Prompt | None = None,
) -> NsfwLevel:
    """The NSFW level of `image`; there is no name argument, so the name cannot reach the call.

    An animated image is rated in one call on its first, middle and last frames (CLS-004.D2).
    """
    prompt = prompt or load_prompt(NSFW_PROMPT)
    indexes = pick_frames(getattr(image, "n_frames", 1))
    images = encode_frames(
        image,
        indexes,
        max_side=prompt.max_side or DEFAULT_MAX_SIDE,
        quality=prompt.jpeg_quality or DEFAULT_JPEG_QUALITY,
    )
    return _ask(
        client,
        model,
        prompt,
        user=prompt.render_user(alt=len(images) > 1),
        system=prompt.render(),
        schema=prompt.output_schema,
        images=images,
        check=_check_level,
    )


def vlm_classify(
    client: OllamaClient,
    model: str,
    image: Image.Image,
    *,
    hint: str | None,
    formats: Sequence[str],
    topics: Sequence[str],
) -> VlmAnswer:
    """Both calls for one image: the node's entry point (CLS-004.2 contract).

    `formats` and `topics` are category names from the node's query; `unsorted` and `none` are
    added when missing. `hint` is `files.original_sanitized` as stored (None or blank: no hint).
    Raises `VlmUnanswered` after a failed retry and lets `OllamaUnavailable` propagate.
    """
    chosen = classify_image(client, model, image, hint=hint, formats=formats, topics=topics)
    level = rate_nsfw(client, model, image)
    return VlmAnswer(format=chosen.format, topic=chosen.topic, level=level)
