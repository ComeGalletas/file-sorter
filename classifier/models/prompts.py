"""Versioned prompt files in `prompts/` (MOD-001.2.1, R-CAP-3, MOD-001.D1).

A prompt file is Markdown with YAML front matter between two `---` lines. The front matter
carries everything a call needs besides the model tag: `version` (equal to the file name, and
what a stage records on the ledger), `temperature`, `seed`, `keep_alive`, optional
`num_predict`, `think`, `raw` and `wrap` (MOD-001.D5), `num_ctx` (CLS-004.D9), `retry_temperature`,
`max_side` and `jpeg_quality` (CLS-004.2.2), the user
message `user` and its variant `user_alt` (CLS-004.1), and the output JSON `schema`. The body
is the template (the system prompt when `user` is set); `{name}` marks a slot.

The folder is the repo's `prompts/` (`/app/prompts` in the container, where the repo is
bind-mounted and the package installed editable). No config key holds it (MOD-001.D1).
"""

import copy
import hashlib
import os
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
_NAME = re.compile(r"[a-z0-9_]+")
_SLOT = re.compile(r"\{([a-z_]+)\}")
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
# PR #72 round 1: text that reaches a prompt as data could hold a chat control token, a think
# tag or a fence marker (`<<<`, `>>>`) and close the turn or the data region. These patterns
# are broken up before rendering.
_INJECTION = re.compile(r"<\||\|>|</?think>|<{3,}|>{3,}", re.IGNORECASE)
# CLS-004.D17 / CLS-004.8: the git-ignored local prompt replaces the committed system text.
# `PROMPTS_LOCAL=off` turns it off; any other value, or none, leaves it on.
LOCAL_DIR = "local"
LOCAL_ENV = "PROMPTS_LOCAL"
MAX_REPLACEMENT_BYTES = 16384


def neutralize(text: str) -> str:
    """`text` with chat control tokens, think tags and fence markers made inert.

    Each match gets a space between its characters (`<|` becomes `< |`), so the model still
    sees the words around it. Spans are matched against the original text, never this one.
    """
    return _INJECTION.sub(lambda m: " ".join(m.group(0)), text)


class PromptError(Exception):
    """A prompt file is missing or malformed, or a render got the wrong slots."""


class Prompt(BaseModel):
    """One prompt file: its front matter and its template."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    version: str
    temperature: float
    seed: int
    keep_alive: str | int
    num_predict: int | None = Field(default=None, gt=0)
    think: bool | None = None
    # MOD-001.D5: `raw` skips Ollama's chat template; `wrap` is the prompt's own, with one
    # `{prompt}` slot. It is the only model-specific part of a prompt file.
    raw: bool = False
    wrap: str | None = None
    # CLS-004.D9: pinned per prompt, because Ollama reloads the model when the context changes.
    num_ctx: int | None = Field(default=None, gt=0)
    # CLS-004.2.2: a retried call differs from the first (temperature 0 and a fixed seed would
    # repeat the answer); the longest side and JPEG quality of an image sent with the prompt.
    retry_temperature: float | None = Field(default=None, ge=0)
    max_side: int | None = Field(default=None, gt=0)
    jpeg_quality: int | None = Field(default=None, ge=1, le=95)
    # CLS-004.1: the user message and its variant (the hinted or multi-frame wording). The
    # variant may hold slots; `render_user` neutralizes their values.
    user: str | None = Field(default=None, repr=False)
    user_alt: str | None = Field(default=None, repr=False)
    output_schema: dict[str, Any] = Field(alias="schema")
    template: str
    # CLS-004.8: set only by `load_effective_prompt`, never by a prompt file. The text is the
    # human's local system text, so it stays out of every repr; the hash is what gets recorded.
    replacement_hash: str | None = None
    replacement: str | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def _raw_needs_wrap(self) -> Self:
        if self.raw != (self.wrap is not None):
            raise ValueError("`raw: true` and `wrap` go together")
        if self.wrap is not None and self.wrap.count("{prompt}") != 1:
            raise ValueError("`wrap` must hold exactly one {prompt} slot")
        if self.user_alt is not None and self.user is None:
            raise ValueError("`user_alt` needs `user`")
        return self

    @property
    def effective_version(self) -> str:
        """`version`, plus `+<8 hex>` of the local replacement when one is in use (CLS-004.8)."""
        if self.replacement_hash is None:
            return self.version
        return f"{self.version}+{self.replacement_hash}"

    @property
    def options(self) -> dict[str, Any]:
        """The sampling options for Ollama's `options` field."""
        options: dict[str, Any] = {"temperature": self.temperature, "seed": self.seed}
        if self.num_predict is not None:
            options["num_predict"] = self.num_predict
        if self.num_ctx is not None:
            options["num_ctx"] = self.num_ctx
        return options

    @property
    def retry_options(self) -> dict[str, Any]:
        """`options` for the one retry of a failed answer, with `retry_temperature` if set."""
        options = self.options
        if self.retry_temperature is not None:
            options["temperature"] = self.retry_temperature
        return options

    @property
    def slots(self) -> frozenset[str]:
        return frozenset(_SLOT.findall(self.template))

    def render(self, **values: str) -> str:
        """The template with every slot filled, in one pass: a value is never re-scanned."""
        if set(values) != self.slots:
            raise PromptError(
                f"prompt {self.version} takes slots {sorted(self.slots)}, got {sorted(values)}"
            )
        # CLS-004.8: the local replacement is the whole system text; its slots are a subset of
        # the committed ones (checked at load), and the user templates stay the committed ones.
        source = self.template if self.replacement is None else f"{self.replacement}\n"
        body = _SLOT.sub(lambda m: values[m.group(1)], source)
        # Only the wrapper is scanned for {prompt}, so the body can't inject a second one.
        return self.wrap.replace("{prompt}", body) if self.wrap is not None else body

    def render_user(self, *, alt: bool = False, **values: str) -> str:
        """The user message (or its variant), slots filled in one pass with neutralized values."""
        text = self.user_alt if alt else self.user
        if text is None:
            raise PromptError(f"prompt {self.version} has no such user message")
        slots = frozenset(_SLOT.findall(text))
        if set(values) != slots:
            raise PromptError(
                f"user message of {self.version} takes slots {sorted(slots)}, got {sorted(values)}"
            )
        return _SLOT.sub(lambda m: neutralize(values[m.group(1)]), text)

    def schema_with_enums(self, **enums: Sequence[str]) -> dict[str, Any]:
        """A copy of the output schema with `enum` set on the named top-level fields.

        Used for the category lists, which come from the `categories` table at run time.
        """
        schema = copy.deepcopy(self.output_schema)
        properties = schema.get("properties")
        for field, values in enums.items():
            names = list(values)
            if not isinstance(properties, dict) or not isinstance(properties.get(field), dict):
                raise PromptError(f"prompt {self.version} schema lacks a field to give an enum")
            if not names or len(set(names)) != len(names) or not all(names):
                raise PromptError("enum values must be a non-empty list of unique names")
            properties[field]["enum"] = names
        return schema


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
    if {"template", "replacement", "replacement_hash"} & set(meta):
        raise PromptError(f"prompt {name} front matter must not set 'template' or a replacement")
    try:
        prompt = Prompt.model_validate({**meta, "template": match.group(2)})
    except ValidationError as exc:
        raise PromptError(f"prompt {name} front matter is invalid: {exc}") from None
    if prompt.version != name:
        raise PromptError(f"prompt {name} declares version {prompt.version!r}")
    return prompt


