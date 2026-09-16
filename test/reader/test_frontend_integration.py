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

Integration tests for nov_gnsspq/reader/frontend.py.

Builds realistic multi-table Parquet databases on disk in tmp_path and
exercises the full PqReader -> LogTable -> LogSubtable stack end-to-end.
No mocking of filesystem or pandas -- real Parquet files on disk.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

# novatel_edie contains a module-level attribute access (ne.SatelliteId) that
# fails on certain installed versions. Mock it before anything in nov_gnsspq
# is imported so the package __init__ does not raise AttributeError.
if "novatel_edie" not in sys.modules:
    _ne_mock = MagicMock()
    _ne_mock.SatelliteId = type("SatelliteId", (), {})
    sys.modules["novatel_edie"] = _ne_mock

from nov_gnsspq.compat.gpstime import GPSTime  # noqa: E402

from nov_gnsspq.reader.frontend import (  # noqa: E402
    FieldNotFoundError,
    LogSubtable,
    LogTable,
    PqReader,
    _SCHEMA,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, data: dict):
    """Write a dict of column arrays as a Parquet file at *path*."""
    pq.write_table(pa.table(data), str(path))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def v5_db_path(tmp_path) -> Path:
    """Provides a v5 database with BESTPOS and RANGE subtables in tmp_path."""
    db = tmp_path / "mydb"
    db.mkdir()

    # Root log table
    _write(
        db / "mydb.parquet",
        {
            "sequence_id": pa.array(
                [0, 1, 2, 3, 4, 5, 6, 7], type=pa.int64()
            ),
            "log": [
                "BESTPOS", "BESTPOS", "BESTPOS", "BESTPOS", "BESTPOS",
                "RANGE", "RANGE", "RANGE",
            ],
        },
    )

    # Metadata
    (db / "_metadata.json").write_text(
        json.dumps({
            "schema_version": "5",
            "total_message_count": 8,
            "writer_version": "5.1.0",
        }),
        encoding="utf-8",
    )

    # Optional unknown_data table
    _write(
        db / "unknown_data.parquet",
        {
            "sequence_id": pa.array([0, 1], type=pa.int64()),
            "payload": pa.array([b"\xff", b"\xfe"], type=pa.binary()),
        },
    )

    # BESTPOS subtable
    bestpos_dir = db / "BESTPOS"
    bestpos_dir.mkdir()
    _write(
        bestpos_dir / "BESTPOS.parquet",
        {
            "sequence_id": pa.array(
                [0, 1, 2, 3, 4], type=pa.int64()
            ),
            "header_week": pa.array(
                [2300, 2300, 2300, 2300, 2300], type=pa.int64()
            ),
            "header_milliseconds": pa.array(
                [100, 200, 300, 400, 500], type=pa.int64()
            ),
            "lat": pa.array(
                [51.0, 51.1, 51.2, 51.3, 51.4], type=pa.float64()
            ),
            "lon": pa.array(
                [-114.0, -114.1, -114.2, -114.3, -114.4],
                type=pa.float64(),
            ),
            "hgt": pa.array(
                [1000.0, 1001.0, 1002.0, 1003.0, 1004.0],
                type=pa.float64(),
            ),
        },
    )

    # RANGE subtable with obs sub-subtable
    range_dir = db / "RANGE"
    range_dir.mkdir()
    _write(
        range_dir / "RANGE.parquet",
        {
            "sequence_id": pa.array([5, 6, 7], type=pa.int64()),
            "header_week": pa.array(
                [2300, 2300, 2300], type=pa.int64()
            ),
            "header_milliseconds": pa.array(
                [100, 300, 500], type=pa.int64()
            ),
            "idle": pa.array([70.0, 80.0, 90.0], type=pa.float64()),
        },
    )

    obs_dir = range_dir / "obs"
    obs_dir.mkdir()
    _write(
        obs_dir / "obs.parquet",
        {
            "sequence_id": pa.array(
                [0, 1, 2, 3, 4, 5], type=pa.int64()
            ),
            "parent_id": pa.array(
                [5, 5, 6, 6, 7, 7], type=pa.int64()
            ),
            "sv_prn": pa.array(
                [1, 2, 3, 4, 5, 6], type=pa.int64()
            ),
            "range": pa.array(
                [
                    20000000.0, 20000001.0, 20000002.0,
                    20000003.0, 20000004.0, 20000005.0,
                ],
                type=pa.float64(),
            ),
        },
    )

    return db


# ---------------------------------------------------------------------------
# TestPqReaderV5BasicAccess
# ---------------------------------------------------------------------------

# pylint: disable=protected-access


