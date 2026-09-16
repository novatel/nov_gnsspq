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

Unit tests for the GPSWriter class in nov_gnsspq.writer.standard.
"""
import enum
import json
import os
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from nov_gnsspq.reader.schema import (
    METADATA_FILENAME,
    PARENT_ID_COL,
    SEQUENCE_ID_COL,
)
from nov_gnsspq.writer.parallel.edie import TableNode
from nov_gnsspq.writer.standard import GPSWriter


# pylint: disable=protected-access

# ---------------------------------------------------------------------------
# Test doubles for novatel_edie metaclass-based type detection
# ---------------------------------------------------------------------------

_EnumerationType = type("nb_meta", (type,), {})
_PyCStructType = type("nb_meta", (type,), {})


def _make_enum_value(str_rep: str, int_rep: int):
    """Builds a value whose type metaclass is named 'EnumerationType'."""
    cls = _EnumerationType("MockEnum", (object,), {
        "__str__": lambda self: str_rep,
        "__int__": lambda self: int_rep,
    })
    return cls()


def _make_pycstruct_bytes(raw: bytes):
    """Builds a PyCStructType instance with a bytes .value attribute."""
    cls = _PyCStructType("MockBytesStruct", (object,), {"value": raw})
    return cls()


def _make_pycstruct_str_value(val: str):
    """Builds a PyCStructType instance with a non-bytes .value attribute."""
    cls = _PyCStructType("MockStrStruct", (object,), {"value": val})
    return cls()


def _make_pycstruct_no_value():
    """Builds a plain PyCStructType instance with no .value attribute."""
    cls = _PyCStructType("MockPlainStruct", (object,), {})
    return cls()


class _MyPyEnum(enum.Enum):
    """A stdlib enum for testing the enum.Enum branch."""

    OPTION_A = 10
    OPTION_B = 20


class _ValueAttr:
    """Object that has a .value attribute but is not a metaclass or enum type."""

    def __init__(self, v):
        """Initializes _ValueAttr with a value."""
        self.value = v

    def __str__(self):
        """Returns string representation."""
        return f"ValueAttr({self.value})"


@pytest.fixture()
def gps_file(tmp_path):
    """Provides a tiny fake GPS file on disk."""
    f = tmp_path / "test.gps"
    f.write_bytes(b"dummy GPS data")
    return f


@pytest.fixture()
def example_writer(tmp_path, gps_file):
    """Provides a GPSWriter pointing at a temporary output directory."""
    return GPSWriter(str(gps_file), str(tmp_path / "out"))


class TestGPSWriterInit:
    """Tests for the GPSWriter constructor."""

    def test_stores_input_file(self, gps_file, tmp_path):
        """Tests input_file is stored correctly."""
        # Act
        writer = GPSWriter(str(gps_file), str(tmp_path / "out"))
        # Assert
        assert writer.input_file == str(gps_file)

    def test_stores_output_folder(self, gps_file, tmp_path):
        """Tests output_folder is stored correctly."""
        # Arrange
        out = str(tmp_path / "out")
        # Act
        writer = GPSWriter(str(gps_file), out)
        # Assert
        assert writer.output_folder == out

    def test_default_compression_is_zstd(self, gps_file, tmp_path):
        """Tests the default compression codec is 'zstd'."""
        # Act
        writer = GPSWriter(str(gps_file), str(tmp_path / "out"))
        # Assert
        assert writer.compression == "zstd"

    def test_custom_compression_stored(self, gps_file, tmp_path):
        """Tests a custom compression codec is stored."""
        # Act
        writer = GPSWriter(
            str(gps_file), str(tmp_path / "out"), compression="snappy")
        # Assert
        assert writer.compression == "snappy"

    def test_explicit_chunk_size_overrides_auto_tune(self, gps_file, tmp_path):
        """Tests an explicit chunk_size overrides the auto-tune result."""
        # Act
        writer = GPSWriter(
            str(gps_file), str(tmp_path / "out"), chunk_size=99_999)
        # Assert
        assert writer._chunk_size == 99_999

    def test_auto_tune_applied_when_chunk_size_none(self, gps_file, tmp_path):
        """Tests auto-tune provides chunk_size when none is supplied."""
        # Act
        writer = GPSWriter(str(gps_file), str(tmp_path / "out"))
        # Assert
        assert writer._chunk_size > 0

    def test_flush_thread_is_alive_after_init(self, example_writer):
        """Tests the background flush thread is started in __init__."""
        # Act & Assert
        assert example_writer._flush_thread.is_alive()

    def test_tables_start_empty(self, example_writer):
        """Tests the _tables accumulation dict starts empty."""
        # Act & Assert
        assert example_writer._tables == {}

    def test_sequence_id_starts_at_zero(self, example_writer):
        """Tests _sequence_id starts at zero."""
        # Act & Assert
        assert example_writer._sequence_id == 0


class TestGetSeqId:
    """Tests for the GPSWriter._get_seq_id method."""

    def test_returns_zero_when_last_seq_id_is_none(self, example_writer):
        """Tests zero is returned for a brand-new node."""
        # Arrange
        node = TableNode("T", "/o", "T")
        # Act & Assert
        assert example_writer._get_seq_id(node, parent_id=None) == 0

    def test_returns_zero_for_leaf_node_when_parent_changes(
            self, example_writer):
        """Tests sequence resets to 0 for a leaf node when parent changes."""
        # Arrange
        node = TableNode("T", "/o", "T")
        node.last_seq_id = 3
        node.last_parent_id = 5
        # Act
        result = example_writer._get_seq_id(node, parent_id=99)
        # Assert
        assert result == 0

    def test_increments_for_leaf_node_when_same_parent(self, example_writer):
        """Tests sequence increments by 1 when the parent_id is unchanged."""
        # Arrange
        node = TableNode("T", "/o", "T")
        node.last_seq_id = 7
        node.last_parent_id = 5
        # Act
        result = example_writer._get_seq_id(node, parent_id=5)
        # Assert
        assert result == 8

    def test_increments_for_non_leaf_node_regardless_of_parent(
            self, example_writer):
        """Tests non-leaf nodes always increment regardless of parent change."""
        # Arrange
        node = TableNode("T", "/o", "T")
        node.last_seq_id = 2
        node.last_parent_id = 5
        node.subtables["child"] = TableNode("child", "/o/T/child", "child")
        # Act
        result = example_writer._get_seq_id(node, parent_id=99)
        # Assert
        assert result == 3


class TestProcessValue:
    """Tests for the GPSWriter._process_value method."""

    @pytest.mark.parametrize("value, expected", [
        (42, 42),
        (3.14, 3.14),
        ("hello", "hello"),
        (True, True),
        (None, None),
    ])
    def test_fast_path_python_scalars(self, example_writer, value, expected):
        """Tests Python scalars are stored directly without transformation."""
        # Arrange
        cols = {}
        # Act
        example_writer._process_value(value, "field", cols, 0)
        # Assert
        assert cols["field"] == [expected]

    def test_fast_path_backfills_column_with_nones(self, example_writer):
        """Tests a new column is backfilled when row_count > 0."""
        # Arrange
        cols = {}
        # Act
        example_writer._process_value(10, "existing", cols, 3)
        # Assert
        assert cols["existing"] == [None, None, None, 10]

    def test_fast_path_appends_to_existing_column(self, example_writer):
        """Tests subsequent values are appended to an existing column."""
        # Arrange
        cols = {"field": [1, 2]}
        # Act
        example_writer._process_value(3, "field", cols, 2)
        # Assert
        assert cols["field"] == [1, 2, 3]

    def test_enumeration_type_stores_str_column(self, example_writer):
        """Tests an EnumerationType value produces a string column."""
        # Arrange
        val = _make_enum_value("GPS_L1", 0)
        cols = {}
        # Act
        example_writer._process_value(val, "signal", cols, 0)
        # Assert
        assert cols["signal"] == ["GPS_L1"]

    def test_enumeration_type_stores_raw_int_column(self, example_writer):
        """Tests an EnumerationType value also produces a _raw integer column."""
        # Arrange
        val = _make_enum_value("GPS_L1", 7)
        cols = {}
        # Act
        example_writer._process_value(val, "signal", cols, 0)
        # Assert
        assert cols["signal_raw"] == [7]

    def test_enumeration_type_raw_is_none_when_int_conversion_fails(
            self, example_writer):
        """Tests signal_raw is None when int() conversion raises an error."""
        # Arrange
        cls = _EnumerationType("BadEnum", (object,), {
            "__str__": lambda self: "BAD",
            "__int__": lambda self: (
                (_ for _ in ()).throw(TypeError("no int"))),
        })
        val = cls()
        cols = {}
        # Act
        example_writer._process_value(val, "sig", cols, 0)
        # Assert
        assert cols["sig"] == ["BAD"]
        assert cols["sig_raw"] == [None]

    def test_pycstruct_satellite_id_expands_to_prefixed_subfields(
            self, example_writer):
        """Tests SatelliteId values expand into parent-prefixed sub-fields."""
        # Arrange
        SatCls = _EnumerationType("SatelliteId", (object,), {
            "to_dict": lambda self: {"prn": 7, "frequency_channel": 2}
        })
        val = SatCls()
        cols = {}
        with patch("nov_gnsspq.writer.parallel.edie.SAT_ID_TYPE", SatCls):
            # Act
            example_writer._process_value(val, "satellite", cols, 0)
        # Assert
        assert "satellite_prn" in cols
        assert cols["satellite_prn"] == [7]
        assert "satellite_frequency_channel" in cols
        assert cols["satellite_frequency_channel"] == [2]

    def test_pycstruct_bytes_value_stored_as_bytes(self, example_writer):
        """Tests a PyCStructType with bytes .value stores raw bytes."""
        # Arrange
        val = _make_pycstruct_bytes(b"\xAA\x44\x12")
        cols = {}
        # Act
        example_writer._process_value(val, "raw", cols, 0)
        # Assert
        assert cols["raw"] == [b"\xAA\x44\x12"]

    def test_pycstruct_str_value_stored_as_string(self, example_writer):
        """Tests a PyCStructType with non-bytes .value is stored as str."""
        # Arrange
        val = _make_pycstruct_str_value("SOME_VALUE")
        cols = {}
        # Act
        example_writer._process_value(val, "field", cols, 0)
        # Assert
        assert cols["field"] == [str(val)]

    def test_pycstruct_no_value_attr_stored_as_str(self, example_writer):
        """Tests a plain nb_meta object with no .value is stored as str."""
        # Arrange
        val = _make_pycstruct_no_value()
        cols = {}
        # Act
        example_writer._process_value(val, "field", cols, 0)
        # Assert
        assert cols["field"] == [str(val)]
        assert cols["field_raw"] == [None]

    def test_stdlib_enum_stores_str_and_raw(self, example_writer):
        """Tests a Python enum.Enum value stores its name and numeric .value."""
        # Arrange
        cols = {}
        # Act
        example_writer._process_value(_MyPyEnum.OPTION_A, "mode", cols, 0)
        # Assert
        assert cols["mode"] == [str(_MyPyEnum.OPTION_A)]
        assert cols["mode_raw"] == [10]

    def test_value_attr_object_stored_as_str(self, example_writer):
        """Tests objects with .value (but not other recognised types) use str()."""
        # Arrange
        val = _ValueAttr("some_content")
        cols = {}
        # Act
        example_writer._process_value(val, "field", cols, 0)
        # Assert
        assert cols["field"] == [str(val)]

    def test_generic_unknown_type_stored_as_is(self, example_writer):
        """Tests an unrecognised type is stored directly."""
        # Arrange
        class Weird:
            pass
        val = Weird()
        cols = {}
        # Act
        example_writer._process_value(val, "w", cols, 0)
        # Assert
        assert cols["w"] == [val]


class TestAddEntry:
    """Tests for the GPSWriter._add_entry method."""

    def test_creates_new_node_for_unknown_log_type(self, example_writer):
        """Tests a new TableNode is created when log_type is not in the table."""
        # Arrange
        tables = {}
        # Act
        example_writer._add_entry(
            {"lat": 51.0}, tables, "BESTPOS", None,
            _parent_output_dir=example_writer.output_folder)
        # Assert
        assert "BESTPOS" in tables

    def test_sequence_id_starts_at_zero_for_new_node(self, example_writer):
        """Tests the first entry receives sequence_id=0."""
        # Arrange
        tables = {}
        # Act
        example_writer._add_entry(
            {"lat": 51.0}, tables, "BESTPOS", None,
            _parent_output_dir=example_writer.output_folder)
        # Assert
        assert tables["BESTPOS"].cols[SEQUENCE_ID_COL] == [0]

    def test_sequence_id_increments_on_second_entry(self, example_writer):
        """Tests subsequent entries increment sequence_id."""
        # Arrange
        tables = {}
        # Act
        example_writer._add_entry(
            {"lat": 51.0}, tables, "BESTPOS", None,
            _parent_output_dir=example_writer.output_folder)
        example_writer._add_entry(
            {"lat": 52.0}, tables, "BESTPOS", None,
            _parent_output_dir=example_writer.output_folder)
        # Assert
        assert tables["BESTPOS"].cols[SEQUENCE_ID_COL] == [0, 1]

    def test_parent_id_column_added_when_parent_present(self, example_writer):
        """Tests parent_id column is added when parent_id is not None."""
        # Arrange
        tables = {}
        # Act
        example_writer._add_entry(
            {"val": 1}, tables, "obs", parent_id=5,
            _parent_output_dir=example_writer.output_folder)
        # Assert
        assert PARENT_ID_COL in tables["obs"].cols
        assert tables["obs"].cols[PARENT_ID_COL] == [5]

    def test_parent_id_column_absent_when_no_parent(self, example_writer):
        """Tests parent_id column is not created when parent_id is None."""
        # Arrange
        tables = {}
        # Act
        example_writer._add_entry(
            {"val": 1}, tables, "ROOT", None,
            _parent_output_dir=example_writer.output_folder)
        # Assert
        assert PARENT_ID_COL not in tables["ROOT"].cols

    def test_scalar_field_appended_to_cols(self, example_writer):
        """Tests scalar message fields are appended directly to cols."""
        # Arrange
        tables = {}
        # Act
        example_writer._add_entry(
            {"lat": 51.0, "lon": -114.0}, tables, "BESTPOS", None,
            _parent_output_dir=example_writer.output_folder)
        # Assert
        assert tables["BESTPOS"].cols["lat"] == [51.0]
        assert tables["BESTPOS"].cols["lon"] == [-114.0]

    def test_nested_dict_creates_subtable(self, example_writer):
        """Tests a nested dict field creates a child TableNode."""
        # Arrange
        tables = {}
        # Act
        example_writer._add_entry(
            {"obs": {"signal": "L1"}}, tables, "RANGE", None,
            _parent_output_dir=example_writer.output_folder)
        # Assert
        assert "obs" in tables["RANGE"].subtables

    def test_list_of_dicts_creates_subtable_with_multiple_rows(
            self, example_writer):
        """Tests a list-of-dicts field adds one row per item to the subtable."""
        # Arrange
        tables = {}
        msg = {"obs": [{"sig": "L1"}, {"sig": "L2"}, {"sig": "L5"}]}
        # Act
        example_writer._add_entry(
            msg, tables, "RANGE", None,
            _parent_output_dir=example_writer.output_folder)
        # Assert
        assert tables["RANGE"].subtables["obs"].row_count == 3

    def test_list_of_scalars_creates_keyed_subtable(self, example_writer):
        """Tests a list of scalars is stored as key_0, key_1, ... in a subtable."""
        # Arrange
        tables = {}
        msg = {"values": [10, 20, 30]}
        # Act
        example_writer._add_entry(
            msg, tables, "T", None,
            _parent_output_dir=example_writer.output_folder)
        subtable = tables["T"].subtables["values"]
        # Assert
        assert "key_0" in subtable.cols
        assert "key_1" in subtable.cols
        assert "key_2" in subtable.cols

    def test_missing_columns_backfilled_with_none(self, example_writer):
        """Tests a column absent from a later entry gets None backfill."""
        # Arrange
        tables = {}
        example_writer._add_entry(
            {"a": 1, "b": 2}, tables, "T", None,
            _parent_output_dir=example_writer.output_folder)
        # Act
        example_writer._add_entry(
            {"a": 3}, tables, "T", None,
            _parent_output_dir=example_writer.output_folder)
        # Assert
        assert tables["T"].cols["b"] == [2, None]

    def test_row_count_incremented_after_entry(self, example_writer):
        """Tests row_count on the node increases by one per call."""
        # Arrange
        tables = {}
        # Act
        example_writer._add_entry(
            {"x": 1}, tables, "T", None,
            _parent_output_dir=example_writer.output_folder)
        example_writer._add_entry(
            {"x": 2}, tables, "T", None,
            _parent_output_dir=example_writer.output_folder)
        # Assert
        assert tables["T"].row_count == 2

    def test_empty_list_value_not_added_as_subtable(self, example_writer):
        """Tests an empty list field does not create a subtable."""
        # Arrange
        tables = {}
        # Act
        example_writer._add_entry(
            {"items": []}, tables, "T", None,
            _parent_output_dir=example_writer.output_folder)
        # Assert
        assert "items" not in tables["T"].subtables


class TestFlushHelpers:
    """Tests for the GPSWriter flush-related methods."""

    def test_enqueue_flush_snapshots_cols_and_clears_buffer(
            self, example_writer, tmp_path):
        """Tests _enqueue_flush takes a snapshot and clears the node's cols."""
        # Arrange
        tables = {}
        example_writer._add_entry(
            {"val": 1}, tables, "T", None,
            _parent_output_dir=example_writer.output_folder)
        node = tables["T"]
        # Act
        example_writer._enqueue_flush(node)
        # Assert
        assert node.row_count == 0
        for lst in node.cols.values():
            assert lst == []
        example_writer._flush_queue.join()

    def test_maybe_flush_subtree_does_not_flush_below_threshold(
            self, example_writer):
        """Tests _maybe_flush_subtree skips a node below chunk_size."""
        # Arrange
        node = TableNode("T", str(example_writer.output_folder), "T")
        node.cols["a"] = [1]
        node.row_count = 1
        example_writer._chunk_size = 1000
        # Act
        example_writer._maybe_flush_subtree(node)
        # Assert
        assert node.row_count == 1

    def test_maybe_flush_subtree_flushes_when_threshold_reached(
            self, example_writer, tmp_path):
        """Tests _maybe_flush_subtree enqueues flush when row_count >= chunk_size."""
        # Arrange
        example_writer._chunk_size = 1
        tables = {}
        out = str(tmp_path / "out")
        example_writer._add_entry(
            {"val": 1}, tables, "T", None, _parent_output_dir=out)
        node = tables["T"]
        # Act
        example_writer._maybe_flush_subtree(node)
        example_writer._flush_queue.join()
        # Assert
        assert node.row_count == 0

    def test_maybe_flush_subtree_recurses_into_subtables(
            self, example_writer, tmp_path):
        """Tests _maybe_flush_subtree visits all subtable nodes recursively."""
        # Arrange
        example_writer._chunk_size = 1
        tables = {}
        out = str(tmp_path / "out2")
        example_writer._add_entry(
            {"obs": [{"sig": "L1"}]},
            tables, "RANGE", None,
            _parent_output_dir=out,
        )
        parent_node = tables["RANGE"]
        child_node = parent_node.subtables["obs"]
        assert child_node.row_count == 1
        # Act
        example_writer._maybe_flush_subtree(parent_node)
        example_writer._flush_queue.join()
        # Assert
        assert child_node.row_count == 0

    def test_flush_all_remaining_flushes_nodes_with_data(
            self, example_writer, tmp_path):
        """Tests _flush_all_remaining enqueues all non-empty nodes."""
        # Arrange
        tables = example_writer._tables
        out = example_writer.output_folder
        example_writer._add_entry({"v": 1}, tables, "A", None,
                                  _parent_output_dir=out)
        example_writer._add_entry({"v": 2}, tables, "B", None,
                                  _parent_output_dir=out)
        # Act
        example_writer._flush_all_remaining()
        example_writer._flush_queue.join()
        # Assert
        for node in tables.values():
            assert node.row_count == 0


