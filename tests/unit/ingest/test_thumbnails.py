"""`make_thumbnail` (ING-002.1, R-ING-5, R-ING-6, ING-002.D1, ING-002.D2).

Every image is synthetic, made in the test. Nothing here reads `fixtures/images/`.
"""

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from classifier.fileops import thumbs
from classifier.fileops.thumbs import make_thumbnail

HASH = "ab" * 32
SIZE = 64
RED = (220, 20, 20)
BLUE = (20, 20, 220)


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    work = tmp_path / ".work"
    work.mkdir()
    return work


@pytest.fixture
def thumbs_dir(work_dir: Path) -> Path:
    return work_dir / "thumbs"


def _save(image: Image.Image, path: Path, **params: object) -> Path:
    image.save(path, **params)
    return path


def _open(path: Path) -> Image.Image:
    with Image.open(path) as image:
        image.load()
        return image


def _close_to(pixel: tuple[int, ...], colour: tuple[int, int, int]) -> bool:
    return all(abs(a - b) <= 24 for a, b in zip(pixel[:3], colour, strict=True))


class TestSizeAndFormat:
    @pytest.mark.parametrize(
        ("source_size", "expected"),
        [((400, 200), (SIZE, SIZE // 2)), ((150, 300), (SIZE // 2, SIZE))],
    )
    def test_longest_side_is_size_and_aspect_ratio_holds(
        self,
        work_dir: Path,
        thumbs_dir: Path,
        source_size: tuple[int, int],
        expected: tuple[int, int],
    ) -> None:
        copy = _save(Image.new("RGB", source_size, RED), work_dir / f"{HASH}.png")
        dest = make_thumbnail(copy, thumbs_dir, HASH, SIZE)
        assert dest == thumbs_dir / f"{HASH}.webp"  # ING-002.D1: the full source_hash
        thumb = _open(dest)
        assert thumb.format == "WEBP"
        assert thumb.size == expected

    def test_a_smaller_image_is_not_enlarged(self, work_dir: Path, thumbs_dir: Path) -> None:
        copy = _save(Image.new("RGB", (20, 10), RED), work_dir / f"{HASH}.png")
        assert _open(make_thumbnail(copy, thumbs_dir, HASH, SIZE)).size == (20, 10)


class TestMode:
    def test_rgb_stays_rgb(self, work_dir: Path, thumbs_dir: Path) -> None:
        copy = _save(Image.new("RGB", (80, 80), RED), work_dir / f"{HASH}.jpg")
        thumb = _open(make_thumbnail(copy, thumbs_dir, HASH, SIZE))
        assert thumb.mode == "RGB"
        assert _close_to(thumb.getpixel((5, 5)), RED)

    def test_rgba_keeps_its_alpha(self, work_dir: Path, thumbs_dir: Path) -> None:
        copy = _save(Image.new("RGBA", (80, 80), (*RED, 0)), work_dir / f"{HASH}.png")
        thumb = _open(make_thumbnail(copy, thumbs_dir, HASH, SIZE))
        assert thumb.mode == "RGBA"
        assert thumb.getpixel((5, 5))[3] == 0

    def test_palette_with_transparency_becomes_rgba(self, work_dir: Path, thumbs_dir: Path) -> None:
        image = Image.new("P", (80, 80), 0)
        image.putpalette([*RED, *BLUE] + [0] * 762)
        image.paste(1, (0, 0, 40, 80))
        copy = _save(image, work_dir / f"{HASH}.png", transparency=1)
        thumb = _open(make_thumbnail(copy, thumbs_dir, HASH, SIZE))
        assert thumb.mode == "RGBA"
        assert thumb.getpixel((5, 5))[3] == 0  # the transparent half
        assert thumb.getpixel((SIZE - 5, 5))[3] == 255

    @pytest.mark.parametrize("suffix", ["png", "tiff"])
    def test_sixteen_bit_grey_is_scaled_not_clipped(
        self, work_dir: Path, thumbs_dir: Path, suffix: str
    ) -> None:  # ING-002.1.3: a plain convert("RGB") turns mid-grey into white
        copy = _save(Image.new("I;16", (80, 80), 32768), work_dir / f"{HASH}.{suffix}")
        assert _open(copy).mode.startswith("I")  # the input really is 16-bit
        thumb = _open(make_thumbnail(copy, thumbs_dir, HASH, SIZE))
        assert thumb.mode == "RGB"
        assert _close_to(thumb.getpixel((5, 5)), (128, 128, 128))


class TestFirstFrame:  # R-ING-6
    def test_animated_gif_uses_its_first_frame(self, work_dir: Path, thumbs_dir: Path) -> None:
        first, second = Image.new("RGB", (80, 80), RED), Image.new("RGB", (80, 80), BLUE)
        copy = _save(
            first, work_dir / f"{HASH}.gif", save_all=True, append_images=[second], duration=50
        )
        thumb = _open(make_thumbnail(copy, thumbs_dir, HASH, SIZE))
        assert _close_to(thumb.getpixel((5, 5)), RED)

    def test_multi_page_tiff_uses_its_first_page(self, work_dir: Path, thumbs_dir: Path) -> None:
        first, second = Image.new("RGB", (80, 40), RED), Image.new("RGB", (40, 80), BLUE)
        copy = _save(first, work_dir / f"{HASH}.tiff", save_all=True, append_images=[second])
        thumb = _open(make_thumbnail(copy, thumbs_dir, HASH, SIZE))
        assert thumb.size == (SIZE, SIZE // 2)
        assert _close_to(thumb.getpixel((5, 5)), RED)

    def test_heic_decodes(self, work_dir: Path, thumbs_dir: Path) -> None:
        copy = _save(Image.new("RGB", (80, 80), RED), work_dir / f"{HASH}.heic", format="HEIF")
        thumb = _open(make_thumbnail(copy, thumbs_dir, HASH, SIZE))
        assert thumb.size == (SIZE, SIZE)
        assert _close_to(thumb.getpixel((5, 5)), RED)


class TestNoMetadata:  # ING-002.D2
    def test_exif_icc_and_xmp_are_not_carried_over(self, work_dir: Path, thumbs_dir: Path) -> None:
        image = Image.new("RGB", (80, 80), RED)
        exif = Image.Exif()
        exif[0x010E] = "synthetic description"  # ImageDescription
        copy = _save(
            image,
            work_dir / f"{HASH}.webp",
            exif=exif.tobytes(),
            icc_profile=b"synthetic-icc-profile",
            xmp=b"<x:xmpmeta>synthetic</x:xmpmeta>",
        )
        assert {"exif", "icc_profile", "xmp"} <= set(_open(copy).info)  # the input has them
        dest = make_thumbnail(copy, thumbs_dir, HASH, SIZE)
        thumb = _open(dest)
        assert not {"exif", "icc_profile", "xmp"} & set(thumb.info)
        assert len(thumb.getexif()) == 0
        assert b"synthetic" not in dest.read_bytes()


class TestFiles:
    def test_an_existing_thumbnail_is_kept_and_not_decoded(
        self, work_dir: Path, thumbs_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copy = _save(Image.new("RGB", (80, 80), RED), work_dir / f"{HASH}.png")
        thumbs_dir.mkdir()
        existing = thumbs_dir / f"{HASH}.webp"
        existing.write_bytes(b"made-earlier")

        def no_open(*args: object, **kwargs: object) -> None:
            raise AssertionError("the working copy must not be decoded")

        monkeypatch.setattr(thumbs.Image, "open", no_open)
        assert make_thumbnail(copy, thumbs_dir, HASH, SIZE) == existing  # ING-002.D2
        assert existing.read_bytes() == b"made-earlier"

    def test_the_working_copy_is_unchanged(self, work_dir: Path, thumbs_dir: Path) -> None:
        copy = _save(Image.new("RGB", (80, 80), RED), work_dir / f"{HASH}.png")
        before = hashlib.sha256(copy.read_bytes()).hexdigest()
        make_thumbnail(copy, thumbs_dir, HASH, SIZE)
        assert hashlib.sha256(copy.read_bytes()).hexdigest() == before
        assert sorted(p.name for p in work_dir.iterdir()) == sorted([copy.name, "thumbs"])

    def test_no_temp_file_is_left(self, work_dir: Path, thumbs_dir: Path) -> None:
        copy = _save(Image.new("RGB", (80, 80), RED), work_dir / f"{HASH}.png")
        make_thumbnail(copy, thumbs_dir, HASH, SIZE)
        assert [p.name for p in thumbs_dir.iterdir()] == [f"{HASH}.webp"]

    @pytest.mark.parametrize(
        "name", ["ab" * 4, "AB" * 32, "ab" * 32 + "c", "../" + "ab" * 31 + "a", ""]
    )
    def test_a_name_that_is_not_a_source_hash_is_rejected(
        self, work_dir: Path, thumbs_dir: Path, name: str
    ) -> None:
        copy = _save(Image.new("RGB", (80, 80), RED), work_dir / f"{HASH}.png")
        with pytest.raises(ValueError, match="source_hash"):
            make_thumbnail(copy, thumbs_dir, name, SIZE)
        assert not thumbs_dir.exists()

    @pytest.mark.parametrize("size", [0, -1])
    def test_a_size_that_is_not_positive_is_rejected(
        self, work_dir: Path, thumbs_dir: Path, size: int
    ) -> None:
        copy = _save(Image.new("RGB", (80, 80), RED), work_dir / f"{HASH}.png")
        with pytest.raises(ValueError, match="size"):
            make_thumbnail(copy, thumbs_dir, HASH, size)
        assert not thumbs_dir.exists()

    def test_an_undecodable_copy_raises_and_writes_nothing(
        self, work_dir: Path, thumbs_dir: Path
    ) -> None:
        copy = work_dir / f"{HASH}.png"
        copy.write_bytes(b"not an image at all")
        with pytest.raises(OSError):  # UnidentifiedImageError; SAN-001.D9 records it
            make_thumbnail(copy, thumbs_dir, HASH, SIZE)
        assert not thumbs_dir.exists()
