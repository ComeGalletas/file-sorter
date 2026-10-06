"""ING-001.1: hashing, discovery and frame probing. Synthetic data only, generated here."""

import hashlib
from pathlib import Path

from classifier.graph.ingest_files import hash_file


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
