"""RUN-016: one resident Ollama model, and the instruct build pulled by `make models`.

Parses docker-compose.yml with PyYAML and reads the Makefile's model list. Nothing runs.
"""

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]


def ollama_service() -> dict:
    data = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    return data["services"]["ollama"]


def pulled_models() -> list[str]:
    text = (REPO / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^OLLAMA_MODELS\s*:=\s*([^#\n]*)", text, re.MULTILINE)
    assert match, "the Makefile no longer defines OLLAMA_MODELS"
    return match.group(1).split()


def test_ollama_keeps_one_model_resident() -> None:
    env = ollama_service().get("environment") or {}
    if isinstance(env, list):  # the KEY=value list form
        env = dict(item.split("=", 1) for item in env)
    assert str(env.get("OLLAMA_MAX_LOADED_MODELS")) == "1"


def test_make_models_pulls_the_instruct_build() -> None:
    assert "qwen3-vl:8b-instruct" in pulled_models()


def test_make_models_never_pulls_an_adult_vlm() -> None:
    # Q-1 is the human's pick at M5 planning; no agent pulls one before that.
    assert all("abliterated" not in model for model in pulled_models())
