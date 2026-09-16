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

End-to-end integration tests for PqConverter.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from nov_gnsspq.reader.schema import METADATA_FILENAME, SEQUENCE_ID_COL
from nov_gnsspq.writer.generator import PqConverter
from nov_gnsspq.writer.parallel.engine import PARALLEL_MIN_BYTES

# Runs against the committed sample recording by default. Set
# NOV_GNSSPQ_TEST_GPS to point at a longer recording -- for example the
# multi-hundred-megabyte capture that is not committed -- to exercise the
# same assertions over more data.
_REPO_ROOT = Path(__file__).resolve().parents[1]
GPS_FILE = os.environ.get(
    "NOV_GNSSPQ_TEST_GPS",
    str(_REPO_ROOT / "resources" / "sample.GPS"),
)
GPS_NAME = os.path.basename(GPS_FILE)

#: ParallelGPSWriter delegates to the single-threaded writer below this
#: size, so the parallel-only metadata fields are not emitted.
_RUNS_PARALLEL = (
    os.path.exists(GPS_FILE)
    and os.path.getsize(GPS_FILE) >= PARALLEL_MIN_BYTES
)

pytestmark = pytest.mark.skipif(
    not os.path.exists(GPS_FILE),
    reason=f"GPS recording not found at: {GPS_FILE}",
)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _load_meta(db_path: Path) -> dict:
    """Loads and returns the metadata JSON from a database output directory.

    Args:
        db_path: Path to the PqConverter output directory.

    Returns:
        meta: Parsed metadata dictionary.
    """
    with open(db_path / METADATA_FILENAME) as f:
        return json.load(f)


def _log_table(db_path: Path):
    """Reads and returns the root log Parquet table for a database directory.

    Args:
        db_path: Path to the PqConverter output directory.

    Returns:
        table: PyArrow Table for the root log Parquet file.
    """
    return pq.read_table(str(db_path / f"{db_path.name}.parquet"))


def _message_type_parquets(db_path: Path) -> list[Path]:
    """Returns all Parquet files that are not the root log or unknown tables.

    Args:
        db_path: Path to the PqConverter output directory.

    Returns:
        parquets: List of Paths to message-type Parquet files.
    """
    root_parquets = {
        db_path / f"{db_path.name}.parquet",
        db_path / "unknown_data.parquet",
    }
    return [
        p for p in db_path.rglob("*.parquet")
        if p not in root_parquets
    ]


# pylint: disable=protected-access


