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

Tests for module-level worker functions and merge helpers in
nov_gnsspq.writer.parallel.engine.
"""
import enum
import os
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from nov_gnsspq.reader.schema import PARENT_ID_COL, SEQUENCE_ID_COL
from nov_gnsspq.writer.parallel.edie import (
    TableNode,
    _col_append,
    _w_add_entry,
    _w_build_table_tree,
    _w_close_all_writers,
    _w_dispatch_list_field,
    _w_flush_all,
    _w_flush_node,
    _w_get_seq_id,
    _w_maybe_flush_subtree,
    _w_process_value,
    _worker_process,
    _write_row_group,
)
from nov_gnsspq.writer.parallel.merger import (
    _apply_offsets,
    _merge_log_table,
    _merge_tree,
    _merge_unknown_table,
)


# ---------------------------------------------------------------------------
# Test doubles  (same metaclass trick as in test_gps_writer.py)
# ---------------------------------------------------------------------------

_EnumerationType = type("nb_meta", (type,), {})
_PyCStructType = type("nb_meta", (type,), {})


def _make_enum_value(str_rep: str, int_rep: int):
    """Builds a value whose type metaclass is EnumerationType."""
    cls = _EnumerationType("MockEnum", (object,), {
        "__str__": lambda self: str_rep,
        "__int__": lambda self: int_rep,
    })
    return cls()


def _make_pycstruct_bytes(raw: bytes):
    """Builds a PyCStructType instance with a bytes .value attribute."""
    cls = _PyCStructType("BytesStruct", (object,), {"value": raw})
    return cls()


def _make_pycstruct_plain():
    """Builds a PyCStructType instance with no .value attribute."""
    cls = _PyCStructType("PlainStruct", (object,), {})
    return cls()


def _make_pycstruct_str_value(val: str):
    """Builds a PyCStructType instance with a non-bytes .value attribute."""
    cls = _PyCStructType("StrStruct", (object,), {"value": val})
    return cls()


class _StdlibEnum(enum.Enum):
    """Minimal stdlib enum used as a test double."""

    ALPHA = 1
    BETA = 2


# pylint: disable=protected-access


class TestWGetSeqId:
    """Tests for the _w_get_seq_id module-level function."""

    def test_increments_for_leaf_same_parent(self):
        """Tests that sequence increments by 1 when parent_id is unchanged."""
        # Arrange
        node = TableNode("T", "/o", "T")
        node.last_seq_id = 9
        node.last_parent_id = 3
        # Act & Assert
        assert _w_get_seq_id(node, parent_id=3) == 10

    def test_increments_for_non_leaf_regardless_of_parent(self):
        """Tests that non-leaf nodes always increment regardless of parent change."""
        # Arrange
        node = TableNode("T", "/o", "T")
        node.last_seq_id = 2
        node.last_parent_id = 0
        node.subtables["child"] = TableNode("c", "/o/T/c", "c")
        # Act & Assert
        assert _w_get_seq_id(node, parent_id=99) == 3

    def test_returns_zero_for_new_node(self):
        """Tests that zero is returned when last_seq_id is None."""
        # Arrange
        node = TableNode("T", "/o", "T")
        # Act & Assert
        assert _w_get_seq_id(node, parent_id=None) == 0

    def test_returns_zero_on_parent_change_for_leaf(self):
        """Tests that sequence resets to 0 for a leaf node when the parent changes."""
        # Arrange
        node = TableNode("T", "/o", "T")
        node.last_seq_id = 4
        node.last_parent_id = 1
        # Act & Assert
        assert _w_get_seq_id(node, parent_id=99) == 0


class TestWProcessValue:
    """Tests for the _w_process_value module-level function."""

    def test_enumeration_type_raw_none_on_int_fail(self):
        """Tests that _raw column gets None when int() conversion fails."""
        # Arrange
        cls = _EnumerationType("E2", (object,), {
            "__str__": lambda self: "X",
            "__int__": lambda self: (_ for _ in ()).throw(ValueError),
        })
        val = cls()
        cols = {}
        # Act
        _w_process_value(val, "s", cols, 0)
        # Assert
        assert cols["s_raw"] == [None]

    def test_enumeration_type_str_and_raw(self):
        """Tests that EnumerationType creates both a string and _raw int column."""
        # Arrange
        val = _make_enum_value("GOOD", 5)
        cols = {}
        # Act
        _w_process_value(val, "status", cols, 0)
        # Assert
        assert cols["status"] == ["GOOD"]
        assert cols["status_raw"] == [5]

    def test_fallback_stores_value_directly(self):
        """Tests that an unrecognised type is stored without transformation."""
        # Arrange
        class Unrecognised:
            pass
        val = Unrecognised()
        cols = {}
        # Act
        _w_process_value(val, "f", cols, 0)
        # Assert
        assert cols["f"] == [val]

    def test_fast_path_backfills_with_nones(self):
        """Tests that a new column is backfilled when row_count > 0."""
        # Arrange
        cols = {}
        # Act
        _w_process_value(7, "f", cols, 3)
        # Assert
        assert cols["f"] == [None, None, None, 7]

    @pytest.mark.parametrize("value, expected", [
        (42, 42),
        (3.14, 3.14),
        ("text", "text"),
        (False, False),
        (None, None),
    ])
    def test_fast_path_python_scalars(self, value, expected):
        """Tests that Python scalars are stored directly."""
        # Arrange
        cols = {}
        # Act
        _w_process_value(value, "f", cols, 0)
        # Assert
        assert cols["f"] == [expected]

    def test_generic_value_attr_stored_as_str(self):
        """Tests that an object with .value (not otherwise classified) uses str()."""
        # Arrange
        class WithValue:
            value = "inner"
            def __str__(self): return "WithValue(inner)"
        val = WithValue()
        cols = {}
        # Act
        _w_process_value(val, "f", cols, 0)
        # Assert
        assert cols["f"] == ["WithValue(inner)"]

    def test_pycstruct_bytes_value_stored_as_bytes(self):
        """Tests that PyCStructType with bytes .value stores raw bytes."""
        # Arrange
        val = _make_pycstruct_bytes(b"\x01\x02")
        cols = {}
        # Act
        _w_process_value(val, "raw", cols, 0)
        # Assert
        assert cols["raw"] == [b"\x01\x02"]

    def test_pycstruct_no_value_stored_as_str(self):
        """Tests that a plain nb_meta object with no .value is stored as str."""
        # Arrange
        val = _make_pycstruct_plain()
        cols = {}
        # Act
        _w_process_value(val, "f", cols, 0)
        # Assert
        assert cols["f"] == [str(val)]
        assert cols["f_raw"] == [None]

    def test_pycstruct_satellite_id_expands_subfields(self):
        """Tests that SatelliteId-shaped nb_meta type expands into prefixed sub-fields."""
        # Arrange
        SatCls = _EnumerationType("SatelliteId", (object,), {
            "to_dict": lambda self: {"prn": 5, "frequency_channel": -7}
        })
        val = SatCls()
        cols = {}
        # Act
        with patch("nov_gnsspq.writer.parallel.edie.SAT_ID_TYPE", SatCls):
            _w_process_value(val, "sat", cols, 0)
        # Assert
        assert cols["sat_prn"] == [5]
        assert cols["sat_frequency_channel"] == [-7]

    def test_pycstruct_str_value_stored_as_string(self):
        """Tests that PyCStructType with non-bytes .value stores str representation."""
        # Arrange
        val = _make_pycstruct_str_value("some_val")
        cols = {}
        # Act
        _w_process_value(val, "f", cols, 0)
        # Assert
        assert cols["f"] == [str(val)]

    def test_stdlib_enum_stores_str_and_raw(self):
        """Tests that a Python enum.Enum stores its string form and .value."""
        # Arrange
        cols = {}
        # Act
        _w_process_value(_StdlibEnum.ALPHA, "mode", cols, 0)
        # Assert
        assert cols["mode"] == [str(_StdlibEnum.ALPHA)]
        assert cols["mode_raw"] == [1]


class TestWAddEntry:
    """Tests for the _w_add_entry module-level function."""

    def test_creates_new_node(self, tmp_path):
        """Tests that a TableNode is created for an unseen log_type."""
        # Arrange
        tables = {}
        # Act
        _w_add_entry({}, tables, "T", None,
                     parent_output_dir=str(tmp_path),
                     output_folder=str(tmp_path))
        # Assert
        assert "T" in tables

    def test_list_of_dicts_creates_multiple_subtable_rows(self, tmp_path):
        """Tests that a list of dicts creates one subtable row per item."""
        # Arrange
        tables = {}
        # Act
        _w_add_entry(
            {"obs": [{"s": "L1"}, {"s": "L2"}]}, tables, "R", None,
            parent_output_dir=str(tmp_path),
            output_folder=str(tmp_path))
        # Assert
        assert tables["R"].subtables["obs"].row_count == 2

    def test_list_of_scalars_becomes_keyed_subtable(self, tmp_path):
        """Tests that a list of scalars is stored as key_0, key_1, ... in a subtable."""
        # Arrange
        tables = {}
        # Act
        _w_add_entry({"vals": [1, 2, 3]}, tables, "T", None,
                     parent_output_dir=str(tmp_path),
                     output_folder=str(tmp_path))
        sub = tables["T"].subtables["vals"]
        # Assert
        assert (
            "key_0" in sub.cols
            and "key_1" in sub.cols
            and "key_2" in sub.cols
        )

    def test_missing_column_backfilled_with_none(self, tmp_path):
        """Tests that a column absent from a later entry gets None backfill."""
        # Arrange
        tables = {}
        _w_add_entry({"a": 1, "b": 2}, tables, "T", None,
                     parent_output_dir=str(tmp_path),
                     output_folder=str(tmp_path))
        # Act
        _w_add_entry({"a": 3}, tables, "T", None,
                     parent_output_dir=str(tmp_path),
                     output_folder=str(tmp_path))
        # Assert
        assert tables["T"].cols["b"] == [2, None]

    def test_nested_dict_creates_subtable(self, tmp_path):
        """Tests that a nested dict field creates a child TableNode."""
        # Arrange
        tables = {}
        # Act
        _w_add_entry({"obs": {"sig": "L1"}}, tables, "RANGE", None,
                     parent_output_dir=str(tmp_path),
                     output_folder=str(tmp_path))
        # Assert
        assert "obs" in tables["RANGE"].subtables

    def test_parent_id_absent_when_none(self, tmp_path):
        """Tests that the parent_id column is absent when parent_id=None."""
        # Arrange
        tables = {}
        # Act
        _w_add_entry({"v": 1}, tables, "T", None,
                     parent_output_dir=str(tmp_path),
                     output_folder=str(tmp_path))
        # Assert
        assert PARENT_ID_COL not in tables["T"].cols

    def test_parent_id_added_when_not_none(self, tmp_path):
        """Tests that parent_id is stored when provided."""
        # Arrange
        tables = {}
        # Act
        _w_add_entry({"v": 1}, tables, "sub", parent_id=3,
                     parent_output_dir=str(tmp_path),
                     output_folder=str(tmp_path))
        # Assert
        assert tables["sub"].cols[PARENT_ID_COL] == [3]

    def test_row_count_increments(self, tmp_path):
        """Tests that row_count increases for each call."""
        # Arrange
        tables = {}
        # Act
        for _ in range(4):
            _w_add_entry({"x": 1}, tables, "T", None,
                         parent_output_dir=str(tmp_path),
                         output_folder=str(tmp_path))
        # Assert
        assert tables["T"].row_count == 4

    def test_scalar_fields_accumulated(self, tmp_path):
        """Tests that scalar fields are appended to the node's cols."""
        # Arrange
        tables = {}
        # Act
        _w_add_entry({"lat": 51.0, "lon": -114.0}, tables, "P", None,
                     parent_output_dir=str(tmp_path),
                     output_folder=str(tmp_path))
        # Assert
        assert tables["P"].cols["lat"] == [51.0]
        assert tables["P"].cols["lon"] == [-114.0]

    def test_sequence_id_starts_at_zero(self, tmp_path):
        """Tests that the first entry receives sequence_id=0."""
        # Arrange
        tables = {}
        # Act
        _w_add_entry({"v": 1}, tables, "T", None,
                     parent_output_dir=str(tmp_path),
                     output_folder=str(tmp_path))
        # Assert
        assert tables["T"].cols[SEQUENCE_ID_COL] == [0]


