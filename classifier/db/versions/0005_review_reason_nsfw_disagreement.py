"""Allow files.review_reason = 'nsfw_disagreement' (DB-005.1).

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REFUSED = "Downgrade refused: rows with review_reason nsfw_disagreement exist."


def upgrade() -> None:
    # CLS-004.D5, D13: the NSFW cross-check flags a file for review with this reason.
    op.drop_constraint("files_review_reason", "files", type_="check")
    op.create_check_constraint(
        "files_review_reason",
        "files",
        "review_reason in ('unsorted', 'ambiguous_reference', 'nsfw_disagreement')",
    )


def downgrade() -> None:
    # DB-005.D1: never rewrite a row's review_reason; refuse while one holds the new value.
    held = (
        op.get_bind()
        .execute(
            sa.text("select exists (select 1 from files where review_reason = 'nsfw_disagreement')")
        )
        .scalar()
    )
    if held:
        raise RuntimeError(_REFUSED)
    op.drop_constraint("files_review_reason", "files", type_="check")
    op.create_check_constraint(
        "files_review_reason", "files", "review_reason in ('unsorted', 'ambiguous_reference')"
    )
