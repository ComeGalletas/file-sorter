"""SAN-001.4: the `sanitize` graph node (the acceptance test).

Ingest then sanitize, through `run`, on synthetic images generated here under `tmp_path`,
seeded with made-up tag values through exiftool and given made-up names in made-up folders.
The rules file is synthetic too, never the local sanitize.yaml. `run` commits
(PIPE-001.D3), so the module has its own migrated schema (TST-003.1).
"""

import hmac
import logging
import os
import subprocess
from hashlib import sha256
from pathlib import Path

import psycopg
import pytest
import yaml
from PIL import Image, UnidentifiedImageError

from classifier.config import Config
from classifier.fileops.copy_move import WorkingCopy
from classifier.graph import sanitize as node
from classifier.graph.nodes import REGISTRY, NodeContext
from classifier.graph.run import run
from classifier.graph.sanitize import REASONS, SanitizeResult, WorkDirError
from classifier.sanitize.exif import MetadataStripError, is_allowed, read_tags
from classifier.sanitize.rules import (
    LOG_KEY_ENV,
    Redaction,
    SanitizeConfigError,
    load_rules,
)

REAL_CONFIG = Path(__file__).resolve().parents[2] / "config.yaml"
INGEST_ONLY = tuple(n for n in REGISTRY if n.name == "ingest")

pytestmark = pytest.mark.usefixtures("empty_ledger")  # TST-003.1

# Made-up values. REDACTED is matched by the literal rule and must never surface anywhere
# but source_path. RESIDUE is a part of a name no rule matches: it may stay in the
# sanitized stem, but never in a log, an error or a sanitize_log row. TAG_SECRET is a
# seeded tag value: only ever hashed. EXC_SECRET rides in every injected exception.
REDACTED = "Zorvane Quillby"
RESIDUE = "Pemberquill"
TAG_SECRET = "Ostrela Freight Artist"
EXC_SECRET = "Vexmarrow-exception-secret"
NAMED_DIR = f"{REDACTED} trip"
NAMED_FILE = f"Zorvane_Quillby_beach_{RESIDUE}.jpg"
RULES = {
    "exif": {"mode": "strip_all", "keep": ["Orientation", "DateTimeOriginal"]},
    "rules": [
        {"id": "test-person", "type": "literal", "values": [REDACTED], "replace": "[PERSON]"},
        {"id": "test-email", "type": "regex", "pattern": r"\w+@\w+\.\w+", "replace": "[EMAIL]"},
    ],
}
NEVER = (REDACTED, "Zorvane", "Quillby", TAG_SECRET, EXC_SECRET, "12.3456")


# --- setup -------------------------------------------------------------------------------


def _image(path: Path, fmt: str, color: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (24, 16), (color, 120, 30))
    image.save(path, fmt)
    return path


def _seed(path: Path) -> None:
    done = subprocess.run(
        ["exiftool", "-m", "-q", "-q", "-overwrite_original", f"-Artist={TAG_SECRET}",
         "-Software=Thrennick Labs Editor", "-GPSLatitude=12.3456", "-GPSLatitudeRef=N",
         "-XMP-dc:Creator=Mirelda Toskan", "-Orientation#=6", str(path)],
        capture_output=True,
        check=False,
    )  # fmt: skip
    assert done.returncode == 0, "seeding the synthetic image failed"


def _populate(source: Path) -> dict[str, Path]:
    """Three images: a named one in a named folder, a plain one, one in a sub-folder."""
    named = _image(source / NAMED_DIR / NAMED_FILE, "JPEG", 10)
    _seed(named)
    plain = _image(source / "plain.png", "PNG", 90)
    nested = _image(source / "sub" / "photo.tif", "TIFF", 200)
    _seed(nested)
    return {"named": named, "plain": plain, "nested": nested}


@pytest.fixture
def source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    return root


@pytest.fixture
def results(tmp_path: Path) -> Path:
    return tmp_path / "results"


