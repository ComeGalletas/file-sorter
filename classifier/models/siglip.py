"""The SigLIP client (MOD-002.1, R-CLS-2, R-MOD-2, C-5, P-2).

`SiglipBackend` implements the `VisionBackend` seam from `vision.py`. It embeds decoded images
and plain texts into 1152-d, L2-normalised float32 vectors, and exposes the model's
`logit_scale` and `logit_bias`; the scoring maths lives in `vision.py` (MOD-002.D2).

- **Offline.** Weights load from the shared `hf` volume with `local_files_only=True`, on top of
  the compose `HF_HUB_OFFLINE=1`. A missing weight fails with fixed text and never downloads
  (R-MOD-2).
- **GPU only** (MOD-002.D4). SigLIP runs in fp16 on CUDA. With no CUDA it refuses with fixed
  text naming the GPU, rather than crawling on CPU.
- **Lazy and once.** Nothing loads until the first call, and one process loads a model id once.
- **No paths.** The API takes decoded `PIL.Image` objects and strings, so neither a source path
  nor a raw file name can reach the model (P-2).
- **Errors** carry fixed text. A torch, transformers or Pillow message is never forwarded: it
  can embed a path or an input.

The batch size is a module constant, not a config key (CLS-002.D11).
"""

import threading
from collections.abc import Callable, Sequence
from typing import Any, Protocol

import numpy as np
from PIL import Image

from classifier.models.nsfw import NsfwLoader, load_nsfw, score_nsfw
from classifier.models.vision import VisionError, l2_normalize

# CLS-002.D11: a module constant, not a config key. Sized for the 16 GB card with fp16.
BATCH_SIZE = 16
# SigLIP was trained with every text padded to 64 tokens; longer prompts are truncated.
TEXT_MAX_LENGTH = 64

NO_GPU = "SigLIP needs the GPU: no CUDA device is available to this process"
LOAD_FAILED = (
    "could not load the SigLIP weights from the local model volume; run `make models` to fetch them"
)
EMBED_FAILED = "the SigLIP model failed while embedding a batch"
BAD_IMAGE = "embed_images takes decoded PIL images only"
BAD_TEXT = "embed_texts takes strings only"
BAD_OUTPUT = "the SigLIP model returned an unexpected embedding shape"
NON_FINITE = "the SigLIP model returned a non-finite embedding"


class Encoder(Protocol):
    """Raw (un-normalised) embeddings plus the scoring parameters. Faked in unit tests."""

    @property
    def dim(self) -> int: ...

    @property
    def logit_scale(self) -> float: ...

    @property
    def logit_bias(self) -> float: ...

    def encode_images(self, images: Sequence[Image.Image]) -> np.ndarray: ...

    def encode_texts(self, texts: Sequence[str]) -> np.ndarray: ...


Loader = Callable[[str], Encoder]


def _cuda_available() -> bool:
    import torch

    return bool(torch.cuda.is_available())


class _TorchEncoder:
    """The real model: fp16 on CUDA, loaded from the local volume only."""

    def __init__(self, model_id: str) -> None:
        import torch
        from transformers import AutoModel, AutoProcessor

        self._torch = torch
        self._device = "cuda"
        self._processor = AutoProcessor.from_pretrained(model_id, local_files_only=True)
        model = AutoModel.from_pretrained(model_id, local_files_only=True)
        self._model = model.to(device=self._device, dtype=torch.float16).eval()
        self.dim = int(self._model.config.vision_config.hidden_size)
        # The checkpoint stores log(scale): the multiplier is its exponential.
        self.logit_scale = float(self._model.logit_scale.float().exp().item())
        self.logit_bias = float(self._model.logit_bias.float().item())

    def _to_numpy(self, features: Any) -> np.ndarray:
        # Newer transformers return an output object rather than the tensor.
        tensor = features if hasattr(features, "float") else features.pooler_output
        return tensor.float().cpu().numpy()

    def encode_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        torch = self._torch
        batch = [image.convert("RGB") for image in images]
        pixels = self._processor(images=batch, return_tensors="pt")["pixel_values"]
        pixels = pixels.to(device=self._device, dtype=torch.float16)
        with torch.inference_mode():
            return self._to_numpy(self._model.get_image_features(pixel_values=pixels))

    def encode_texts(self, texts: Sequence[str]) -> np.ndarray:
        torch = self._torch
        tokens = self._processor.tokenizer(
            list(texts),
            padding="max_length",
            max_length=TEXT_MAX_LENGTH,
            truncation=True,
            return_tensors="pt",
        )
        ids = tokens["input_ids"].to(self._device)
        with torch.inference_mode():
            return self._to_numpy(self._model.get_text_features(input_ids=ids))