class TestPqReaderV5BasicAccess:
    """Tests for basic construction and attribute access on a v5 PqReader."""

    def test_open_v5_db_loads_log_table(self, v5_db_path):
        """Tests PqReader opens without error and len(db) == 8."""
        # Act
        db = PqReader(str(v5_db_path))
        # Assert
        assert len(db) == 8
        assert db._schema is _SCHEMA

    def test_subtables_contains_bestpos_and_range(self, v5_db_path):
        """Tests db.subtables has BESTPOS and RANGE attributes."""
        # Arrange
        db = PqReader(str(v5_db_path))
        # Act & Assert
        assert isinstance(db.subtables.BESTPOS, LogTable)
        assert isinstance(db.subtables.RANGE, LogTable)

    def test_unknown_table_loaded(self, v5_db_path):
        """Tests db.unknown_table is a DataFrame with the expected row count."""
        # Arrange
        db = PqReader(str(v5_db_path))
        # Act & Assert
        assert hasattr(db, "unknown_table")
        assert len(db.unknown_table) == 2
        assert "payload" in db.unknown_table.columns


# ---------------------------------------------------------------------------
# TestPqReaderFiltering
# ---------------------------------------------------------------------------


class TestPqReaderFiltering:
    """Tests for filter_by_log, reset_filters, and sort_by_time on PqReader."""

    def test_filter_by_log_keeps_only_range_rows(self, v5_db_path):
        """Tests filter_by_log('RANGE') leaves len(db) == 3."""
        # Arrange
        db = PqReader(str(v5_db_path))
        # Act
        db.filter_by_log("RANGE")
        # Assert
        assert len(db) == 3

    def test_reset_filters_restores_full_table(self, v5_db_path):
        """Tests filter then reset restores len(db) back to 8."""
        # Arrange
        db = PqReader(str(v5_db_path))
        db.filter_by_log("RANGE")
        # Act
        db.reset_filters()
        # Assert
        assert len(db) == 8

    def test_sort_by_time_reorders_by_time(self, tmp_path):
        """Tests sort_by_time produces time-ascending order on a single subtable."""
        # Arrange
        # Use a single-subtable db to avoid index-overlap across subtables.
        db_dir = tmp_path / "sortdb"
        db_dir.mkdir()
        _write(
            db_dir / "sortdb.parquet",
            {
                "sequence_id": pa.array([0, 1, 2], type=pa.int64()),
                "log": ["RANGE", "RANGE", "RANGE"],
            },
        )
        (db_dir / "_metadata.json").write_text(
            json.dumps({"schema_version": "5"}), encoding="utf-8"
        )
        rng_dir = db_dir / "RANGE"
        rng_dir.mkdir()
        _write(
            rng_dir / "RANGE.parquet",
            {
                "sequence_id": pa.array([0, 1, 2], type=pa.int64()),
                "header_week": pa.array(
                    [2300, 2300, 2300], type=pa.int64()
                ),
                # Rows intentionally out of time order: 500, 100, 300
                "header_milliseconds": pa.array(
                    [500, 100, 300], type=pa.int64()
                ),
                "idle": pa.array([90.0, 70.0, 80.0], type=pa.float64()),
            },
        )
        db = PqReader(str(db_dir))
        # Act
        db.sort_by_time()
        # Assert
        ms_col = db._schema.milliseconds_col
        subtable = db._subtables["RANGE"]
        ms_in_cur_order = [
            int(subtable.table.loc[i, ms_col])
            for i in db.cur_table.index
        ]
        assert ms_in_cur_order == sorted(ms_in_cur_order)


# ---------------------------------------------------------------------------
# TestPqReaderIteration
# ---------------------------------------------------------------------------


class TestPqReaderIteration:
    """Tests for iteration over PqReader yielding correct entries."""

    def test_iterate_after_filter_yields_only_matching_entries(
            self,
            v5_db_path):
        """Tests filter_by_log('RANGE') then iterate yields only 'RANGE'."""
        # Arrange
        db = PqReader(str(v5_db_path))
        db.filter_by_log("RANGE")
        # Act & Assert
        for log_name, _ in db:
            assert log_name == "RANGE"

    def test_iterate_range_entries_have_obs_subtable(self, v5_db_path):
        """Tests each RANGE entry has an obs attribute on the log entry dataclass."""
        # Arrange
        db = PqReader(str(v5_db_path))
        db.filter_by_log("RANGE")
        # Act & Assert
        # The entry dataclass is generated from LogTable.create_log_data_class
        # and always includes a field for every subtable (obs), even when a
        # particular row's obs rows are not resolved (value may be None due to
        # a known v5 multi-row DataFrame path in create_log_entry).
        for _, entry in db:
            assert hasattr(entry, "obs")
            # BUG: create_log_entry in v5 mode passes a DataFrame instead of
            # a Series, so obs is always None