def _config(tmp_path: Path, source: Path, results: Path, dsn: str, **sanitizer: object) -> Config:
    data = yaml.safe_load(REAL_CONFIG.read_text(encoding="utf-8"))
    data["paths"] = {"source_root": str(source), "results_root": str(results)}
    data["db"] = {"dsn": dsn}
    rules = tmp_path / "rules.yaml"
    if not rules.exists():
        rules.write_text(yaml.safe_dump(RULES), encoding="utf-8")
    data["sanitizer"]["rules_file"] = str(rules)
    data["sanitizer"].update(sanitizer)
    return Config.model_validate(data)


@pytest.fixture
def config(tmp_path: Path, source: Path, results: Path, schema_dsn: str) -> Config:
    return _config(tmp_path, source, results, schema_dsn)


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _query(dsn: str, sql: str, params: tuple[object, ...] = ()) -> list[tuple]:
    with psycopg.connect(dsn) as conn:
        return conn.execute(sql, params).fetchall()


def _files(dsn: str) -> dict[str, tuple]:
    rows = _query(dsn, "select source_hash, status, error, original_sanitized from files")
    return {row[0]: row[1:] for row in rows}


def _log(dsn: str, source_hash: str | None = None) -> list[tuple]:
    sql = "select id, source_hash, rule_id, field, before_hash, after_value from sanitize_log"
    if source_hash is None:
        return _query(dsn, sql + " order by id")
    return _query(dsn, sql + " where source_hash = %s order by id", (source_hash,))


def _tree(root: Path) -> list[tuple[str, int, int]]:
    """Every entry with its size and mtime: the source must not change at all (P-1)."""
    return sorted(
        (str(p.relative_to(root)), p.lstat().st_size, p.lstat().st_mtime_ns)
        for p in root.rglob("*")
    )


def _hmac(value: str) -> str:
    key = os.environ[LOG_KEY_ENV].encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), sha256).hexdigest()


def _assert_clean(*texts: object, allow_residue: bool = False) -> None:
    joined = "\n".join(str(text) for text in texts)
    for secret in (*NEVER, *(() if allow_residue else (RESIDUE,))):
        assert secret not in joined


# --- the happy path -----------------------------------------------------------------------