class TestWFlushHelpers:
    """Tests for the stateless flush helper functions."""

    def test_w_flush_all_flushes_every_non_empty_node(self, tmp_path):
        """Tests that _w_flush_all processes all nodes with data."""
        # Arrange
        node_a = TableNode("A", str(tmp_path / "A"), "A")
        node_a.cols = {"v": [1]}
        node_a.row_count = 1
        node_b = TableNode("B", str(tmp_path / "B"), "B")
        node_b.cols = {"v": [2]}
        node_b.row_count = 1
        tables = {"A": node_a, "B": node_b}
        # Act
        _w_flush_all(tables, "zstd")
        # Assert
        assert node_a.row_count == 0
        assert node_b.row_count == 0

    def test_w_flush_all_skips_empty_nodes(self, tmp_path):
        """Tests that _w_flush_all does not flush nodes with row_count == 0."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        node.row_count = 0
        # Act
        _w_flush_all({"T": node}, "zstd")
        # Assert
        assert node.parquet_writer is None

    def test_w_flush_node_clears_cols(self, tmp_path):
        """Tests that _w_flush_node empties the cols lists."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        node.cols = {"a": [1, 2, 3]}
        node.row_count = 3
        # Act
        _w_flush_node(node, "zstd")
        # Assert
        assert node.cols["a"] == []

    def test_w_flush_node_writes_parquet(self, tmp_path):
        """Tests that _w_flush_node writes a Parquet file and clears the node."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        node.cols = {"a": [1, 2]}
        node.row_count = 2
        # Act
        _w_flush_node(node, "zstd")
        node.parquet_writer.close()
        # Assert
        assert (tmp_path / "T.parquet").exists()
        assert node.row_count == 0

    def test_w_maybe_flush_subtree_flushes_at_threshold(self, tmp_path):
        """Tests that _w_maybe_flush_subtree flushes when row_count >= chunk_size."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        node.cols = {"a": [1]}
        node.row_count = 1
        # Act
        _w_maybe_flush_subtree(node, chunk_size=1, compression="zstd")
        # Assert
        assert node.row_count == 0

    def test_w_maybe_flush_subtree_recurses(self, tmp_path):
        """Tests that _w_maybe_flush_subtree flushes nested subtable nodes."""
        # Arrange
        parent = TableNode("P", str(tmp_path), "P")
        parent.row_count = 0
        child = TableNode("C", str(tmp_path / "C"), "C")
        child.cols = {"x": [10]}
        child.row_count = 1
        parent.subtables["C"] = child
        # Act
        _w_maybe_flush_subtree(parent, chunk_size=1, compression="zstd")
        # Assert
        assert child.row_count == 0

    def test_w_maybe_flush_subtree_skips_below_threshold(self, tmp_path):
        """Tests that _w_maybe_flush_subtree skips a node below chunk_size."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        node.cols = {"a": [1]}
        node.row_count = 1
        # Act
        _w_maybe_flush_subtree(node, chunk_size=1000, compression="zstd")
        # Assert
        assert node.row_count == 1


class TestWCloseAllWriters:
    """Tests for the _w_close_all_writers helper."""

    def test_closes_open_writer(self, tmp_path):
        """Tests that _w_close_all_writers calls .close() on each open writer."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        mock_pw = MagicMock()
        node.parquet_writer = mock_pw
        # Act
        _w_close_all_writers({"T": node})
        # Assert
        mock_pw.close.assert_called_once()
        assert node.parquet_writer is None

    def test_skips_none_writers(self, tmp_path):
        """Tests that _w_close_all_writers does not crash on None parquet_writer."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        node.parquet_writer = None
        # Act & Assert
        _w_close_all_writers({"T": node})  # must not raise


class TestWBuildTableTree:
    """Tests for the _w_build_table_tree serialisation helper."""

    def test_node_with_parquet_file_has_correct_row_count(self, tmp_path):
        """Tests that a node whose parquet file exists has the correct row_count."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        _write_row_group({"a": [1, 2, 3]}, node, "zstd")
        node.parquet_writer.close()
        node.parquet_writer = None
        # Act
        tree = _w_build_table_tree({"T": node})
        # Assert
        assert tree["T"]["row_count"] == 3
        assert tree["T"]["parquet_path"] is not None

    def test_node_without_parquet_file_has_none_path(self, tmp_path):
        """Tests that a node whose parquet file doesn't exist gets parquet_path=None."""
        # Arrange
        node = TableNode("T", str(tmp_path / "missing"), "T")
        # Act
        tree = _w_build_table_tree({"T": node})
        # Assert
        assert tree["T"]["parquet_path"] is None
        assert tree["T"]["row_count"] == 0

    def test_read_metadata_exception_returns_zero_row_count(self, tmp_path):
        """Tests that pq.read_metadata exception yields row_count=0."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        (tmp_path / "T.parquet").write_bytes(b"not-valid-parquet")
        # Act
        with patch("nov_gnsspq.writer.parallel.edie.pq.read_metadata",
                   side_effect=pa.lib.ArrowInvalid("corrupt file")):
            tree = _w_build_table_tree({"T": node})
        # Assert
        assert tree["T"]["row_count"] == 0
        assert tree["T"]["parquet_path"] is not None

    def test_returns_empty_dict_for_empty_tables(self):
        """Tests that an empty tables dict produces an empty tree."""
        # Act & Assert
        assert _w_build_table_tree({}) == {}

    def test_subtables_are_included_recursively(self, tmp_path):
        """Tests that nested subtables appear under the 'subtables' key."""
        # Arrange
        parent = TableNode("P", str(tmp_path), "P")
        child = TableNode("C", str(tmp_path / "C"), "C")
        parent.subtables["C"] = child
        # Act
        tree = _w_build_table_tree({"P": parent})
        # Assert
        assert "C" in tree["P"]["subtables"]


class TestApplyOffsets:
    """Tests for the _apply_offsets merge helper."""

    def _child_table(
            self, seq_ids: list[int], parent_ids: list[int]) -> pa.Table:
        """Builds a subtable with both sequence_id and parent_id columns."""
        return pa.table({
            SEQUENCE_ID_COL: pa.array(seq_ids, type=pa.int64()),
            PARENT_ID_COL: pa.array(parent_ids, type=pa.int64()),
        })

    def _root_table(self, seq_ids: list[int]) -> pa.Table:
        """Builds a root-level table with no parent_id column."""
        return pa.table({
            SEQUENCE_ID_COL: pa.array(seq_ids, type=pa.int64()),
        })

    def test_leaf_subtable_offsets_only_parent_id(self):
        """Tests that leaf subtables offset parent_id but not sequence_id."""
        # Arrange
        tbl = self._child_table([0, 1, 0, 1], [0, 0, 1, 1])
        # Act
        result = _apply_offsets(
            tbl, seq_offset=5, parent_offset=10, is_leaf=True)
        # Assert
        assert result[SEQUENCE_ID_COL].to_pylist() == [0, 1, 0, 1]
        assert result[PARENT_ID_COL].to_pylist() == [10, 10, 11, 11]

    def test_non_leaf_subtable_offsets_both_columns(self):
        """Tests that non-leaf subtables offset both sequence_id and parent_id."""
        # Arrange
        tbl = self._child_table([0, 1], [0, 0])
        # Act
        result = _apply_offsets(
            tbl, seq_offset=3, parent_offset=7, is_leaf=False)
        # Assert
        assert result[SEQUENCE_ID_COL].to_pylist() == [3, 4]
        assert result[PARENT_ID_COL].to_pylist() == [7, 7]

    def test_root_node_seq_id_offset_applied(self):
        """Tests that sequence_id is shifted by seq_offset for root nodes."""
        # Arrange
        tbl = self._root_table([0, 1, 2])
        # Act
        result = _apply_offsets(
            tbl, seq_offset=10, parent_offset=0, is_leaf=False)
        # Assert
        assert result[SEQUENCE_ID_COL].to_pylist() == [10, 11, 12]

    def test_root_node_zero_offset_unchanged(self):
        """Tests that a root node is unchanged when seq_offset=0."""
        # Arrange
        tbl = self._root_table([0, 1])
        # Act
        result = _apply_offsets(
            tbl, seq_offset=0, parent_offset=0, is_leaf=False)
        # Assert
        assert result[SEQUENCE_ID_COL].to_pylist() == [0, 1]

    def test_zero_offsets_no_change(self):
        """Tests that zero offsets produce no change to any column."""
        # Arrange
        tbl = self._child_table([0, 1], [2, 3])
        # Act
        result = _apply_offsets(
            tbl, seq_offset=0, parent_offset=0, is_leaf=False)
        # Assert
        assert result[SEQUENCE_ID_COL].to_pylist() == [0, 1]
        assert result[PARENT_ID_COL].to_pylist() == [2, 3]


class TestMergeLogTable:
    """Tests for the _merge_log_table function."""

    def _write_log_parquet(
            self, path: str, log_types: list, seq_ids: list):
        """Writes a minimal log parquet file to path."""
        pq.write_table(
            pa.table({
                "log": pa.array(log_types, type=pa.string()),
                SEQUENCE_ID_COL: pa.array(seq_ids, type=pa.int64()),
            }),
            path,
            compression="zstd",
        )

    def test_single_worker_no_offset(self, tmp_path):
        """Tests that single-worker merge writes the log table unchanged."""
        # Arrange
        log_path = str(tmp_path / "w0_log.parquet")
        self._write_log_parquet(log_path, ["BESTPOS", "RANGE"], [0, 1])
        result = [{"log_table_path": log_path, "total_messages": 2}]
        # Act
        total = _merge_log_table(result, str(tmp_path), "zstd")
        table = pq.read_table(str(tmp_path / f"{tmp_path.name}.parquet"))
        # Assert
        assert total == 2
        assert table.num_rows == 2
        assert table[SEQUENCE_ID_COL].to_pylist() == [0, 1]

    def test_two_workers_sequence_ids_offset(self, tmp_path):
        """Tests that second worker's sequence_ids are offset by first worker's count."""
        # Arrange
        log0 = str(tmp_path / "w0_log.parquet")
        log1 = str(tmp_path / "w1_log.parquet")
        self._write_log_parquet(log0, ["BESTPOS"], [0])
        self._write_log_parquet(log1, ["RANGE"], [0])
        results = [
            {"log_table_path": log0, "total_messages": 1},
            {"log_table_path": log1, "total_messages": 1},
        ]
        # Act
        total = _merge_log_table(results, str(tmp_path), "zstd")
        table = pq.read_table(str(tmp_path / f"{tmp_path.name}.parquet"))
        # Assert
        assert total == 2
        assert table[SEQUENCE_ID_COL].to_pylist() == [0, 1]
        assert table["log"].to_pylist() == ["BESTPOS", "RANGE"]


class TestMergeUnknownTable:
    """Tests for the _merge_unknown_table function."""

    def _write_unknown(
            self, path: str, seq_ids: list, payloads: list):
        """Writes a minimal unknown-data parquet file to path."""
        pq.write_table(
            pa.table({
                SEQUENCE_ID_COL: pa.array(seq_ids, type=pa.int64()),
                "payload": pa.array(payloads, type=pa.binary()),
            }),
            path,
            compression="zstd",
        )

    def test_empty_result_list_writes_empty_table(self, tmp_path):
        """Tests that an empty results list produces an empty unknown table."""
        # Act
        _merge_unknown_table([], str(tmp_path), "zstd")
        table = pq.read_table(str(tmp_path / "unknown_data.parquet"))
        # Assert
        assert table.num_rows == 0

    def test_merges_two_workers_with_offset(self, tmp_path):
        """Tests that second worker's sequence_ids are offset in the merged unknown table."""
        # Arrange
        u0 = str(tmp_path / "u0.parquet")
        u1 = str(tmp_path / "u1.parquet")
        self._write_unknown(u0, [0], [b"\xAA"])
        self._write_unknown(u1, [0], [b"\xBB"])
        results = [
            {"unknown_path": u0, "total_messages": 2},
            {"unknown_path": u1, "total_messages": 2},
        ]
        # Act
        _merge_unknown_table(results, str(tmp_path), "zstd")
        table = pq.read_table(str(tmp_path / "unknown_data.parquet"))
        # Assert
        assert table.num_rows == 2
        assert table[SEQUENCE_ID_COL].to_pylist() == [0, 2]


