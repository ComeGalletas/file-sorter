"""CLS-002.2.1: classify's settings check, the NodeContext seam and the result types."""

from pathlib import Path
from types import MappingProxyType

import pytest
import yaml

from classifier.config import Config
from classifier.graph.classify import ClassifyConfigError, ClassifyResult, check_settings
from classifier.graph.ingest import IngestResult
from classifier.graph.nodes import NodeContext
from classifier.graph.state import RunResult

REPO = Path(__file__).resolve().parents[3]


def _config(**nsfw: object) -> Config:
    data = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))
    data["nsfw"].update(nsfw)
    return Config.model_validate(data)


# --- settings (CLS-002.D9) ---------------------------------------------------------------


def test_mirror_mode_passes() -> None:
    check_settings(_config(mode="mirror"))


def test_separate_mode_fails_naming_the_key() -> None:
    with pytest.raises(ClassifyConfigError, match=r"nsfw\.mode"):
        check_settings(_config(mode="separate"))


# --- seam and result ----------------------------------------------------------------------


def test_node_context_vision_defaults_to_none_and_is_not_in_repr() -> None:
    ctx = NodeContext(Path("/s"), True, Path("/r"), _config())
    assert ctx.vision is None
    assert "vision" not in repr(ctx)


def test_classify_result_total_and_defaults() -> None:
    found = ClassifyResult(classified=3, unsorted=1, errored=2)
    assert found.total == 5
    assert ClassifyResult().total == 0
    assert dict(ClassifyResult().by_reason) == {}


def test_run_result_classify_accessor() -> None:
    found = ClassifyResult(classified=1, by_reason=MappingProxyType({}))
    assert RunResult("r", True, MappingProxyType({"classify": found})).classify is found


def test_run_result_classify_rejects_a_foreign_count() -> None:
    result = RunResult("r", True, MappingProxyType({"classify": IngestResult()}))
    with pytest.raises(TypeError, match="ClassifyResult"):
        _ = result.classify


def test_prompt_texts_never_reach_a_repr() -> None:  # privacy checklist 4
    from classifier.graph.classify import _Prompts

    secret = "Qorvex-Zhyndel-secret"
    shown = repr(_Prompts([secret], [secret]))
    assert secret not in shown
