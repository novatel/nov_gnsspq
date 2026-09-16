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

Unit tests for nov_gnsspq.writer.generator.zip_database.
"""
import zipfile
from pathlib import Path

from nov_gnsspq.writer.generator import zip_database


# pylint: disable=protected-access


class TestZipDatabase:
    """Tests for the zip_database function."""

    def test_archive_created_next_to_output_dir(self, tmp_path):
        """Tests archive lands at {parent}/{basename}.gnsspq."""
        # Arrange
        db_dir = tmp_path / "my_db"
        db_dir.mkdir()
        (db_dir / "log_table.parquet").write_bytes(b"parquet")
        # Act
        result = zip_database(db_dir)
        # Assert
        assert result == tmp_path / "my_db.gnsspq"
        assert result.exists()

    def test_archive_contains_all_files_with_relative_paths(self, tmp_path):
        """Tests all files are stored under {basename}/... inside the archive."""
        # Arrange
        db_dir = tmp_path / "survey"
        db_dir.mkdir()
        (db_dir / "log_table.parquet").write_bytes(b"a")
        sub = db_dir / "BESTPOS"
        sub.mkdir()
        (sub / "BESTPOS.parquet").write_bytes(b"b")
        # Act
        zip_database(db_dir)
        # Assert
        with zipfile.ZipFile(tmp_path / "survey.gnsspq") as zf:
            names = zf.namelist()
        assert "survey/log_table.parquet" in names
        assert "survey/BESTPOS/BESTPOS.parquet" in names

    def test_original_directory_preserved(self, tmp_path):
        """Tests the source directory still exists after zipping."""
        # Arrange
        db_dir = tmp_path / "my_db"
        db_dir.mkdir()
        (db_dir / "log_table.parquet").write_bytes(b"x")
        # Act
        zip_database(db_dir)
        # Assert
        assert db_dir.is_dir()
        assert (db_dir / "log_table.parquet").exists()

    def test_existing_archive_overwritten(self, tmp_path):
        """Tests a pre-existing archive at the target path is silently replaced."""
        # Arrange
        db_dir = tmp_path / "my_db"
        db_dir.mkdir()
        (db_dir / "a.parquet").write_bytes(b"new")
        archive_path = tmp_path / "my_db.gnsspq"
        archive_path.write_bytes(b"stale")
        # Act
        zip_database(db_dir)
        # Assert
        with zipfile.ZipFile(archive_path) as zf:
            names = zf.namelist()
        assert names == ["my_db/a.parquet"]

    def test_returns_path_object(self, tmp_path):
        """Tests return type is Path."""
        # Arrange
        db_dir = tmp_path / "my_db"
        db_dir.mkdir()
        (db_dir / "f.parquet").write_bytes(b"x")
        # Act
        result = zip_database(db_dir)
        # Assert
        assert isinstance(result, Path)
