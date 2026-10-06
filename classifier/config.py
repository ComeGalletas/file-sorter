"""Typed configuration (DESIGN.md §6, CFG-001, R-CFG-1).

`config.yaml` holds container paths only. Every section is a strict model: an unknown key
is an error. Values that are not decided yet stay `None`: `models.vlm_nsfw` (Q-1) and the
`classify.*.default_min_score` values (calibrated in M3).
"""

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

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
    dsn: str | None = None  # filled from DB_DSN by load_config


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


def load_config(path: str | Path | None = None) -> Config:
    """Load the config once: `path`, else `$CLASSIFIER_CONFIG`; the DSN comes from `$DB_DSN`."""
    source = path if path is not None else os.environ.get(CONFIG_ENV)
    if not source:
        raise ConfigError(f"no config file: pass a path or set {CONFIG_ENV}")
    file = Path(source)
    if not file.is_file():
        raise ConfigError(f"config file not found: {file}")
    data = yaml.safe_load(file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"config file is not a mapping: {file}")
    config = Config.model_validate(data)
    dsn = config.db.dsn or os.environ.get(DSN_ENV)
    if not dsn:
        raise ConfigError(f"no database DSN: set {DSN_ENV}")
    config.db.dsn = dsn
    return config
