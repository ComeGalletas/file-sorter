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


# DB-003.D4: DESIGN §4.3 verbatim, in table order. Prompts are hand-tuned values (CLAUDE.md
# §1.7): never edit them here; later changes are seed-data migrations after 0003 (CLS-003.D2).
# Every min_score stays null (DB-003.D3). `unsorted` has no prompts (DB-003.D2).
SEED: list[tuple[str, str, str, list[str]]] = [
    ("format", "photos", "Photos",
     ["a photo taken with a camera", "a portrait", "a photo of an object"]),
    ("format", "game-screenshots", "Game Screenshots",
     ["a screenshot taken inside a video game", "a video game scene with a game HUD",
      "a video game character in a 3D game world"]),
    ("format", "screenshots", "Screenshots",
     ["a screenshot of a phone", "a screenshot of a desktop app or website",
      "a cropped screen capture of part of a window",
      "a snippet of a webpage, chat or app"]),
    ("format", "memes", "Memes", ["a meme with text", "a reaction image"]),
    ("format", "artwork", "Artwork",
     ["a digital illustration", "a drawing", "concept art", "an animated abstract graphic"]),
    ("format", "documents", "Documents", ["a scanned document", "a receipt", "a form"]),
    ("format", "unsorted", "Unsorted", []),
    ("topic", "videogames", "Videogames",
     ["a video game screenshot", "a video game character", "a game user interface"]),
    ("topic", "anime", "Anime", ["an anime character", "manga style art"]),
    ("topic", "cartoons", "Cartoons", ["a western cartoon character", "a comic drawing"]),
    ("topic", "pc-equipment", "PC Equipment", ["a computer case", "PC hardware components"]),
    ("topic", "animals", "Animals", ["a photo of a cat", "a photo of a dog", "an animal"]),
    ("topic", "people", "People", ["a photo of people", "a person's face"]),
    ("topic", "landscapes", "Landscapes",
     ["a landscape", "a beach", "a cityscape", "a view from a high floor"]),
    ("topic", "music", "Music", ["a list of song names", "a music player"]),
    ("topic", "tv-shows", "TV Shows", ["a still from a TV show"]),
    ("topic", "software", "Software", ["a code editor", "a mobile app screen"]),
    ("topic", "memes", "Memes",
     ["a joke or humorous image", "an image with an ironic meaning"]),
    ("topic", "documents", "Documents",
     ["a document", "a receipt", "a form", "a list of text"]),
]  # fmt: skip

INSERT_CATEGORY = sa.text(
    "insert into categories (axis, name, folder) values (:axis, :name, :folder) returning id"
)
INSERT_PROMPT = sa.text(
    "insert into category_prompts (category_id, position, prompt) "
    "values (:category_id, :position, :prompt)"
)


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

    bind = op.get_bind()
    for axis, name, folder, prompts in SEED:
        category_id = bind.execute(
            INSERT_CATEGORY, {"axis": axis, "name": name, "folder": folder}
        ).scalar_one()
        for position, prompt in enumerate(prompts):
            bind.execute(
                INSERT_PROMPT,
                {"category_id": category_id, "position": position, "prompt": prompt},
            )


def downgrade() -> None:
    op.drop_table("category_prompts")
    op.drop_table("categories")  # its indexes go with it
    op.drop_column("files", "image_vec")
