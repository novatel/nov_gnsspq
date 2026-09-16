"""
################################################################################

MIT License

Copyright (c) 2026 NovAtel Inc.

This project is licensed under the MIT License. A copy of the license is
available in the LICENSE file included with this repository.

This software may incorporate or depend upon third-party software components
that are subject to separate license terms. Users are responsible for
complying with any applicable third-party licenses.

NovAtel® and other product names, logos, and trademarks referenced in this
project are the property of their respective owners. No rights or licenses to
NovAtel trademarks are granted under the MIT License.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, AS MORE FULLY SET FORTH IN THE LICENSE FILE.
################################################################################

Unit tests for compare in nov_gnsspq.validate.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from nov_gnsspq import ValidationResult, compare
from nov_gnsspq.reader.schema import METADATA_FILENAME


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gps_bytes() -> bytes:
    """Small synthetic GPS payload — no real parsing needed."""
    return b"\xaa\x44\x12" * 512  # 1536 bytes


def _write_db_dir(tmp_path: Path, gps_content: bytes, *, name: str = "testdb", meta_override: dict | None = None) -> Path:
    """Write a minimal database directory with a matching _metadata.json."""
    db_dir = tmp_path / name
    db_dir.mkdir()
    meta = {
        "source_filename": "test.GPS",
        "file_size": len(gps_content),
        "sha256": hashlib.sha256(gps_content).hexdigest(),
        "total_message_count": 0,
        "schema_version": "1",
        "writer_version": "1.0.0",
    }
    if meta_override is not None:
        meta = meta_override
    (db_dir / METADATA_FILENAME).write_text(json.dumps(meta), encoding="utf-8")
    return db_dir


def _write_gps_file(tmp_path: Path, content: bytes, name: str = "test.GPS") -> Path:
    gps = tmp_path / name
    gps.write_bytes(content)
    return gps


def _make_zip(db_dir: Path) -> Path:
    """Create a zip archive matching zip_database() layout: {stem}/files."""
    zip_path = db_dir.parent / f"{db_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in db_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(db_dir.parent))
    return zip_path


# ---------------------------------------------------------------------------
# Directory branch
# ---------------------------------------------------------------------------

class TestDirectoryBranch:
    """Tests for compare() when the database is a directory."""

    def test_happy_path(self, tmp_path):
        """Tests that a GPS file matching its database directory returns valid=True."""
        # Arrange
        content = _gps_bytes()
        db_dir = _write_db_dir(tmp_path, content)
        gps = _write_gps_file(tmp_path, content)
        # Act
        result = compare(db_dir, gps)
        # Assert
        assert result.valid is True
        assert result.reason is None
        assert result.detail is None

    def test_metadata_missing(self, tmp_path):
        """Tests that a directory without _metadata.json returns metadata_missing."""
        # Arrange
        db_dir = tmp_path / "emptydb"
        db_dir.mkdir()
        gps = _write_gps_file(tmp_path, _gps_bytes())
        # Act
        result = compare(db_dir, gps)
        # Assert
        assert result.valid is False
        assert result.reason == "metadata_missing"
        assert result.detail == "first argument"

    @pytest.mark.parametrize("meta_override", [
        {"file_size": 1536},        # sha256 key absent
        {"sha256": "placeholder"},  # file_size key absent
        {},                         # both keys absent
    ], ids=["missing_sha256", "missing_file_size", "both_absent"])
    def test_metadata_incomplete(self, tmp_path, meta_override):
        """Tests that _metadata.json missing file_size or sha256 returns metadata_incomplete."""
        # Arrange
        content = _gps_bytes()
        db_dir = _write_db_dir(tmp_path, content, meta_override=meta_override)
        gps = _write_gps_file(tmp_path, content)
        # Act
        result = compare(db_dir, gps)
        # Assert
        assert result.valid is False
        assert result.reason == "metadata_incomplete"
        assert result.detail == "first argument"

    def test_file_size_mismatch(self, tmp_path):
        """Tests that a GPS file with a different byte count returns file_size_mismatch."""
        # Arrange
        content = _gps_bytes()
        db_dir = _write_db_dir(tmp_path, content)
        gps = _write_gps_file(tmp_path, content + b"\x00")
        # Act
        result = compare(db_dir, gps)
        # Assert
        assert result.valid is False
        assert result.reason == "file_size_mismatch"
        assert result.detail is None

    def test_sha256_mismatch(self, tmp_path):
        """Tests that a GPS file with the same size but different content returns sha256_mismatch."""
        # Arrange
        original = _gps_bytes()
        different = bytes(b ^ 0xFF for b in original)
        assert len(different) == len(original)
        db_dir = _write_db_dir(tmp_path, original)
        gps = _write_gps_file(tmp_path, different)
        # Act
        result = compare(db_dir, gps)
        # Assert
        assert result.valid is False
        assert result.reason == "sha256_mismatch"
        assert result.detail is None

    def test_gps_file_not_found_raises(self, tmp_path):
        """Tests that a non-existent GPS path as the second argument raises FileNotFoundError."""
        # Arrange
        content = _gps_bytes()
        db_dir = _write_db_dir(tmp_path, content)
        # Act & Assert
        with pytest.raises(FileNotFoundError):
            compare(db_dir, tmp_path / "nonexistent.GPS")

    def test_file_not_found_raises_for_first_argument(self, tmp_path):
        """Tests that a non-existent first argument raises FileNotFoundError."""
        # Arrange
        gps = _write_gps_file(tmp_path, _gps_bytes())
        # Act & Assert
        with pytest.raises(FileNotFoundError):
            compare(tmp_path / "nonexistent.GPS", gps)

    def test_order_agnostic(self, tmp_path):
        """Tests that compare() returns the same result regardless of argument order."""
        # Arrange
        content = _gps_bytes()
        db_dir = _write_db_dir(tmp_path, content)
        gps = _write_gps_file(tmp_path, content)
        # Act
        result_db_first = compare(db_dir, gps)
        result_gps_first = compare(gps, db_dir)
        # Assert
        assert result_db_first.valid is True
        assert result_gps_first.valid is True
        assert result_db_first.reason == result_gps_first.reason


# ---------------------------------------------------------------------------
# Zip branch
# ---------------------------------------------------------------------------

class TestZipBranch:
    """Tests for compare() when the database is a .zip archive."""

    def test_happy_path(self, tmp_path):
        """Tests that a GPS file matching its zipped database returns valid=True."""
        # Arrange
        content = _gps_bytes()
        db_dir = _write_db_dir(tmp_path, content)
        gps = _write_gps_file(tmp_path, content)
        zip_path = _make_zip(db_dir)
        # Act
        result = compare(zip_path, gps)
        # Assert
        assert result.valid is True
        assert result.reason is None
        assert result.detail is None

    def test_metadata_missing(self, tmp_path):
        """Tests that a zip archive without _metadata.json returns metadata_missing."""
        # Arrange
        zip_path = tmp_path / "emptydb.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("emptydb/unrelated.txt", "x")
        gps = _write_gps_file(tmp_path, _gps_bytes())
        # Act
        result = compare(zip_path, gps)
        # Assert
        assert result.valid is False
        assert result.reason == "metadata_missing"
        assert result.detail == "first argument"

    def test_metadata_incomplete(self, tmp_path):
        """Tests that a zip archive with an empty _metadata.json returns metadata_incomplete."""
        # Arrange
        zip_path = tmp_path / "testdb.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("testdb/_metadata.json", "{}")
        gps = _write_gps_file(tmp_path, _gps_bytes())
        # Act
        result = compare(zip_path, gps)
        # Assert
        assert result.valid is False
        assert result.reason == "metadata_incomplete"
        assert result.detail == "first argument"

    def test_file_size_mismatch(self, tmp_path):
        """Tests that a GPS file with a different byte count returns file_size_mismatch."""
        # Arrange
        content = _gps_bytes()
        db_dir = _write_db_dir(tmp_path, content)
        zip_path = _make_zip(db_dir)
        gps = _write_gps_file(tmp_path, content + b"\x00")
        # Act
        result = compare(zip_path, gps)
        # Assert
        assert result.valid is False
        assert result.reason == "file_size_mismatch"
        assert result.detail is None

    def test_sha256_mismatch(self, tmp_path):
        """Tests that a GPS file with the same size but different content returns sha256_mismatch."""
        # Arrange
        original = _gps_bytes()
        different = bytes(b ^ 0xFF for b in original)
        db_dir = _write_db_dir(tmp_path, original)
        zip_path = _make_zip(db_dir)
        gps = _write_gps_file(tmp_path, different)
        # Act
        result = compare(zip_path, gps)
        # Assert
        assert result.valid is False
        assert result.reason == "sha256_mismatch"
        assert result.detail is None


# ---------------------------------------------------------------------------
# GPS vs GPS
# ---------------------------------------------------------------------------

class TestGpsVsGps:
    """Tests for compare() with two GPS file arguments."""

    def test_happy_path(self, tmp_path):
        """Tests that two identical GPS files return valid=True."""
        # Arrange
        content = _gps_bytes()
        gps_a = _write_gps_file(tmp_path, content, name="a.GPS")
        gps_b = _write_gps_file(tmp_path, content, name="b.GPS")
        # Act
        result = compare(gps_a, gps_b)
        # Assert
        assert result.valid is True
        assert result.reason is None
        assert result.detail is None

    def test_file_size_mismatch(self, tmp_path):
        """Tests that two GPS files with different byte counts return file_size_mismatch."""
        # Arrange
        content = _gps_bytes()
        gps_a = _write_gps_file(tmp_path, content, name="a.GPS")
        gps_b = _write_gps_file(tmp_path, content + b"\x00", name="b.GPS")
        # Act
        result = compare(gps_a, gps_b)
        # Assert
        assert result.valid is False
        assert result.reason == "file_size_mismatch"
        assert result.detail is None

    def test_sha256_mismatch(self, tmp_path):
        """Tests that two GPS files with the same size but different content return sha256_mismatch."""
        # Arrange
        original = _gps_bytes()
        different = bytes(b ^ 0xFF for b in original)
        assert len(different) == len(original)
        gps_a = _write_gps_file(tmp_path, original, name="a.GPS")
        gps_b = _write_gps_file(tmp_path, different, name="b.GPS")
        # Act
        result = compare(gps_a, gps_b)
        # Assert
        assert result.valid is False
        assert result.reason == "sha256_mismatch"
        assert result.detail is None


# ---------------------------------------------------------------------------
# DB vs DB
# ---------------------------------------------------------------------------

class TestDbVsDb:
    """Tests for compare() with two database arguments."""

    def test_happy_path(self, tmp_path):
        """Tests that two databases derived from the same GPS content return valid=True."""
        # Arrange
        content = _gps_bytes()
        db_a = _write_db_dir(tmp_path, content, name="db_a")
        db_b = _write_db_dir(tmp_path, content, name="db_b")
        # Act
        result = compare(db_a, db_b)
        # Assert
        assert result.valid is True
        assert result.reason is None
        assert result.detail is None

    @pytest.mark.parametrize("bad_arg, expected_detail", [
        ("first", "first argument"),
        ("second", "second argument"),
    ])
    def test_metadata_missing(self, tmp_path, bad_arg, expected_detail):
        """Tests that a database directory without _metadata.json returns metadata_missing."""
        # Arrange
        content = _gps_bytes()
        if bad_arg == "first":
            db_a = tmp_path / "db_a"
            db_a.mkdir()
            db_b = _write_db_dir(tmp_path, content, name="db_b")
        else:
            db_a = _write_db_dir(tmp_path, content, name="db_a")
            db_b = tmp_path / "db_b"
            db_b.mkdir()
        # Act
        result = compare(db_a, db_b)
        # Assert
        assert result.valid is False
        assert result.reason == "metadata_missing"
        assert result.detail == expected_detail

    @pytest.mark.parametrize("bad_arg, expected_detail", [
        ("first", "first argument"),
        ("second", "second argument"),
    ])
    def test_metadata_incomplete(self, tmp_path, bad_arg, expected_detail):
        """Tests that a database with _metadata.json missing required keys returns metadata_incomplete."""
        # Arrange
        content = _gps_bytes()
        if bad_arg == "first":
            db_a = _write_db_dir(tmp_path, content, name="db_a", meta_override={})
            db_b = _write_db_dir(tmp_path, content, name="db_b")
        else:
            db_a = _write_db_dir(tmp_path, content, name="db_a")
            db_b = _write_db_dir(tmp_path, content, name="db_b", meta_override={})
        # Act
        result = compare(db_a, db_b)
        # Assert
        assert result.valid is False
        assert result.reason == "metadata_incomplete"
        assert result.detail == expected_detail

    def test_file_size_mismatch(self, tmp_path):
        """Tests that two databases from different-sized GPS files return file_size_mismatch."""
        # Arrange
        content_a = _gps_bytes()
        content_b = _gps_bytes() + b"\x00"
        db_a = _write_db_dir(tmp_path, content_a, name="db_a")
        db_b = _write_db_dir(tmp_path, content_b, name="db_b")
        # Act
        result = compare(db_a, db_b)
        # Assert
        assert result.valid is False
        assert result.reason == "file_size_mismatch"
        assert result.detail is None

    def test_sha256_mismatch(self, tmp_path):
        """Tests that two databases with the same size but different source hashes return sha256_mismatch."""
        # Arrange
        content = _gps_bytes()
        db_a = _write_db_dir(tmp_path, content, name="db_a")
        db_b = _write_db_dir(tmp_path, content, name="db_b",
                              meta_override={"file_size": len(content), "sha256": "a" * 64})
        # Act
        result = compare(db_a, db_b)
        # Assert
        assert result.valid is False
        assert result.reason == "sha256_mismatch"
        assert result.detail is None


# ---------------------------------------------------------------------------
# .gnsspq extension
# ---------------------------------------------------------------------------

class TestGnsspqExtension:
    """Tests for compare() with .gnsspq archive arguments."""

    def test_happy_path(self, tmp_path):
        """Tests that a .gnsspq archive is treated identically to a .zip archive."""
        # Arrange
        content = _gps_bytes()
        db_dir = _write_db_dir(tmp_path, content)
        zip_path = _make_zip(db_dir)
        gnsspq_path = zip_path.with_suffix(".gnsspq")
        zip_path.rename(gnsspq_path)
        gps = _write_gps_file(tmp_path, content)
        # Act
        result = compare(gnsspq_path, gps)
        # Assert
        assert result.valid is True
        assert result.reason is None
        assert result.detail is None

    def test_metadata_missing(self, tmp_path):
        """Tests that a .gnsspq archive without _metadata.json returns metadata_missing."""
        # Arrange
        zip_path = tmp_path / "emptydb.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("emptydb/unrelated.txt", "x")
        gnsspq_path = zip_path.with_suffix(".gnsspq")
        zip_path.rename(gnsspq_path)
        gps = _write_gps_file(tmp_path, _gps_bytes())
        # Act
        result = compare(gnsspq_path, gps)
        # Assert
        assert result.valid is False
        assert result.reason == "metadata_missing"
        assert result.detail == "first argument"

    def test_order_agnostic_gnsspq_as_second_argument(self, tmp_path):
        """Tests that a .gnsspq archive works correctly as the second argument."""
        # Arrange
        content = _gps_bytes()
        db_dir = _write_db_dir(tmp_path, content)
        zip_path = _make_zip(db_dir)
        gnsspq_path = zip_path.with_suffix(".gnsspq")
        zip_path.rename(gnsspq_path)
        gps = _write_gps_file(tmp_path, content)
        # Act
        result = compare(gps, gnsspq_path)
        # Assert
        assert result.valid is True
