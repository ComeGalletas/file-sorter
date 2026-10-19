"""MOD-002.3.2: the vision seam on replayed real-model answers (MOD-002.D6, TST-008.D3).

The recordings in `tests/recordings/models/` hold what the real SigLIP and NSFW gate returned for
the synthetic inputs in `vision_inputs.py`. No model loads here. Assertions are about shape,
range and the maths on real vectors, never about what a score should be for any content.
"""

import numpy as np
import pytest
from PIL import Image

from classifier.config import load_config
from classifier.models.vision import VisionBackend
from tests.recordings.replay import RecordingError
from tests.unit.models.vision_inputs import flat_image, nsfw_images, scoring_images

DIM = 1152


@pytest.fixture
def backend(vision_backend):
    models = load_config().models
    return vision_backend("models", models.classifier, models.nsfw)


def test_replay_satisfies_the_protocol_and_carries_the_config_ids(backend) -> None:
    models = load_config().models
    assert isinstance(backend, VisionBackend)
    assert (backend.classifier_id, backend.nsfw_id) == (models.classifier, models.nsfw)


def test_replayed_embeddings_are_float32_unit_rows_of_the_model_width(backend) -> None:
    images = scoring_images()
    out = backend.embed_images(images)
    assert out.dtype == np.float32
    assert out.shape == (len(images), DIM)
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-5)


def test_different_images_get_different_embeddings(backend) -> None:
    out = backend.embed_images(scoring_images())
    gram = out @ out.T
    off_diagonal = gram[~np.eye(len(out), dtype=bool)]
    assert off_diagonal.max() < 1.0 - 1e-4


def test_replayed_nsfw_scores_are_float32_in_range_one_per_image(backend) -> None:
    images = nsfw_images()
    out = backend.nsfw_scores(images)
    assert out.dtype == np.float32 and out.shape == (len(images),)
    assert np.isfinite(out).all() and out.min() >= 0.0 and out.max() <= 1.0
    assert backend.nsfw_scores([]).shape == (0,)


def test_an_unrecorded_image_raises_instead_of_returning_a_default(vision_backend) -> None:
    models = load_config().models
    backend = vision_backend("models", models.classifier, models.nsfw)
    stranger = Image.new("RGB", (5, 7), (3, 1, 4))
    with pytest.raises(RecordingError) as info:
        backend.embed_images([stranger])
    # `raise ... from None` (QA's replay): no cause, and the context is suppressed.
    assert info.value.__cause__ is None and info.value.__suppress_context__
    assert "(3, 1, 4)" not in str(info.value)
    backend.failures.clear()  # the miss is expected here; the fixture net is for swallowed ones


def test_a_flat_image_has_an_nsfw_recording_of_its_own(backend) -> None:
    (score,) = backend.nsfw_scores([flat_image("black")])
    assert 0.0 <= float(score) <= 1.0
