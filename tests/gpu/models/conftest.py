"""Session-scoped real SigLIP for the `gpu` model tests (MOD-002.D4).

One load per session. A missing prerequisite fails the test naming it, never skips (CLAUDE.md §3).
"""

import pytest

from classifier.config import load_config
from classifier.models.siglip import SiglipBackend
from classifier.models.vision import VisionError

SIGLIP_PREREQS = (
    "an NVIDIA GPU visible to the test container, and models.classifier fetched into the hf "
    "volume (make models)"
)


@pytest.fixture(scope="session")
def siglip_backend() -> SiglipBackend:
    models = load_config().models
    backend = SiglipBackend(models.classifier, models.nsfw)
    try:
        backend.embed_texts(["warm-up"])
    except VisionError as error:
        pytest.fail(f"SigLIP did not load ({error}); prerequisites: {SIGLIP_PREREQS}")
    return backend
