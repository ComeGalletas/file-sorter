"""The vision-model seam (MOD-002.1, CLS-002.D10, P-2).

`VisionBackend` is the one protocol the classify node talks to (MOD-002.D1). The real backend
(`siglip.py`, with the Falconsai NSFW cross-check from MOD-002.2) and TST-008.1's replay both
implement it. A backend takes decoded images, never a path or a file name (P-2). Classification
itself is the VLM's (CLS-004); the SigLIP image vector is kept for the reference store and the
Falconsai score is the cross-check (CLS-004.D5). The SigLIP scoring maths was removed in
CLS-006.1.

Errors carry fixed text only: never a prompt, a category name, a path or a library message.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import numpy as np
from PIL import Image

# Kept apart from the code so each failure site raises a precomputed string (privacy checklist 5).
BAD_EMBEDDING_SHAPE = "embeddings must be 2-D with matching widths"


class VisionError(Exception):
    """A vision backend refused or failed. The message is fixed text, never a library message."""


@runtime_checkable
class VisionBackend(Protocol):
    """Image embeddings, NSFW scores and the model ids."""

    @property
    def classifier_id(self) -> str: ...

    @property
    def nsfw_id(self) -> str: ...

    def embed_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        """Float32 `(n, dim)`, L2-normalised. Decoded images only."""
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