class TestStandardMode:
    """Tests for standard (sequential) PqConverter output."""

    @pytest.fixture(scope="session")
    def standard_db(self, tmp_path_factory) -> Path:
        """Provides a PqConverter output directory from a standard-mode run."""
        # Arrange
        out = tmp_path_factory.mktemp("standard_db")
        # Act
        with PqConverter(str(out)) as db:
            db.consume(GPS_FILE)
        # Assert
        return out

    def test_metadata_file_exists(self, standard_db):
        """Tests that _metadata.json is present after a standard-mode run."""
        # Act & Assert
        assert (standard_db / METADATA_FILENAME).exists()

    def test_metadata_has_required_fields(self, standard_db):
        """Tests that _metadata.json contains all mandatory fields."""
        # Arrange
        required = (
            "total_message_count",
            "schema_version",
            "writer_version",
            "source_filename",
            "sha256",
            "file_size",
        )
        # Act
        meta = _load_meta(standard_db)
        # Assert
        for field in required:
            assert field in meta, f"Missing field: {field}"

    def test_source_filename_is_correct(self, standard_db):
        """Tests that source_filename matches the input file basename."""
        # Act
        meta = _load_meta(standard_db)
        # Assert
        assert meta["source_filename"] == GPS_NAME

    def test_total_message_count_is_positive(self, standard_db):
        """Tests that total_message_count is greater than zero."""
        # Act
        meta = _load_meta(standard_db)
        # Assert
        assert meta["total_message_count"] > 0

    def test_log_table_exists(self, standard_db):
        """Tests that a log-index Parquet file named after the output dir exists."""
        # Arrange
        log_path = standard_db / f"{standard_db.name}.parquet"
        # Act & Assert
        assert log_path.exists(), f"Log table not found: {log_path}"

    def test_log_table_row_count_matches_metadata(self, standard_db):
        """Tests that log table row count equals total_message_count."""
        # Act
        meta = _load_meta(standard_db)
        log_table = _log_table(standard_db)
        # Assert
        assert log_table.num_rows == meta["total_message_count"], (
            f"Log rows {log_table.num_rows} != "
            f"metadata count {meta['total_message_count']}"
        )

    def test_log_table_has_sequence_id_column(self, standard_db):
        """Tests that the log table contains a sequence_id column."""
        # Act
        log_table = _log_table(standard_db)
        # Assert
        assert SEQUENCE_ID_COL in log_table.schema.names

    def test_log_table_sequence_ids_are_contiguous(self, standard_db):
        """Tests that sequence_ids run 0 ... N-1 with no gaps."""
        # Act
        log_table = _log_table(standard_db)
        seq_ids = log_table[SEQUENCE_ID_COL].to_pylist()
        expected = list(range(len(seq_ids)))
        # Assert
        assert seq_ids == expected, "sequence_id gaps detected in log table"

    def test_unknown_data_parquet_exists(self, standard_db):
        """Tests that unknown_data.parquet is always created."""
        # Act & Assert
        assert (standard_db / "unknown_data.parquet").exists()

    def test_at_least_one_message_type_directory_written(self, standard_db):
        """Tests that at least one message-type Parquet file is written."""
        # Act
        type_parquets = _message_type_parquets(standard_db)
        # Assert
        assert len(type_parquets) > 0, "No message-type Parquet files found"

    def test_message_type_parquets_are_readable(self, standard_db):
        """Tests that every message-type Parquet file is readable by PyArrow."""
        # Act & Assert
        for parquet_path in _message_type_parquets(standard_db):
            table = pq.read_table(str(parquet_path))
            assert table.num_rows > 0, f"Empty table: {parquet_path}"

    def test_message_type_parquets_contain_sequence_id(self, standard_db):
        """Tests that every message-type Parquet file has a sequence_id column."""
        # Act & Assert
        for parquet_path in _message_type_parquets(standard_db):
            table = pq.read_table(str(parquet_path))
            assert SEQUENCE_ID_COL in table.schema.names, (
                f"{parquet_path} missing sequence_id column"
            )


