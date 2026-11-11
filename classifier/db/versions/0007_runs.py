"""Add the runs table (DB-007.1; R-API-6, C-11, DESIGN §5).

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),  # null while running
        # Per-node counts, e.g. {"ingest": 3}; numbers only, never a path or a name.
        sa.Column("counts", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text),  # a fixed error code, or null
        sa.CheckConstraint("kind in ('dry_run', 'sort', 'watch', 'reclassify')", name="runs_kind"),
        sa.CheckConstraint("state in ('running', 'finished', 'failed')", name="runs_state"),
        sa.CheckConstraint("jsonb_typeof(counts) = 'object'", name="runs_counts_object"),
        # DB-007.D2: a fixed code only, so no path, name or free text fits.
        sa.CheckConstraint("error ~ '^[a-z][a-z0-9_]{0,63}$'", name="runs_error_code"),
        # DB-007.D2: the state, finished_at and error agree.
        sa.CheckConstraint("(state = 'running') = (finished_at is null)",
                           name="runs_finished_iff_done"),
        sa.CheckConstraint("error is null or state = 'failed'", name="runs_error_only_failed"),
        sa.CheckConstraint("finished_at is null or finished_at >= started_at",
                           name="runs_finished_after_start"),
    )  # fmt: skip


def downgrade() -> None:
    op.drop_table("runs")
