"""Create the pgvector extension, the file_status enum and the files ledger (DB-001.1).

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = (
    "queued", "sanitized", "classified", "captioned", "resolved", "named",
    "proposed", "filed", "skipped", "error", "deleted",
)  # fmt: skip

file_status = postgresql.ENUM(*STATUSES, name="file_status", create_type=False)


def upgrade() -> None:
    op.execute("create extension if not exists vector")
    file_status.create(op.get_bind(), checkfirst=False)
    op.create_table(
        "files",
        sa.Column("source_hash", sa.String(64), primary_key=True),
        sa.Column("short_hash", sa.String(8), nullable=False),
        sa.Column("source_path", sa.Text, nullable=False),
        sa.Column(
            "duplicate_paths", postgresql.ARRAY(sa.Text), nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("source_mtime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ext", sa.String(16), nullable=False),
        sa.Column("status", file_status, nullable=False, server_default="queued"),
        sa.Column("needs_review", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("branch", sa.String(16)),
        sa.Column("nsfw_score", sa.Float),
        sa.Column("animated", sa.Boolean),
        sa.Column("format", sa.Text),
        sa.Column("topic", sa.Text),
        sa.Column("format_scores", postgresql.JSONB),
        sa.Column("topic_scores", postgresql.JSONB),
        sa.Column("caption", postgresql.JSONB),
        sa.Column("prompt_version", sa.Text),
        sa.Column("reference_id", sa.BigInteger),
        sa.Column("template", sa.Text),
        sa.Column("proposed_path", sa.Text),
        sa.Column("output_path", sa.Text),
        sa.Column("output_hash", sa.String(64)),
        sa.Column("review_reason", sa.Text),
        sa.Column("has_sensitive_text", sa.Boolean),
        sa.Column("error", sa.Text),
        sa.CheckConstraint(
            "review_reason in ('unsorted', 'ambiguous_reference')", name="files_review_reason"
        ),
    )  # fmt: skip
    op.create_index("ix_files_status", "files", ["status"])
    op.create_index("ix_files_short_hash", "files", ["short_hash"])


def downgrade() -> None:
    # The vector extension stays: other tables will use it and it is database-wide.
    op.drop_table("files")
    file_status.drop(op.get_bind(), checkfirst=False)
