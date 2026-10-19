"""SQLAlchemy 2.0 models mirroring the Alembic migrations (DESIGN.md §5).

Check constraints are mirrored for the reader; autogenerate doesn't compare them, so the
db-tier migration tests check them against the database.
"""

import enum
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class FileStatus(enum.Enum):
    """The only pipeline checkpoint (DESIGN §5, P-4). Order is the pipeline order."""

    queued = "queued"
    sanitized = "sanitized"
    classified = "classified"
    captioned = "captioned"
    resolved = "resolved"
    named = "named"
    proposed = "proposed"
    filed = "filed"
    skipped = "skipped"
    error = "error"
    deleted = "deleted"


# "Unsorted" is a format, not a status: review is needs_review + review_reason (§5).
REVIEW_REASONS = ("unsorted", "ambiguous_reference", "nsfw_disagreement")


class File(Base):
    """One ledger row per distinct source hash (R-ING-1)."""

    __tablename__ = "files"
    __table_args__ = (
        CheckConstraint(
            "review_reason in ('unsorted', 'ambiguous_reference', 'nsfw_disagreement')",
            name="files_review_reason",
        ),
        CheckConstraint(
            "nsfw_level in ('safe', 'suggestive', 'nudity', 'explicit')", name="files_nsfw_level"
        ),
        Index("ix_files_status", "status"),
        Index("ix_files_short_hash", "short_hash"),
    )

    # Filled at ingest.
    source_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    short_hash: Mapped[str] = mapped_column(String(8))
    # DOC-004.D3 / ING-001.D2: the container path (/source/...) is allowed here, nowhere else.
    source_path: Mapped[str] = mapped_column(Text)
    duplicate_paths: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )  # R-ING-7
    source_mtime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ext: Mapped[str] = mapped_column(String(16))
    status: Mapped[FileStatus] = mapped_column(
        Enum(FileStatus, name="file_status", values_callable=lambda e: [m.value for m in e]),
        server_default=FileStatus.queued.value,
    )
    needs_review: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # ORM-level onupdate: only updates made through SQLAlchemy refresh it; raw SQL must set it.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Filled by later milestones, nullable until then.
    branch: Mapped[str | None] = mapped_column(String(16))
    nsfw_score: Mapped[float | None] = mapped_column(Float)
    animated: Mapped[bool | None] = mapped_column(Boolean)
    format: Mapped[str | None] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(Text)  # null = no topic, not "Unsorted"
    format_scores: Mapped[Any | None] = mapped_column(JSONB)  # top-k
    topic_scores: Mapped[Any | None] = mapped_column(JSONB)  # top-k
    caption: Mapped[Any | None] = mapped_column(JSONB)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    reference_id: Mapped[int | None] = mapped_column(BigInteger)  # no FK until `references`
    template: Mapped[str | None] = mapped_column(Text)
    proposed_path: Mapped[str | None] = mapped_column(Text)
    output_path: Mapped[str | None] = mapped_column(Text)
    output_hash: Mapped[str | None] = mapped_column(String(64))
    review_reason: Mapped[str | None] = mapped_column(Text)
    has_sensitive_text: Mapped[bool | None] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text)
    # SAN-001.D8: the sanitized stem; models get this, never source_path.
    original_sanitized: Mapped[str | None] = mapped_column(Text)
    # CLS-002.D10: the SigLIP image embedding of the sanitized copy.
    image_vec: Mapped[Any | None] = mapped_column(Vector(1152))
    # CLS-004.D3: the VLM's NSFW level; null until classified (DB-004.D1, no backfill).
    nsfw_level: Mapped[str | None] = mapped_column(Text)


class SanitizeLog(Base):
    """One row per redaction (R-SAN-6). Original values are never stored, only hashed."""

    __tablename__ = "sanitize_log"
    __table_args__ = (
        # SAN-001.1's RuleId; SAN-001.D12's `exif-strip-all` fits it.
        CheckConstraint("rule_id ~ '^[a-z0-9][a-z0-9_-]{0,63}$'", name="sanitize_log_rule_id"),
        # DB-002.D1; the tag part mirrors SAN-001.1's TagName.
        CheckConstraint(
            "field in ('filename', 'path_segment') "
            "or field ~ '^exif:[A-Za-z][A-Za-z0-9_:-]{0,63}$'",
            name="sanitize_log_field",
        ),
        # SAN-001.D5: HMAC-SHA256 keyed with SANITIZE_LOG_KEY, lowercase hex.
        CheckConstraint("before_hash ~ '^[0-9a-f]{64}$'", name="sanitize_log_before_hash"),
        Index("ix_sanitize_log_source_hash", "source_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # DB-002.D2: no cascade; a files row is never deleted (`deleted` is a status).
    source_hash: Mapped[str] = mapped_column(
        String(64), ForeignKey("files.source_hash", name="fk_sanitize_log_source_hash_files")
    )
    rule_id: Mapped[str] = mapped_column(String(64))
    field: Mapped[str] = mapped_column(String(70))
    before_hash: Mapped[str] = mapped_column(String(64))
    after_value: Mapped[str | None] = mapped_column(Text)  # the replacement token only
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Category(Base):
    """One category on one axis (DESIGN §5, R-CLS-0). `files.format`/`topic` hold names, no FK.

    `min_score` is a SigLIP-era column: kept, but unread on the VLM path (CLS-004.D7, DOC-009.D3).
    """

    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("axis in ('format', 'topic')", name="categories_axis"),
        CheckConstraint("branch in ('any', 'safe', 'nsfw')", name="categories_branch"),
        UniqueConstraint("axis", "name", name="uq_categories_axis_name"),
        # FOP-002.D4: siblings differ by case-insensitive folder; top-level counts as parent 0.
        Index(
            "uq_categories_axis_parent_folder",
            "axis",
            text("coalesce(parent_id, 0)"),
            text("lower(folder)"),
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    axis: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(Text)
    folder: Mapped[str] = mapped_column(Text)
    min_score: Mapped[float | None] = mapped_column(REAL)  # null = axis default (DB-003.D3)
    branch: Mapped[str] = mapped_column(String(8), server_default="any")  # R-CLS-6
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", name="fk_categories_parent_id_categories")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        # Names and folders can be user-added, so they stay out of logs and tracebacks.
        return f"Category(id={self.id!r}, axis={self.axis!r})"


class CategoryPrompt(Base):
    """One SigLIP prompt of a category; `position` follows the seed's table order (DB-003.D4).

    The table is kept but unread on the VLM path (CLS-004.D7, DOC-009.D3).
    """

    __tablename__ = "category_prompts"
    __table_args__ = (
        UniqueConstraint("category_id", "position", name="uq_category_prompts_category_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey(
            "categories.id", name="fk_category_prompts_category_id_categories", ondelete="CASCADE"
        )
    )
    position: Mapped[int] = mapped_column(Integer)
    prompt: Mapped[str] = mapped_column(Text)  # a hand-tuned value (CLAUDE.md §1.7)

    def __repr__(self) -> str:
        return f"CategoryPrompt(category_id={self.category_id!r}, position={self.position!r})"
