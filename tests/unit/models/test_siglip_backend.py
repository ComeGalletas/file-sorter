"""MOD-002.1.2: `SiglipBackend` on a fake encoder, never a real model (MOD-002.D1, D4).

The real model is exercised by `tests/gpu/models/test_siglip.py`. Names are artificial coinages.
"""

import sys
import types
from collections.abc import Sequence
from typing import Any

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

    def __init__(self) -> None:
        self.image_batches: list[int] = []

    def encode_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        self.image_batches.append(len(images))
        return np.array([[float(i + 1)] * DIM for i in range(len(images))]) * 3.0


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
    backend.embed_images(images(1))
    backend.embed_images(images(2))
    assert loads == ["qorvex/classifier"]


def test_embeddings_are_float32_unit_rows_of_the_encoder_width() -> None:
    backend = backend_with(FakeEncoder())
    out = backend.embed_images(images(3))
    assert out.dtype == np.float32
    assert out.shape == (3, DIM)
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0, atol=1e-6)


def test_batches_are_capped_at_the_module_constant_and_order_is_kept() -> None:
    encoder = FakeEncoder()
    backend = backend_with(encoder)
    out = backend.embed_images(images(BATCH_SIZE + 3))
    assert encoder.image_batches == [BATCH_SIZE, 3]
    assert out.shape == (BATCH_SIZE + 3, DIM)


def test_empty_input_gives_an_empty_matrix_without_encoding() -> None:
    encoder = FakeEncoder()
    backend = backend_with(encoder)
    assert backend.embed_images([]).shape == (0, DIM)
    assert encoder.image_batches == []


def test_non_images_are_refused_with_fixed_text() -> None:
    backend = backend_with(FakeEncoder())
    with pytest.raises(VisionError, match="decoded PIL images only") as image_error:
        backend.embed_images([SECRET])  # type: ignore[list-item]
    assert SECRET not in str(image_error.value)
    assert_unchained(image_error.value)


class BrokenEncoder(FakeEncoder):
    def __init__(self, mode: str) -> None:
        super().__init__()
        self.mode = mode

    def encode_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        if self.mode == "raise":
            raise OSError(f"cannot read {SECRET}")
        if self.mode == "shape":
            return np.ones((len(images) + 1, DIM))
        return np.full((len(images), DIM), np.inf)


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
        backend.embed_images(images(1))
    assert SECRET not in str(info.value) and SECRET not in repr(info.value)
    assert_unchained(info.value)


def planted_image() -> Image.Image:
    """A decoded image that carries SECRET where a backend could echo it."""
    image = Image.new("RGB", (4, 4))
    image.info["comment"] = SECRET
    image.info["filename"] = SECRET
    return image


def test_repr_and_str_hold_no_input() -> None:
    backend = backend_with(FakeEncoder())
    backend.embed_images([planted_image()])
    assert SECRET not in repr(backend) and SECRET not in str(backend)
    broken = backend_with(BrokenEncoder("raise"))
    with pytest.raises(VisionError) as info:
        broken.embed_images([planted_image()])
    assert SECRET not in repr(broken) and SECRET not in str(broken)
    assert SECRET not in str(info.value) and SECRET not in repr(info.value)
    assert_unchained(info.value)


class FakeNsfw:
    def __init__(self) -> None:
        self.batches: list[int] = []

    def score_batch(self, batch: Sequence[Image.Image]) -> np.ndarray:
        self.batches.append(len(batch))
        return np.full((len(batch),), 0.5)


def backend_with_nsfw(scorer: FakeNsfw, loads: list[str]) -> SiglipBackend:
    def nsfw_loader(model_id: str) -> FakeNsfw:
        loads.append(model_id)
        return scorer

    def no_siglip(model_id: str) -> FakeEncoder:
        raise AssertionError("the SigLIP encoder must not load for NSFW scores")

    return SiglipBackend(
        "qorvex/classifier", "qorvex/gate", loader=no_siglip, nsfw_loader=nsfw_loader
    )


def test_nsfw_scores_load_the_gate_lazily_on_first_call_and_only_then() -> None:
    loads: list[str] = []
    backend = backend_with_nsfw(FakeNsfw(), loads)
    assert loads == []
    out = backend.nsfw_scores(images(3))
    assert loads == ["qorvex/gate"]
    assert out.dtype == np.float32 and out.shape == (3,)
    assert out.min() >= 0.0 and out.max() <= 1.0


def test_embedding_never_loads_the_nsfw_gate() -> None:
    loads: list[str] = []

    def nsfw_loader(model_id: str) -> FakeNsfw:
        loads.append(model_id)
        return FakeNsfw()

    backend = SiglipBackend(
        "qorvex/classifier",
        "qorvex/gate",
        loader=lambda model_id: FakeEncoder(),
        nsfw_loader=nsfw_loader,
    )
    backend.embed_images(images(2))
    assert loads == []


def test_nsfw_scores_edge_cases_and_refusals_are_fixed_text() -> None:
    loads: list[str] = []
    backend = backend_with_nsfw(FakeNsfw(), loads)
    assert backend.nsfw_scores([]).shape == (0,)
    assert loads == []
    with pytest.raises(VisionError, match="decoded PIL images only") as info:
        backend.nsfw_scores([SECRET])  # type: ignore[list-item]
    assert SECRET not in str(info.value) and SECRET not in repr(info.value)
    assert_unchained(info.value)
    assert loads == []


def test_siglip_from_pretrained_calls_are_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """MOD-002.2 carried finding (a): `local_files_only=True` on both SigLIP loads."""
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeModel:
        config = types.SimpleNamespace(vision_config=types.SimpleNamespace(hidden_size=DIM))

        def to(self, **kwargs: Any) -> "FakeModel":
            return self

        def eval(self) -> "FakeModel":
            return self

    def auto(name: str, result: Any) -> Any:
        class Auto:
            @staticmethod
            def from_pretrained(model_id: str, **kwargs: Any) -> Any:
                calls.append((name, kwargs))
                return result

        return Auto

    torch = types.ModuleType("torch")
    torch.float16 = "fp16"  # type: ignore[attr-defined]
    transformers = types.ModuleType("transformers")
    transformers.AutoProcessor = auto("processor", object())  # type: ignore[attr-defined]
    transformers.AutoModel = auto("model", FakeModel())  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    load_encoder("qorvex/classifier", cuda_check=lambda: True)
    assert [name for name, _ in calls] == ["processor", "model"]
    assert all(kwargs.get("local_files_only") is True for _, kwargs in calls)


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