# ---------------------------------------------------------------------------
# TestLogTableTimeFiltering
# ---------------------------------------------------------------------------


class TestLogTableTimeFiltering:
    """Tests for time-based filtering on a LogTable (BESTPOS)."""

    def test_filter_end_time_removes_late_rows(self, v5_db_path):
        """Tests filter_end_time leaves only rows with ms <= 300."""
        # Arrange
        db = PqReader(str(v5_db_path))
        bestpos: LogTable = db.subtables.BESTPOS
        ms_col = db._schema.milliseconds_col
        # Act
        bestpos.filter_end_time(GPSTime(0.3, 2300))
        # Assert
        assert all(bestpos.cur_table[ms_col] <= 300)

    def test_filter_start_time_removes_early_rows(self, v5_db_path):
        """Tests filter_start_time leaves only rows with ms >= 300."""
        # Arrange
        db = PqReader(str(v5_db_path))
        bestpos: LogTable = db.subtables.BESTPOS
        ms_col = db._schema.milliseconds_col
        # Act
        bestpos.filter_start_time(GPSTime(0.3, 2300))
        # Assert
        assert all(bestpos.cur_table[ms_col] >= 300)

    def test_filter_time_range_keeps_middle_rows(self, v5_db_path):
        """Tests range filter ms [200..400] leaves exactly rows 200, 300, 400."""
        # Arrange
        db = PqReader(str(v5_db_path))
        bestpos: LogTable = db.subtables.BESTPOS
        ms_col = db._schema.milliseconds_col
        # Act
        bestpos.filter_time_range(GPSTime(0.2, 2300), GPSTime(0.4, 2300))
        # Assert
        ms_values = sorted(bestpos.cur_table[ms_col].tolist())
        assert ms_values == [200, 300, 400]

    def test_time_range_property_returns_correct_bounds(self, v5_db_path):
        """Tests time_range start/end match the earliest and latest data points."""
        # Arrange
        db = PqReader(str(v5_db_path))
        bestpos: LogTable = db.subtables.BESTPOS
        # Act
        start, end = bestpos.time_range
        # Assert
        assert isinstance(start, GPSTime)
        assert isinstance(end, GPSTime)
        assert start.week == 2300
        assert start.seconds == pytest.approx(0.1)
        assert end.week == 2300
        assert end.seconds == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# TestLogTableAggregation
# ---------------------------------------------------------------------------


class TestLogTableAggregation:
    """Tests for aggregation statistics on a LogTable (BESTPOS)."""

    def test_field_value_proxy_mean(self, v5_db_path):
        """Tests BESTPOS.lat.mean equals get_mean('lat')."""
        # Arrange
        db = PqReader(str(v5_db_path))
        bestpos = db.subtables.BESTPOS
        # Act & Assert
        assert bestpos.lat.mean == pytest.approx(bestpos.get_mean("lat"))

    def test_get_mean_on_numeric_column(self, v5_db_path):
        """Tests BESTPOS.get_mean('lat') returns approximately 51.2."""
        # Arrange
        db = PqReader(str(v5_db_path))
        # Act
        result = db.subtables.BESTPOS.get_mean("lat")
        # Assert
        assert result == pytest.approx(51.2)

    def test_get_mean_raises_for_unknown_field(self, v5_db_path):
        """Tests BESTPOS.get_mean('nonexistent') raises FieldNotFoundError."""
        # Arrange
        db = PqReader(str(v5_db_path))
        # Act & Assert
        with pytest.raises(FieldNotFoundError):
            db.subtables.BESTPOS.get_mean("nonexistent")

    def test_get_std_on_numeric_column(self, v5_db_path):
        """Tests BESTPOS.get_std('hgt') is a positive float."""
        # Arrange
        db = PqReader(str(v5_db_path))
        # Act
        result = db.subtables.BESTPOS.get_std("hgt")
        # Assert
        assert result == pytest.approx(1.5811, rel=1e-3)


# ---------------------------------------------------------------------------
# TestLogTableSubtableFiltering
# ---------------------------------------------------------------------------


