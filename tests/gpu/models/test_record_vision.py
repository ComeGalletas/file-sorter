"""MOD-002.3.1: make (and re-check) the replay recordings for `classifier/models/` unit tests.

Tier `gpu`. Run with `--record-vision` to write `tests/recordings/models/`; run without it to
confirm the committed set still matches the real models. The recorder keeps an existing recording
when the new answer is within `atol=1e-3` and fails naming the key otherwise (fp16 differs in the
last bits). Inputs are the synthetic ones in `tests/unit/models/vision_inputs.py` (MOD-002.D6).

Prerequisites, named on failure by `conftest.py` (never skipped): an NVIDIA GPU and the
`models.classifier` and `models.nsfw` weights in the hf volume (`make models`).
"""

import numpy as np

from classifier.config import load_config
from classifier.models.siglip import SiglipBackend
from tests.unit.models.vision_inputs import PROMPTS, nsfw_images, scoring_images

DIM = 1152


def test_record_embeddings_params_and_nsfw_scores(siglip_backend: SiglipBackend, vision_backend):
    models = load_config().models
    backend = vision_backend("models", models.classifier, models.nsfw, upstream=siglip_backend)
    images = scoring_images()
    image_vectors = backend.embed_images(images)
    text_vectors = backend.embed_texts(PROMPTS)
    assert image_vectors.shape == (len(images), DIM)
    assert text_vectors.shape == (len(PROMPTS), DIM)
    for vectors in (image_vectors, text_vectors):
        assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)
    assert backend.logit_scale > 0 and np.isfinite(backend.logit_bias)
    scores = backend.nsfw_scores(nsfw_images())
    assert scores.shape == (len(nsfw_images()),)
    assert scores.min() >= 0.0 and scores.max() <= 1.0
