"""NAME-001.1: the template engine (R-NAME-1, R-NAME-2, R-NAME-3, R-NAME-5, R-NAME-7, R-NAME-8,
R-SAN-7).

Pure: no I/O, no logging, no model calls. Errors are fixed text and never quote the
template, a token value or a name (privacy items 2 and 19).

Grammar: literal text and fields `{name[:width]|filter|filter...}`. Filters are `title`,
`max=N` and `or=<fallback>`, where the fallback is literal text or one `{token}`
(NAME-001.D2). Only `seq` takes a `:width`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from classifier.config import NamingConfig

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


# --- render (R-NAME-2, R-NAME-3, R-NAME-5, R-NAME-8, R-SAN-7) ------------------------------

_NON_NAME = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    """R-NAME-5: ASCII-fold, lowercase, non-`[a-z0-9]` runs to one `_`, no edge `_`.

    `encode(..., "ignore")` drops what doesn't fold (a lone surrogate included), so no
    UnicodeError can quote a character (privacy item 7).
    """
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return _NON_NAME.sub("_", folded.lower()).strip("_")


def _when(tokens: Tokens) -> datetime | None:
    # R-NAME-3: the kept EXIF DateTimeOriginal, else the source mtime from ingest.
    return tokens.taken_at if tokens.taken_at is not None else tokens.mtime


def _value(ref: Ref, tokens: Tokens) -> str:
    name = ref.name
    if name == "seq":
        return str(tokens.seq).zfill(ref.width or 1)
    if name == "tags":
        return "_".join(tokens.tags)
    if name == "topic":
        return tokens.topic or ""
    if name == "category":  # R-NAME-2: {topic}_{format}, or {format} without a topic
        return f"{tokens.topic}_{tokens.format}" if tokens.topic else tokens.format
    if name == "animated":
        return "animated" if tokens.animated else ""
    if name == "ext":
        return tokens.ext.lstrip(".")
    if name in ("date", "time", "year"):
        when = _when(tokens)
        if when is None:
            return ""
        return when.strftime({"date": "%Y-%m-%d", "time": "%H%M%S", "year": "%Y"}[name])
    value = getattr(tokens, name)
    return value if isinstance(value, str) else ""


def _field(part: Field, tokens: Tokens) -> str:
    value = _value(part.ref, tokens)
    for f in part.filters:  # left to right
        if f.kind == "or":
            if not value.strip():
                value = _value(f.arg, tokens) if isinstance(f.arg, Ref) else str(f.arg)
        elif f.kind == "max":
            value = value[: int(f.arg)]  # type: ignore[arg-type]
        else:  # title
            value = value.title()
    return value


def render(
    template: str | Template,
    tokens: Tokens,
    *,
    config: NamingConfig,
    sanitize: Callable[[str], str],
) -> str:
    """The normalized stem: prefix and cap applied, before collisions (NAME-001.2).

    1. substitute the tokens and filters;
    2. normalize (R-NAME-5);
    3. re-run the sanitize rules (R-SAN-7), injected so the engine stays pure, and
       normalize again, since a rule's replacement may hold `[` or capitals;
    4. an empty stem falls back to `short_hash` (NAME-001.D4);
    5. adult rows get `nsfw_prefix` (R-NAME-8; `""` disables it);
    6. cap at `max_len`, prefix included, keeping the head (NAME-001.D5).
    """
    parsed = template if isinstance(template, Template) else parse(template)
    raw = "".join(part if isinstance(part, str) else _field(part, tokens) for part in parsed.parts)
    stem = normalize(sanitize(normalize(raw)))
    if not stem:
        stem = normalize(tokens.short_hash)  # NAME-001.D4
    prefix = config.nsfw_prefix if tokens.branch == "nsfw" else ""
    return (prefix + stem)[: config.max_len].rstrip("_")  # NAME-001.D5