class TestParallelMode:
    """Tests for parallel PqConverter output."""

    @pytest.fixture(scope="session")
    def parallel_db(self, tmp_path_factory) -> Path:
        """Provides a PqConverter output directory from a parallel-mode run."""
        # Arrange
        out = tmp_path_factory.mktemp("parallel_db")
        # Act
        with PqConverter(str(out), parallel=True) as db:
            db.consume(GPS_FILE)
        # Assert
        return out

    def test_metadata_file_exists(self, parallel_db):
        """Tests that _metadata.json is present after a parallel-mode run."""
        # Act & Assert
        assert (parallel_db / METADATA_FILENAME).exists()

    def test_metadata_has_required_fields(self, parallel_db):
        """Tests that _metadata.json contains all mandatory fields in parallel mode."""
        # Arrange
        required = (
            "total_message_count",
            "schema_version",
            "writer_version",
            "source_filename",
            "sha256",
            "file_size",
        )
        # Act
        meta = _load_meta(parallel_db)
        # Assert
        for field in required:
            assert field in meta, f"Missing field (parallel): {field}"

    @pytest.mark.skipif(
        not _RUNS_PARALLEL,
        reason=(
            "recording is below PARALLEL_MIN_BYTES, so ParallelGPSWriter "
            "delegates to GPSWriter and emits no parallel_workers field"
        ),
    )
    def test_parallel_workers_field_is_positive(self, parallel_db):
        """Tests that parallel_workers is at least 1."""
        # Act
        meta = _load_meta(parallel_db)
        # Assert
        assert meta["parallel_workers"] >= 1

    def test_total_message_count_is_positive(self, parallel_db):
        """Tests that total_message_count is greater than zero in parallel mode."""
        # Act
        meta = _load_meta(parallel_db)
        # Assert
        assert meta["total_message_count"] > 0

    def test_log_table_exists(self, parallel_db):
        """Tests that a log-index Parquet file exists in parallel mode."""
        # Arrange
        log_path = parallel_db / f"{parallel_db.name}.parquet"
        # Act & Assert
        assert log_path.exists(), f"Log table not found: {log_path}"

    def test_log_table_row_count_matches_metadata(self, parallel_db):
        """Tests that log table row count equals total_message_count in parallel."""
        # Act
        meta = _load_meta(parallel_db)
        log_table = _log_table(parallel_db)
        # Assert
        assert log_table.num_rows == meta["total_message_count"], (
            f"Log rows {log_table.num_rows} != "
            f"metadata count {meta['total_message_count']}"
        )

    def test_unknown_data_parquet_exists(self, parallel_db):
        """Tests that unknown_data.parquet is created in parallel mode."""
        # Act & Assert
        assert (parallel_db / "unknown_data.parquet").exists()

    def test_at_least_one_message_type_directory_written(self, parallel_db):
        """Tests that at least one message-type Parquet file exists in parallel."""
        # Act
        type_parquets = _message_type_parquets(parallel_db)
        # Assert
        assert len(type_parquets) > 0, (
            "No message-type Parquet files found (parallel)"
        )

    def test_message_type_parquets_are_readable(self, parallel_db):
        """Tests that every message-type Parquet file is readable in parallel mode."""
        # Act & Assert
        for parquet_path in _message_type_parquets(parallel_db):
            table = pq.read_table(str(parquet_path))
            assert table.num_rows > 0, f"Empty table (parallel): {parquet_path}"

    def test_sha256_matches_file_on_disk(self, parallel_db):
        """Tests that the stored sha256 matches the actual file hash."""
        # Arrange
        meta = _load_meta(parallel_db)
        h = hashlib.sha256()
        # Act
        with open(GPS_FILE, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        # Assert
        assert h.hexdigest() == meta["sha256"]


class TestCrossModConsistency:
    """Tests that standard and parallel modes produce consistent output."""

    @pytest.fixture(scope="session")
    def standard_db(self, tmp_path_factory) -> Path:
        """Provides a PqConverter output directory from a standard-mode run."""
        out = tmp_path_factory.mktemp("xmode_standard_db")
        with PqConverter(str(out)) as db:
            db.consume(GPS_FILE)
        return out

    @pytest.fixture(scope="session")
    def parallel_db(self, tmp_path_factory) -> Path:
        """Provides a PqConverter output directory from a parallel-mode run."""
        out = tmp_path_factory.mktemp("xmode_parallel_db")
        with PqConverter(str(out), parallel=True) as db:
            db.consume(GPS_FILE)
        return out

    def test_total_message_count_is_equal(self, standard_db, parallel_db):
        """Tests that both modes report the same total_message_count."""
        # Act
        std_meta = _load_meta(standard_db)
        par_meta = _load_meta(parallel_db)
        # Assert
        assert std_meta["total_message_count"] == par_meta["total_message_count"], (
            f"Count mismatch -- standard: {std_meta['total_message_count']}, "
            f"parallel: {par_meta['total_message_count']}"
        )

    def test_log_table_message_type_sets_are_equal(
            self, standard_db, parallel_db):
        """Tests that both modes produce the same set of distinct message types."""
        # Act
        std_types = set(_log_table(standard_db)["log"].to_pylist())
        par_types = set(_log_table(parallel_db)["log"].to_pylist())
        # Assert
        assert std_types == par_types, (
            f"Type mismatch -- only in standard: {std_types - par_types}, "
            f"only in parallel: {par_types - std_types}"
        )

    def test_sha256_recorded_consistently(self, standard_db, parallel_db):
        """Tests that both modes record the same file sha256."""
        # Act
        std_sha = _load_meta(standard_db)["sha256"]
        par_sha = _load_meta(parallel_db)["sha256"]
        # Assert
        assert std_sha == par_sha, (
            "sha256 mismatch between standard and parallel"
        )
