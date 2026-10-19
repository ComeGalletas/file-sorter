"""Session-scoped real SigLIP for the classify recorder (CLS-002.2.4), tier `gpu`.

One load per session. A missing prerequisite fails the test naming it, never skips (CLAUDE.md §3).
"""

import pytest
from PIL import Image

from classifier.config import load_config
from classifier.models.siglip import SiglipBackend
from classifier.models.vision import VisionError

PREREQS = (
    "an NVIDIA GPU visible to the test container, and models.classifier and models.nsfw "
    "fetched into the hf volume (make models)"
)


@pytest.fixture(scope="session")
def siglip_backend() -> SiglipBackend:
    models = load_config().models
    backend = SiglipBackend(models.classifier, models.nsfw)
    try:
        backend.embed_images([Image.new("RGB", (8, 8))])
    except VisionError as error:
        pytest.fail(f"SigLIP did not load ({error}); prerequisites: {PREREQS}")
    return backend
