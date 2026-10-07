"""Sanitization rules: load `sanitize.yaml` and redact text (DESIGN.md §4.2, R-SAN-3/4/6).

The rules file is git-ignored and holds the human's own values, so no error message here
ever repeats a value from it: messages name `make init` and the key location only
(SAN-001.D1). `before_hash` is keyed with `SANITIZE_LOG_KEY` from the environment
(SAN-001.D5, DOC-007.D2). `sanitize_text` is reused on the rendered name in M5 (R-SAN-7).
"""

import hashlib
import hmac
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from classifier.graph.ingest_files import IMAGE_EXTENSIONS

LOG_KEY_ENV = "SANITIZE_LOG_KEY"

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


# --- Redaction (R-SAN-3, R-SAN-4, R-SAN-6) ---------------------------------------------

FILENAME = "filename"  # DB-002.D1: the sanitize_log.field values this module writes
PATH_SEGMENT = "path_segment"

# entity(text, labels) -> [(span, label)]: the detector SAN-001.3 adapts (MOD-001.2).
EntityFn = Callable[[str, Sequence[str]], Sequence[tuple[str, str]]]


@dataclass(frozen=True)
class Redaction:
    """One `sanitize_log` row's text fields. The redacted value itself is never kept."""

    rule_id: str
    field: str
    before_hash: str
    after_value: str | None


@dataclass(frozen=True)
class SanitizedName:
    stem: str  # stored as files.original_sanitized (SAN-001.D8)
    suffix: str  # the extension, never passed to the rules (SAN-001.D1)
    segments: tuple[str, ...]
    redactions: tuple[Redaction, ...]


def before_hash(value: str, key: bytes) -> str:
    """HMAC-SHA256 of the redacted value, hex (SAN-001.D5, DOC-007.D2)."""
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _literal_pattern(value: str) -> str:
    # SAN-001.D1: each separator in the value matches any one of the four.
    sep = "[" + re.escape(SEPARATORS) + "]"
    return sep.join(re.escape(part) for part in re.split(sep, value))


def _apply_literals(text: str, field: str, rules: Rules, out: list[Redaction]) -> str:
    # One pass over every value, longest first, so a full name wins over its first word
    # and no literal matches inside another literal's replacement.
    values = sorted(
        ((value, rule) for rule in rules.of_type(LiteralRule) for value in rule.values),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    if not values:
        return text
    combined = re.compile(
        "|".join(f"({_literal_pattern(value)})" for value, _ in values), re.IGNORECASE
    )

    def replace(match: re.Match[str]) -> str:
        rule = values[match.lastindex - 1][1]  # type: ignore[operator]
        out.append(Redaction(rule.id, field, before_hash(match[0], rules.log_key), rule.replace))
        return rule.replace

    return combined.sub(replace, text)


def _apply_regexes(text: str, field: str, rules: Rules, out: list[Redaction]) -> str:
    for rule in rules.of_type(RegexRule):

        def replace(match: re.Match[str], rule: RegexRule = rule) -> str:
            if not match[0]:  # an empty match redacts nothing
                return ""
            out.append(
                Redaction(rule.id, field, before_hash(match[0], rules.log_key), rule.replace)
            )
            return rule.replace  # inserted as is: no group expansion

        text = re.sub(rule.pattern, replace, text)
    return text


def _apply_entities(
    text: str, field: str, rules: Rules, entity: EntityFn, out: list[Redaction]
) -> str:
    for rule in rules.of_type(EntityRule):
        spans = {
            (span, label)
            for span, label in entity(text, list(rule.labels))
            if span and label in rule.labels and span in text
        }
        for span, label in sorted(spans, key=lambda pair: len(pair[0]), reverse=True):
            after = rule.replace.format(label=label)
            hashed = before_hash(span, rules.log_key)
            count = text.count(span)
            if not count:  # already covered by a longer span
                continue
            out.extend(Redaction(rule.id, field, hashed, after) for _ in range(count))
            text = text.replace(span, after)
    return text


def sanitize_text(
    text: str, field: str, rules: Rules, entity: EntityFn | None = None
) -> tuple[str, list[Redaction]]:
    """Redact `text`: literal, then regex, then entity when given (R-SAN-4, SAN-001.D1).

    Returns the redacted text and one `Redaction` per replaced match.
    """
    redactions: list[Redaction] = []
    text = _apply_literals(text, field, rules, redactions)
    text = _apply_regexes(text, field, rules, redactions)
    if entity is not None:
        text = _apply_entities(text, field, rules, entity, redactions)
    return text, redactions


def sanitize_name(
    relative_path: str | PurePosixPath, rules: Rules, entity: EntityFn | None = None
) -> SanitizedName:
    """Redact a source-relative path: each folder segment and the file stem (SAN-001.D1).

    An image extension is split off first and never reaches the rules. Any other dotted
    tail (`first.last`) is part of the name and is redacted with it: fail closed (P-2).
    """
    path = PurePosixPath(relative_path)
    if path.is_absolute() or not path.name or ".." in path.parts:
        raise ValueError("expected a path relative to source_root")
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        stem, suffix = path.stem, path.suffix
    else:
        stem, suffix = path.name, ""
    redactions: list[Redaction] = []
    segments = []
    for segment in path.parts[:-1]:
        clean, found = sanitize_text(segment, PATH_SEGMENT, rules, entity)
        segments.append(clean)
        redactions.extend(found)
    stem, found = sanitize_text(stem, FILENAME, rules, entity)
    redactions.extend(found)
    return SanitizedName(stem, suffix, tuple(segments), tuple(redactions))