def _read_replacement(path: Path, name: str) -> str | None:
    """The text of the local replacement at `path`, or None when absent, off or blank.

    Refuses a symlink, a non-regular file, a file over `MAX_REPLACEMENT_BYTES` and bytes that are
    not UTF-8. Every refusal is fixed text raised outside any `except`, so it carries no cause or
    context and never quotes the path or the text (CLS-004.8).
    """
    if os.environ.get(LOCAL_ENV) == "off":
        return None
    problem: str | None = None
    raw = b""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        info = None
        problem = "cannot be read"
    if info is not None:
        if not stat.S_ISREG(info.st_mode):
            problem = "is not a regular file"
        elif info.st_size > MAX_REPLACEMENT_BYTES:
            problem = f"is over {MAX_REPLACEMENT_BYTES} bytes"
        else:
            try:
                with path.open("rb") as handle:
                    raw = handle.read(MAX_REPLACEMENT_BYTES + 1)
            except OSError:
                problem = "cannot be read"
            if problem is None and len(raw) > MAX_REPLACEMENT_BYTES:
                problem = f"is over {MAX_REPLACEMENT_BYTES} bytes"
    text = ""
    if problem is None:
        try:
            text = raw.decode("utf-8").replace("\r\n", "\n").strip()
        except UnicodeDecodeError:
            problem = "is not UTF-8"
    if problem is not None:
        raise PromptError(f"local prompt for {name} {problem}")
    return text or None


def load_effective_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> Prompt:
    """`load_prompt`, with the system text replaced by `<prompts_dir>/local/<name>.md` if present.

    The replacement is the whole system text (CLS-004.D17). The front matter and the user
    templates stay the committed file's, and the replacement may use only the slots the committed
    body declares. `load_prompt` itself never reads `local/`, and `*.example.md` files are never
    loaded: only the exact name is.
    """
    prompt = load_prompt(name, prompts_dir)
    text = _read_replacement(prompts_dir / LOCAL_DIR / f"{name}.md", name)
    if text is None:
        return prompt
    undeclared = not set(_SLOT.findall(text)) <= prompt.slots
    if undeclared:  # raised outside any except; fixed text, as the slot name is the human's text
        raise PromptError(f"local prompt for {name} uses a slot the committed prompt lacks")
    digest = hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:8]
    return prompt.model_copy(update={"replacement": neutralize(text), "replacement_hash": digest})
