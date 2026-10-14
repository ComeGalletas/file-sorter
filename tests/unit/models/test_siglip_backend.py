"""MOD-002.1.2: `SiglipBackend` on a fake encoder, never a real model (MOD-002.D1, D4).

The real model is exercised by `tests/gpu/models/test_siglip.py`. Names are artificial coinages.
"""

from collections.abc import Sequence

import numpy as np
import pytest
from PIL import Image

from classifier.models import siglip
from classifier.models.siglip import BATCH_SIZE, SiglipBackend, load_encoder
from classifier.models.vision import VisionBackend, VisionError

DIM = 8
SECRET = "/source/Zhyndel-Qorvex/planted-secret.png"


class FakeEncoder:
    dim = DIM
    logit_scale = 117.5
    logit_bias = -16.5

    def __init__(self) -> None:
        self.image_batches: list[int] = []
        self.text_batches: list[int] = []

    def encode_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        self.image_batches.append(len(images))
        return np.array([[float(i + 1)] * DIM for i in range(len(images))]) * 3.0

    def encode_texts(self, texts: Sequence[str]) -> np.ndarray:
        self.text_batches.append(len(texts))
        return np.tile(np.arange(1, DIM + 1, dtype=np.float32), (len(texts), 1)) * 2.0


def backend_with(encoder: FakeEncoder, loads: list[str] | None = None) -> SiglipBackend:
    def loader(model_id: str) -> FakeEncoder:
        if loads is not None:
            loads.append(model_id)
        return encoder

    return SiglipBackend("qorvex/classifier", "qorvex/gate", loader=loader)


def images(n: int) -> list[Image.Image]:
    return [Image.new("RGB", (4, 4), (i, 0, 0)) for i in range(n)]


def assert_unchained(error: BaseException) -> None:
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.fixture(autouse=True)
def clear_encoder_cache() -> None:
    siglip._ENCODERS.clear()


def test_satisfies_the_protocol_and_exposes_the_ids() -> None:
    backend = backend_with(FakeEncoder())
    assert isinstance(backend, VisionBackend)
    assert backend.classifier_id == "qorvex/classifier"
    assert backend.nsfw_id == "qorvex/gate"


def test_nothing_loads_until_first_use_and_then_once() -> None:
    loads: list[str] = []
    backend = backend_with(FakeEncoder(), loads)
    assert loads == []
    assert backend.logit_scale == pytest.approx(117.5)
    backend.embed_texts(["a"])
    backend.embed_images(images(1))
    assert backend.logit_bias == pytest.approx(-16.5)
    assert loads == ["qorvex/classifier"]


def test_embeddings_are_float32_unit_rows_of_the_encoder_width() -> None:
    backend = backend_with(FakeEncoder())
    for out, rows in ((backend.embed_images(images(3)), 3), (backend.embed_texts(["a", "b"]), 2)):
        assert out.dtype == np.float32
        assert out.shape == (rows, DIM)
        assert np.allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-6)


def test_batches_are_capped_at_the_module_constant_and_order_is_kept() -> None:
    encoder = FakeEncoder()
    backend = backend_with(encoder)
    out = backend.embed_images(images(BATCH_SIZE + 3))
    assert encoder.image_batches == [BATCH_SIZE, 3]
    assert out.shape == (BATCH_SIZE + 3, DIM)
    backend.embed_texts(["t"] * (2 * BATCH_SIZE))
    assert encoder.text_batches == [BATCH_SIZE, BATCH_SIZE]


def test_empty_input_gives_an_empty_matrix_without_encoding() -> None:
    encoder = FakeEncoder()
    backend = backend_with(encoder)
    assert backend.embed_images([]).shape == (0, DIM)
    assert backend.embed_texts([]).shape == (0, DIM)
    assert encoder.image_batches == [] and encoder.text_batches == []


