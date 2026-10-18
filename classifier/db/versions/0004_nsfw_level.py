"""Add files.nsfw_level (DB-004.1).

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # CLS-004.D3: the VLM's NSFW level, stored so a changed `nsfw.min_level` can re-file without
    # re-running the model. Null until classified; no backfill (DB-004.D1). `nsfw_score` stays.
    op.add_column("files", sa.Column("nsfw_level", sa.Text))
    op.create_check_constraint(
        "files_nsfw_level",
        "files",
        "nsfw_level in ('safe', 'suggestive', 'nudity', 'explicit')",
    )


def downgrade() -> None:
    op.drop_constraint("files_nsfw_level", "files", type_="check")
    op.drop_column("files", "nsfw_level")
