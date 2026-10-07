"""Sanitization rules: load `sanitize.yaml` (DESIGN.md §4.2, R-SAN-3, R-CFG-1).

The rules file is git-ignored and holds the human's own values, so no error message here
ever repeats a value from it: messages name `make init` and the key location only
(SAN-001.D1). `before_hash` is keyed with `SANITIZE_LOG_KEY` from the environment
(SAN-001.D5, DOC-007.D2).
"""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

LOG_KEY_ENV = "SANITIZE_LOG_KEY"
ENTITY_LABELS = ("PERSON", "ORG", "LOCATION")

# SAN-001.D1: space, `_`, `-` and `.` are interchangeable inside a literal value.
SEPARATORS = " _-."


class SanitizeConfigError(Exception):
    """The rules file or the log key is missing or invalid. Never carries a value."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExifSettings(_Strict):
    mode: Literal["strip_all"]
    keep: list[str] = Field(default_factory=lambda: ["Orientation", "DateTimeOriginal"])


class LiteralRule(_Strict):
    id: str = Field(min_length=1)
    type: Literal["literal"]
    values: list[str] = Field(min_length=1)
    replace: str

    @field_validator("values")
    @classmethod
    def _not_only_separators(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value.strip(SEPARATORS):
                raise ValueError("a value is empty or only separators")
        return values


class RegexRule(_Strict):
    id: str = Field(min_length=1)
    type: Literal["regex"]
    pattern: str = Field(min_length=1)
    replace: str

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, pattern: str) -> str:
        try:
            re.compile(pattern)
        except re.error:
            raise ValueError("invalid regex") from None
        return pattern


class EntityRule(_Strict):
    id: str = Field(min_length=1)
    type: Literal["entity"]
    labels: list[Literal["PERSON", "ORG", "LOCATION"]] = Field(min_length=1)
    replace: str

    @field_validator("replace")
    @classmethod
    def _formats(cls, replace: str) -> str:
        try:
            replace.format(label="PERSON")
        except (KeyError, IndexError, ValueError):
            raise ValueError("replace may only use the {label} placeholder") from None
        return replace


class ExifFieldRule(_Strict):
    """Tags that are always removed, even when `exif.keep` names them (SAN-001.D3, D11)."""

    id: str = Field(min_length=1)
    type: Literal["exif_field"]
    fields: list[str] = Field(min_length=1)


Rule = Annotated[LiteralRule | RegexRule | EntityRule | ExifFieldRule, Field(discriminator="type")]


class RulesFile(_Strict):
    exif: ExifSettings
    rules: list[Rule]

    @field_validator("rules")
    @classmethod
    def _unique_ids(cls, rules: list[Rule]) -> list[Rule]:
        ids = [rule.id for rule in rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule ids must be unique")
        return rules


@dataclass(frozen=True)
class Rules:
    """The loaded rules plus the HMAC key for `before_hash` (never printed)."""

    exif: ExifSettings
    rules: tuple[Rule, ...]
    log_key: bytes = field(repr=False)

    def of_type[T](self, kind: type[T]) -> list[T]:
        return [rule for rule in self.rules if isinstance(rule, kind)]


_UNION_TAGS = {"literal", "regex", "entity", "exif_field"}
_KNOWN_KEYS = {
    name
    for model in (RulesFile, ExifSettings, LiteralRule, RegexRule, EntityRule, ExifFieldRule)
    for name in model.model_fields
}


def _where(loc: tuple[int | str, ...]) -> str:
    """The error's location. An unknown key is not named: a misplaced value can land there."""
    text = ""
    for part in loc:
        if isinstance(part, int):
            text += f"[{part}]"
        elif part not in _UNION_TAGS:
            name = part if part in _KNOWN_KEYS else "<unknown key>"
            text += f".{name}" if text else name
    return text or "(top level)"


def _describe(error: ValidationError) -> str:
    """Rebuild pydantic's errors from location and type only: its `msg` and `input` may echo
    a value from the rules file (SAN-001.D1)."""
    lines = []
    for err in error.errors():
        reason = err["type"]
        if reason == "value_error":
            reason = str(err.get("ctx", {}).get("error", reason))
        lines.append(f"{_where(err['loc'])}: {reason}")
    return "; ".join(lines)


def log_key(env: Mapping[str, str] | None = None) -> bytes:
    """The `before_hash` HMAC key: the UTF-8 bytes of `SANITIZE_LOG_KEY` as written (SAN-001.D5)."""
    value = (os.environ if env is None else env).get(LOG_KEY_ENV, "")
    if not value.strip():
        raise SanitizeConfigError(f"{LOG_KEY_ENV} is not set: run make init")
    return value.encode("utf-8")


def load_rules(path: str | Path, env: Mapping[str, str] | None = None) -> Rules:
    """Load and validate the rules file (`sanitizer.rules_file`), and the log key."""
    file = Path(path)
    if not file.is_file():
        raise SanitizeConfigError(f"rules file not found: {file}; run make init")
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        # The YAML error quotes the offending text, so only its line number is kept.
        mark = getattr(exc, "problem_mark", None)
        line = f" at line {mark.line + 1}" if mark is not None else ""
        raise SanitizeConfigError(
            f"rules file is not valid YAML{line}: {file}; compare it with "
            "sanitize.example.yaml (make init)"
        ) from None
    if not isinstance(data, dict):
        raise SanitizeConfigError(f"rules file is empty or not a mapping: {file}; run make init")
    try:
        parsed = RulesFile.model_validate(data)
    except ValidationError as exc:
        raise SanitizeConfigError(
            f"invalid rules file {file}: {_describe(exc)}; compare it with "
            "sanitize.example.yaml (make init)"
        ) from None
    return Rules(exif=parsed.exif, rules=tuple(parsed.rules), log_key=log_key(env))