class TestSanitize:
    def test_ingest_then_sanitize_writes_names_logs_copies_and_thumbnails(
        self, source: Path, results: Path, config: Config, schema_dsn: str
    ) -> None:
        images = _populate(source)
        hashes = {key: _hash(path) for key, path in images.items()}

        result = run(config, dry_run=True)

        assert result.ingest.new == 3
        assert (result.sanitize.sanitized, result.sanitize.errored) == (3, 0)
        assert dict(result.sanitize.by_reason) == {}
        files = _files(schema_dsn)
        assert {status for status, _, _ in files.values()} == {"sanitized"}
        assert files[hashes["named"]][2] == f"[PERSON]_beach_{RESIDUE}"  # SAN-001.D8
        assert files[hashes["plain"]][2] == "plain"
        assert files[hashes["nested"]][2] == "photo"

        named_log = _log(schema_dsn, hashes["named"])
        by_field = {}
        for _, _, rule_id, field, before, after in named_log:
            by_field.setdefault(field, []).append((rule_id, before, after))
        # R-SAN-6: the folder segment and the stem, each hashed, never stored.
        assert by_field["path_segment"] == [("test-person", _hmac(REDACTED), "[PERSON]")]
        assert by_field["filename"] == [("test-person", _hmac("Zorvane_Quillby"), "[PERSON]")]
        # SAN-001.D3, D12: each removed tag, hashed, with no after_value.
        assert ("exif-strip-all", _hmac(TAG_SECRET), None) in by_field["exif:EXIF:Artist"]
        assert "exif:EXIF:GPSLatitude" in by_field
        assert "exif:EXIF:Orientation" not in by_field  # the keep list
        assert _log(schema_dsn, hashes["plain"]) == []  # a plain PNG: nothing to redact

        rules = load_rules(config.sanitizer.rules_file)
        for key, path in images.items():
            ext = path.suffix.lstrip(".").lower()
            copy = results / ".work" / f"{hashes[key]}.{ext}"
            assert copy.is_file() and not copy.is_symlink()
            assert all(is_allowed(tag, rules) for tag in read_tags(copy).entries)
            assert (results / ".work" / "thumbs" / f"{hashes[key]}.webp").is_file()
        assert "Orientation" in {t.name for t in read_tags(results / ".work" / (
            f"{hashes['named']}.jpg")).entries}  # fmt: skip

    def test_only_work_appears_under_results_and_the_source_is_unchanged(
        self, source: Path, results: Path, config: Config
    ) -> None:
        _populate(source)
        before = _tree(source)
        run(config, dry_run=True)
        assert _tree(source) == before  # P-1, R-SAN-1
        assert [p.name for p in results.iterdir()] == [".work"]
        work_dir = results / ".work"
        work = {p.relative_to(work_dir).as_posix() for p in work_dir.rglob("*")}
        assert "thumbs" in work
        stems = {name.rsplit("/", 1)[-1].split(".")[0] for name in work - {"thumbs"}}
        assert all(len(stem) == 64 for stem in stems)  # named by source_hash only
        assert not any(name.endswith(".tmp") for name in work)
        _assert_clean(*work)

    def test_a_re_run_is_a_no_op(
        self, source: Path, results: Path, config: Config, schema_dsn: str
    ) -> None:
        _populate(source)
        run(config, dry_run=True)
        files, log = _files(schema_dsn), _log(schema_dsn)
        work = _tree(results)

        again = run(config, dry_run=True)

        assert again.sanitize == SanitizeResult()  # R-PIPE-1, P-4
        assert _files(schema_dsn) == files
        assert _log(schema_dsn) == log
        assert _tree(results) == work  # no copy or thumbnail rewritten

    def test_the_node_never_commits(self, source: Path, config: Config, schema_dsn: str) -> None:
        _populate(source)
        run(config, dry_run=True, nodes=INGEST_ONLY)
        ctx = NodeContext(
            source_root=source, dry_run=True, results_root=Path(config.paths.results_root),
            config=config,
        )  # fmt: skip
        with psycopg.connect(schema_dsn) as conn:
            assert node.sanitize(conn, ctx).sanitized == 3
            conn.rollback()  # PIPE-001.D3: the caller owns the transaction
        assert {status for status, _, _ in _files(schema_dsn).values()} == {"queued"}
        assert _log(schema_dsn) == []

    def test_an_autocommit_connection_is_refused(self, config: Config, schema_dsn: str) -> None:
        ctx = NodeContext(
            source_root=Path(config.paths.source_root), dry_run=True,
            results_root=Path(config.paths.results_root), config=config,
        )  # fmt: skip
        with psycopg.connect(schema_dsn, autocommit=True) as conn:
            with pytest.raises(ValueError, match="PIPE-001.D3"):
                node.sanitize(conn, ctx)


# --- fail closed, per file (SAN-001.D2, D9, D16, D17) -------------------------------------


def _raiser(exc: BaseException):
    def fail(*args: object, **kwargs: object) -> object:
        raise exc

    return fail


def _only_for(target: str, exc: BaseException, real):
    """Fail only for the named image (by its source hash in an argument), else call `real`."""

    def maybe(*args: object, **kwargs: object) -> object:
        if any(target in str(arg) for arg in (*args, *kwargs.values())):
            raise exc
        return real(*args, **kwargs)

    return maybe


OS_ERROR = OSError(2, EXC_SECRET, f"/source/{EXC_SECRET}")  # a FileNotFoundError naming a path
FAILURES = {
    # step patched → (exception carrying a secret, the fixed reason it must map to)
    "sanitize_name": (ValueError(f"bad name {EXC_SECRET}"), "sanitize_name_failed"),
    "make_working_copy": (OS_ERROR, "sanitize_working_copy_failed"),
    "strip_metadata": (MetadataStripError(EXC_SECRET), "sanitize_metadata_residual"),
    "make_thumbnail": (RecursionError(EXC_SECRET), "sanitize_thumbnail_failed"),
    "make_thumbnail_pillow": (UnidentifiedImageError(EXC_SECRET), "sanitize_thumbnail_failed"),
}


