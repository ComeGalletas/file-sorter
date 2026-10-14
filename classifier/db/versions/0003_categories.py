"""Add categories, category_prompts and files.image_vec (DB-003.1).

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # CLS-002.D10: the SigLIP embedding of the sanitized copy; no ANN index until M6.
    op.add_column("files", sa.Column("image_vec", Vector(1152)))
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("axis", sa.String(8), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("folder", sa.Text, nullable=False),
        sa.Column("min_score", sa.REAL),  # real; null = the axis default (DB-003.D3)
        sa.Column("branch", sa.String(8), nullable=False, server_default="any"),
        # DB-003.D1: files.format/topic hold names, so nothing else references this table.
        sa.Column("parent_id", sa.Integer,
                  sa.ForeignKey("categories.id", name="fk_categories_parent_id_categories")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("axis in ('format', 'topic')", name="categories_axis"),
        sa.CheckConstraint("branch in ('any', 'safe', 'nsfw')", name="categories_branch"),
        sa.UniqueConstraint("axis", "name", name="uq_categories_axis_name"),
    )  # fmt: skip
    # Siblings share a folder name only if they differ in case-insensitive folder (FOP-002.D4).
    op.execute(
        "create unique index uq_categories_axis_parent_folder on categories "
        "(axis, coalesce(parent_id, 0), lower(folder))"
    )
    op.create_table(
        "category_prompts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("category_id", sa.Integer,
                  sa.ForeignKey("categories.id", name="fk_category_prompts_category_id_categories",
                                ondelete="CASCADE"),
                  nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("prompt", sa.Text, nullable=False),
        sa.UniqueConstraint("category_id", "position",
                            name="uq_category_prompts_category_position"),
    )  # fmt: skip


def downgrade() -> None:
    op.drop_table("category_prompts")
    op.drop_table("categories")  # its indexes go with it
    op.drop_column("files", "image_vec")