class TestMergeTree:
    """Tests for the _merge_tree recursive merge function."""

    def _write_root_parquet(
            self, path: str, seq_ids: list, vals: list):
        """Writes a root-level parquet table to path."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        pq.write_table(
            pa.table({
                SEQUENCE_ID_COL: pa.array(seq_ids, type=pa.int64()),
                "val": pa.array(vals, type=pa.int64()),
            }),
            path,
            compression="zstd",
        )

    def test_merges_single_log_type_from_two_workers(self, tmp_path):
        """Tests that _merge_tree concatenates matching log_type tables."""
        # Arrange
        p0 = str(tmp_path / "w0" / "BESTPOS" / "BESTPOS.parquet")
        p1 = str(tmp_path / "w1" / "BESTPOS" / "BESTPOS.parquet")
        self._write_root_parquet(p0, [0, 1], [10, 20])
        self._write_root_parquet(p1, [0, 1], [30, 40])
        trees = [
            {"BESTPOS": {"row_count": 2, "parquet_path": p0, "subtables": {}}},
            {"BESTPOS": {"row_count": 2, "parquet_path": p1, "subtables": {}}},
        ]
        out = str(tmp_path / "merged")
        # Act
        _merge_tree(
            trees, out, "zstd",
            parent_seq_offsets=[0, 0], path_parts=[])
        table = pq.read_table(
            os.path.join(out, "BESTPOS", "BESTPOS.parquet"))
        # Assert
        assert table.num_rows == 4
        assert table[SEQUENCE_ID_COL].to_pylist() == [0, 1, 2, 3]

    def test_missing_log_type_for_one_worker_is_skipped(self, tmp_path):
        """Tests that a log_type absent from worker 0 is still merged from worker 1."""
        # Arrange
        p1 = str(tmp_path / "w1" / "RANGE" / "RANGE.parquet")
        self._write_root_parquet(p1, [0], [99])
        trees = [
            {},
            {"RANGE": {"row_count": 1, "parquet_path": p1, "subtables": {}}},
        ]
        out = str(tmp_path / "merged2")
        # Act
        _merge_tree(
            trees, out, "zstd",
            parent_seq_offsets=[0, 0], path_parts=[])
        table = pq.read_table(os.path.join(out, "RANGE", "RANGE.parquet"))
        # Assert
        assert table.num_rows == 1


class TestWorkerProcess:
    """Tests for the _worker_process function."""

    def _make_args(self, tmp_path, worker_id=0):
        """Builds a minimal args dict with a real source file."""
        src = tmp_path / "src.GPS"
        src.write_bytes(b"x" * 100)
        worker_dir = str(tmp_path / f"w{worker_id}")
        return {
            "worker_id": worker_id,
            "input_file": str(src),
            "start_byte": 0,
            "end_byte": 100,
            "worker_output_dir": worker_dir,
            "compression": "zstd",
            "chunk_size": 1000,
        }

    def test_empty_file_returns_zero_messages(self, tmp_path):
        """Tests that _worker_process returns total_messages=0 for empty iteration."""
        # Arrange
        args = self._make_args(tmp_path)
        # Act
        with patch("nov_gnsspq.writer.parallel.edie.ne_oem") as mock_ne_oem:
            mock_ne_oem.Message = type("Msg", (), {})
            mock_ne_oem.UnknownMessage = type("UM", (), {})
            mock_ne_oem.Response = type("Response", (), {})
            mock_ne_oem.FileParser.return_value = iter([])
            result = _worker_process(args)
        # Assert
        assert result["total_messages"] == 0
        assert result["worker_id"] == 0
        assert os.path.exists(result["log_table_path"])
        assert os.path.exists(result["unknown_path"])

    def test_known_message_produces_table_tree_entry(self, tmp_path):
        """Tests that _worker_process returns a table_tree entry for a known message."""
        # Arrange
        args = self._make_args(tmp_path)

        class FakeMsg:
            name = "BESTPOS"
            def to_dict(self): return {"header": {"week": 2200}, "lat": 51.0}

        # Act
        with patch("nov_gnsspq.writer.parallel.edie.ne_oem") as mock_ne_oem:
            mock_ne_oem.Message = FakeMsg
            mock_ne_oem.UnknownMessage = type("UM", (), {})
            mock_ne_oem.Response = type("Response", (), {})
            mock_ne_oem.FileParser.return_value = iter([FakeMsg()])
            result = _worker_process(args)
        # Assert
        assert result["total_messages"] == 1
        assert "BESTPOS" in result["table_tree"]

    def test_other_message_data_exception_stores_none_payload(self, tmp_path):
        """Tests that bytes(message.data) exception in else-branch stores None payload."""
        # Arrange
        args = self._make_args(tmp_path)

        class OtherMsg:
            @property
            def data(self):
                raise RuntimeError("no data")

        # Act
        with patch("nov_gnsspq.writer.parallel.edie.ne_oem") as mock_ne_oem:
            mock_ne_oem.Message = type("Msg", (), {})
            mock_ne_oem.UnknownMessage = type("UM", (), {})
            mock_ne_oem.Response = type("Response", (), {})
            mock_ne_oem.FileParser.return_value = iter([OtherMsg()])
            result = _worker_process(args)
        table = pq.read_table(result["unknown_path"])
        # Assert
        assert table.num_rows == 1
        assert table["payload"].to_pylist()[0] is None

    def test_other_message_type_stored_in_unknown_parquet(self, tmp_path):
        """Tests that non-Message/non-UnknownMessage types land in the unknown table."""
        # Arrange
        args = self._make_args(tmp_path)

        class OtherMsg:
            data = b"\x01\x02"

        # Act
        with patch("nov_gnsspq.writer.parallel.edie.ne_oem") as mock_ne_oem:
            mock_ne_oem.Message = type("Msg", (), {})
            mock_ne_oem.UnknownMessage = type("UM", (), {})
            mock_ne_oem.Response = type("Response", (), {})
            mock_ne_oem.FileParser.return_value = iter([OtherMsg()])
            result = _worker_process(args)
        table = pq.read_table(result["unknown_path"])
        # Assert
        assert table.num_rows == 1

    def test_periodic_flush_triggered_at_500_messages(self, tmp_path):
        """Tests that _w_maybe_flush_subtree is called when flush_ctr reaches 500."""
        # Arrange
        args = self._make_args(tmp_path)

        class FakeMsg:
            name = "T"
            def to_dict(self): return {"header": {}, "v": 1}

        messages = [FakeMsg() for _ in range(502)]
        # Act
        with patch("nov_gnsspq.writer.parallel.edie.ne_oem") as mock_ne_oem:
            mock_ne_oem.Message = FakeMsg
            mock_ne_oem.UnknownMessage = type("UM", (), {})
            mock_ne_oem.Response = type("Response", (), {})
            mock_ne_oem.FileParser.return_value = iter(messages)
            with patch(
                    "nov_gnsspq.writer.parallel.edie._w_maybe_flush_subtree"
            ) as mock_flush:
                result = _worker_process(args)
        # Assert
        assert result["total_messages"] == 502
        mock_flush.assert_called()

    def test_slice_beyond_file_size_handles_early_eof(self, tmp_path):
        """Tests that early EOF in the copy loop is handled cleanly."""
        # Arrange
        src = tmp_path / "short.GPS"
        src.write_bytes(b"x" * 50)
        args = {
            "worker_id": 0,
            "input_file": str(src),
            "start_byte": 0,
            "end_byte": 200,
            "worker_output_dir": str(tmp_path / "w0_eof"),
            "compression": "zstd",
            "chunk_size": 1000,
        }
        # Act
        with patch("nov_gnsspq.writer.parallel.edie.ne_oem") as mock_ne_oem:
            mock_ne_oem.Message = type("Msg", (), {})
            mock_ne_oem.UnknownMessage = type("UM", (), {})
            mock_ne_oem.Response = type("Response", (), {})
            mock_ne_oem.FileParser.return_value = iter([])
            result = _worker_process(args)
        # Assert
        assert result["total_messages"] == 0

    def test_tmp_file_removal_oserror_is_silenced(self, tmp_path):
        """Tests that OSError during temp-file cleanup is swallowed."""
        # Arrange
        args = self._make_args(tmp_path)
        # Act
        with patch("nov_gnsspq.writer.parallel.edie.ne_oem") as mock_ne_oem:
            mock_ne_oem.Message = type("Msg", (), {})
            mock_ne_oem.UnknownMessage = type("UM", (), {})
            mock_ne_oem.Response = type("Response", (), {})
            mock_ne_oem.FileParser.return_value = iter([])
            with patch(
                    "nov_gnsspq.writer.parallel.edie.os.unlink",
                    side_effect=OSError("locked")):
                result = _worker_process(args)  # must not raise
        # Assert
        assert result["total_messages"] == 0

    def test_unknown_message_stored_in_unknown_parquet(self, tmp_path):
        """Tests that ne.UnknownMessage payload is written to the worker unknown file."""
        # Arrange
        args = self._make_args(tmp_path)

        class FakeUnknown:
            payload = b"\xFF\xFE"

        # Act
        with patch("nov_gnsspq.writer.parallel.edie.ne_oem") as mock_ne_oem:
            mock_ne_oem.Message = type("Msg", (), {})
            mock_ne_oem.UnknownMessage = FakeUnknown
            mock_ne_oem.FileParser.return_value = iter([FakeUnknown()])
            result = _worker_process(args)
        table = pq.read_table(result["unknown_path"])
        # Assert
        assert table.num_rows == 1
        assert table["payload"].to_pylist()[0] == b"\xFF\xFE"

    def test_unknown_payload_exception_yields_none(self, tmp_path):
        """Tests that bytes(payload) exception on UnknownMessage stores None payload."""
        # Arrange
        args = self._make_args(tmp_path)

        class FakeUnknown:
            @property
            def payload(self):
                raise RuntimeError("bad payload")

        # Act
        with patch("nov_gnsspq.writer.parallel.edie.ne_oem") as mock_ne_oem:
            mock_ne_oem.Message = type("Msg", (), {})
            mock_ne_oem.UnknownMessage = FakeUnknown
            mock_ne_oem.FileParser.return_value = iter([FakeUnknown()])
            result = _worker_process(args)
        table = pq.read_table(result["unknown_path"])
        # Assert
        assert table.num_rows == 1
        assert table["payload"].to_pylist()[0] is None

    def test_message_to_dict_runtime_error_stored_as_unknown(self, tmp_path):
        """Tests that ne.Message.to_dict() RuntimeError stores message as unknown."""
        # Arrange
        args = self._make_args(tmp_path)

        class FakeMsg:
            name = "BADMSG"
            payload = b"\xCA\xFE"
            def to_dict(self):
                raise RuntimeError("to_dict failed")

        # Act
        with patch("nov_gnsspq.writer.parallel.edie.ne_oem") as mock_ne_oem:
            mock_ne_oem.Message = FakeMsg
            mock_ne_oem.UnknownMessage = type("UM", (), {})
            mock_ne_oem.Response = type("Response", (), {})
            mock_ne_oem.FileParser.return_value = iter([FakeMsg()])
            result = _worker_process(args)
        table = pq.read_table(result["unknown_path"])
        # Assert
        assert table.num_rows == 1
        assert table["payload"].to_pylist()[0] == b"\xCA\xFE"

    def test_message_to_dict_runtime_error_payload_failure_stores_none(
            self, tmp_path):
        """Tests that payload bytes() failure after to_dict() RuntimeError stores None."""
        # Arrange
        args = self._make_args(tmp_path)

        class FakeMsg:
            name = "BADMSG"
            @property
            def payload(self):
                raise RuntimeError("payload broken too")
            def to_dict(self):
                raise RuntimeError("to_dict failed")

        # Act
        with patch("nov_gnsspq.writer.parallel.edie.ne_oem") as mock_ne_oem:
            mock_ne_oem.Message = FakeMsg
            mock_ne_oem.UnknownMessage = type("UM", (), {})
            mock_ne_oem.Response = type("Response", (), {})
            mock_ne_oem.FileParser.return_value = iter([FakeMsg()])
            result = _worker_process(args)
        table = pq.read_table(result["unknown_path"])
        # Assert
        assert table.num_rows == 1
        assert table["payload"].to_pylist()[0] is None

    def test_response_message_stored_in_unknown_table_with_none_payload(
            self, tmp_path):
        """Tests that ne.oem.Response instances are stored as unknown with None payload."""
        # Arrange
        args = self._make_args(tmp_path)

        class FakeResponse:
            pass

        # Act
        with patch("nov_gnsspq.writer.parallel.edie.ne_oem") as mock_ne_oem:
            mock_ne_oem.Message = type("Msg", (), {})
            mock_ne_oem.UnknownMessage = type("UM", (), {})
            mock_ne_oem.Response = type("Response", (), {})
            mock_ne_oem.Response = FakeResponse
            mock_ne_oem.FileParser.return_value = iter([FakeResponse()])
            result = _worker_process(args)
        table = pq.read_table(result["unknown_path"])
        # Assert
        assert table.num_rows == 1
        assert table["payload"].to_pylist()[0] is None


class TestColAppend:
    """Tests for the _col_append helper."""

    def test_initializes_new_column_with_backfill(self):
        """Tests that a new column is backfilled with None when row_count > 0."""
        # Arrange
        cols = {}
        # Act
        _col_append(cols, "x", 3, 99)
        # Assert
        assert cols["x"] == [None, None, None, 99]

    def test_appends_to_existing_column(self):
        """Tests that an existing column receives the value appended."""
        # Arrange
        cols = {"x": [1, 2]}
        # Act
        _col_append(cols, "x", 2, 3)
        # Assert
        assert cols["x"] == [1, 2, 3]

    def test_no_backfill_when_row_count_zero(self):
        """Tests that a new column with row_count=0 starts with just the value."""
        # Arrange
        cols = {}
        # Act
        _col_append(cols, "y", 0, "hello")
        # Assert
        assert cols["y"] == ["hello"]

    def test_none_value_appended(self):
        """Tests that None is appended correctly."""
        # Arrange
        cols = {}
        # Act
        _col_append(cols, "z", 1, None)
        # Assert
        assert cols["z"] == [None, None]

    def test_multiple_fields_independent(self):
        """Tests that multiple calls create independent columns."""
        # Arrange
        cols = {}
        # Act
        _col_append(cols, "a", 0, 1)
        _col_append(cols, "b", 0, 2)
        # Assert
        assert cols["a"] == [1]
        assert cols["b"] == [2]


class TestWDispatchListField:
    """Tests for the _w_dispatch_list_field helper."""

    def test_empty_list_does_nothing(self, tmp_path):
        """Tests that an empty list does not create subtable entries."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        # Act
        _w_dispatch_list_field(
            "obs", [], node, seq_id=0, output_folder=str(tmp_path)
        )
        # Assert
        assert "obs" not in node.subtables

    def test_list_of_dicts_creates_one_subtable_row_each(self, tmp_path):
        """Tests that list-of-dicts creates one subtable row per item."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        # Act
        _w_dispatch_list_field(
            "obs",
            [{"s": "L1"}, {"s": "L2"}],
            node,
            seq_id=0,
            output_folder=str(tmp_path),
        )
        # Assert
        assert node.subtables["obs"].row_count == 2

    def test_list_of_scalars_creates_keyed_subtable(self, tmp_path):
        """Tests that list of scalars creates key_0, key_1, ... subtable entries."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        # Act
        _w_dispatch_list_field(
            "vals",
            [10, 20, 30],
            node,
            seq_id=0,
            output_folder=str(tmp_path),
        )
        # Assert
        subtable = node.subtables["vals"]
        assert "key_0" in subtable.cols
        assert "key_1" in subtable.cols
        assert "key_2" in subtable.cols

    def test_list_of_scalars_values_stored_correctly(self, tmp_path):
        """Tests that scalar list values are stored under the keyed columns."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        # Act
        _w_dispatch_list_field(
            "vals",
            [10, 20],
            node,
            seq_id=0,
            output_folder=str(tmp_path),
        )
        # Assert
        subtable = node.subtables["vals"]
        assert subtable.cols["key_0"] == [10]
        assert subtable.cols["key_1"] == [20]

    def test_mixed_list_treated_as_scalars(self, tmp_path):
        """Tests that a mixed list is key-indexed: scalars become columns, dicts recurse."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        # Act
        _w_dispatch_list_field(
            "mixed",
            [{"a": 1}, 99],
            node,
            seq_id=0,
            output_folder=str(tmp_path),
        )
        mixed_node = node.subtables["mixed"]
        # Assert: the scalar (99) becomes key_1 in cols; the dict {"a":1} recurses
        assert mixed_node.cols["key_1"] == [99]
        assert "key_0" in mixed_node.subtables
