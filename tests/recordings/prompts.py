"""TST-010.1: an image request may carry prompt text rendered from a committed `prompts/` file.

TST-009.D2 holds the `prompt` of an image request to TST-008.D9's text rule, so a committed prompt
(far longer, with `.` and `:`) could not be recorded, and `system` was not an allowed field. This
module lets `prompt` and `system` be either D9 text, or a rendering of a committed prompt file:

    "prompt_source": {"name": "classify_v1", "sha256": "<hash of prompts/classify_v1.md>",
                      "system": {"slots": {"formats": ..., "topics": ...}},
                      "prompt": {"alt": true, "slots": {"name": ...}}}

The recording still stores the exact text sent (the key covers it), so replay is exact. The check
re-renders from the committed file and requires the stored or sent text to match exactly, and the
file's hash to match the recorded one, so a recording holds only committed public text plus slot
values that passed a rule. A live body has no `prompt_source` (the client sends text only), so it
is inferred by matching the text against each committed prompt. Record, replay and the lint all
call `resolve`, so they refuse alike, before anything is forwarded or written.

Slot rules (TST-010.1, lead): `formats` and `topics` take a `", "`-joined category list (names of
`[a-z0-9]+(-[a-z0-9]+)*`, 1 to 40 characters, 1 to 64 names). Every other slot, `name` included,
takes TST-008.D9's rule. Every error is fixed text, raised unchained.
"""

import hashlib
import re
from collections.abc import Callable, Mapping
from typing import Any

from classifier.models.prompts import PROMPTS_DIR as COMMITTED_PROMPTS_DIR
from classifier.models.prompts import Prompt, PromptError, load_prompt
from tests.recordings.replay import PromptSourceError, RecordingError

# Tests point this at a temporary copy; the lint and the transports read it at call time.
PROMPTS_DIR = COMMITTED_PROMPTS_DIR
PARTS = ("system", "prompt")
SOURCE_FIELDS = {"name", "sha256", *PARTS}
NAME_RE = re.compile(r"[a-z0-9_]+")
SHA_RE = re.compile(r"[0-9a-f]{64}")
SLOT_RE = re.compile(r"\{([a-z_]+)\}")
MAX_TEXT_CHARS = 20_000  # the rendered system text with 64 long names fits well inside
CATEGORY_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
MAX_NAME_CHARS = 40
MAX_NAMES = 64
CATEGORY_RULE = (
    'a categories slot must be 1 to 64 names joined by ", ", each of lower-case letters and '
    "digits with single hyphens, 1 to 40 characters"
)
NOT_TEXT = "the prompt or system of an image request is not text"
UNSOURCED = (
    "the prompt or system of an image request does not pass the text rule and is not a "
    "rendering of a committed prompts file"
)
BAD_SOURCE = "the prompt_source of a request is malformed"
STALE = "its prompt file changed since it was recorded; re-record it"
MISSING = "its prompt file is missing or invalid; re-record it"
NO_MATCH = "its prompt text is not what its prompt file renders; re-record it"
TEXT_ONLY = "a text-only request may not carry a prompt_source"


def _fixed(text: str) -> PromptSourceError:
    return PromptSourceError(text)


def check_category_list(value: str) -> None:
    """A `", "`-joined category list (the public defaults and coined names pass)."""
    names = value.split(", ")
    if (
        not 1 <= len(names) <= MAX_NAMES
        or not all(CATEGORY_NAME.fullmatch(n) and len(n) <= MAX_NAME_CHARS for n in names)
        or len(set(names)) != len(names)
    ):
        raise RecordingError(CATEGORY_RULE)


# Pinned by slot name; any other slot falls back to D9.
SLOT_RULES: dict[str, Callable[[str], None]] = {
    "formats": check_category_list,
    "topics": check_category_list,
}


def check_slot(name: str, value: object) -> None:
    from tests.recordings.vision import check_text_input

    if not isinstance(value, str):
        raise _fixed(BAD_SOURCE)
    SLOT_RULES.get(name, check_text_input)(value)


def _d9_ok(text: str) -> bool:
    from tests.recordings.vision import check_text_input

    try:
        check_text_input(text)
    except RecordingError:
        return False
    return True


def load_committed(name: object) -> tuple[Prompt, str]:
    """A committed prompt and the SHA-256 of its LF-normalised text, or a fixed refusal."""
    loaded: tuple[Prompt, str] | None = None
    if isinstance(name, str) and NAME_RE.fullmatch(name):
        try:
            prompt = load_prompt(name, PROMPTS_DIR)
            text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").replace("\r\n", "\n")
            loaded = (prompt, hashlib.sha256(text.encode("utf-8")).hexdigest())
        except (PromptError, OSError, UnicodeError):
            loaded = None
    if loaded is None:
        raise _fixed(MISSING)
    return loaded


