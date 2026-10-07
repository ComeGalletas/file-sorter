"""Typed configuration (DESIGN.md §6, CFG-001, R-CFG-1).

`config.yaml` holds container paths only. Every section is a strict model: an unknown key
is an error. Values that are not decided yet stay `None`: `models.vlm_nsfw` (Q-1) and the
`classify.*.default_min_score` values (calibrated in M3).

No error raised by `load_config` repeats a value from the file or the environment: messages
name the file, the key location and the error type only (CFG-002).
"""

import os
import posixpath
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

CONFIG_ENV = "CLASSIFIER_CONFIG"
DSN_ENV = "DB_DSN"


class ConfigError(Exception):
    """The configuration cannot be loaded or is not allowed."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PathsConfig(_Section):
    source_root: str
    results_root: str


class FoldersConfig(_Section):
    auto_create: bool
    layout: str
    no_topic: str
    animated_subfolder: bool


class ModelsConfig(_Section):
    classifier: str
    nsfw: str
    vlm_safe: str
    vlm_nsfw: str | None = None  # Q-1: never picked by an agent
    text_llm: str
    text_embed: str


class AxisConfig(_Section):
    default_min_score: float | None = None  # calibrated in M3 (R-CLS-8)
    margin: float


class ClassifyConfig(_Section):
    score: Literal["sigmoid", "cosine"]
    format: AxisConfig
    topic: AxisConfig


class NsfwConfig(_Section):
    threshold: float
    mode: Literal["mirror", "separate"]
    root: str


class NamingConfig(_Section):
    default_template: str
    nsfw_template: str | None = None
    nsfw_prefix: str
    max_len: int


class SimilarityConfig(_Section):
    image: float
    text: float


class RagConfig(_Section):
    top_k: int
    min_similarity: SimilarityConfig
    max_exemplars: int
    web_backend: Literal["searxng", "brave", "claude"]
    web_for_nsfw: Literal["text_only", False]


class SanitizerConfig(_Section):
    backend: Literal["local", "claude"]
    rules_file: str
    ocr: bool


class WatchConfig(_Section):
    debounce_s: float
    polling: Literal["auto", True, False]


class ThumbsConfig(_Section):
    size: int


class DeletionConfig(_Section):
    enabled: bool = False  # R-FOP-0: purge-sources / delete refuse unless true


class ApiConfig(_Section):
    host: str
    port: int


class DbConfig(_Section):
    # CFG-001.D2: null in config.yaml, filled from DB_DSN by load_config. It holds the
    # database password, so it is kept out of repr.
    dsn: str | None = Field(default=None, repr=False)


class Config(_Section):
    paths: PathsConfig
    folders: FoldersConfig
    models: ModelsConfig
    classify: ClassifyConfig
    nsfw: NsfwConfig
    naming: NamingConfig
    rag: RagConfig
    sanitizer: SanitizerConfig
    watch: WatchConfig
    thumbs: ThumbsConfig
    deletion: DeletionConfig = DeletionConfig()
    api: ApiConfig
    db: DbConfig


def _key_names(model: type[BaseModel]) -> frozenset[str]:
    names: set[str] = set()
    for name, info in model.model_fields.items():
        names.add(name)
        if isinstance(info.annotation, type) and issubclass(info.annotation, BaseModel):
            names |= _key_names(info.annotation)
    return frozenset(names)


_KNOWN_KEYS = _key_names(Config)


def _where(loc: tuple[int | str, ...]) -> str:
    """The error's location. An unknown key is not named: a misplaced value can land there.

    The config has no lists, so an int part (an int or bool YAML key) is an unknown key too.
    """
    text = ""
    for part in loc:
        known = isinstance(part, str) and part in _KNOWN_KEYS
        name = part if known else "<unknown key>"
        text += f".{name}" if text else str(name)
    return text or "(top level)"


def _describe(error: ValidationError) -> str:
    """Rebuild pydantic's errors from location and type only: its `msg` and `input` may echo
    a value from the file (CFG-002)."""
    return "; ".join(f"{_where(err['loc'])}: {err['type']}" for err in error.errors())


def _normalised(path: str) -> PurePosixPath:
    normal = posixpath.normpath(path)
    if normal.startswith("//"):  # normpath keeps exactly two leading slashes (POSIX)
        normal = "/" + normal.lstrip("/")
    return PurePosixPath(normal)


def check_roots(config: Config) -> None:
    """Refuse unless both roots are absolute, distinct and not nested (R-FOP-9, CFG-002).

    Pure path comparison: trailing slashes, `//` and `..` segments are normalised first,
    and nothing on disk is touched. The messages name the keys, never the paths.
    """
    source = _normalised(config.paths.source_root)
    results = _normalised(config.paths.results_root)
    if not (source.is_absolute() and results.is_absolute()):
        raise ConfigError(
            "paths.source_root and paths.results_root must both be absolute container "
            "paths (R-FOP-9)"
        )
    if source == results or source in results.parents or results in source.parents:
        raise ConfigError(
            "paths.source_root and paths.results_root must not be the same "
            "or nested in one another (R-FOP-9)"
        )


def load_config(path: str | Path | None = None) -> Config:
    """Load the config once: `path`, else `$CLASSIFIER_CONFIG`.

    The DSN comes from `$DB_DSN` only; a non-null `db.dsn` in the file is refused (CFG-001.D2).
    """
    source = path if path is not None else os.environ.get(CONFIG_ENV)
    if not source:
        raise ConfigError(f"no config file: pass a path or set {CONFIG_ENV}")
    file = Path(source)
    if not file.is_file():
        raise ConfigError(f"config file not found: {file}")
    # Each error is raised after its except block, from the location and type only, so the
    # original exception (which quotes the file's text) is not even kept as __context__.
    problem = None
    try:
        text = file.read_text(encoding="utf-8")
    except UnicodeDecodeError:  # it holds the raw bytes
        problem = f"config file is not UTF-8 text: {file}"
    except OSError:
        problem = f"config file can't be read: {file}"
    if problem is not None:
        raise ConfigError(problem)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = f" at line {mark.line + 1}" if mark is not None else ""
        problem = f"config file is not valid YAML{line}: {file}"
    if problem is not None:
        raise ConfigError(problem)
    if not isinstance(data, dict):
        raise ConfigError(f"config file is not a mapping: {file}")
    try:
        config = Config.model_validate(data)
    except ValidationError as exc:
        problem = f"invalid config file {file}: {_describe(exc)}"
    if problem is not None:
        raise ConfigError(problem)
    if config.db.dsn is not None:  # CFG-001.D2: secrets come from the environment only
        raise ConfigError(f"db.dsn must be null in the config file, set {DSN_ENV}: {file}")
    check_roots(config)
    dsn = os.environ.get(DSN_ENV)
    if not dsn:
        raise ConfigError(f"no database DSN: set {DSN_ENV}")
    config.db.dsn = dsn
    return config
