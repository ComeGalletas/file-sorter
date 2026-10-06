"""SQLAlchemy 2.0 models mirroring the Alembic migrations (DESIGN.md §5)."""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    Index,
    String,
    Text,
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
REVIEW_REASONS = ("unsorted", "ambiguous_reference")


class File(Base):
    """One ledger row per distinct source hash (R-ING-1)."""

    __tablename__ = "files"
    __table_args__ = (
        CheckConstraint(
            "review_reason in ('unsorted', 'ambiguous_reference')", name="files_review_reason"
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
