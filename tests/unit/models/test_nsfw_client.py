"""MOD-002.2.1: the NSFW gate client on fakes, never a real model (MOD-002.D3, D4).

The real model is exercised by `tests/gpu/models/test_nsfw.py`. Scores here are faked numbers on
flat benign images; names are artificial coinages.
"""

import sys
import types
from collections.abc import Sequence
from typing import Any

import numpy as np
import pytest
from PIL import Image

from classifier.models import nsfw
from classifier.models.nsfw import (
    NSFW_BATCH_SIZE,
    load_nsfw,
    nsfw_class_index,
    score_nsfw,
)
from classifier.models.vision import VisionError

SECRET = "/source/Zhyndel-Qorvex/planted-secret.png"


def images(n: int) -> list[Image.Image]:
    return [Image.new("RGB", (4, 4), (i, 0, 0)) for i in range(n)]


def assert_unchained(error: BaseException) -> None:
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.fixture(autouse=True)
def clear_scorer_cache() -> None:
    nsfw._SCORERS.clear()


class FakeScorer:
    def __init__(self) -> None:
        self.batches: list[int] = []

    def score_batch(self, batch: Sequence[Image.Image]) -> np.ndarray:
        self.batches.append(len(batch))
        return np.array([0.25 + 0.5 * (i % 2) for i in range(len(batch))])


@pytest.mark.parametrize(
    "labels, expected",
    [
        ({0: "normal", 1: "nsfw"}, 1),
        ({0: "NSFW", 1: "normal"}, 0),
        ({"0": " Nsfw ", "1": "normal"}, 0),
        ({0: "normal", 1: "other"}, None),
        ({0: "nsfw", 1: "NSFW"}, None),
        ({}, None),
    ],
)
def test_exactly_one_nsfw_label_is_accepted(labels: dict[Any, str], expected: int | None) -> None:
    assert nsfw_class_index(labels) == expected


def test_scores_are_float32_in_range_batched_and_ordered() -> None:
    scorer = FakeScorer()
    out = score_nsfw(scorer, images(NSFW_BATCH_SIZE + 3))
    assert out.dtype == np.float32
    assert out.shape == (NSFW_BATCH_SIZE + 3,)
    assert out.min() >= 0.0 and out.max() <= 1.0
    assert scorer.batches == [NSFW_BATCH_SIZE, 3]
    assert out[0] == pytest.approx(0.25) and out[1] == pytest.approx(0.75)


def test_empty_input_gives_an_empty_array_without_scoring() -> None:
    scorer = FakeScorer()
    out = score_nsfw(scorer, [])
    assert out.shape == (0,) and out.dtype == np.float32
    assert scorer.batches == []


def test_non_images_are_refused_with_fixed_text() -> None:
    with pytest.raises(VisionError, match="decoded PIL images only") as info:
        score_nsfw(FakeScorer(), [SECRET])  # type: ignore[list-item]
    assert SECRET not in str(info.value) and SECRET not in repr(info.value)
    assert_unchained(info.value)


class BrokenScorer:
    def __init__(self, mode: str) -> None:
        self.mode = mode

    def score_batch(self, batch: Sequence[Image.Image]) -> np.ndarray:
        if self.mode == "raise":
            raise OSError(f"cannot read {SECRET}")
        if self.mode == "shape":
            return np.ones((len(batch) + 1,))
        return np.full((len(batch),), np.nan)


@pytest.mark.parametrize(
    "mode, text",
    [
        ("raise", "failed while scoring"),
        ("shape", "unexpected score shape"),
        ("nan", "non-finite"),
    ],
)
def test_scorer_failures_become_unchained_fixed_text(mode: str, text: str) -> None:
    with pytest.raises(VisionError, match=text) as info:
        score_nsfw(BrokenScorer(mode), images(1))
    assert SECRET not in str(info.value) and SECRET not in repr(info.value)
    assert_unchained(info.value)


# --- the load, on fake torch and transformers -----------------------------------------------


class FakeProcessor:
    pass


class FakeModel:
    config = types.SimpleNamespace(id2label={0: "normal", 1: "nsfw"})

    def to(self, **kwargs: Any) -> "FakeModel":
        self.moved = kwargs
        return self

    def eval(self) -> "FakeModel":
        return self


