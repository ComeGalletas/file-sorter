"""The Falconsai NSFW cross-check client (MOD-002.2, CLS-004.D5, R-MOD-2, P-2).

`load_nsfw(model_id)` returns the process-wide scorer for the adult cross-check. It maps decoded
images to one score each in `[0, 1]`: the softmax probability of the label named `nsfw` in the
model's `id2label` (MOD-002.D3). No threshold is applied here; `classify_rules.nsfw_cross_check`
owns it, and the VLM's level decides the branch (CLS-004.D3).

- **Offline.** Weights load from the shared `hf` volume with `local_files_only=True` (R-MOD-2).
- **GPU when there is one, CPU otherwise** (MOD-002.D4, DESIGN §8). This is the only model with a
  CPU fallback. fp16 on CUDA, fp32 on CPU.
- **Exactly one `nsfw` label.** A model with none, or with several, is refused with fixed text.
- **No paths.** The scorer takes decoded `PIL.Image` objects only (P-2).
- **Errors** carry fixed text. A torch, transformers or Pillow message is never forwarded.

The batch size is a module constant, not a config key (CLS-002.D11).
"""

import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

import numpy as np
from PIL import Image

from classifier.models.vision import VisionError

NSFW_BATCH_SIZE = 16
NSFW_LABEL = "nsfw"

LOAD_FAILED = (
    "could not load the NSFW weights from the local model volume; run `make models` to fetch them"
)
BAD_LABELS = "the NSFW model must name exactly one class `nsfw` in its labels"
SCORE_FAILED = "the NSFW model failed while scoring a batch"
BAD_IMAGE = "nsfw_scores takes decoded PIL images only"
BAD_OUTPUT = "the NSFW model returned an unexpected score shape"
NON_FINITE = "the NSFW model returned a non-finite score"


class NsfwScorer(Protocol):
    """Raw probabilities of the `nsfw` class, one per image. Faked in unit tests."""

    def score_batch(self, images: Sequence[Image.Image]) -> np.ndarray: ...


NsfwLoader = Callable[[str], NsfwScorer]


def nsfw_class_index(id2label: Mapping[Any, Any]) -> int | None:
    """The index of the single `nsfw` label, or `None` for none or several (MOD-002.D3)."""
    hits = [
        int(index) for index, label in id2label.items() if str(label).strip().lower() == NSFW_LABEL
    ]
    return hits[0] if len(hits) == 1 else None


def _cuda_available() -> bool:
    import torch

    return bool(torch.cuda.is_available())


class _TorchNsfw:
    """The real model, loaded from the local volume only."""

    def __init__(self, model_id: str, *, use_cuda: bool) -> None:
        import torch
        from transformers import AutoImageProcessor, AutoModelForImageClassification

        self._torch = torch
        self._device = "cuda" if use_cuda else "cpu"
        self._dtype = torch.float16 if use_cuda else torch.float32
        self._processor = AutoImageProcessor.from_pretrained(model_id, local_files_only=True)
        model = AutoModelForImageClassification.from_pretrained(model_id, local_files_only=True)
        index = nsfw_class_index(model.config.id2label)
        if index is None:
            raise VisionError(BAD_LABELS)
        self._index = index
        self._model = model.to(device=self._device, dtype=self._dtype).eval()

    def score_batch(self, images: Sequence[Image.Image]) -> np.ndarray:
        torch = self._torch
        batch = [image.convert("RGB") for image in images]
        pixels = self._processor(images=batch, return_tensors="pt")["pixel_values"]
        pixels = pixels.to(device=self._device, dtype=self._dtype)
        with torch.inference_mode():
            logits = self._model(pixel_values=pixels).logits.float()
            probs = torch.softmax(logits, dim=-1)[:, self._index]
        return probs.cpu().numpy()


# One load per process and model id (MOD-002.D1).
_SCORERS: dict[str, NsfwScorer] = {}
_LOCK = threading.Lock()


def load_nsfw(model_id: str, *, cuda_check: Callable[[], bool] = _cuda_available) -> NsfwScorer:
    """The process-wide scorer for `model_id`, loaded on first use. A failed load isn't cached."""
    with _LOCK:
        cached = _SCORERS.get(model_id)
        if cached is not None:
            return cached
        try:
            use_cuda = bool(cuda_check())
        except Exception:
            use_cuda = False
        scorer: NsfwScorer | None = None
        failure: str | None = None
        try:
            scorer = _TorchNsfw(model_id, use_cuda=use_cuda)
        except VisionError as error:
            failure = str(error) if str(error) == BAD_LABELS else LOAD_FAILED
        except Exception:
            failure = LOAD_FAILED
        if scorer is None:
            raise VisionError(failure or LOAD_FAILED)
        _SCORERS[model_id] = scorer
        return scorer


def score_nsfw(scorer: NsfwScorer, images: Sequence[Image.Image]) -> np.ndarray:
    """Float32 `(n,)` in `[0, 1]`, batched at `NSFW_BATCH_SIZE`, order kept."""
    if not all(isinstance(image, Image.Image) for image in images):
        raise VisionError(BAD_IMAGE)
    parts: list[np.ndarray] = [np.zeros((0,), dtype=np.float32)]
    for start in range(0, len(images), NSFW_BATCH_SIZE):
        batch = list(images[start : start + NSFW_BATCH_SIZE])
        raw: np.ndarray | None = None
        failure: str | None = None
        try:
            raw = np.asarray(scorer.score_batch(batch), dtype=np.float32)
        except VisionError:
            raise
        except Exception:
            failure = SCORE_FAILED
        if failure is not None or raw is None:
            raise VisionError(failure or SCORE_FAILED)
        if raw.shape != (len(batch),):
            raise VisionError(BAD_OUTPUT)
        if not np.isfinite(raw).all():
            raise VisionError(NON_FINITE)
        parts.append(np.clip(raw, 0.0, 1.0))
    return np.concatenate(parts)
