"""ING-001.1: hashing, discovery and frame probing. Synthetic data only, generated here."""

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from classifier.graph.ingest_files import (
    IMAGE_EXTENSIONS,
    Candidate,
    Probe,
    Skipped,
    discover,
    hash_file,
    probe_image,
)


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


def _frames(count: int, size: tuple[int, int] = (8, 6)) -> list[Image.Image]:
    return [Image.new("RGB", size, (40 * i % 256, 90, 160)) for i in range(count)]


def _save_multi(path: Path, count: int, **kwargs: object) -> None:
    first, *rest = _frames(count)
    first.save(path, save_all=True, append_images=rest, **kwargs)


class TestProbeImage:
    def test_still_png(self, tmp_path: Path) -> None:
        path = tmp_path / "still.png"
        Image.new("RGB", (8, 6)).save(path)
        result = probe_image(path)
        assert isinstance(result, Probe)
        assert (result.width, result.height, result.format, result.animated) == (8, 6, "PNG", False)

    def test_jpeg_and_bmp_are_decoded(self, tmp_path: Path) -> None:
        Image.new("RGB", (5, 4)).save(tmp_path / "a.jpg")
        Image.new("RGB", (5, 4)).save(tmp_path / "a.bmp")
        formats = [probe_image(tmp_path / n) for n in ("a.jpg", "a.bmp")]
        assert [r.format for r in formats if isinstance(r, Probe)] == ["JPEG", "BMP"]

    @pytest.mark.parametrize(
        ("name", "fmt"), [("two.gif", "GIF"), ("two.webp", "WEBP"), ("two.png", "PNG")]
    )
    def test_two_frames_are_animated(self, tmp_path: Path, name: str, fmt: str) -> None:
        path = tmp_path / name  # the PNG case is an APNG
        _save_multi(path, 2, duration=50, loop=0, **({"lossless": True} if fmt == "WEBP" else {}))
        result = probe_image(path)
        assert isinstance(result, Probe)
        assert (result.format, result.animated) == (fmt, True)
        assert (result.width, result.height) == (8, 6)  # the first frame's size

    @pytest.mark.parametrize("name", ["one.gif", "one.webp"])
    def test_single_frame_is_not_animated(self, tmp_path: Path, name: str) -> None:
        path = tmp_path / name
        Image.new("RGB", (8, 6)).save(path)
        result = probe_image(path)
        assert isinstance(result, Probe)
        assert result.animated is False

    def test_multi_page_tiff_is_not_animated_and_uses_the_first_page(self, tmp_path: Path) -> None:
        # ING-001.D3 (decided by the human): a 2-page TIFF is not animated
        path = tmp_path / "pages.tiff"
        first, *rest = [Image.new("RGB", (10 + i, 7)) for i in range(3)]
        first.save(path, save_all=True, append_images=rest)
        assert Image.open(path).n_frames == 3
        result = probe_image(path)
        assert isinstance(result, Probe)
        assert (result.format, result.animated, result.width) == ("TIFF", False, 10)

    def test_multi_image_mpo_is_not_animated(self, tmp_path: Path) -> None:
        # ING-001.D3: MPO (multi-image JPEG) is outside the allow-list, whatever Pillow says
        path = tmp_path / "multi.jpg"
        first, *rest = _frames(2)
        first.save(path, format="MPO", save_all=True, append_images=rest)
        with Image.open(path) as image:
            assert (image.format, image.is_animated) == ("MPO", True)
        result = probe_image(path)
        assert isinstance(result, Probe)
        assert (result.format, result.animated) == ("MPO", False)

    def test_heic_decodes_through_pillow_heif(self, tmp_path: Path) -> None:
        path = tmp_path / "pic.heic"
        Image.new("RGB", (16, 16), (200, 30, 30)).save(path, format="HEIF")
        result = probe_image(path)
        assert isinstance(result, Probe)
        assert (result.width, result.height, result.animated) == (16, 16, False)

    def test_truncated_png_is_skipped(self, tmp_path: Path) -> None:
        good = tmp_path / "good.png"
        Image.effect_noise((64, 64), 80).convert("RGB").save(good)
        data = good.read_bytes()
        bad = tmp_path / "bad.png"
        bad.write_bytes(data[: len(data) // 2])
        result = probe_image(bad)
        assert isinstance(result, Skipped)
        assert result.path == bad
        assert result.reason.startswith("undecodable image")

    def test_text_file_named_png_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "fake.png"
        path.write_text("not an image")
        assert isinstance(probe_image(path), Skipped)

    def test_empty_file_and_missing_file_are_skipped_not_raised(self, tmp_path: Path) -> None:
        (tmp_path / "empty.png").write_bytes(b"")
        assert isinstance(probe_image(tmp_path / "empty.png"), Skipped)
        assert isinstance(probe_image(tmp_path / "missing.png"), Skipped)

    def test_skip_reason_never_contains_the_path(self, tmp_path: Path) -> None:
        path = tmp_path / "secret-name-xyz.png"
        path.write_text("nope")
        result = probe_image(path)
        assert isinstance(result, Skipped)
        assert "secret-name-xyz" not in result.reason
        assert str(tmp_path) not in result.reason

    def test_mtime_is_the_source_mtime_in_utc(self, tmp_path: Path) -> None:
        path = tmp_path / "dated.png"
        Image.new("RGB", (4, 4)).save(path)
        stamp = datetime(2021, 3, 4, 5, 6, 7, tzinfo=UTC).timestamp()
        os.utime(path, (stamp, stamp))
        result = probe_image(path)
        assert isinstance(result, Probe)
        assert result.mtime == datetime(2021, 3, 4, 5, 6, 7, tzinfo=UTC)

    def test_probe_leaves_the_file_untouched(self, tmp_path: Path) -> None:
        path = tmp_path / "keep.png"
        Image.new("RGB", (4, 4)).save(path)
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        probe_image(path)
        assert (path.read_bytes(), path.stat().st_mtime_ns) == before
