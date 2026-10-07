"""Versioned prompt files in `prompts/` (MOD-001.2.1, R-CAP-3, MOD-001.D1).

A prompt file is Markdown with YAML front matter between two `---` lines. The front matter
carries everything a call needs besides the model tag: `version` (equal to the file name, and
what a stage records on the ledger), `temperature`, `seed`, `keep_alive`, an optional `think`,
and the output JSON `schema`. The body is the template; `{name}` marks a slot.

The folder is the repo's `prompts/` (`/app/prompts` in the container, where the repo is
bind-mounted and the package installed editable). No config key holds it (MOD-001.D1).
"""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
_NAME = re.compile(r"[a-z0-9_]+")
_SLOT = re.compile(r"\{([a-z_]+)\}")
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


class PromptError(Exception):
    """A prompt file is missing or malformed, or a render got the wrong slots."""


class Prompt(BaseModel):
    """One prompt file: its front matter and its template."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    version: str
    temperature: float
    seed: int
    keep_alive: str | int
    think: bool | None = None
    output_schema: dict[str, Any] = Field(alias="schema")
    template: str

    @property
    def options(self) -> dict[str, Any]:
        """The sampling options for Ollama's `options` field."""
        return {"temperature": self.temperature, "seed": self.seed}

    @property
    def slots(self) -> frozenset[str]:
        return frozenset(_SLOT.findall(self.template))

    def render(self, **values: str) -> str:
        """The template with every slot filled, in one pass: a value is never re-scanned."""
        if set(values) != self.slots:
            raise PromptError(
                f"prompt {self.version} takes slots {sorted(self.slots)}, got {sorted(values)}"
            )
        return _SLOT.sub(lambda m: values[m.group(1)], self.template)


def load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> Prompt:
    """Load `<prompts_dir>/<name>.md`. Its front matter's `version` must equal `name`."""
    if not _NAME.fullmatch(name):
        raise PromptError(f"invalid prompt name {name!r}")
    path = prompts_dir / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except OSError as exc:
        raise PromptError(f"cannot read prompt {name}: {type(exc).__name__}") from None
    match = _FRONT_MATTER.match(text)
    if not match:
        raise PromptError(f"prompt {name} has no front matter between '---' lines")
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise PromptError(f"prompt {name} front matter is not YAML: {exc}") from None
    if not isinstance(meta, Mapping):
        raise PromptError(f"prompt {name} front matter is not a mapping")
    if "template" in meta:
        raise PromptError(f"prompt {name} front matter must not set 'template'")
    try:
        prompt = Prompt.model_validate({**meta, "template": match.group(2)})
    except ValidationError as exc:
        raise PromptError(f"prompt {name} front matter is invalid: {exc}") from None
    if prompt.version != name:
        raise PromptError(f"prompt {name} declares version {prompt.version!r}")
    return prompt