# One load per process and model id (MOD-002.D1).
_ENCODERS: dict[str, Encoder] = {}
_LOCK = threading.Lock()


def load_encoder(model_id: str, *, cuda_check: Callable[[], bool] = _cuda_available) -> Encoder:
    """The process-wide encoder for `model_id`, loaded on first use."""
    with _LOCK:
        cached = _ENCODERS.get(model_id)
        if cached is not None:
            return cached
        try:
            has_gpu = cuda_check()
        except Exception:
            has_gpu = False
        if not has_gpu:
            failure: str | None = NO_GPU
            encoder: Encoder | None = None
        else:
            failure = None
            try:
                encoder = _TorchEncoder(model_id)
            except Exception:
                encoder, failure = None, LOAD_FAILED
        if failure is not None or encoder is None:
            raise VisionError(failure or LOAD_FAILED)
        _ENCODERS[model_id] = encoder
        return encoder


class SiglipBackend:
    """`VisionBackend` over SigLIP, with the NSFW gate from `nsfw.py` loaded on first use."""

    def __init__(
        self,
        classifier_id: str,
        nsfw_id: str,
        *,
        loader: Loader = load_encoder,
        nsfw_loader: NsfwLoader = load_nsfw,
    ) -> None:
        self._classifier_id = classifier_id
        self._nsfw_id = nsfw_id
        self._loader = loader
        self._nsfw_loader = nsfw_loader
        self._encoder: Encoder | None = None

    @property
    def classifier_id(self) -> str:
        return self._classifier_id

    @property
    def nsfw_id(self) -> str:
        return self._nsfw_id

    def _get(self) -> Encoder:
        if self._encoder is None:
            self._encoder = self._loader(self._classifier_id)
        return self._encoder

    @property
    def logit_scale(self) -> float:
        return float(self._get().logit_scale)

    @property
    def logit_bias(self) -> float:
        return float(self._get().logit_bias)

    def _embed(
        self,
        items: Sequence[Any],
        encode: Callable[[Sequence[Any]], np.ndarray],
        dim: int,
    ) -> np.ndarray:
        parts: list[np.ndarray] = [np.zeros((0, dim), dtype=np.float32)]
        for start in range(0, len(items), BATCH_SIZE):
            batch = items[start : start + BATCH_SIZE]
            failure: str | None = None
            raw: np.ndarray | None = None
            try:
                raw = np.asarray(encode(batch), dtype=np.float32)
            except VisionError:
                raise
            except Exception:
                failure = EMBED_FAILED
            if failure is not None or raw is None:
                raise VisionError(failure or EMBED_FAILED)
            if raw.shape != (len(batch), dim):
                raise VisionError(BAD_OUTPUT)
            if not np.isfinite(raw).all():
                raise VisionError(NON_FINITE)
            parts.append(raw)
        return l2_normalize(np.concatenate(parts, axis=0))

    def embed_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        if not all(isinstance(image, Image.Image) for image in images):
            raise VisionError(BAD_IMAGE)
        encoder = self._get()
        return self._embed(list(images), encoder.encode_images, encoder.dim)

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        if not all(isinstance(text, str) for text in texts):
            raise VisionError(BAD_TEXT)
        encoder = self._get()
        return self._embed(list(texts), encoder.encode_texts, encoder.dim)

    def nsfw_scores(self, images: Sequence[Image.Image]) -> np.ndarray:
        # MOD-002.2: the gate loads on the first call, so embedding never pays for it.
        if not all(isinstance(image, Image.Image) for image in images):
            raise VisionError(BAD_IMAGE)
        if not images:
            return np.zeros((0,), dtype=np.float32)
        return score_nsfw(self._nsfw_loader(self._nsfw_id), images)
