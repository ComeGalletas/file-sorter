"""ING-001.1: hashing, discovery and frame probing. Synthetic data only, generated here."""

import hashlib
from pathlib import Path

from classifier.graph.ingest_files import IMAGE_EXTENSIONS, Candidate, Skipped, discover, hash_file


class TestHashFile:
    def test_matches_sha256_of_the_bytes(self, tmp_path: Path) -> None:
        data = b"synthetic-bytes"
        path = tmp_path / "a.bin"
        path.write_bytes(data)
        result = hash_file(path)
        assert result.source_hash == hashlib.sha256(data).hexdigest()
        assert result.short_hash == result.source_hash[:8]

    def test_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.bin"
        path.write_bytes(b"")
        assert hash_file(path).source_hash == hashlib.sha256(b"").hexdigest()

    def test_file_larger_than_one_chunk(self, tmp_path: Path) -> None:
        data = b"x" * (1024 * 1024 * 2 + 1)
        path = tmp_path / "big.bin"
        path.write_bytes(data)
        assert hash_file(path).source_hash == hashlib.sha256(data).hexdigest()

    def test_same_bytes_at_two_paths_hash_alike(self, tmp_path: Path) -> None:
        (tmp_path / "one.bin").write_bytes(b"same")
        (tmp_path / "two.bin").write_bytes(b"same")
        assert hash_file(tmp_path / "one.bin") == hash_file(tmp_path / "two.bin")


class TestDiscover:
    def _touch(self, root: Path, *names: str) -> None:
        for name in names:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"")

    def test_walks_nested_folders_in_sorted_order(self, tmp_path: Path) -> None:
        self._touch(tmp_path, "b.png", "a.png", "sub/c.png", "sub/deeper/d.png")
        found = [item.path.relative_to(tmp_path).as_posix() for item in discover(tmp_path)]
        assert found == ["a.png", "b.png", "sub/c.png", "sub/deeper/d.png"]

    def test_every_mvp_extension_is_a_candidate_in_any_case(self, tmp_path: Path) -> None:
        names = [f"f{i}{ext}" for i, ext in enumerate(sorted(IMAGE_EXTENSIONS))]
        names += ["UPPER.JPG", "Mixed.PnG", "photo.TIF"]
        self._touch(tmp_path, *names)
        items = list(discover(tmp_path))
        assert len(items) == len(names)
        assert all(isinstance(item, Candidate) for item in items)

    def test_mvp_types_are_the_design_list(self) -> None:
        wanted = {"jpg", "jpeg", "png", "webp", "gif", "bmp", "heic", "tiff"}
        assert {ext.lstrip(".") for ext in IMAGE_EXTENSIONS} == wanted | {"tif"}

    def test_other_extensions_are_skipped_with_a_reason(self, tmp_path: Path) -> None:
        self._touch(tmp_path, "notes.txt", "clip.mp3", "noext", "archive.png.zip")
        items = list(discover(tmp_path))
        assert len(items) == 4
        assert all(isinstance(item, Skipped) for item in items)
        assert {item.reason for item in items} == {"not an image type"}

    def test_os_metadata_files_are_dropped_silently(self, tmp_path: Path) -> None:
        self._touch(
            tmp_path,
            "desktop.ini",
            "Thumbs.db",
            "THUMBS.DB",
            ".DS_Store",
            "sub/Desktop.INI",
            "keep.png",
        )
        items = list(discover(tmp_path))
        assert [item.path.name for item in items] == ["keep.png"]

    def test_a_text_file_named_png_is_a_candidate(self, tmp_path: Path) -> None:
        # discover filters by extension only; probe_image is the sole judge of decodability.
        (tmp_path / "fake.png").write_text("not an image")
        assert [type(item) for item in discover(tmp_path)] == [Candidate]

    def test_directories_are_not_yielded_and_an_empty_root_is_empty(self, tmp_path: Path) -> None:
        (tmp_path / "empty_dir").mkdir()
        assert list(discover(tmp_path)) == []

    def test_discovery_leaves_the_tree_untouched(self, tmp_path: Path) -> None:
        self._touch(tmp_path, "a.png", "notes.txt", "desktop.ini")
        before = sorted(p.name for p in tmp_path.rglob("*"))
        list(discover(tmp_path))
        assert sorted(p.name for p in tmp_path.rglob("*")) == before