def _slots(entry: object, part: str) -> tuple[bool, dict[str, str]]:
    allowed = {"slots", "alt"} if part == "prompt" else {"slots"}
    if not isinstance(entry, Mapping) or not {"slots"} <= set(entry) <= allowed:
        raise _fixed(BAD_SOURCE)
    slots = entry["slots"]
    alt = entry.get("alt", False)
    if not isinstance(slots, Mapping) or not isinstance(alt, bool):
        raise _fixed(BAD_SOURCE)
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in slots.items()):
        raise _fixed(BAD_SOURCE)
    return alt, dict(slots)


def _render(prompt: Prompt, part: str, alt: bool, slots: dict[str, str]) -> str | None:
    if prompt.user is None:
        return None
    try:
        if part == "system":
            return prompt.render(**slots)
        return prompt.render_user(alt=alt, **slots)
    except PromptError:
        return None


def verify(source: object, body: Mapping[str, Any]) -> dict[str, Any]:
    """`source` checked against `body`: the file, its hash, the slots, the exact text."""
    if not isinstance(source, Mapping) or not {"name", "sha256"} <= set(source):
        raise _fixed(BAD_SOURCE)
    if not set(source) <= SOURCE_FIELDS or not any(part in source for part in PARTS):
        raise _fixed(BAD_SOURCE)
    sha = source["sha256"]
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise _fixed(BAD_SOURCE)
    prompt, current = load_committed(source["name"])
    if current != sha:
        raise _fixed(STALE)
    checked: dict[str, Any] = {"name": source["name"], "sha256": sha}
    for part in PARTS:
        text = body.get(part)
        if part not in source:
            if text is not None and (not isinstance(text, str) or not _d9_ok(text)):
                raise _fixed(UNSOURCED)
            continue
        if not isinstance(text, str):
            raise _fixed(NOT_TEXT)
        alt, slots = _slots(source[part], part)
        problem = None
        for slot, value in slots.items():
            try:
                check_slot(slot, value)
            except RecordingError as exc:
                problem = str(exc)  # a fixed rule text, never the value
        if problem is not None:
            raise _fixed(problem)
        if _render(prompt, part, alt, slots) != text:
            raise _fixed(NO_MATCH)
        checked[part] = {"slots": slots, **({"alt": alt} if part == "prompt" else {})}
    return checked


def _pattern(template: str) -> re.Pattern[str]:
    pieces = SLOT_RE.split(template)  # literal, name, literal, name, ...
    seen: set[str] = set()
    regex = []
    for index, piece in enumerate(pieces):
        if index % 2 == 0:
            regex.append(re.escape(piece))
        elif piece in seen:
            regex.append(f"(?P=s_{piece})")
        else:
            seen.add(piece)
            regex.append(f"(?P<s_{piece}>.+?)")
    return re.compile("".join(regex), re.DOTALL)


def _match(template: str | None, text: str) -> dict[str, str] | None:
    if template is None:
        return None
    found = _pattern(template).fullmatch(text)
    if found is None:
        return None
    return {name[2:]: value for name, value in found.groupdict().items()}


def _infer_for(name: str, body: Mapping[str, Any], need: list[str]) -> dict[str, Any] | None:
    prompt, digest = load_committed(name)
    source: dict[str, Any] = {"name": name, "sha256": digest}
    for part in need:
        text = body[part]
        if part == "system":
            slots = _match(prompt.template, text)
            entry = None if slots is None else {"slots": slots}
        else:
            entry = None
            for alt, template in ((False, prompt.user), (True, prompt.user_alt)):
                slots = _match(template, text)
                if slots is not None:
                    entry = {"alt": alt, "slots": slots}
                    break
        if entry is None:
            return None
        source[part] = entry
    return source


def _committed_names() -> list[str]:
    try:
        return sorted(p.stem for p in PROMPTS_DIR.glob("*.md") if NAME_RE.fullmatch(p.stem))
    except OSError:
        return []


def resolve(body: Mapping[str, Any]) -> dict[str, Any] | None:
    """The verified `prompt_source` of an image request, or None when both texts are D9 text.

    Raises a fixed `RecordingError` for text that is neither D9 text nor a committed rendering.
    """
    texts = {part: body[part] for part in PARTS if part in body}
    if not all(isinstance(text, str) for text in texts.values()):
        raise _fixed(NOT_TEXT)
    if "prompt_source" in body:
        return verify(body["prompt_source"], body)
    need = [part for part, text in texts.items() if not _d9_ok(text)]
    if not need:
        return None
    if any(len(texts[part]) > MAX_TEXT_CHARS for part in need):
        raise _fixed(UNSOURCED)
    for name in _committed_names():
        try:
            source = _infer_for(name, body, need)
            if source is not None:
                return verify(source, body)
        except RecordingError:
            continue  # this file does not fit; another one may
    raise _fixed(UNSOURCED)


__all__ = ["PROMPTS_DIR", "PromptSourceError", "resolve", "verify"]
