"""NAME-001.1: the template engine (R-NAME-1, R-NAME-2, R-NAME-3, R-NAME-7).

Pure: no I/O, no logging, no model calls. Errors are fixed text and never quote the
template, a token value or a name (privacy items 2 and 19).

Grammar: literal text and fields `{name[:width]|filter|filter...}`. Filters are `title`,
`max=N` and `or=<fallback>`, where the fallback is literal text or one `{token}`
(NAME-001.D2). Only `seq` takes a `:width`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

# R-NAME-2's tokens.
TOKENS = frozenset(
    {
        "subject",
        "detail",
        "caption",
        "tags",
        "reference",
        "date",
        "time",
        "year",
        "format",
        "topic",
        "category",
        "animated",
        "branch",
        "ext",
        "original_sanitized",
        "short_hash",
        "seq",
    }
)

MAX_TEMPLATE_LEN = 200  # DB-009.1's naming_templates.template column

# R-NAME-1; NAME-001.D1 (descriptive) and NAME-001.D2 (the others).
BUILTINS = MappingProxyType(
    {
        "descriptive": "{subject}_{detail|max=40}_{seq:3}",
        "reference": "{reference|or={subject}}_{seq:3}",
        "dated": "{date}_{subject}_{seq:3}",
        "category-seq": "{category}_{seq:4}",
        "keep-original": "{original_sanitized}",
        "hash": "{short_hash}",
    }
)

_NAME = re.compile(r"[a-z_]+")
_DIGITS = re.compile(r"[0-9]+")
_LITERAL_OR = re.compile(r"[^{}|]+")


class TemplateError(ValueError):
    """A template that doesn't parse. The message is fixed text: it never quotes the template."""


@dataclass(frozen=True)
class Ref:
    """A token reference: `seq` may carry a zero-pad width."""

    name: str
    width: int | None = None


@dataclass(frozen=True)
class Filter:
    kind: str  # "title" | "max" | "or"
    arg: int | str | Ref | None = None


@dataclass(frozen=True)
class Field:
    ref: Ref
    filters: tuple[Filter, ...] = ()


@dataclass(frozen=True)
class Template:
    parts: tuple[str | Field, ...]

    @property
    def has_seq(self) -> bool:
        """True when `{seq}` appears, as a field or an `or=` fallback (R-NAME-6, NAME-001.2)."""
        for part in self.parts:
            if isinstance(part, Field):
                if part.ref.name == "seq":
                    return True
                if any(isinstance(f.arg, Ref) and f.arg.name == "seq" for f in part.filters):
                    return True
        return False


@dataclass(frozen=True, kw_only=True)
class Tokens:
    """One row's tokens (R-NAME-2). Only `short_hash`, `branch`, `animated` and `seq` show
    in repr: the text fields come from captions, names and categories, and the dates may be
    the kept EXIF value."""

    short_hash: str
    branch: str = "safe"  # "safe" | "nsfw"
    animated: bool = False
    seq: int = 1
    subject: str = field(default="", repr=False)
    detail: str = field(default="", repr=False)
    caption: str = field(default="", repr=False)
    tags: tuple[str, ...] = field(default=(), repr=False)
    reference: str = field(default="", repr=False)  # empty until M6 (R-NAME-7)
    format: str = field(default="", repr=False)
    topic: str | None = field(default=None, repr=False)
    original_sanitized: str = field(default="", repr=False)
    ext: str = field(default="", repr=False)
    taken_at: datetime | None = field(default=None, repr=False)  # kept EXIF DateTimeOriginal
    mtime: datetime | None = field(default=None, repr=False)  # source mtime from ingest


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def expect(self, char: str) -> None:
        if self.peek() != char:
            raise TemplateError("malformed template field")
        self.pos += 1

    def match(self, pattern: re.Pattern[str]) -> str:
        found = pattern.match(self.text, self.pos)
        if found is None:
            raise TemplateError("malformed template field")
        self.pos = found.end()
        return found[0]

    def ref(self) -> Ref:
        name = self.match(_NAME)
        if name not in TOKENS:
            raise TemplateError("unknown template token")
        width = None
        if self.peek() == ":":
            if name != "seq":
                raise TemplateError("only seq takes a width")
            self.pos += 1
            width = int(self.match(_DIGITS))
            if not 1 <= width <= 9:
                raise TemplateError("seq width must be 1 to 9")
        return Ref(name, width)

    def filter(self) -> Filter:
        kind = self.match(_NAME)
        if kind == "title":
            return Filter("title")
        if kind == "max":
            self.expect("=")
            limit = int(self.match(_DIGITS))
            if limit < 1:
                raise TemplateError("max must be at least 1")
            return Filter("max", limit)
        if kind == "or":
            self.expect("=")
            if self.peek() == "{":
                self.pos += 1
                ref = self.ref()
                self.expect("}")
                return Filter("or", ref)
            return Filter("or", self.match(_LITERAL_OR))
        raise TemplateError("unknown template filter")

    def field(self) -> Field:
        self.expect("{")
        ref = self.ref()
        filters = []
        while self.peek() == "|":
            self.pos += 1
            filters.append(self.filter())
        self.expect("}")
        return Field(ref, tuple(filters))

    def template(self) -> Template:
        parts: list[str | Field] = []
        literal = ""
        while self.pos < len(self.text):
            char = self.peek()
            if char == "{":
                if literal:
                    parts.append(literal)
                    literal = ""
                parts.append(self.field())
            elif char == "}":
                raise TemplateError("unbalanced brace in template")
            else:
                literal += char
                self.pos += 1
        if literal:
            parts.append(literal)
        if not any(isinstance(part, Field) for part in parts):
            raise TemplateError("template has no token")
        return Template(tuple(parts))


def parse(template: str) -> Template:
    """Validate and parse a template (CLI-010 calls this before storing one)."""
    if not isinstance(template, str) or not template:
        raise TemplateError("template is empty")
    if len(template) > MAX_TEMPLATE_LEN:
        raise TemplateError("template is longer than 200 characters")
    if "\n" in template or "\r" in template:
        raise TemplateError("template must be one line")
    return _Parser(template).template()