class TestFailClosed:
    @pytest.mark.parametrize("step", sorted(FAILURES))
    def test_any_exception_fails_only_that_file_with_a_fixed_reason(
        self,
        step: str,
        source: Path,
        config: Config,
        schema_dsn: str,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        images = _populate(source)
        target = _hash(images["named"])
        exc, reason = FAILURES[step]
        name = step.removesuffix("_pillow")
        if name == "sanitize_name":
            # The relative path carries the named folder: fail on that one only.
            patched = _only_for(NAMED_DIR, exc, node.sanitize_name)
        elif name == "strip_metadata":
            real = node.strip_metadata
            patched = _only_for(target, exc, real)  # the temp file is named by the hash
        else:
            patched = _only_for(target, exc, getattr(node, name))
        monkeypatch.setattr(node, name, patched)
        caplog.set_level(logging.DEBUG)

        result = run(config, dry_run=True)

        assert (result.sanitize.sanitized, result.sanitize.errored) == (2, 1)
        assert dict(result.sanitize.by_reason) == {reason: 1}
        files = _files(schema_dsn)
        assert files[target] == ("error", reason, None)  # D2: no sanitized name kept
        assert _log(schema_dsn, target) == []  # D9: no log rows for a failed file
        assert sum(status == "sanitized" for status, _, _ in files.values()) == 2
        assert f"{target[:8]} error {reason} ({type(exc).__name__})" in caplog.text
        _assert_clean(caplog.text, capsys.readouterr(), result, files, _log(schema_dsn))

    def test_a_rejected_log_row_rolls_back_only_that_file(
        self, source: Path, config: Config, schema_dsn: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        images = _populate(source)
        target = _hash(images["named"])
        real = node.strip_metadata

        def bad_field(path: Path, rules: object) -> list[Redaction]:
            rows = real(path, rules)
            if target in str(path):  # a field DB-002.D1's check refuses
                rows.append(Redaction("exif-strip-all", "exif:no spaces", "0" * 64, None))
            return rows

        monkeypatch.setattr(node, "strip_metadata", bad_field)
        result = run(config, dry_run=True)

        assert dict(result.sanitize.by_reason) == {"sanitize_ledger_rejected": 1}
        assert _files(schema_dsn)[target] == ("error", "sanitize_ledger_rejected", None)
        assert _log(schema_dsn, target) == []  # the savepoint undid the rows it had written
        assert len({row[1] for row in _log(schema_dsn)}) == 1  # the other seeded file's rows

    def test_a_failed_file_is_retried_on_the_next_run(
        self, source: Path, config: Config, schema_dsn: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        images = _populate(source)
        target = _hash(images["named"])
        monkeypatch.setattr(
            node, "make_thumbnail", _only_for(target, OSError("x"), node.make_thumbnail)
        )
        run(config, dry_run=True)
        monkeypatch.undo()

        again = run(config, dry_run=True)  # R-ING-2: ingest re-queues the error row

        assert again.ingest.new == 1
        assert again.sanitize.sanitized == 1
        assert _files(schema_dsn)[target] == ("sanitized", None, f"[PERSON]_beach_{RESIDUE}")
        assert _log(schema_dsn, target)

    def test_a_second_sanitize_replaces_the_log_rows(
        self, source: Path, config: Config, schema_dsn: str
    ) -> None:
        # SAN-001.D18: a row re-queued after a later error gets a fresh log, not a second set.
        images = _populate(source)
        target = _hash(images["named"])
        run(config, dry_run=True)
        first = [row[2:] for row in _log(schema_dsn, target)]
        with psycopg.connect(schema_dsn) as conn:
            conn.execute(
                "update files set status = 'error', error = 'later' where source_hash = %s",
                (target,),
            )

        run(config, dry_run=True)

        assert sorted(row[2:] for row in _log(schema_dsn, target)) == sorted(first)


# --- the work folders (SAN-001.D16) --------------------------------------------------------


class TestPaths:
    def test_a_work_folder_linked_into_the_source_is_refused_before_any_write(
        self, source: Path, results: Path, config: Config, schema_dsn: str
    ) -> None:
        _populate(source)
        results.mkdir()
        (results / ".work").symlink_to(source, target_is_directory=True)
        before = _tree(source)

        with pytest.raises(WorkDirError, match="real folder") as raised:
            run(config, dry_run=True)

        assert _tree(source) == before
        assert {status for status, _, _ in _files(schema_dsn).values()} == {"queued"}
        assert str(source) not in str(raised.value)

    def test_a_results_root_linked_into_the_source_is_refused(
        self, tmp_path: Path, source: Path, schema_dsn: str
    ) -> None:
        _populate(source)
        linked = tmp_path / "results-link"
        linked.symlink_to(source, target_is_directory=True)
        config = _config(tmp_path, source, linked, schema_dsn)  # lexically distinct roots
        before = _tree(source)

        with pytest.raises(WorkDirError, match="overlap"):
            run(config, dry_run=True)

        assert _tree(source) == before

    def test_a_copy_published_outside_work_fails_that_file(
        self, source: Path, config: Config, schema_dsn: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        images = _populate(source)
        target = _hash(images["named"])
        real = node.make_working_copy

        def escaped(src: Path, work: Path, source_hash: str, *rest: object) -> WorkingCopy:
            copy = real(src, work, source_hash, *rest)
            if source_hash == target:  # as if a link had redirected it
                return WorkingCopy(images["named"], copy.copy_sha256)
            return copy

        monkeypatch.setattr(node, "make_working_copy", escaped)
        result = run(config, dry_run=True)

        assert dict(result.sanitize.by_reason) == {"sanitize_path_escape": 1}
        assert _files(schema_dsn)[target] == ("error", "sanitize_path_escape", None)


# --- pre-flight (SAN-001.D1, D5, D6) -------------------------------------------------------


class TestPreFlight:
    @pytest.mark.parametrize(
        ("setting", "match"),
        [({"ocr": True}, "sanitizer.ocr"), ({"backend": "claude"}, "sanitizer.backend")],
    )
    def test_unsupported_settings_fail_fast_naming_the_key(
        self,
        tmp_path: Path,
        source: Path,
        results: Path,
        schema_dsn: str,
        setting: dict[str, object],
        match: str,
    ) -> None:
        _populate(source)
        config = _config(tmp_path, source, results, schema_dsn, **setting)
        with pytest.raises(SanitizeConfigError, match=match):
            run(config, dry_run=True)
        assert not results.exists()
        assert {status for status, _, _ in _files(schema_dsn).values()} == {"queued"}

    def test_a_missing_rules_file_names_make_init(
        self, tmp_path: Path, source: Path, results: Path, schema_dsn: str
    ) -> None:
        _populate(source)
        config = _config(tmp_path, source, results, schema_dsn, rules_file=str(tmp_path / "x"))
        with pytest.raises(SanitizeConfigError, match="make init"):
            run(config, dry_run=True)
        assert not results.exists()

    def test_a_missing_log_key_names_make_init(
        self, source: Path, results: Path, config: Config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _populate(source)
        monkeypatch.delenv(LOG_KEY_ENV)
        with pytest.raises(SanitizeConfigError, match=f"{LOG_KEY_ENV}.*make init"):
            run(config, dry_run=True)
        assert not results.exists()

    def test_an_entity_rule_fails_fast_until_the_detector_is_wired(
        self, tmp_path: Path, source: Path, results: Path, schema_dsn: str
    ) -> None:
        # SAN-001.4.3 only: SAN-001.4.4 replaces this with the replayed entity tests.
        _populate(source)
        rules = tmp_path / "rules.yaml"
        entity = {"id": "test-entity", "type": "entity", "labels": ["PERSON"], "replace": "[P]"}
        with_entity = {**RULES, "rules": [*RULES["rules"], entity]}
        rules.write_text(yaml.safe_dump(with_entity), encoding="utf-8")
        config = _config(tmp_path, source, results, schema_dsn)
        with pytest.raises(SanitizeConfigError, match="entity"):
            run(config, dry_run=True)
        assert {status for status, _, _ in _files(schema_dsn).values()} == {"queued"}


def test_every_reason_is_a_fixed_label() -> None:
    assert len(set(REASONS)) == len(REASONS) == 7  # SAN-001.D17
    assert all(reason.startswith("sanitize_") and reason.isascii() for reason in REASONS)
