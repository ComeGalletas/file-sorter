"""Thumbnails made from the sanitized working copy (ING-002.1, R-ING-5).

The working copy is only ever opened for reading, and the thumbnail is published through
`write_new`, so nothing here opens a file for writing or replaces one (FOP-001.D2). Nothing
here logs or prints a path or a file name (CLAUDE.md "Hard rules").
"""

import io
from pathlib import Path

from PIL import Image
from pillow_heif import register_heif_opener

from classifier.fileops.copy_move import _SOURCE_HASH, write_new

register_heif_opener()  # R-ING-6: HEIC decodes through Pillow

_ALPHA_MODES = frozenset({"RGBA", "LA", "PA", "RGBa", "La"})


def _has_alpha(image: Image.Image) -> bool:
    return image.mode in _ALPHA_MODES or "transparency" in image.info


def make_thumbnail(working_copy: Path, thumbs_dir: Path, name: str, size: int) -> Path:
    """Make `thumbs_dir/<name>.webp` from `working_copy`, longest side `size`, and return it.

    `name` is the full `source_hash` (ING-002.D1). An existing thumbnail is kept and the
    working copy isn't decoded (ING-002.D2). Otherwise the first frame or page (R-ING-6) is
    converted to RGB, or RGBA when it has alpha, shrunk with `thumbnail()` so the aspect
    ratio holds and a smaller image is never enlarged, and encoded as WebP with no metadata
    (ING-002.D2). Pillow's errors propagate for the caller to record (SAN-001.D9).
    """
    if not _SOURCE_HASH.fullmatch(name):
        raise ValueError("name must be the source_hash: 64 lowercase hex characters")
    if size <= 0:
        raise ValueError("size must be a positive number of pixels")
    dest = thumbs_dir / f"{name}.webp"
    if dest.exists():  # ING-002.D2: kept, never replaced
        return dest
    with Image.open(working_copy) as image:  # opens on the first frame or page (R-ING-6)
        frame = image.convert("RGBA" if _has_alpha(image) else "RGB")
    frame.thumbnail((size, size))
    frame.info.clear()  # ING-002.D2: nothing carried over from the working copy
    buffer = io.BytesIO()
    frame.save(buffer, format="WEBP", exif=b"", icc_profile=None, xmp=b"")
    write_new(dest, buffer.getvalue())  # False only if another writer made it meanwhile
    return dest