def test_non_images_and_non_strings_are_refused_with_fixed_text() -> None:
    backend = backend_with(FakeEncoder())
    with pytest.raises(VisionError, match="decoded PIL images only") as image_error:
        backend.embed_images([SECRET])  # type: ignore[list-item]
    with pytest.raises(VisionError, match="strings only") as text_error:
        backend.embed_texts([b"bytes"])  # type: ignore[list-item]
    for error in (image_error.value, text_error.value):
        assert SECRET not in str(error)
        assert_unchained(error)


class BrokenEncoder(FakeEncoder):
    def __init__(self, mode: str) -> None:
        super().__init__()
        self.mode = mode

    def encode_texts(self, texts: Sequence[str]) -> np.ndarray:
        if self.mode == "raise":
            raise OSError(f"cannot read {SECRET}")
        if self.mode == "shape":
            return np.ones((len(texts) + 1, DIM))
        return np.full((len(texts), DIM), np.inf)


@pytest.mark.parametrize(
    "mode, text",
    [
        ("raise", "failed while embedding"),
        ("shape", "unexpected embedding"),
        ("inf", "non-finite"),
    ],
)
def test_encoder_failures_become_unchained_fixed_text(mode: str, text: str) -> None:
    backend = backend_with(BrokenEncoder(mode))
    with pytest.raises(VisionError, match=text) as info:
        backend.embed_texts([SECRET])
    assert SECRET not in str(info.value) and SECRET not in repr(info.value)
    assert_unchained(info.value)


def test_repr_and_str_hold_no_input() -> None:
    backend = backend_with(FakeEncoder())
    backend.embed_texts([SECRET])
    backend.embed_images(images(1))
    assert SECRET not in repr(backend) and SECRET not in str(backend)


def test_nsfw_scores_is_a_fixed_text_stub_until_mod_002_2() -> None:
    with pytest.raises(VisionError, match="MOD-002.2") as info:
        backend_with(FakeEncoder()).nsfw_scores(images(1))
    assert_unchained(info.value)


def test_no_cuda_refuses_naming_the_gpu_and_never_loads() -> None:
    with pytest.raises(VisionError, match="needs the GPU") as info:
        load_encoder("qorvex/classifier", cuda_check=lambda: False)
    assert_unchained(info.value)
    assert "qorvex/classifier" not in str(info.value)
    assert "qorvex/classifier" not in siglip._ENCODERS


def test_a_failing_cuda_probe_counts_as_no_gpu_without_leaking_its_message() -> None:
    def probe() -> bool:
        raise RuntimeError(SECRET)

    with pytest.raises(VisionError, match="needs the GPU") as info:
        load_encoder("qorvex/classifier", cuda_check=probe)
    assert SECRET not in str(info.value)
    assert_unchained(info.value)


def test_load_failure_is_unchained_fixed_text(monkeypatch: pytest.MonkeyPatch) -> None:
    class Failing:
        def __init__(self, model_id: str) -> None:
            raise OSError(f"no such file {SECRET}")

    monkeypatch.setattr(siglip, "_TorchEncoder", Failing)
    with pytest.raises(VisionError, match="make models") as info:
        load_encoder("qorvex/classifier", cuda_check=lambda: True)
    assert SECRET not in str(info.value) and SECRET not in repr(info.value)
    assert_unchained(info.value)
    assert siglip._ENCODERS == {}


def test_one_load_per_process_and_model_id(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[str] = []

    class Counting(FakeEncoder):
        def __init__(self, model_id: str) -> None:
            super().__init__()
            built.append(model_id)

    monkeypatch.setattr(siglip, "_TorchEncoder", Counting)
    first = load_encoder("qorvex/classifier", cuda_check=lambda: True)
    again = load_encoder("qorvex/classifier", cuda_check=lambda: True)
    other = load_encoder("zhyndel/other", cuda_check=lambda: True)
    assert first is again and first is not other
    assert built == ["qorvex/classifier", "zhyndel/other"]
