"""MOD-002.1.1: the `VisionBackend` seam and `l2_normalize`, on fake vectors only.

No model, no image decode: arrays in, arrays out (MOD-002.D2).
"""

from collections.abc import Sequence

import numpy as np
import pytest
from PIL import Image

from classifier.models.vision import VisionBackend, VisionError, l2_normalize


def test_l2_normalize_gives_unit_rows_and_keeps_zero_rows_finite() -> None:
    out = l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert out.dtype == np.float32
    assert np.allclose(out[0], [0.6, 0.8])
    assert np.array_equal(out[1], [0.0, 0.0])
    with pytest.raises(VisionError):
        l2_normalize(np.zeros(4))


class FakeBackend:
    """A VisionBackend with fixed embeddings: what TST-008.1's replay also implements."""

    classifier_id = "qorvex/fake-classifier"
    nsfw_id = "qorvex/fake-gate"

    def embed_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        return l2_normalize(np.array([[1.0, 0.0], [0.0, 1.0]])[: len(images)])

    def nsfw_scores(self, images: Sequence[Image.Image]) -> np.ndarray:
        return np.zeros(len(images), dtype=np.float32)


def test_fake_satisfies_the_protocol() -> None:
    assert isinstance(FakeBackend(), VisionBackend)


def test_a_backend_with_the_removed_text_members_alone_is_not_a_backend() -> None:
    class TextOnly:
        classifier_id = "qorvex/fake-classifier"
        nsfw_id = "qorvex/fake-gate"

    assert not isinstance(TextOnly(), VisionBackend)


def test_error_messages_carry_no_input() -> None:
    with pytest.raises(VisionError) as info:
        l2_normalize(np.zeros(3))
    assert info.value.__cause__ is None and info.value.__context__ is None