def install_fakes(
    monkeypatch: pytest.MonkeyPatch, calls: list[tuple[str, str, dict[str, Any]]], model: Any
) -> None:
    torch = types.ModuleType("torch")
    torch.float16 = "fp16"  # type: ignore[attr-defined]
    torch.float32 = "fp32"  # type: ignore[attr-defined]
    transformers = types.ModuleType("transformers")

    def factory(name: str, result: Any) -> Any:
        class Auto:
            @staticmethod
            def from_pretrained(model_id: str, **kwargs: Any) -> Any:
                calls.append((name, model_id, kwargs))
                if isinstance(result, BaseException):
                    raise result
                return result

        return Auto

    transformers.AutoImageProcessor = factory("processor", FakeProcessor())  # type: ignore[attr-defined]
    transformers.AutoModelForImageClassification = factory("model", model)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", transformers)


def test_every_from_pretrained_call_is_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []
    install_fakes(monkeypatch, calls, FakeModel())
    load_nsfw("qorvex/gate", cuda_check=lambda: True)
    assert [name for name, _, _ in calls] == ["processor", "model"]
    assert all(kwargs.get("local_files_only") is True for _, _, kwargs in calls)


@pytest.mark.parametrize(
    "has_cuda, device, dtype", [(True, "cuda", "fp16"), (False, "cpu", "fp32")]
)
def test_gpu_when_there_is_one_and_cpu_otherwise(
    monkeypatch: pytest.MonkeyPatch, has_cuda: bool, device: str, dtype: str
) -> None:
    model = FakeModel()
    install_fakes(monkeypatch, [], model)
    load_nsfw("qorvex/gate", cuda_check=lambda: has_cuda)
    assert model.moved == {"device": device, "dtype": dtype}


def test_a_failing_cuda_probe_falls_back_to_cpu_without_leaking_its_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FakeModel()
    install_fakes(monkeypatch, [], model)

    def probe() -> bool:
        raise RuntimeError(SECRET)

    load_nsfw("qorvex/gate", cuda_check=probe)
    assert model.moved["device"] == "cpu"


@pytest.mark.parametrize(
    "labels", [{0: "normal", 1: "other"}, {0: "nsfw", 1: "NSFW"}], ids=["none", "several"]
)
def test_a_model_without_exactly_one_nsfw_label_is_refused_and_not_cached(
    monkeypatch: pytest.MonkeyPatch, labels: dict[int, str]
) -> None:
    model = FakeModel()
    model.config = types.SimpleNamespace(id2label=labels)
    install_fakes(monkeypatch, [], model)
    with pytest.raises(VisionError, match="exactly one class `nsfw`") as info:
        load_nsfw("qorvex/gate", cuda_check=lambda: False)
    assert_unchained(info.value)
    assert nsfw._SCORERS == {}


def test_load_failure_is_unchained_fixed_text_and_not_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fakes(monkeypatch, [], OSError(f"no such file {SECRET}"))
    with pytest.raises(VisionError, match="make models") as info:
        load_nsfw("qorvex/gate", cuda_check=lambda: True)
    assert SECRET not in str(info.value) and SECRET not in repr(info.value)
    assert "qorvex/gate" not in str(info.value)
    assert_unchained(info.value)
    assert nsfw._SCORERS == {}


def test_one_load_per_process_and_model_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []
    install_fakes(monkeypatch, calls, FakeModel())
    first = load_nsfw("qorvex/gate", cuda_check=lambda: True)
    again = load_nsfw("qorvex/gate", cuda_check=lambda: True)
    other = load_nsfw("zhyndel/other", cuda_check=lambda: True)
    assert first is again and first is not other
    assert [model_id for name, model_id, _ in calls if name == "model"] == [
        "qorvex/gate",
        "zhyndel/other",
    ]


def test_repr_and_str_hold_no_input(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fakes(monkeypatch, [], FakeModel())
    scorer = load_nsfw("qorvex/gate", cuda_check=lambda: False)
    score_nsfw(FakeScorer(), images(1))
    for text in (repr(scorer), str(scorer)):
        assert SECRET not in text