class TestWriterLifecycle:
    """Tests for GPSWriter._close_all_writers."""

    def test_close_all_writers_closes_open_parquet_writer(self, tmp_path):
        """Tests _close_all_writers calls close() on each open ParquetWriter."""
        # Arrange
        mock_pw = MagicMock()
        node = TableNode("T", str(tmp_path), "T")
        node.parquet_writer = mock_pw
        tables = {"T": node}
        writer = GPSWriter.__new__(GPSWriter)
        # Act
        writer._close_all_writers(tables)
        # Assert
        mock_pw.close.assert_called_once()
        assert node.parquet_writer is None

    def test_close_all_writers_skips_none_writer(self, tmp_path):
        """Tests _close_all_writers is a no-op for nodes without a writer."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        node.parquet_writer = None
        tables = {"T": node}
        writer = GPSWriter.__new__(GPSWriter)
        # Act & Assert
        writer._close_all_writers(tables)

    def test_close_all_writers_recurses_into_subtables(self, tmp_path):
        """Tests _close_all_writers closes writers in nested subtables."""
        # Arrange
        mock_pw_child = MagicMock()
        parent = TableNode("P", str(tmp_path), "P")
        child = TableNode("C", str(tmp_path / "C"), "C")
        child.parquet_writer = mock_pw_child
        parent.subtables["C"] = child
        tables = {"P": parent}
        writer = GPSWriter.__new__(GPSWriter)
        # Act
        writer._close_all_writers(tables)
        # Assert
        mock_pw_child.close.assert_called_once()


class TestFinalTableWrites:
    """Tests for GPSWriter._write_log_table, _write_unknown_table, _write_raw_table."""

    def test_write_log_table_creates_parquet_file(self, tmp_path, gps_file):
        """Tests _write_log_table writes a parquet file named after output_folder."""
        # Arrange
        out = tmp_path / "mydb"
        writer = GPSWriter(str(gps_file), str(out))
        writer._log_table_cols = {
            "log": ["BESTPOS", "BESTPOS"],
            SEQUENCE_ID_COL: [0, 1],
        }
        os.makedirs(str(out), exist_ok=True)
        # Act
        writer._write_log_table()
        # Assert
        assert (out / "mydb.parquet").exists()
        table = pq.read_table(str(out / "mydb.parquet"))
        assert table.num_rows == 2

    def test_write_unknown_table_empty_schema_when_no_unknowns(
            self, tmp_path, gps_file):
        """Tests _write_unknown_table writes an empty-schema file when no unknowns."""
        # Arrange
        out = tmp_path / "out"
        os.makedirs(str(out))
        writer = GPSWriter(str(gps_file), str(out))
        writer._unknown_cols = {SEQUENCE_ID_COL: [], "payload": []}
        # Act
        writer._write_unknown_table()
        # Assert
        path = out / "unknown_data.parquet"
        assert path.exists()
        table = pq.read_table(str(path))
        assert table.num_rows == 0
        assert SEQUENCE_ID_COL in table.schema.names
        assert "payload" in table.schema.names

    def test_write_unknown_table_with_data(self, tmp_path, gps_file):
        """Tests _write_unknown_table writes rows when unknowns are present."""
        # Arrange
        out = tmp_path / "out"
        os.makedirs(str(out))
        writer = GPSWriter(str(gps_file), str(out))
        writer._unknown_cols = {
            SEQUENCE_ID_COL: [5, 10],
            "payload": [b"\xff", b"\xfe"],
        }
        # Act
        writer._write_unknown_table()
        # Assert
        table = pq.read_table(str(out / "unknown_data.parquet"))
        assert table.num_rows == 2
        assert table[SEQUENCE_ID_COL].to_pylist() == [5, 10]

class TestWriteMetadata:
    """Tests for GPSWriter._write_metadata."""

    def test_write_metadata_creates_json_file(self, tmp_path, gps_file):
        """Tests _write_metadata writes a _metadata.json file."""
        # Arrange
        out = tmp_path / "out"
        os.makedirs(str(out))
        writer = GPSWriter(str(gps_file), str(out))
        # Act
        writer._write_metadata(
            file_size=1000, sha256="abc123", total_messages=50)
        # Assert
        assert (out / METADATA_FILENAME).exists()

    def test_write_metadata_contents(self, tmp_path, gps_file):
        """Tests _metadata.json contains the expected fields."""
        # Arrange
        out = tmp_path / "out"
        os.makedirs(str(out))
        writer = GPSWriter(str(gps_file), str(out))
        # Act
        writer._write_metadata(
            file_size=2048, sha256="deadbeef", total_messages=7)
        # Assert
        with open(out / METADATA_FILENAME) as f:
            meta = json.load(f)
        assert meta["file_size"] == 2048
        assert meta["sha256"] == "deadbeef"
        assert meta["total_message_count"] == 7
        assert "schema_version" in meta
        assert "writer_version" in meta
        assert meta["source_filename"] == "test.gps"


class TestComputeSha256:
    """Tests for the GPSWriter._compute_sha256 static method."""

    def test_returns_hex_string(self, tmp_path):
        """Tests _compute_sha256 returns a hex digest string."""
        # Arrange
        f = tmp_path / "file.bin"
        f.write_bytes(b"hello")
        # Act
        result = GPSWriter._compute_sha256(str(f))
        # Assert
        assert isinstance(result, str)
        assert len(result) == 64

    def test_correct_hash_for_known_content(self, tmp_path):
        """Tests _compute_sha256 returns the correct SHA-256 digest."""
        # Arrange
        import hashlib
        data = b"gps test data 12345"
        expected = hashlib.sha256(data).hexdigest()
        f = tmp_path / "known.bin"
        f.write_bytes(data)
        # Act & Assert
        assert GPSWriter._compute_sha256(str(f)) == expected

    def test_different_contents_produce_different_hashes(self, tmp_path):
        """Tests two files with different content have different hashes."""
        # Arrange
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"data_a")
        b.write_bytes(b"data_b")
        # Act & Assert
        assert GPSWriter._compute_sha256(str(a)) != GPSWriter._compute_sha256(
            str(b))


class TestWriteToDb:
    """Integration tests for GPSWriter.write_to_db with a mocked file parser."""

    def _make_fake_message(self, name: str, body: dict):
        """Builds a fake ne.Message-shaped object."""
        class FakeMsg:
            pass
        msg = FakeMsg()
        msg.name = name
        msg.to_dict = lambda: {
            "header": {"week": 2200, "milliseconds": 100.0}, **body}
        return msg

    def _make_fake_unknown(self, payload: bytes):
        """Builds a fake ne.UnknownMessage-shaped object."""
        class FakeUnknown:
            pass
        msg = FakeUnknown()
        msg.payload = payload
        return msg

    def test_creates_output_directory(self, tmp_path, gps_file):
        """Tests write_to_db creates the output folder if it doesn't exist."""
        # Arrange
        out_dir = tmp_path / "new_db"
        writer = GPSWriter(str(gps_file), str(out_dir))

        class FakeMsg:
            name = "BESTPOS"
            def to_dict(self): return {"header": {}, "lat": 51.0}

        with patch("nov_gnsspq.writer.standard.ne_oem") as mock_ne_oem:
            with patch("nov_gnsspq.writer.standard.tqdm"):
                mock_ne_oem.Message = FakeMsg
                mock_ne_oem.UnknownMessage = type("UM", (), {})
                mock_ne_oem.FileParser.return_value = iter([])
                # Act
                writer.write_to_db()
        # Assert
        assert out_dir.exists()

    def test_processes_known_message_creates_table_parquet(
            self, tmp_path, gps_file):
        """Tests write_to_db writes a type-specific Parquet file for known messages."""
        # Arrange
        out_dir = tmp_path / "out_known"
        writer = GPSWriter(str(gps_file), str(out_dir))

        class FakeMsg:
            name = "BESTPOS"
            def to_dict(self): return {"header": {"week": 2200}, "lat": 51.0}

        with patch("nov_gnsspq.writer.standard.ne_oem") as mock_ne_oem:
            with patch("nov_gnsspq.writer.standard.tqdm"):
                mock_ne_oem.Message = FakeMsg
                mock_ne_oem.UnknownMessage = type("UM", (), {})
                mock_ne_oem.FileParser.return_value = iter([FakeMsg()])
                # Act
                writer.write_to_db()
        # Assert
        assert (out_dir / "BESTPOS" / "BESTPOS.parquet").exists()

    def test_writes_log_table_after_processing(self, tmp_path, gps_file):
        """Tests write_to_db creates the log index Parquet file."""
        # Arrange
        out_dir = tmp_path / "out_log"
        writer = GPSWriter(str(gps_file), str(out_dir))

        class FakeMsg:
            name = "RANGE"
            def to_dict(self): return {"header": {}, "data": 1}

        with patch("nov_gnsspq.writer.standard.ne_oem") as mock_ne_oem:
            with patch("nov_gnsspq.writer.standard.tqdm"):
                mock_ne_oem.Message = FakeMsg
                mock_ne_oem.UnknownMessage = type("UM", (), {})
                mock_ne_oem.FileParser.return_value = iter([FakeMsg()])
                # Act
                writer.write_to_db()
        # Assert
        assert (out_dir / "out_log.parquet").exists()

    def test_writes_unknown_data_parquet(self, tmp_path, gps_file):
        """Tests write_to_db always creates unknown_data.parquet."""
        # Arrange
        out_dir = tmp_path / "out_unk"
        writer = GPSWriter(str(gps_file), str(out_dir))
        with patch("nov_gnsspq.writer.standard.ne_oem") as mock_ne_oem:
            with patch("nov_gnsspq.writer.standard.tqdm"):
                mock_ne_oem.Message = type("Msg", (), {})
                mock_ne_oem.UnknownMessage = type("UM", (), {})
                mock_ne_oem.FileParser.return_value = iter([])
                # Act
                writer.write_to_db()
        # Assert
        assert (out_dir / "unknown_data.parquet").exists()

    def test_writes_metadata_json(self, tmp_path, gps_file):
        """Tests write_to_db writes _metadata.json with basic fields."""
        # Arrange
        out_dir = tmp_path / "out_meta"
        writer = GPSWriter(str(gps_file), str(out_dir))
        with patch("nov_gnsspq.writer.standard.ne_oem") as mock_ne_oem:
            with patch("nov_gnsspq.writer.standard.tqdm"):
                mock_ne_oem.Message = type("Msg", (), {})
                mock_ne_oem.UnknownMessage = type("UM", (), {})
                mock_ne_oem.FileParser.return_value = iter([])
                # Act
                writer.write_to_db()
        # Assert
        with open(out_dir / METADATA_FILENAME) as f:
            meta = json.load(f)
        assert "sha256" in meta
        assert "schema_version" in meta
        assert meta["total_message_count"] == 0

    def test_processes_unknown_message_into_unknown_table(
            self, tmp_path, gps_file):
        """Tests ne.UnknownMessage is recorded in unknown_data.parquet."""
        # Arrange
        class FakeUnknown:
            payload = b"\xAA\xBB"

        out_dir = tmp_path / "out_unknmsg"
        writer = GPSWriter(str(gps_file), str(out_dir))
        with patch("nov_gnsspq.writer.standard.ne_oem") as mock_ne_oem:
            with patch("nov_gnsspq.writer.standard.tqdm"):
                mock_ne_oem.Message = type("Msg", (), {})
                mock_ne_oem.UnknownMessage = FakeUnknown
                mock_ne_oem.FileParser.return_value = iter([FakeUnknown()])
                # Act
                writer.write_to_db()
        # Assert
        table = pq.read_table(str(out_dir / "unknown_data.parquet"))
        assert table.num_rows == 1
        assert table["payload"].to_pylist()[0] == b"\xAA\xBB"

    def test_sequence_id_increments_per_message(self, tmp_path, gps_file):
        """Tests each parsed message increments the sequence_id counter."""
        # Arrange
        class FakeMsg:
            name = "BESTPOS"
            def to_dict(self): return {"header": {}, "lat": 0.0}

        out_dir = tmp_path / "out_seq"
        writer = GPSWriter(str(gps_file), str(out_dir))
        with patch("nov_gnsspq.writer.standard.ne_oem") as mock_ne_oem:
            with patch("nov_gnsspq.writer.standard.tqdm"):
                mock_ne_oem.Message = FakeMsg
                mock_ne_oem.UnknownMessage = type("UM", (), {})
                mock_ne_oem.FileParser.return_value = iter(
                    [FakeMsg(), FakeMsg(), FakeMsg()])
                # Act
                writer.write_to_db()
        # Assert
        assert writer._sequence_id == 3

    def test_unknown_message_payload_exception_stores_none(
            self, tmp_path, gps_file):
        """Tests bytes(payload) exception falls back to None payload."""
        # Arrange
        class FakeUnknown:
            @property
            def payload(self):
                raise RuntimeError("bad payload")

        out_dir = tmp_path / "out_unkpay"
        writer = GPSWriter(str(gps_file), str(out_dir))
        with patch("nov_gnsspq.writer.standard.ne_oem") as mock_ne_oem:
            with patch("nov_gnsspq.writer.standard.tqdm"):
                mock_ne_oem.Message = type("Msg", (), {})
                mock_ne_oem.UnknownMessage = FakeUnknown
                mock_ne_oem.FileParser.return_value = iter([FakeUnknown()])
                # Act
                writer.write_to_db()
        # Assert
        table = pq.read_table(str(out_dir / "unknown_data.parquet"))
        assert table.num_rows == 1
        assert table["payload"].to_pylist()[0] is None

    def test_other_message_type_stored_in_unknown_table(
            self, tmp_path, gps_file):
        """Tests else-branch handles messages that are neither Message nor Unknown."""
        # Arrange
        class OtherMsg:
            data = b"\x01\x02\x03"

        out_dir = tmp_path / "out_other"
        writer = GPSWriter(str(gps_file), str(out_dir))
        with patch("nov_gnsspq.writer.standard.ne_oem") as mock_ne_oem:
            with patch("nov_gnsspq.writer.standard.tqdm"):
                mock_ne_oem.Message = type("Msg", (), {})
                mock_ne_oem.UnknownMessage = type("UM", (), {})
                mock_ne_oem.FileParser.return_value = iter([OtherMsg()])
                # Act
                writer.write_to_db()
        # Assert
        table = pq.read_table(str(out_dir / "unknown_data.parquet"))
        assert table.num_rows == 1

    def test_other_message_data_exception_stores_none(
            self, tmp_path, gps_file):
        """Tests bytes(message.data) exception in else-branch stores None payload."""
        # Arrange
        class OtherMsg:
            @property
            def data(self):
                raise RuntimeError("no data")

        out_dir = tmp_path / "out_otherfail"
        writer = GPSWriter(str(gps_file), str(out_dir))
        with patch("nov_gnsspq.writer.standard.ne_oem") as mock_ne_oem:
            with patch("nov_gnsspq.writer.standard.tqdm"):
                mock_ne_oem.Message = type("Msg", (), {})
                mock_ne_oem.UnknownMessage = type("UM", (), {})
                mock_ne_oem.FileParser.return_value = iter([OtherMsg()])
                # Act
                writer.write_to_db()
        # Assert
        table = pq.read_table(str(out_dir / "unknown_data.parquet"))
        assert table.num_rows == 1
        assert table["payload"].to_pylist()[0] is None

    def test_message_to_dict_runtime_error_stored_as_unknown(
            self, tmp_path, gps_file):
        """Tests ne.Message.to_dict() RuntimeError stores message as unknown."""
        # Arrange
        class FakeMsg:
            name = "BADMSG"
            payload = b"\xDE\xAD"
            def to_dict(self):
                raise RuntimeError("to_dict failed")

        out_dir = tmp_path / "out_todict_err"
        writer = GPSWriter(str(gps_file), str(out_dir))
        with patch("nov_gnsspq.writer.standard.ne_oem") as mock_ne_oem:
            with patch("nov_gnsspq.writer.standard.tqdm"):
                mock_ne_oem.Message = FakeMsg
                mock_ne_oem.UnknownMessage = type("UM", (), {})
                mock_ne_oem.FileParser.return_value = iter([FakeMsg()])
                # Act
                writer.write_to_db()
        # Assert
        table = pq.read_table(str(out_dir / "unknown_data.parquet"))
        assert table.num_rows == 1
        assert table["payload"].to_pylist()[0] == b"\xDE\xAD"

    def test_message_to_dict_runtime_error_payload_failure_stores_none(
            self, tmp_path, gps_file):
        """Tests that payload bytes() failure after to_dict() RuntimeError stores None."""
        # Arrange
        class FakeMsg:
            name = "BADMSG"
            @property
            def payload(self):
                raise RuntimeError("payload also broken")
            def to_dict(self):
                raise RuntimeError("to_dict failed")

        out_dir = tmp_path / "out_todict_payerr"
        writer = GPSWriter(str(gps_file), str(out_dir))
        with patch("nov_gnsspq.writer.standard.ne_oem") as mock_ne_oem:
            with patch("nov_gnsspq.writer.standard.tqdm"):
                mock_ne_oem.Message = FakeMsg
                mock_ne_oem.UnknownMessage = type("UM", (), {})
                mock_ne_oem.FileParser.return_value = iter([FakeMsg()])
                # Act
                writer.write_to_db()
        # Assert
        table = pq.read_table(str(out_dir / "unknown_data.parquet"))
        assert table.num_rows == 1
        assert table["payload"].to_pylist()[0] is None

    def test_periodic_flush_triggers_at_500_messages(
            self, tmp_path, gps_file):
        """Tests the flush counter resets and calls _maybe_flush_subtree at 500."""
        # Arrange
        class FakeMsg:
            name = "BESTPOS"
            def to_dict(self): return {"header": {}, "v": 1}

        out_dir = tmp_path / "out_flush500"
        writer = GPSWriter(str(gps_file), str(out_dir))
        writer._flush_ctr = 499
        with patch("nov_gnsspq.writer.standard.ne_oem") as mock_ne_oem:
            with patch("nov_gnsspq.writer.standard.tqdm"):
                mock_ne_oem.Message = FakeMsg
                mock_ne_oem.UnknownMessage = type("UM", (), {})
                mock_ne_oem.FileParser.return_value = iter([FakeMsg()])
                with patch.object(
                        writer, "_maybe_flush_subtree") as mock_flush:
                    # Act
                    writer.write_to_db()
        # Assert
        mock_flush.assert_called()
