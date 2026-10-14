"""TST-008.1: replay and record the `VisionBackend` seam (MOD-002.D1, TST-008.D3, D7).

`ReplayVisionBackend` implements the protocol in `classifier/models/vision.py` from recordings
and never loads a model. A miss raises `RecordingError`, which is a `BaseException`, so a
fail-closed `except Exception` in the code under test cannot swallow it; every failure is also
kept in `failures` so the fixture can fail the test at teardown.

`RecordingVisionBackend` (record mode, `gpu` tier only) wraps the real backend that the caller
built, forwards each call, and writes one recording per image, text, NSFW score or param.
The caller builds the real backend (the ML desk's session-scoped gpu fixture): QA never loads
a model.

Privacy (DOC-007.D1): recordings come from synthetic inputs only. The text inputs and arrays
keyed by them are `repr=False`, and every error names at most the package, the 64-hex key, the
kind and the test id, raised unchained.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from tests.recordings.replay import RECORDINGS, RecordingError, _is_file, package_dir
from tests.recordings.vision import (
    check_request,
    encode_array,
    expected_shape_ok,
    image_digest,
    load_vision_recording,
    vision_key,
)

# TST-008 lead ruling 2: SigLIP runs fp16 on CUDA, so two runs agree to a tolerance, not bits.
TOLERANCE = 1e-3
RECORD_HINT = "record it in the gpu tier: pytest -m gpu --record-vision <test path>"
NO_UPSTREAM = "a gpu test needs the real VisionBackend passed to the vision_backend fixture"


class _Tracked:
    """Shared failure bookkeeping for the replay and the recorder."""

    def __init__(self, package: str, test_id: str, root: Path) -> None:
        self.directory = package_dir(package, root)
        self.test_id = test_id
        self.failures: list[str] = []

    def _fail(self, problem: str) -> RecordingError:
        message = f"{problem} (test {self.test_id})"
        self.failures.append(message)
        return RecordingError(message)

    def _name(self, model: str, kind: str, value: str) -> tuple[str, Path, str]:
        """The key, the file and the label of a request, or a tracked `RecordingError`."""
        try:
            check_request({"model": model, "kind": kind, "input": value})
            key = vision_key(model, kind, value)
        except RecordingError as exc:
            raise self._fail(str(exc)) from None
        return key, self.directory / f"{key}.json", f"{self.directory.name}/{key}.json"

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.directory.name} {self.test_id}>"


class ReplayVisionBackend(_Tracked):
    """Serves recorded embeddings, scores and params. A miss raises `RecordingError`."""

    def __init__(
        self,
        package: str,
        test_id: str,
        classifier_id: str,
        nsfw_id: str,
        root: Path = RECORDINGS,
    ) -> None:
        super().__init__(package, test_id, root)
        self._classifier_id = classifier_id
        self._nsfw_id = nsfw_id

    @property
    def classifier_id(self) -> str:
        return self._classifier_id

    @property
    def nsfw_id(self) -> str:
        return self._nsfw_id

    def _serve(self, model: str, kind: str, value: str) -> np.ndarray:
        key, path, name = self._name(model, kind, value)
        try:
            if not _is_file(path, f"recording {name}"):
                raise RecordingError(f"no recording {name} (kind {kind}); {RECORD_HINT}")
            return load_vision_recording(path, f"recording {name}").array
        except RecordingError as exc:
            raise self._fail(str(exc)) from None

    @property
    def logit_scale(self) -> float:
        return float(self._serve(self._classifier_id, "param", "logit_scale"))

    @property
    def logit_bias(self) -> float:
        return float(self._serve(self._classifier_id, "param", "logit_bias"))

    def _stack(self, rows: list[np.ndarray]) -> np.ndarray:
        if not rows:
            return np.zeros((0, 0), dtype=np.float32)
        if len({row.shape for row in rows}) != 1:
            raise self._fail("the recorded rows of one call differ in width")
        return np.stack(rows).astype(np.float32, copy=False)

    def embed_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        return self._stack(
            [self._serve(self._classifier_id, "image", self._digest(i)) for i in images]
        )

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        return self._stack([self._serve(self._classifier_id, "text", text) for text in texts])

    def nsfw_scores(self, images: Sequence[Image.Image]) -> np.ndarray:
        scores = [self._serve(self._nsfw_id, "nsfw", self._digest(i)) for i in images]
        return np.array([float(s) for s in scores], dtype=np.float32)

    def _digest(self, image: Image.Image) -> str:
        try:
            return image_digest(image)
        except RecordingError as exc:
            raise self._fail(str(exc)) from None


class RecordingVisionBackend(_Tracked):
    """Record mode: forwards to `upstream` and writes each answer as a recording.

    An existing recording within `TOLERANCE` of the new answer is left as it is (fp16 runs
    differ in the last bits). A different answer fails naming the key: overwriting it silently
    would hide a model change. Delete the file first to re-record on purpose.
    """

    def __init__(self, package: str, upstream: Any, test_id: str, root: Path = RECORDINGS) -> None:
        super().__init__(package, test_id, root)
        self._upstream = upstream

    @property
    def classifier_id(self) -> str:
        return str(self._upstream.classifier_id)

    @property
    def nsfw_id(self) -> str:
        return str(self._upstream.nsfw_id)

    def _record(self, model: str, kind: str, value: str, answer: Any) -> None:
        key, path, name = self._name(model, kind, value)
        try:
            response = encode_array(answer)
        except RecordingError as exc:
            raise self._fail(f"the answer for {name} cannot be recorded: {exc}") from None
        shape = tuple(response["shape"])
        if not expected_shape_ok(kind, shape):
            raise self._fail(f"the answer for {name} has a shape that does not fit {kind}")
        try:
            existing = (
                load_vision_recording(path, f"recording {name}").array
                if _is_file(path, f"recording {name}")
                else None
            )
        except RecordingError as exc:
            raise self._fail(f"{exc}; delete it to re-record") from None
        if existing is not None:
            same = existing.shape == shape and np.allclose(
                existing, np.asarray(answer, dtype=np.float32), rtol=0.0, atol=TOLERANCE
            )
            if not same:
                raise self._fail(
                    f"recording {name} exists with a different answer; delete it to re-record"
                )
            return
        request = {"model": model, "kind": kind, "input": value}
        text = json.dumps({"request": request, "response": response}, sort_keys=True, indent=2)
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path.write_bytes((text + "\n").encode("utf-8"))
        except OSError:
            # The OSError's text carries the checkout path, so it is not chained (PR #71).
            raise self._fail(f"recording {name} cannot be written") from None

    @property
    def logit_scale(self) -> float:
        value = float(self._upstream.logit_scale)
        self._record(self.classifier_id, "param", "logit_scale", np.float32(value))
        return value

    @property
    def logit_bias(self) -> float:
        value = float(self._upstream.logit_bias)
        self._record(self.classifier_id, "param", "logit_bias", np.float32(value))
        return value

    def embed_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        result = np.asarray(self._upstream.embed_images(images), dtype=np.float32)
        self._check_rows(result, len(images))
        for image, row in zip(images, result, strict=True):
            self._record(self.classifier_id, "image", self._digest(image), row)
        return result

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        result = np.asarray(self._upstream.embed_texts(texts), dtype=np.float32)
        self._check_rows(result, len(texts))
        for text, row in zip(texts, result, strict=True):
            self._record(self.classifier_id, "text", text, row)
        return result

    def nsfw_scores(self, images: Sequence[Image.Image]) -> np.ndarray:
        result = np.asarray(self._upstream.nsfw_scores(images), dtype=np.float32)
        if result.shape != (len(images),):
            raise self._fail("the upstream NSFW scores do not match the number of images")
        for image, score in zip(images, result, strict=True):
            self._record(self.nsfw_id, "nsfw", self._digest(image), score)
        return result

    def _check_rows(self, result: np.ndarray, count: int) -> None:
        if result.ndim != 2 or result.shape[0] != count:
            raise self._fail("the upstream embeddings do not match the number of inputs")

    def _digest(self, image: Image.Image) -> str:
        try:
            return image_digest(image)
        except RecordingError as exc:
            raise self._fail(str(exc)) from None
