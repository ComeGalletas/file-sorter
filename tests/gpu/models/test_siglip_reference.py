"""CLS-003.1.7: `SiglipBackend` against transformers' own reference behaviour, tier `gpu`.

Two checks on synthetic images generated in code (flat colour squares, nothing real):

1. Known answer: a blue and a red square must each rank their own prompt first, with a clear
   margin, in both score modes.
2. Reference agreement: our `sigmoid` scores equal `sigmoid(logits_per_image)` from the model's
   own forward, loaded offline from the same local weights, within the fp16 tolerances below,
   and the per-image rankings are identical.

Prerequisites, named on failure by `conftest.py` (never skipped): an NVIDIA GPU and
`models.classifier` fetched into the hf volume (`make models`).
"""

import numpy as np
import pytest
import torch
from PIL import Image

from classifier.config import load_config
from classifier.models.siglip import TEXT_MAX_LENGTH, SiglipBackend
from classifier.models.vision import cosine_matrix, score_matrix

COLOURS = {"blue": (20, 40, 220), "red": (220, 30, 30), "green": (30, 190, 60)}
PROMPTS = [
    "a photo of a blue square",
    "a photo of a red square",
    "a photo of a green square",
    "a photo of a cat",
    "a screenshot of a user interface",
]
# fp16 inference against the fp32 reference. Measured on the box: logits within 0.03 and
# probabilities within 0.003; the tolerances leave a small margin above that.
LOGIT_ATOL = 0.1
SCORE_ATOL = 0.01
# "A clear margin" for the known answer: cosine gap, and a probability ratio in sigmoid mode.
COSINE_MARGIN = 0.02
SIGMOID_RATIO = 3.0


def square(name: str) -> Image.Image:
    return Image.new("RGB", (224, 224), COLOURS[name])


@pytest.fixture(scope="module")
def images() -> list[Image.Image]:
    return [square(name) for name in COLOURS]


def our_matrix(backend: SiglipBackend, images, mode: str) -> np.ndarray:
    cosines = cosine_matrix(backend.embed_images(images), backend.embed_texts(PROMPTS))
    return score_matrix(
        cosines, mode=mode, logit_scale=backend.logit_scale, logit_bias=backend.logit_bias
    )


@pytest.mark.parametrize("mode", ["sigmoid", "cosine"])
def test_each_square_ranks_its_own_prompt_first_with_a_clear_margin(siglip_backend, images, mode):
    scores = our_matrix(siglip_backend, images, mode)
    for row, own in ((0, 0), (1, 1)):  # blue square -> blue prompt, red square -> red prompt
        order = np.argsort(-scores[row])
        assert order[0] == own, f"{mode}: image {row} ranked prompt {order[0]} first"
        runner_up = scores[row][order[1]]
        if mode == "cosine":
            assert scores[row][own] - runner_up >= COSINE_MARGIN
        else:
            assert scores[row][own] >= SIGMOID_RATIO * max(runner_up, 1e-9)


@pytest.fixture(scope="module")
def reference_logits(images) -> np.ndarray:
    """`logits_per_image` from transformers' own forward, offline, in fp32 (the reference)."""
    from transformers import AutoModel, AutoProcessor

    model_id = load_config().models.classifier
    processor = AutoProcessor.from_pretrained(model_id, local_files_only=True)
    model = AutoModel.from_pretrained(model_id, local_files_only=True).to("cuda").float().eval()
    inputs = processor(
        text=PROMPTS,
        images=images,
        padding="max_length",
        max_length=TEXT_MAX_LENGTH,
        return_tensors="pt",
    ).to("cuda")
    with torch.inference_mode():
        logits = model(**inputs).logits_per_image
    return logits.float().cpu().numpy()


def test_our_logits_and_sigmoid_scores_match_logits_per_image(
    siglip_backend, images, reference_logits
):
    cosines = cosine_matrix(
        siglip_backend.embed_images(images), siglip_backend.embed_texts(PROMPTS)
    )
    ours = siglip_backend.logit_scale * cosines + siglip_backend.logit_bias
    assert ours.shape == reference_logits.shape
    assert np.abs(ours - reference_logits).max() <= LOGIT_ATOL

    reference = 1.0 / (1.0 + np.exp(-reference_logits.astype(np.float64)))
    assert np.abs(our_matrix(siglip_backend, images, "sigmoid") - reference).max() <= SCORE_ATOL


def test_the_per_image_rankings_are_identical_to_the_reference(
    siglip_backend, images, reference_logits
):
    ours = our_matrix(siglip_backend, images, "sigmoid")
    for row in range(len(images)):
        # Ranks of near-equal scores may swap under fp16: compare only separated pairs.
        ref_order = np.argsort(-reference_logits[row])
        assert (np.argsort(-ours[row]) == ref_order).all() or _only_ties_differ(
            reference_logits[row], np.argsort(-ours[row]), ref_order
        )


def _only_ties_differ(ref_row: np.ndarray, ours: np.ndarray, ref: np.ndarray) -> bool:
    """True when every position where the orders differ holds logits within LOGIT_ATOL."""
    return all(abs(ref_row[a] - ref_row[b]) <= LOGIT_ATOL for a, b in zip(ours, ref, strict=True))
