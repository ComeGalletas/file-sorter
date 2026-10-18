"""DB-001.1.2, DB-002.1: the models carry the §5 key columns, the enum and sanitize_log."""

from classifier.db.models import (
    REVIEW_REASONS,
    Category,
    CategoryPrompt,
    File,
    FileStatus,
    SanitizeLog,
)

KEY_COLUMNS = {
    "source_hash", "short_hash", "source_path", "duplicate_paths", "source_mtime", "ext",
    "status", "branch", "nsfw_score", "animated", "format", "topic", "format_scores",
    "topic_scores", "caption", "prompt_version", "reference_id", "template", "proposed_path",
    "output_path", "output_hash", "needs_review", "review_reason", "has_sensitive_text",
    "error", "created_at", "updated_at", "original_sanitized", "image_vec",
    "nsfw_level",
}  # fmt: skip
FILLED_AT_INGEST = {
    "source_hash", "short_hash", "source_path", "duplicate_paths", "source_mtime", "ext",
    "status", "needs_review", "created_at", "updated_at",
}  # fmt: skip


def test_status_enum_matches_design() -> None:
    assert [s.value for s in FileStatus] == [
        "queued", "sanitized", "classified", "captioned", "resolved", "named",
        "proposed", "filed", "skipped", "error", "deleted",
    ]  # fmt: skip


def test_columns_and_primary_key() -> None:
    table = File.__table__
    assert {c.name for c in table.columns} == KEY_COLUMNS
    assert [c.name for c in table.primary_key] == ["source_hash"]


def test_only_ingest_columns_are_required() -> None:
    required = {c.name for c in File.__table__.columns if not c.nullable}
    assert required == FILLED_AT_INGEST


def test_updated_at_refreshes_through_the_orm() -> None:
    assert File.__table__.c.updated_at.onupdate is not None


def test_review_reasons() -> None:
    assert REVIEW_REASONS == ("unsorted", "ambiguous_reference", "nsfw_disagreement")


def test_sanitize_log_columns_and_foreign_key() -> None:
    """DB-002.1: SanitizeLog mirrors 0002; only after_value is nullable; FK has no cascade."""
    table = SanitizeLog.__table__
    assert {c.name for c in table.columns} == {
        "id", "source_hash", "rule_id", "field", "before_hash", "after_value", "created_at",
    }  # fmt: skip
    assert {c.name for c in table.columns if c.nullable} == {"after_value"}
    (fk,) = table.foreign_keys
    assert fk.target_fullname == "files.source_hash"
    assert fk.ondelete is None  # DB-002.D2
    assert {i.name for i in table.indexes} == {"ix_sanitize_log_source_hash"}


def test_category_tables_mirror_0003() -> None:
    """DB-003.1: columns, nullability and the cascade, as migration 0003 creates them."""
    cats = Category.__table__
    assert {c.name: c.nullable for c in cats.columns} == {
        "id": False, "axis": False, "name": False, "folder": False, "min_score": True,
        "branch": False, "parent_id": True, "created_at": False,
    }  # fmt: skip
    prompts = CategoryPrompt.__table__
    assert {c.name for c in prompts.columns} == {"id", "category_id", "position", "prompt"}
    (fk,) = prompts.c.category_id.foreign_keys
    assert fk.ondelete == "CASCADE"
    assert File.__table__.c.image_vec.nullable is True


def test_nsfw_level_mirrors_0004() -> None:
    """DB-004.1: a nullable text column, checked against the four levels."""
    column = File.__table__.c.nsfw_level
    assert column.nullable is True
    assert column.type.python_type is str
    (check,) = [
        c for c in File.__table__.constraints if getattr(c, "name", None) == "files_nsfw_level"
    ]
    assert str(check.sqltext) == "nsfw_level in ('safe', 'suggestive', 'nudity', 'explicit')"


def test_category_reprs_hide_names_folders_and_prompts() -> None:
    """DB-003.1 (lead ruling on checklist item 4): repr and str carry only ids and the axis."""
    cat = Category(
        id=7, axis="topic", name="secret-qorvex-name", folder="Secret Zhyndel Folder", parent_id=3
    )
    prompt = CategoryPrompt(category_id=7, position=2, prompt="a secret vlintar prompt")
    for obj in (cat, prompt):
        for text in (repr(obj), str(obj), f"{obj!r}", f"{obj}"):
            lowered = text.lower()
            assert "secret" not in lowered
            assert "qorvex" not in lowered and "zhyndel" not in lowered
            assert "vlintar" not in lowered
    assert repr(cat) == "Category(id=7, axis='topic')"
    assert repr(prompt) == "CategoryPrompt(category_id=7, position=2)"
