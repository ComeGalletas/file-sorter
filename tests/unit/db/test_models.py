"""DB-001.1.2, DB-002.1: the models carry the §5 key columns, the enum and sanitize_log."""

from classifier.db.models import REVIEW_REASONS, File, FileStatus, SanitizeLog

KEY_COLUMNS = {
    "source_hash", "short_hash", "source_path", "duplicate_paths", "source_mtime", "ext",
    "status", "branch", "nsfw_score", "animated", "format", "topic", "format_scores",
    "topic_scores", "caption", "prompt_version", "reference_id", "template", "proposed_path",
    "output_path", "output_hash", "needs_review", "review_reason", "has_sensitive_text",
    "error", "created_at", "updated_at", "original_sanitized",
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
    assert REVIEW_REASONS == ("unsorted", "ambiguous_reference")


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
