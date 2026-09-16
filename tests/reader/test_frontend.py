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

Unit tests for nov_gnsspq/reader/frontend.py public API.
"""
import datetime
import json
import os
import sys
from unittest.mock import MagicMock, patch
import zipfile

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

# novatel_edie contains a module-level attribute access (ne.SatelliteId) that
# fails on certain installed versions. Mock it before anything in
# nov_gnsspq.writer is imported so the package __init__ does not raise
# AttributeError.
if "novatel_edie" not in sys.modules:
    _ne_mock = MagicMock()
    _ne_mock.SatelliteId = MagicMock()
    sys.modules["novatel_edie"] = _ne_mock

from nov_gnsspq.compat.gpstime import GPSTime  # noqa: E402

from nov_gnsspq.reader.frontend import (  # noqa: E402
    FieldNotFoundError,
    FieldValue,
    LogFrame,
    LogSubtable,
    LogTable,
    LogTableFrame,
    PqReader,
    SchemaConfig,
    Utils,
    _SCHEMA,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_parquet(path: str, data: dict):
    """Write *data* dict as a Parquet file at *path* using pyarrow."""
    pq.write_table(pa.table(data), path)


def make_simple_logtable(tmp_path, data: dict | None = None, schema=None):
    """Return a LogTable backed by a real Parquet file in *tmp_path*."""
    if data is None:
        data = {
            "sequence_id": [0, 1, 2],
            "header_week": [2200, 2200, 2201],
            "header_milliseconds": [100_000, 200_000, 50_000],
            "value": [10, 20, 30],
        }
    if schema is None:
        schema = _SCHEMA
    write_parquet(str(tmp_path / "test.parquet"), data)
    return LogTable("test", str(tmp_path), schema=schema)


# pylint: disable=protected-access


# ---------------------------------------------------------------------------
# SchemaConfig
# ---------------------------------------------------------------------------


class TestSchemaConfig:
    """Tests for the SchemaConfig dataclass."""

    def test_time_columns_returns_week_and_milliseconds(self):
        """Tests time_columns returns [week_col, milliseconds_col]."""
        # Arrange
        cfg = SchemaConfig(
            week_col="w",
            milliseconds_col="ms",
            sequence_id_col="seq",
        )
        # Act & Assert
        assert cfg.time_columns == ["w", "ms"]


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------


class TestUtilsConvertTimeFormat:
    """Tests for Utils.convert_time_format."""

    def test_converts_datetime_to_gpstime(self):
        """Tests convert_time_format converts a datetime input to GPSTime."""
        # Arrange
        dt = datetime.datetime(2023, 6, 1, 12, 0, 0)
        # Act
        result = Utils.convert_time_format(dt)
        # Assert
        assert isinstance(result, GPSTime)

    def test_returns_gpstime_unchanged(self):
        """Tests convert_time_format returns a GPSTime input as-is."""
        # Arrange
        gps = GPSTime(100.0, 2200)
        # Act
        result = Utils.convert_time_format(gps)
        # Assert
        assert result is gps


class TestUtilsStringifyTree:
    """Tests for Utils.stringify_tree and _stringify_tree_recursive.

    Tree format: top-level dict has one root key whose value is a dict of
    branches. Each branch value is either a nested dict (rendered as a
    sub-tree) or a non-dict scalar (printed directly as a leaf line).
    """

    def test_multi_level_tree_renders_correctly(self):
        """Tests stringify_tree renders all node labels in a three-level tree."""
        # Arrange
        # Leaf is a non-dict value inside the branch dict so it is printed
        # directly (the value string is the leaf label, not the key).
        tree = {"root": {"branch": {"leaf_key": "leaf_label"}}}
        # Act
        result = Utils.stringify_tree(tree)
        # Assert
        assert "root" in result
        assert "branch" in result
        assert "leaf_label" in result

    def test_multiple_siblings_use_correct_connectors(self):
        """Tests stringify_tree uses correct branch connectors for siblings."""
        # Arrange
        # Two branches: first uses corner connector, second (last) uses T-connector
        tree = {"root": {"a": {}, "b": {}}}
        # Act
        result = Utils.stringify_tree(tree)
        # Assert
        assert "├──" in result
        assert "└──" in result

    def test_single_level_tree_renders_root_and_branch(self):
        """Tests stringify_tree renders root and branch for a one-level tree."""
        # Arrange
        # {"root": {"branch": {}}} -- branch has no children
        tree = {"root": {"branch": {}}}
        # Act
        result = Utils.stringify_tree(tree)
        # Assert
        assert result.startswith("root\n")
        assert "branch" in result


# ---------------------------------------------------------------------------
# LogFrame
# ---------------------------------------------------------------------------


class TestLogFrame:
    """Tests for LogFrame.__init__ and basic methods (filesystem mocked)."""

    @pytest.fixture()
    def mock_df(self):
        """Provides a simple two-column DataFrame."""
        return pd.DataFrame({"col1": [1, 2, 3], "col2": [4, 5, 6]})

    @pytest.fixture()
    def frame(self, mock_df):
        """Provides a LogFrame with mocked filesystem and parquet reads."""
        with (
            patch(
                "nov_gnsspq.reader.frontend.pd.read_parquet",
                return_value=mock_df,
            ),
            patch(
                "nov_gnsspq.reader.frontend.os.listdir",
                return_value=[],
            ),
            patch(
                "nov_gnsspq.reader.frontend.os.path.isdir",
                return_value=False,
            ),
        ):
            return LogFrame("mytable", "/fake/path", schema=_SCHEMA)

    def test_check_time_info_raises_when_columns_absent(self, mock_df):
        """Tests _check_time_info raises FieldNotFoundError for missing columns."""
        # Arrange
        with (
            patch(
                "nov_gnsspq.reader.frontend.pd.read_parquet",
                return_value=mock_df,
            ),
            patch(
                "nov_gnsspq.reader.frontend.os.listdir",
                return_value=[],
            ),
            patch(
                "nov_gnsspq.reader.frontend.os.path.isdir",
                return_value=False,
            ),
        ):
            frame = LogFrame("mytable", "/fake/path", schema=_SCHEMA)
        # Act & Assert
        with pytest.raises(FieldNotFoundError):
            frame._check_time_info()

    def test_cur_table_initially_equals_table(self, frame):
        """Tests cur_table initially references the same object as table."""
        # Act & Assert
        assert frame.cur_table is frame.table

    def test_get_columns_includes_subtable_columns(self, mock_df):
        """Tests get_columns includes columns from subtables when present."""
        # Arrange
        subtable_mock = MagicMock(spec=LogFrame)
        subtable_mock.get_columns.return_value = ["sub_col"]
        with (
            patch(
                "nov_gnsspq.reader.frontend.pd.read_parquet",
                return_value=mock_df,
            ),
            patch(
                "nov_gnsspq.reader.frontend.os.listdir",
                return_value=[],
            ),
            patch(
                "nov_gnsspq.reader.frontend.os.path.isdir",
                return_value=False,
            ),
        ):
            frame = LogFrame("mytable", "/fake/path", schema=_SCHEMA)
        frame._subtables = {"sub": subtable_mock}
        # Act
        cols = frame.get_columns()
        # Assert
        assert "col1" in cols
        assert "sub_col" in cols

    def test_get_columns_returns_main_table_columns(self, frame):
        """Tests get_columns returns the column names from the main table."""
        # Act & Assert
        assert set(frame.get_columns()) == {"col1", "col2"}

    def test_len_returns_cur_table_row_count(self, frame):
        """Tests __len__ returns the number of rows in cur_table."""
        # Act & Assert
        assert len(frame) == 3

    def test_repr_is_non_empty_and_contains_table_name(self, frame):
        """Tests __repr__ returns a string containing the table_name."""
        # Act
        r = repr(frame)
        # Assert
        assert "mytable" in r

    def test_stores_folder_path(self, frame):
        """Tests constructor stores the folder_path attribute."""
        # Act & Assert
        assert frame.folder_path == "/fake/path"

    def test_stores_schema(self, frame):
        """Tests constructor stores the _schema attribute."""
        # Act & Assert
        assert frame._schema is _SCHEMA

    def test_stores_table_name(self, frame):
        """Tests constructor stores the table_name attribute."""
        # Act & Assert
        assert frame.table_name == "mytable"

    def test_subtables_empty_when_no_subdirectories(self, frame):
        """Tests _subtables is empty when the folder has no subdirectories."""
        # Act & Assert
        assert frame._subtables == {}

    def test_table_is_dataframe_from_read_parquet(self, frame, mock_df):
        """Tests table attribute is the DataFrame returned by pd.read_parquet."""
        # Act & Assert
        pd.testing.assert_frame_equal(frame.table, mock_df)


# ---------------------------------------------------------------------------
# PqReader
# ---------------------------------------------------------------------------


class TestPqReader:
    """Tests for PqReader construction and filter methods."""

    def _make_db(
            self,
            tmp_path,
            metadata_content=None,
            with_unknown=False):
        """Build a minimal real PqReader on disk."""
        db_dir = tmp_path / "mydb"
        db_dir.mkdir()
        write_parquet(
            str(db_dir / "mydb.parquet"),
            {"index": [0, 1, 2], "log": ["A", "B", "A"]},
        )
        if metadata_content is not None:
            (db_dir / "_metadata.json").write_text(
                json.dumps(metadata_content), encoding="utf-8"
            )
        if with_unknown:
            write_parquet(
                str(db_dir / "unknown_data.parquet"),
                {"payload": [b"\xff", b"\xfe"]},
            )
        return PqReader(str(db_dir))

    def test_filter_by_log_reduces_cur_table(self, tmp_path):
        """Tests filter_by_log keeps only rows matching the given log name."""
        # Arrange
        db = self._make_db(tmp_path)
        # Act
        db.filter_by_log("A")
        # Assert
        assert all(db.cur_table["log"] == "A")

    def test_reset_filters_restores_full_table(self, tmp_path):
        """Tests reset_filters restores cur_table to the original full table."""
        # Arrange
        db = self._make_db(tmp_path)
        original_len = len(db.cur_table)
        db.filter_by_log("A")
        # Act
        db.reset_filters()
        # Assert
        assert len(db.cur_table) == original_len

    def test_sort_by_time_reorders_by_week_then_milliseconds(self, tmp_path):
        """Tests sort_by_time reorders cur_table in ascending time order."""
        # Arrange
        db_dir = tmp_path / "mydb"
        db_dir.mkdir()
        write_parquet(
            str(db_dir / "mydb.parquet"),
            {"sequence_id": [0, 1, 2], "log": ["T", "T", "T"]},
        )
        # Subtable with time columns in non-sorted order
        t_dir = db_dir / "T"
        t_dir.mkdir()
        write_parquet(
            str(t_dir / "T.parquet"),
            {
                "sequence_id": [0, 1, 2],
                "header_week": [2200, 2201, 2200],
                "header_milliseconds": [500_000, 100_000, 100_000],
            },
        )
        db = PqReader(str(db_dir))
        # Act
        db.sort_by_time()
        # Assert
        # The (header_week, header_milliseconds) pairs from the T subtable,
        # retrieved in the order dictated by db.cur_table, must be ascending.
        week_col = db._schema.week_col
        ms_col = db._schema.milliseconds_col
        t_table = db._subtables["T"].table
        pairs = [
            (t_table.loc[i, week_col], t_table.loc[i, ms_col])
            for i in db.cur_table.index
        ]
        assert pairs == sorted(pairs)

    def test_unknown_table_absent_when_file_missing(self, tmp_path):
        """Tests unknown_table is not set when unknown_data.parquet is missing."""
        # Arrange
        db = self._make_db(tmp_path)
        # Act & Assert
        assert not hasattr(db, "unknown_table")

    def test_unknown_table_set_when_file_exists(self, tmp_path):
        """Tests unknown_table is a DataFrame when unknown_data.parquet exists."""
        # Arrange
        db = self._make_db(tmp_path, with_unknown=True)
        # Act & Assert
        assert hasattr(db, "unknown_table")
        assert isinstance(db.unknown_table, pd.DataFrame)

    def test_uses_default_schema(self, tmp_path):
        """Tests PqReader always uses the default schema."""
        db = self._make_db(tmp_path)
        assert db._schema is _SCHEMA

    # --- Regression tests ---------------------------------------------------

    def test_sort_by_time_two_subtables_no_index_overlap(self, tmp_path):
        """Regression: sort_by_time must use sequence_id not subtable indices.

        Before the fix, each subtable's DataFrame had 0-based integer indices
        that overlapped between subtables.  The old implementation used those
        raw indices to reindex cur_table, producing wrong or duplicate rows.
        """
        # Arrange: two subtables A and B, each with 0-based DataFrame indices
        db_dir = tmp_path / "mydb"
        db_dir.mkdir()
        write_parquet(
            str(db_dir / "mydb.parquet"),
            {"sequence_id": [0, 1, 2, 3], "log": ["A", "B", "A", "B"]},
        )
        a_dir = db_dir / "A"
        a_dir.mkdir()
        write_parquet(
            str(a_dir / "A.parquet"),
            {
                "sequence_id": [0, 2],
                "header_week": [2200, 2200],
                "header_milliseconds": [500_000, 100_000],
            },
        )
        b_dir = db_dir / "B"
        b_dir.mkdir()
        write_parquet(
            str(b_dir / "B.parquet"),
            {
                "sequence_id": [1, 3],
                "header_week": [2200, 2201],
                "header_milliseconds": [200_000, 50_000],
            },
        )
        db = PqReader(str(db_dir))
        # Act
        db.sort_by_time()
        # Assert: seq 2=(2200,100k) < seq 1=(2200,200k) < seq 0=(2200,500k) < seq 3=(2201,50k)
        assert list(db.cur_table["sequence_id"]) == [2, 1, 0, 3]

    def test_iter_first_match_used_when_sequence_id_nonunique(self, tmp_path):
        """Regression: __iter__ must take iloc[0] when seq_id is non-unique.

        Before the fix, a duplicate seq_id caused a DataFrame (not a Series)
        to be passed to create_log_entry, making row.to_dict() return
        {col: Series} instead of {col: scalar}, producing a malformed entry.
        """
        # Arrange: subtable has two rows with the same sequence_id
        db_dir = tmp_path / "mydb"
        db_dir.mkdir()
        write_parquet(
            str(db_dir / "mydb.parquet"),
            {"sequence_id": [0], "log": ["A"]},
        )
        a_dir = db_dir / "A"
        a_dir.mkdir()
        write_parquet(
            str(a_dir / "A.parquet"),
            {"sequence_id": [0, 0], "value": [10, 20]},
        )
        db = PqReader(str(db_dir))
        # Act: must not raise and must use the first matching row
        entries = list(db)
        # Assert
        assert len(entries) == 1
        name, entry = entries[0]
        assert name == "A"
        assert entry.value == 10

    def test_reset_filters_on_log_table_with_reader_parent_no_key_error(
            self, tmp_path):
        """Regression: reset_filters on a LogTable with a PqReader parent
        must not raise KeyError when the subtable lacks a parent_id column.

        Before the fix the method always called _filter_down, which accessed
        cur_table['parent_id'] on a table that only has sequence_id and log.
        """
        # Arrange: PqReader with one LogTable subtable (no parent_id column)
        db_dir = tmp_path / "mydb"
        db_dir.mkdir()
        write_parquet(
            str(db_dir / "mydb.parquet"),
            {"sequence_id": [0, 1, 2], "log": ["T", "T", "T"]},
        )
        t_dir = db_dir / "T"
        t_dir.mkdir()
        write_parquet(
            str(t_dir / "T.parquet"),
            {"sequence_id": [0, 1, 2], "value": [1, 2, 3]},
        )
        db = PqReader(str(db_dir))
        db.filter_by_log("T")
        # Act: calling reset_filters on the child LogTable must not crash
        db._subtables["T"].reset_filters()

    def test_field_not_found_error_catchable_via_exceptions_module(
            self, tmp_path):
        """Regression: FieldNotFoundError must be importable from
        nov_gnsspq.exceptions so callers are not coupled to frontend.py.
        """
        from nov_gnsspq.exceptions import FieldNotFoundError as ExceptionsErr
        db = self._make_db(tmp_path)
        with pytest.raises(ExceptionsErr):
            db.filter_by_log("nonexistent_log")

    # --- New-feature tests --------------------------------------------------

    def test_pqreader_accepts_zip_path(self, tmp_path):
        """Tests PqReader can be initialised directly from a zip archive."""
        # Arrange
        db_dir = tmp_path / "mydb"
        db_dir.mkdir()
        write_parquet(
            str(db_dir / "mydb.parquet"),
            {"sequence_id": [0, 1], "log": ["A", "B"]},
        )
        zip_path = tmp_path / "mydb.zip"
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            zf.write(str(db_dir / "mydb.parquet"), "mydb/mydb.parquet")
        # Act
        db = PqReader(str(zip_path))
        # Assert
        assert len(db.cur_table) == 2

    def test_pqreader_accepts_gnsspq_path(self, tmp_path):
        """Tests PqReader can be initialised directly from a .gnsspq archive."""
        # Arrange
        db_dir = tmp_path / "mydb"
        db_dir.mkdir()
        write_parquet(
            str(db_dir / "mydb.parquet"),
            {"sequence_id": [0, 1], "log": ["A", "B"]},
        )
        gnsspq_path = tmp_path / "mydb.gnsspq"
        with zipfile.ZipFile(str(gnsspq_path), "w") as zf:
            zf.write(str(db_dir / "mydb.parquet"), "mydb/mydb.parquet")
        # Act
        db = PqReader(str(gnsspq_path))
        # Assert
        assert len(db.cur_table) == 2


# ---------------------------------------------------------------------------
# LogTableFrame
# ---------------------------------------------------------------------------


class TestLogTableFrame:
    """Tests for LogTableFrame filter and statistics methods."""

    @pytest.fixture()
    def table(self, tmp_path):
        """Provides a LogTable with three rows and a 'value' column."""
        return make_simple_logtable(tmp_path)

    def test_apply_filter_mask_keeps_matching_rows(self, table):
        """Tests apply_filter_mask reduces cur_table to rows where mask is True."""
        # Arrange
        mask = table.cur_table["value"] > 15
        # Act
        table.apply_filter_mask(mask)
        # Assert
        assert all(table.cur_table["value"] > 15)

    def test_fields_excludes_sequence_id_col(self, table):
        """Tests fields property omits the sequence_id_col from the column list."""
        # Act & Assert
        assert _SCHEMA.sequence_id_col not in table.fields

    def test_filter_entries_by_direct_column(self, table):
        """Tests filter_entries filters cur_table by a direct column comparison."""
        # Act
        table.filter_entries("value", ">", 15)
        # Assert
        assert all(table.cur_table["value"] > 15)

    def test_filter_entries_raises_when_field_not_found_anywhere(self, table):
        """Tests filter_entries raises FieldNotFoundError for unknown fields."""
        # Act & Assert
        with pytest.raises(FieldNotFoundError):
            table.filter_entries("ghost_field", "==", 0)

    def test_filter_entries_raises_with_hint_when_field_is_in_subtable(
            self,
            tmp_path):
        """Tests filter_entries raises FieldNotFoundError naming the subtable."""
        # Arrange
        main_data = {
            "index": [0, 1],
            "field1": [10, 20],
        }
        write_parquet(str(tmp_path / "test.parquet"), main_data)
        sub_dir = tmp_path / "sub"
        sub_dir.mkdir()
        write_parquet(
            str(sub_dir / "sub.parquet"),
            {"index": [0, 1], "sub_field": [100, 200]},
        )
        lt = LogTable("test", str(tmp_path), schema=_SCHEMA)
        # Act & Assert
        with pytest.raises(FieldNotFoundError, match="sub_field"):
            lt.filter_entries("sub_field", ">", 50)

    def test_get_max_returns_correct_value(self, table):
        """Tests get_max returns the maximum value in the column."""
        # Act & Assert
        assert table.get_max("value") == 30

    def test_get_mean_raises_for_unknown_field(self, table):
        """Tests get_mean raises FieldNotFoundError for a missing column."""
        # Act & Assert
        with pytest.raises(FieldNotFoundError):
            table.get_mean("nonexistent")

    def test_get_mean_returns_correct_value(self, table):
        """Tests get_mean returns the arithmetic mean of the column."""
        # Act & Assert
        assert table.get_mean("value") == pytest.approx(20.0)

    def test_get_median_returns_correct_value(self, table):
        """Tests get_median returns the median of the column."""
        # Act & Assert
        assert table.get_median("value") == pytest.approx(20.0)

    def test_get_min_returns_correct_value(self, table):
        """Tests get_min returns the minimum value in the column."""
        # Act & Assert
        assert table.get_min("value") == 10

    def test_get_std_returns_positive_value(self, table):
        """Tests get_std returns a positive standard deviation."""
        # Act & Assert
        assert table.get_std("value") > 0

    def test_get_rms_returns_correct_value(self, table):
        """Tests get_rms returns the root mean square of the column."""
        # values are [10, 20, 30]; RMS = sqrt((100+400+900)/3) = sqrt(1400/3)
        import math
        expected = math.sqrt((10**2 + 20**2 + 30**2) / 3)
        # Act & Assert
        assert table.get_rms("value") == pytest.approx(expected)

    def test_get_sum_returns_correct_value(self, table):
        """Tests get_sum returns the sum of the column."""
        # Act & Assert
        assert table.get_sum("value") == 60

    def test_reset_filters_restores_cur_table(self, table):
        """Tests reset_filters restores cur_table to the full original table."""
        # Arrange
        original_len = len(table.cur_table)
        table.filter_entries("value", ">", 15)
        assert len(table.cur_table) < original_len
        # Act
        table.reset_filters()
        # Assert
        assert len(table.cur_table) == original_len

    def test_sort_by_ascending_default(self, table):
        """Tests sort_by sorts cur_table in ascending order by default."""
        # Act
        table.sort_by("value")
        # Assert
        values = list(table.cur_table["value"])
        assert values == sorted(values)

    def test_sort_by_descending(self, table):
        """Tests sort_by with ascending=False sorts in descending order."""
        # Act
        table.sort_by("value", ascending=False)
        # Assert
        values = list(table.cur_table["value"])
        assert values == sorted(values, reverse=True)

    def test_sort_by_raises_for_unknown_field(self, table):
        """Tests sort_by raises FieldNotFoundError for a nonexistent column."""
        # Act & Assert
        with pytest.raises(FieldNotFoundError):
            table.sort_by("nonexistent")

    def test_apply_summary_op_raises_for_unknown_operation(self, table):
        """Regression: _apply_summary_op must raise ValueError for an unknown
        operation name rather than silently executing arbitrary code via eval.
        """
        # Act & Assert
        with pytest.raises(ValueError, match="Unknown summary operation"):
            table._apply_summary_op(table.cur_table["value"], "magic_method")


# ---------------------------------------------------------------------------
# LogTable
# ---------------------------------------------------------------------------


class TestLogTable:
    """Tests for LogTable time-related methods."""

    @pytest.fixture()
    def no_time_table(self, tmp_path):
        """Provides a LogTable without any time columns."""
        data = {"sequence_id": [0, 1], "value": [5, 10]}
        write_parquet(str(tmp_path / "test.parquet"), data)
        return LogTable("test", str(tmp_path), schema=_SCHEMA)

    @pytest.fixture()
    def table(self, tmp_path):
        """Provides a LogTable with time columns in non-sorted order."""
        data = {
            "sequence_id": [0, 1, 2],
            "header_week": [2200, 2201, 2200],
            "header_milliseconds": [500_000, 100_000, 100_000],
            "value": [10, 20, 30],
        }
        return make_simple_logtable(tmp_path, data=data)

    def test_filter_end_time_removes_later_rows(self, tmp_path):
        """Tests filter_end_time removes rows whose time is after the given end."""
        # Arrange
        data = {
            "sequence_id": [0, 1, 2],
            "header_week": [2200, 2200, 2200],
            "header_milliseconds": [100_000, 200_000, 300_000],
            "value": [1, 2, 3],
        }
        lt = make_simple_logtable(tmp_path, data=data)
        # Act
        lt.filter_end_time(GPSTime(200.0, 2200))
        # Assert
        assert all(lt.cur_table["header_milliseconds"] <= 200_000)

    def test_filter_start_time_removes_earlier_rows(self, tmp_path):
        """Tests filter_start_time removes rows before the given start time."""
        # Arrange
        data = {
            "sequence_id": [0, 1, 2],
            "header_week": [2200, 2200, 2200],
            "header_milliseconds": [100_000, 200_000, 300_000],
            "value": [1, 2, 3],
        }
        lt = make_simple_logtable(tmp_path, data=data)
        # Act
        lt.filter_start_time(GPSTime(200.0, 2200))
        # Assert
        assert all(lt.cur_table["header_milliseconds"] >= 200_000)

    def test_filter_time_range_keeps_only_rows_within_range(self, tmp_path):
        """Tests filter_time_range keeps only rows within the half-open interval."""
        # Arrange
        data = {
            "sequence_id": [0, 1, 2, 3, 4],
            "header_week": [2200, 2200, 2200, 2200, 2200],
            "header_milliseconds": [50_000, 100_000, 200_000, 300_000, 400_000],
            "value": [1, 2, 3, 4, 5],
        }
        lt = make_simple_logtable(tmp_path, data=data)
        start_ms = 100_000
        end_ms = 300_000
        # Act
        lt.filter_time_range(GPSTime(100.0, 2200), GPSTime(300.0, 2200))
        # Assert
        ms = list(lt.cur_table["header_milliseconds"])
        assert start_ms in ms, "boundary start row must be included"
        assert end_ms in ms, "boundary end row must be included"
        assert 50_000 not in ms, "row before start must be excluded"
        assert 400_000 not in ms, "row after end must be excluded"
        assert all(start_ms <= m <= end_ms for m in ms)
        assert len(ms) == 3

    def test_sort_by_time_ascending(self, table):
        """Tests sort_by_time sorts cur_table by (header_week, header_milliseconds) ascending."""
        # Act
        table.sort_by_time()
        # Assert
        weeks = list(table.cur_table["header_week"])
        ms = list(table.cur_table["header_milliseconds"])
        pairs = list(zip(weeks, ms))
        assert pairs == sorted(pairs)

    def test_sort_by_time_descending(self, table):
        """Tests sort_by_time with ascending=False sorts in descending order."""
        # Act
        table.sort_by_time(ascending=False)
        # Assert
        weeks = list(table.cur_table["header_week"])
        ms = list(table.cur_table["header_milliseconds"])
        pairs = list(zip(weeks, ms))
        assert pairs == sorted(pairs, reverse=True)

    def test_sort_by_time_raises_when_time_columns_missing(
            self,
            no_time_table):
        """Tests sort_by_time raises FieldNotFoundError for missing time cols."""
        # Act & Assert
        with pytest.raises(FieldNotFoundError):
            no_time_table.sort_by_time()

    def test_time_range_returns_correct_gpstime_tuple(self, table):
        """Tests time_range returns a (GPSTime, GPSTime) for start and end."""
        # Act
        start, end = table.time_range
        # Assert
        assert isinstance(start, GPSTime)
        assert isinstance(end, GPSTime)
        # Earliest entry: week=2200, ms=100_000 -> 100 seconds
        assert start.week == 2200
        assert start.seconds == pytest.approx(100.0)
        # Latest entry: week=2201, ms=100_000 -> 100 seconds
        assert end.week == 2201


# ---------------------------------------------------------------------------
# FieldValue
# ---------------------------------------------------------------------------


class TestFieldValue:
    """Tests for the FieldValue proxy object."""

    @pytest.fixture()
    def table_and_fv(self, tmp_path):
        """Provides a (LogTable, FieldValue) pair for the 'value' column."""
        lt = make_simple_logtable(tmp_path)
        fv = FieldValue("value", lt)
        return lt, fv

    def test_grouped_mean_delegates_to_get_mean_with_group_true(
            self,
            table_and_fv):
        """Tests grouped_mean calls get_mean with group=True."""
        # Arrange
        lt, fv = table_and_fv
        # Act
        with patch.object(lt, "get_mean") as mock_get_mean:
            mock_get_mean.return_value = pd.Series([1.0])
            _ = fv.grouped_mean
        # Assert
        mock_get_mean.assert_called_once_with("value", group=True)

    def test_max_delegates_to_get_max(self, table_and_fv):
        """Tests max property calls get_max with the field name."""
        # Arrange
        table, fv = table_and_fv
        # Act
        with patch.object(table, "get_max") as mock_get:
            _ = fv.max
        # Assert
        mock_get.assert_called_once_with(fv.name)

    def test_mean_delegates_to_get_mean(self, table_and_fv):
        """Tests mean property calls get_mean with the field name."""
        # Arrange
        table, fv = table_and_fv
        # Act
        with patch.object(table, "get_mean") as mock_get:
            _ = fv.mean
        # Assert
        mock_get.assert_called_once_with(fv.name)

    def test_median_delegates_to_get_median(self, table_and_fv):
        """Tests median property calls get_median with the field name."""
        # Arrange
        table, fv = table_and_fv
        # Act
        with patch.object(table, "get_median") as mock_get:
            _ = fv.median
        # Assert
        mock_get.assert_called_once_with(fv.name)

    def test_min_delegates_to_get_min(self, table_and_fv):
        """Tests min property calls get_min with the field name."""
        # Arrange
        table, fv = table_and_fv
        # Act
        with patch.object(table, "get_min") as mock_get:
            _ = fv.min
        # Assert
        mock_get.assert_called_once_with(fv.name)

    def test_repr_returns_string(self, table_and_fv):
        """Tests __repr__ returns a string representation of the column data."""
        # Arrange
        _, fv = table_and_fv
        # Act & Assert
        assert isinstance(repr(fv), str)

    def test_rms_delegates_to_get_rms(self, table_and_fv):
        """Tests rms property calls get_rms with the field name."""
        # Arrange
        table, fv = table_and_fv
        # Act
        with patch.object(table, "get_rms") as mock_get:
            _ = fv.rms
        # Assert
        mock_get.assert_called_once_with(fv.name)

    def test_grouped_rms_delegates_to_get_rms_grouped(self, table_and_fv):
        """Tests grouped_rms property calls get_rms with group=True."""
        # Arrange
        lt, fv = table_and_fv
        # Act
        with patch.object(lt, "get_rms") as mock_get:
            mock_get.return_value = pd.Series([1.0])
            _ = fv.grouped_rms
        # Assert
        mock_get.assert_called_once_with("value", group=True)

    def test_std_delegates_to_get_std(self, table_and_fv):
        """Tests std property calls get_std with the field name."""
        # Arrange
        table, fv = table_and_fv
        # Act
        with patch.object(table, "get_std") as mock_get:
            _ = fv.std
        # Assert
        mock_get.assert_called_once_with(fv.name)

    def test_sum_delegates_to_get_sum(self, table_and_fv):
        """Tests sum property calls get_sum with the field name."""
        # Arrange
        table, fv = table_and_fv
        # Act
        with patch.object(table, "get_sum") as mock_get:
            _ = fv.sum
        # Assert
        mock_get.assert_called_once_with(fv.name)


# ---------------------------------------------------------------------------
# create_log_data_class / create_log_entry
# ---------------------------------------------------------------------------


class TestCreateLogDataClass:
    """Tests for create_log_data_class and create_log_entry."""

    @pytest.fixture()
    def table(self, tmp_path):
        """Provides a simple LogTable for dataclass creation tests."""
        return make_simple_logtable(tmp_path)

    def test_create_log_data_class_returns_dataclass_with_column_fields(
            self,
            table):
        """Tests create_log_data_class returns a dataclass matching table columns."""
        # Act
        cls = table.create_log_data_class()
        # Assert
        assert hasattr(cls, "__dataclass_fields__")
        for col in table.cur_table.columns:
            assert col in cls.__dataclass_fields__

    def test_create_log_entry_returns_instance_with_correct_values(
            self,
            table):
        """Tests create_log_entry returns a dataclass instance from row data."""
        # Arrange
        cls = table.create_log_data_class()
        first_row = table.table.iloc[0]
        # Act
        entry = table.create_log_entry(cls, first_row)
        # Assert
        assert entry.value == 10
        assert entry.header_week == 2200
