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

# Frozen here, not imported, so a later edit to models.py can't change this revision.
RUN_NODES = ("ingest", "sanitize", "classify", "caption", "retrieve", "name", "fileops")
RUN_ERRORS = (
    "sanitize_config", "work_dir", "classify_config", "classify_rules",
    "vision", "ollama", "database", "interrupted", "internal",
)  # fmt: skip


def _quoted(words: tuple[str, ...]) -> str:
    return ", ".join(f"'{w}'" for w in words)


def _no_match(path: str) -> str:
    # The jsonpath errors on a non-object top level, so it runs only on an object;
    # runs_counts_object refuses the rest (CHECKs run in name order).
    return (
        "case when jsonb_typeof(counts) = 'object' "
        f"then not jsonb_path_exists(counts, '{path}') else true end"
    )


# DB-007.D3: {node: {field: number}}. The number check is strict: lax mode would unwrap
# an array value and pass it.
COUNTS_CHECKS: tuple[tuple[str, str], ...] = (
    (
        "runs_counts_nodes",
        _no_match(f'$.keyvalue() ? (!(@.key like_regex "^({"|".join(RUN_NODES)})$"))'),
    ),
    ("runs_counts_node_objects", _no_match('$.* ? (@.type() != "object")')),
    (
        "runs_counts_fields",
        _no_match(
            '$.* ? (@.type() == "object").keyvalue() ? (!(@.key like_regex "^[a-z][a-z_]{0,31}$"))'
        ),
    ),
    (
        "runs_counts_numbers",
        _no_match('strict $.* ? (@.type() == "object").* ? (@.type() != "number")'),
    ),
)


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
        # DB-007.D3: counts is {node: {field: number}}, so no path, name or text fits.
        *(sa.CheckConstraint(sql, name=name) for name, sql in COUNTS_CHECKS),
        # DB-007.D3: a closed set of fixed codes.
        sa.CheckConstraint(f"error in ({_quoted(RUN_ERRORS)})", name="runs_error_code"),
        # DB-007.D2: the state, finished_at and error agree.
        sa.CheckConstraint("(state = 'running') = (finished_at is null)",
                           name="runs_finished_iff_done"),
        sa.CheckConstraint("error is null or state = 'failed'", name="runs_error_only_failed"),
        sa.CheckConstraint("finished_at is null or finished_at >= started_at",
                           name="runs_finished_after_start"),
    )  # fmt: skip


def downgrade() -> None:
    op.drop_table("runs")
