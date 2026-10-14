"""The vision-model seam and the pure scoring maths (MOD-002.1, R-CLS-2, C-5, P-2).

`VisionBackend` is the one protocol the classify node talks to (MOD-002.D1). The real backend
(`siglip.py`, with the NSFW gate from MOD-002.2) and TST-008.1's replay both implement it. A
backend takes decoded images and plain texts, never a path or a file name (P-2).

The scoring functions are pure (MOD-002.D2): arrays in, arrays out, no model. `score_matrix` is
`sigmoid(logit_scale * cos + logit_bias)` (`classify.score: sigmoid`) or the raw cosine
(`cosine`); `max_over_prompts` takes each category's best prompt (R-CLS-2).

Errors carry fixed text only: never a prompt, a category name, a path or a library message.
"""

from collections.abc import Sequence
from typing import Literal, Protocol, runtime_checkable

import numpy as np
from PIL import Image

ScoreMode = Literal["sigmoid", "cosine"]
SCORE_MODES: tuple[str, ...] = ("sigmoid", "cosine")

# Kept apart from the code so each failure site raises a precomputed string (privacy checklist 5).
BAD_SCORE_MODE = "unknown score mode; expected sigmoid or cosine"
BAD_COSINE_SHAPE = "cosine matrix must be 2-D (images x prompts)"
BAD_EMBEDDING_SHAPE = "embeddings must be 2-D with matching widths"
BAD_PROMPT_CATEGORIES = "prompt categories must match the score matrix columns"
BAD_SCORE_VALUE = "scoring parameters must be finite numbers"
EMPTY_CATEGORIES = "at least one prompt is needed to score"


class VisionError(Exception):
    """A vision backend refused or failed. The message is fixed text, never a library message."""


@runtime_checkable
class VisionBackend(Protocol):
    """Image and text embeddings, the scoring parameters, NSFW scores and the model ids."""

    @property
    def classifier_id(self) -> str: ...

    @property
    def nsfw_id(self) -> str: ...

    @property
    def logit_scale(self) -> float:
        """The multiplier applied to the cosine, already exponentiated."""
        ...

    @property
    def logit_bias(self) -> float: ...

    def embed_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        """Float32 `(n, dim)`, L2-normalised. Decoded images only."""
        ...

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        """Float32 `(m, dim)`, L2-normalised."""
        ...

    def nsfw_scores(self, images: Sequence[Image.Image]) -> np.ndarray:
        """Float32 `(n,)` in `[0, 1]`: the probability that an image is adult (MOD-002.D3)."""
        ...


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    """Row-wise unit length, float32. A zero row stays zero rather than becoming NaN."""
    array = np.asarray(vectors, dtype=np.float32)
    if array.ndim != 2:
        raise VisionError(BAD_EMBEDDING_SHAPE)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    return (array / np.maximum(norms, np.float32(1e-12))).astype(np.float32, copy=False)


def cosine_matrix(image_embeddings: np.ndarray, text_embeddings: np.ndarray) -> np.ndarray:
    """Cosine similarity `(n_images, n_prompts)` of two L2-normalised embedding sets."""
    images = np.asarray(image_embeddings, dtype=np.float32)
    texts = np.asarray(text_embeddings, dtype=np.float32)
    if images.ndim != 2 or texts.ndim != 2 or images.shape[1] != texts.shape[1]:
        raise VisionError(BAD_EMBEDDING_SHAPE)
    return (images @ texts.T).astype(np.float32, copy=False)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    """Overflow-free logistic function, in float64 inside and float32 out."""
    values = np.asarray(x, dtype=np.float64)
    out = np.empty_like(values)
    positive = values >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-values[positive]))
    exp = np.exp(values[~positive])
    out[~positive] = exp / (1.0 + exp)
    return out.astype(np.float32)


def score_matrix(
    cosines: np.ndarray,
    *,
    mode: str,
    logit_scale: float,
    logit_bias: float,
) -> np.ndarray:
    """Per image and prompt: `sigmoid(logit_scale * cos + logit_bias)`, or the raw cosine."""
    if mode not in SCORE_MODES:
        raise VisionError(BAD_SCORE_MODE)
    array = np.asarray(cosines, dtype=np.float32)
    if array.ndim != 2:
        raise VisionError(BAD_COSINE_SHAPE)
    if mode == "cosine":
        return array
    if not (np.isfinite(logit_scale) and np.isfinite(logit_bias)):
        raise VisionError(BAD_SCORE_VALUE)
    return _sigmoid(np.float64(logit_scale) * array.astype(np.float64) + np.float64(logit_bias))


def max_over_prompts(
    scores: np.ndarray, prompt_categories: Sequence[str]
) -> list[dict[str, float]]:
    """Per image, `{category: best score over that category's prompts}` (R-CLS-2).

    `prompt_categories[j]` names the category of column `j`. Categories come back in the order
    of their first prompt.
    """
    array = np.asarray(scores, dtype=np.float32)
    if array.ndim != 2 or array.shape[1] != len(prompt_categories):
        raise VisionError(BAD_PROMPT_CATEGORIES)
    if array.shape[1] == 0:
        raise VisionError(EMPTY_CATEGORIES)
    columns: dict[str, list[int]] = {}
    for index, category in enumerate(prompt_categories):
        columns.setdefault(category, []).append(index)
    best = {category: array[:, cols].max(axis=1) for category, cols in columns.items()}
    return [
        {category: float(values[row]) for category, values in best.items()}
        for row in range(array.shape[0])
    ]


def score_images(
    backend: VisionBackend,
    images: Sequence[Image.Image],
    prompts: Sequence[str],
    prompt_categories: Sequence[str],
    *,
    mode: str,
) -> list[dict[str, float]]:
    """Embed, score and take the max over prompts, for one batch of decoded images."""
    if len(prompts) != len(prompt_categories):
        raise VisionError(BAD_PROMPT_CATEGORIES)
    cosines = cosine_matrix(backend.embed_images(images), backend.embed_texts(prompts))
    scores = score_matrix(
        cosines, mode=mode, logit_scale=backend.logit_scale, logit_bias=backend.logit_bias
    )
    return max_over_prompts(scores, prompt_categories)
