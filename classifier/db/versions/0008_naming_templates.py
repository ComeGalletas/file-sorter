"""Add naming_templates and template_assignments (DB-009.1; DESIGN §5, R-NAME-1).

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen here, not imported, so a later edit to models.py or classifier/naming/ can't change
# this revision. NAME-001.D1 (descriptive) and NAME-001.D2 (the other five), in R-NAME-1's order.
BUILTINS: tuple[tuple[str, str], ...] = (
    ("descriptive", "{subject}_{detail|max=40}_{seq:3}"),
    ("reference", "{reference|or={subject}}_{seq:3}"),
    ("dated", "{date}_{subject}_{seq:3}"),
    ("category-seq", "{category}_{seq:4}"),
    ("keep-original", "{original_sanitized}"),
    ("hash", "{short_hash}"),
)
DEFAULT_TEMPLATE = "descriptive"  # R-NAME-1's default, seeded as the global row (DB-009.D1)

NAME_CHECK = "name ~ '^[a-z][a-z0-9-]{0,31}$'"
# One line of 1-200 characters, not blank: no C0 control or DEL (so no \n, \r or tab), and no
# Unicode line break (NEL, LS, PS).
TEMPLATE_CHECK = (
    "char_length(template) between 1 and 200 and template ~ '[^[:space:]]' "
    "and template !~ '[\\x01-\\x1f\\x7f\\u0085\\u2028\\u2029]'"
)


def upgrade() -> None:
    op.create_table(
        "naming_templates",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("template", sa.Text, nullable=False),
        # DB-009.D2: not enforced in the schema; CLI-010 refuses changes to a built-in.
        sa.Column("builtin", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(NAME_CHECK, name="naming_templates_name"),
        sa.CheckConstraint(TEMPLATE_CHECK, name="naming_templates_template"),
        sa.UniqueConstraint("name", name="uq_naming_templates_name"),
    )  # fmt: skip
    op.create_table(
        "template_assignments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("category_id", sa.Integer,
                  sa.ForeignKey("categories.id",
                                name="fk_template_assignments_category_id_categories",
                                ondelete="CASCADE")),
        # An assigned template can't be deleted.
        sa.Column("template_id", sa.Integer,
                  sa.ForeignKey("naming_templates.id",
                                name="fk_template_assignments_template_id_naming_templates",
                                ondelete="RESTRICT"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("scope in ('global', 'category')", name="template_assignments_scope"),
        sa.CheckConstraint("(scope = 'global') = (category_id is null)",
                           name="template_assignments_scope_category"),
        # At most one assignment per category.
        sa.UniqueConstraint("category_id", name="uq_template_assignments_category_id"),
    )  # fmt: skip
    # At most one global assignment.
    op.create_index(
        "uq_template_assignments_global",
        "template_assignments",
        ["scope"],
        unique=True,
        postgresql_where=sa.text("scope = 'global'"),
    )

    bind = op.get_bind()
    for name, template in BUILTINS:
        bind.execute(
            sa.text(
                "insert into naming_templates (name, template, builtin) "
                "values (:name, :template, true)"
            ),
            {"name": name, "template": template},
        )
    bind.execute(
        sa.text(
            "insert into template_assignments (scope, template_id) "
            "select 'global', id from naming_templates where name = :name"
        ),
        {"name": DEFAULT_TEMPLATE},
    )


def downgrade() -> None:
    op.drop_table("template_assignments")  # its indexes go with it
    op.drop_table("naming_templates")
