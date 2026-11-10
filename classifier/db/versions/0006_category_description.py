"""categories.description (seeded) and files.nsfw_traces (DB-006.1).

Revision ID: 0006
Revises: 0005
"""

# ruff: noqa: E501  (the seeds are DESIGN §4.3's text, verbatim)

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# DESIGN §4.3's generic descriptions, verbatim minus the bold markers (DB-006.D1).
# User-added categories stay null. Rows are matched by (axis, name).
_FORMATS: tuple[tuple[str, str], ...] = (
    (
        "photos",
        "a real-world photograph taken with a camera or phone camera, not a capture of a screen",
    ),
    (
        "game-screenshots",
        "a capture taken inside a video game: the game world, a game HUD, or a menu rendered by the game, on any platform",
    ),
    (
        "screenshots",
        "a capture of a computer or phone screen showing an app, website, chat, social media post or OS interface, even when its content is about games",
    ),
    (
        "memes",
        "a joke: an image made or shared as a joke, in any style (a captioned picture, a meme template, a funny drawing or photo, an edited image)",
    ),
    (
        "artwork",
        "a drawing, digital illustration, anime or cartoon art, concept art, 3D render or abstract graphic",
    ),
    ("documents", "a scanned or photographed document, receipt or form"),
)

_TOPICS: tuple[tuple[str, str], ...] = (
    ("videogames", "video games: game captures, game characters, game interfaces"),
    ("anime", "anime characters or manga-style art"),
    ("cartoons", "western cartoon characters or comics"),
    ("pc-equipment", "computer cases, PC hardware and components"),
    ("animals", "animals, pets"),
    ("people", "real people, faces, groups of people"),
    ("landscapes", "landscapes, beaches, cityscapes, views"),
    ("music", "music: song lists, music players, artists' albums"),
    ("tv-shows", "stills or scenes from TV shows or films"),
    ("software", "software: code editors, app screens, programs"),
    ("memes", "a joke: the image's meaning is a joke, humor or irony (its meaning, not its form)"),
    ("documents", "documents, receipts, forms, lists of text, as its subject"),
)

# Null, or non-blank, at most 200 characters and no control character (line breaks included):
# the CLI's rule. A NUL can't be stored in text, so the class starts at \x01.
_RULE = (
    "description is null or (description ~ '[^[:space:]]' and char_length(description) <= 200 "
    "and description !~ '[\\x01-\\x1f\\x7f]')"
)


def upgrade() -> None:
    op.add_column("categories", sa.Column("description", sa.Text(), nullable=True))
    op.create_check_constraint("categories_description", "categories", _RULE)
    categories = sa.table(
        "categories",
        sa.column("axis", sa.Text),
        sa.column("name", sa.Text),
        sa.column("description", sa.Text),
    )
    for axis, seeds in (("format", _FORMATS), ("topic", _TOPICS)):
        for name, description in seeds:
            op.execute(
                categories.update()
                .where(categories.c.axis == axis, categories.c.name == name)
                .values(description=description)
            )
    # CLS-007.2 writes it; null = not rated (an older row).
    op.add_column("files", sa.Column("nsfw_traces", sa.Boolean(), nullable=True))


def downgrade() -> None:
    # Development tooling (DB-006.D2): a plain drop. The values live only in a local database.
    op.drop_column("files", "nsfw_traces")
    op.drop_constraint("categories_description", "categories", type_="check")
    op.drop_column("categories", "description")