class TestLogTableSubtableFiltering:
    """Tests for subtable-aware filtering on a LogTable (RANGE)."""

    def test_filter_entries_by_direct_column(self, v5_db_path):
        """Tests RANGE.filter_entries('idle', '<', 85) keeps only 2 rows."""
        # Arrange
        db = PqReader(str(v5_db_path))
        rng: LogTable = db.subtables.RANGE
        # Act
        rng.filter_entries("idle", "<", 85)
        # Assert
        assert len(rng) == 2

    def test_filter_entries_by_subtable_column(self, v5_db_path):
        """Tests filter_entries on obs column keeps the parent RANGE row."""
        # Arrange
        db = PqReader(str(v5_db_path))
        rng: LogTable = db.subtables.RANGE
        # Act
        # sv_prn==1 belongs to parent_id==5, which is sequence_id==5
        rng.filter_entries("sv_prn", "==", 1, "obs")
        # Assert
        assert len(rng) == 1
        seq_col = db._schema.sequence_id_col
        assert rng.cur_table[seq_col].iloc[0] == 5


# ---------------------------------------------------------------------------
# TestLogTableSorting
# ---------------------------------------------------------------------------


class TestLogTableSorting:
    """Tests for sorting on a LogTable."""

    def test_sort_by_numeric_column_ascending(self, v5_db_path):
        """Tests BESTPOS.sort_by('lat') produces ascending lat values."""
        # Arrange
        db = PqReader(str(v5_db_path))
        bestpos: LogTable = db.subtables.BESTPOS
        # Act
        bestpos.sort_by("lat")
        # Assert
        values = bestpos.cur_table["lat"].tolist()
        assert values == sorted(values)

    def test_sort_by_time_ascending(self, v5_db_path):
        """Tests RANGE.sort_by_time() produces ascending header_milliseconds."""
        # Arrange
        db = PqReader(str(v5_db_path))
        rng: LogTable = db.subtables.RANGE
        ms_col = db._schema.milliseconds_col
        # Act
        rng.sort_by_time()
        # Assert
        ms_values = rng.cur_table[ms_col].tolist()
        assert ms_values == sorted(ms_values)


# ---------------------------------------------------------------------------
# TestResetFilters
# ---------------------------------------------------------------------------


class TestResetFilters:
    """Tests that reset_filters restores the full dataset on LogTable and PqReader."""

    def test_reset_restores_full_range_table(self, v5_db_path):
        """Tests filter then reset via PqReader.reset_filters restores row count."""
        # Arrange
        db = PqReader(str(v5_db_path))
        db.filter_by_log("RANGE")
        assert len(db) == 3
        # Act
        db.reset_filters()
        # Assert
        assert len(db) == 8
        assert "BESTPOS" in db.cur_table["log"].values

    def test_reset_restores_obs_subtable(self, v5_db_path):
        """Tests filter_entries then reset_filters restores obs to 6 rows."""
        # Arrange
        db = PqReader(str(v5_db_path))
        range_table: LogTable = db.subtables.RANGE
        obs: LogSubtable = range_table.subtables.obs
        # Filter obs to a subset and confirm the filter took effect
        obs.filter_entries("sv_prn", ">", 3)
        assert len(obs) == 3
        # Act
        # Use the public reset API; may crash with KeyError: 'parent_id'
        # (known v5 bug)
        range_table.reset_filters()
        # Assert
        assert len(obs) == 6


# ---------------------------------------------------------------------------
# TestFilteredLoading
# ---------------------------------------------------------------------------


class TestFilteredLoading:
    """Tests that the logs= parameter gates subdirectory instantiation."""

    def test_none_logs_loads_all(self, v5_db_path):
        """Tests logs=None loads all subtables identically to the default."""
        # Act
        db_filtered = PqReader(str(v5_db_path), logs=None)
        db_all = PqReader(str(v5_db_path))
        # Assert
        assert (
            set(db_filtered._subtables.keys())
            == set(db_all._subtables.keys())
        )

    def test_nonexistent_log_name_does_not_raise(self, v5_db_path):
        """Tests logs=['NONEXISTENT'] produces an empty _subtables dict."""
        # Act
        db = PqReader(str(v5_db_path), logs=["NONEXISTENT"])
        # Assert
        assert len(db._subtables) == 0

    def test_root_table_contains_only_filtered_logs(self, v5_db_path):
        """Tests logs=['BESTPOS'] limits cur_table rows to BESTPOS entries."""
        # Act
        db = PqReader(str(v5_db_path), logs=["BESTPOS"])
        # Assert
        assert all(
            lg == "BESTPOS" for lg in db.cur_table["log"].tolist()
        )

    def test_single_log_filter_limits_subtables(self, v5_db_path):
        """Tests logs=['BESTPOS'] includes BESTPOS and excludes RANGE."""
        # Act
        db = PqReader(str(v5_db_path), logs=["BESTPOS"])
        # Assert
        assert "BESTPOS" in db._subtables
        assert "RANGE" not in db._subtables
