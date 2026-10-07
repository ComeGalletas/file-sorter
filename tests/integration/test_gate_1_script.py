"""TST-002.4: gate 1 end to end on synthetic images (the real fixtures only run at `make gate-1`).

Drives `scripts/gate_1.py` the way the container does: a fresh private schema, two dry runs,
the verdict on run 2. Synthetic images are generated under `tmp_path`.
"""

import importlib.util
from pathlib import Path

import pytest
from PIL import Image

from tests.db.db_support import require_db_dsn

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gate_1.py"
spec = importlib.util.spec_from_file_location("gate_1", SCRIPT)
assert spec and spec.loader
gate_1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate_1)


@pytest.fixture
def images(tmp_path: Path) -> Path:
    root = tmp_path / "gate-images-secret-name"
    (root / "nested-secret-folder").mkdir(parents=True)
    first = root / "a-secret.png"
    Image.new("RGB", (8, 6), (10, 20, 30)).save(first)
    Image.new("RGB", (8, 6), (200, 20, 30)).save(root / "nested-secret-folder" / "b.png")
    (root / "copy-secret.png").write_bytes(first.read_bytes())
    (root / "notes.txt").write_text("not an image")
    return root


def test_rerun_passes_and_prints_aggregates_only(
    images: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DB_DSN", require_db_dsn())
    assert gate_1.main(images) == 0
    out = capsys.readouterr()
    text = out.out + out.err
    assert "100.0%" in text and "new ledger rows: 0" in text and "PASS" in text
    assert "secret" not in text and str(images) not in text and "notes" not in text


def test_tree_of_non_images_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "only-notes"
    root.mkdir()
    (root / "notes.txt").write_text("not an image")
    (root / "more.dat").write_text("still not an image")
    monkeypatch.setenv("DB_DSN", require_db_dsn())
    assert gate_1.main(root) == 1
    out = capsys.readouterr()
    assert "ingested nothing" in out.out + out.err
    assert "PASS" not in out.out + out.err


def test_an_error_prints_only_its_type(
    images: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(db_dsn: str, root: Path) -> None:
        raise RuntimeError(f"secret detail {db_dsn} {root}")

    monkeypatch.setenv("DB_DSN", "postgresql://user:pw@host/db")
    monkeypatch.setattr(gate_1, "measure", boom)
    assert gate_1.main(images) == 1
    out = capsys.readouterr()
    text = out.out + out.err
    assert "run errored (RuntimeError)" in text
    assert "secret" not in text and "pw" not in text and str(images) not in text
