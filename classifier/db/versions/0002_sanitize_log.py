"""Add the sanitize_log table and files.original_sanitized (DB-002.1).

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SAN-001.D8: the sanitized stem, the only stored form of the file's name for models.
    op.add_column("files", sa.Column("original_sanitized", sa.Text))
    op.create_table(
        "sanitize_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        # DB-002.D2: no cascade; a files row is never deleted (`deleted` is a status).
        sa.Column("source_hash", sa.String(64),
                  sa.ForeignKey("files.source_hash", name="fk_sanitize_log_source_hash_files"),
                  nullable=False),
        sa.Column("rule_id", sa.String(64), nullable=False),
        sa.Column("field", sa.String(70), nullable=False),
        sa.Column("before_hash", sa.String(64), nullable=False),
        sa.Column("after_value", sa.Text),  # the replacement token only, never an original
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        # SAN-001.1's RuleId; SAN-001.D12's `exif-strip-all` fits it.
        sa.CheckConstraint("rule_id ~ '^[a-z0-9][a-z0-9_-]{0,63}$'",
                           name="sanitize_log_rule_id"),
        # DB-002.D1; the tag part mirrors SAN-001.1's TagName.
        sa.CheckConstraint(
            "field in ('filename', 'path_segment') "
            "or field ~ '^exif:[A-Za-z][A-Za-z0-9_:-]{0,63}$'",
            name="sanitize_log_field",
        ),
        # SAN-001.D5: HMAC-SHA256, lowercase hex.
        sa.CheckConstraint("before_hash ~ '^[0-9a-f]{64}$'", name="sanitize_log_before_hash"),
    )  # fmt: skip
    op.create_index("ix_sanitize_log_source_hash", "sanitize_log", ["source_hash"])


def downgrade() -> None:
    op.drop_table("sanitize_log")
    op.drop_column("files", "original_sanitized")
