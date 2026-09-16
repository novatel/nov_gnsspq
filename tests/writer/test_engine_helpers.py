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

Unit tests for module-level helper functions in
nov_gnsspq.writer.parallel.engine and nov_gnsspq.writer.parallel.edie.
"""
import queue
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from nov_gnsspq.writer.parallel.edie import (
    TableNode,
    _SENTINEL,
    _count_messages,
    _find_message_boundary,
    _flush_worker,
    _write_row_group,
)
from tests.utils import resource
from nov_gnsspq.writer.parallel.engine import _auto_tune


# pylint: disable=protected-access


class TestResourceFunction:
    """Tests for the resource() helper that resolves test-file paths."""

    def test_returns_string_containing_filename(self):
        """Tests resource() returns a path string that ends with the filename."""
        # Act
        result = resource("test.GPS")
        # Assert
        assert isinstance(result, str)
        assert result.endswith("test.GPS")

    def test_different_filenames_produce_different_paths(self):
        """Tests resource() produces distinct paths for distinct filenames."""
        # Act & Assert
        assert resource("a.GPS") != resource("b.GPS")


class TestCountMessages:
    """Tests for the _count_messages function."""

    def test_returns_correct_count_for_non_empty_file(self, tmp_path):
        """Tests _count_messages returns the number of items yielded by FileParser."""
        # Arrange
        gps_file = tmp_path / "test.GPS"
        gps_file.write_bytes(b"x" * 100)

        class _Item:
            pass

        with patch("nov_gnsspq.writer.parallel.edie.ne") as mock_ne, \
                patch("nov_gnsspq.writer.parallel.edie.ne_oem") as mock_ne_oem:
            mock_ne.ENCODE_FORMAT.FLATTENED_BINARY = "fb"
            mock_parser = MagicMock()
            mock_parser.__iter__ = MagicMock(
                return_value=iter([_Item(), _Item(), _Item()]))
            mock_ne_oem.FileParser.return_value = mock_parser
            # Act
            result = _count_messages(str(gps_file))
        # Assert
        assert result == 3

    def test_returns_zero_for_empty_iteration(self, tmp_path):
        """Tests _count_messages returns 0 when FileParser yields nothing."""
        # Arrange
        gps_file = tmp_path / "empty.GPS"
        gps_file.write_bytes(b"")
        with patch("nov_gnsspq.writer.parallel.edie.ne") as mock_ne, \
                patch("nov_gnsspq.writer.parallel.edie.ne_oem") as mock_ne_oem:
            mock_ne.ENCODE_FORMAT.FLATTENED_BINARY = "fb"
            mock_parser = MagicMock()
            mock_parser.__iter__ = MagicMock(return_value=iter([]))
            mock_ne_oem.FileParser.return_value = mock_parser
            # Act
            result = _count_messages(str(gps_file))
        # Assert
        assert result == 0


class TestAutoTune:
    """Tests for the _auto_tune function."""

    def test_returns_required_keys(self, tmp_path):
        """Tests _auto_tune returns workers, chunk_size, and est_messages."""
        # Arrange
        gps_file = tmp_path / "test.gps"
        gps_file.write_bytes(b"x" * 100_000)
        # Act
        result = _auto_tune(str(gps_file))
        # Assert
        assert "workers" in result
        assert "chunk_size" in result
        assert "est_messages" in result

    def test_chunk_size_clamped_to_lower_bound_for_tiny_file(self, tmp_path):
        """Tests chunk_size is at least 20_000 even for tiny files."""
        # Arrange
        gps_file = tmp_path / "tiny.gps"
        gps_file.write_bytes(b"x" * 100)
        # Act
        result = _auto_tune(str(gps_file))
        # Assert
        assert result["chunk_size"] >= 20_000

    def test_chunk_size_clamped_to_upper_bound_for_moderate_file(
            self, tmp_path):
        """Tests chunk_size does not exceed 200_000 for moderate files."""
        # Arrange
        gps_file = tmp_path / "moderate.gps"
        gps_file.write_bytes(b"x" * 10_000_000)
        # Act
        result = _auto_tune(str(gps_file))
        # Assert
        assert result["chunk_size"] <= 200_000

    def test_workers_between_2_and_8(self, tmp_path):
        """Tests worker count is always in range [2, 8]."""
        # Arrange
        gps_file = tmp_path / "test.gps"
        gps_file.write_bytes(b"x" * 1_000)
        # Act
        result = _auto_tune(str(gps_file))
        # Assert
        assert 2 <= result["workers"] <= 8

    def test_large_file_raises_chunk_size_minimum(self, tmp_path):
        """Tests files over 1 GB raise chunk_size minimum to 200_000."""
        # Arrange
        gps_file = tmp_path / "large.gps"
        gps_file.write_bytes(b"x")
        with patch(
                "nov_gnsspq.writer.parallel.engine.os.path.getsize",
                return_value=2 * 1024 ** 3):
            # Act
            result = _auto_tune(str(gps_file))
        # Assert
        assert result["chunk_size"] >= 200_000

    def test_est_messages_proportional_to_file_size(self, tmp_path):
        """Tests est_messages scales with file size."""
        # Arrange
        small = tmp_path / "small.gps"
        large = tmp_path / "large.gps"
        small.write_bytes(b"x" * 10_000)
        large.write_bytes(b"x" * 100_000)
        # Act
        small_result = _auto_tune(str(small))
        large_result = _auto_tune(str(large))
        # Assert
        assert large_result["est_messages"] > small_result["est_messages"]


class TestWriteRowGroup:
    """Tests for the _write_row_group function."""

    def test_creates_parquet_file_on_first_call(self, tmp_path):
        """Tests a Parquet file is created when node has no writer yet."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        cols = {"sequence_id": [0, 1], "value": [10, 20]}
        # Act
        _write_row_group(cols, node, "zstd")
        node.parquet_writer.close()
        # Assert
        assert (tmp_path / "T.parquet").exists()

    def test_parquet_writer_assigned_to_node(self, tmp_path):
        """Tests node.parquet_writer is set after first write."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        # Act
        _write_row_group({"a": [1]}, node, "zstd")
        # Assert
        assert node.parquet_writer is not None

    def test_schema_cached_after_first_write(self, tmp_path):
        """Tests node.schema_cached is set and reflects the written columns."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        # Act
        _write_row_group({"sequence_id": [0], "name": ["x"]}, node, "zstd")
        # Assert
        assert node.schema_cached is not None
        assert "sequence_id" in node.schema_cached.names
        assert "name" in node.schema_cached.names

    def test_parquet_writer_reused_on_second_call(self, tmp_path):
        """Tests the same ParquetWriter instance is reused across row groups."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        _write_row_group({"a": [1]}, node, "zstd")
        first_writer = node.parquet_writer
        # Act
        _write_row_group({"a": [2]}, node, "zstd")
        # Assert
        assert node.parquet_writer is first_writer

    def test_cached_schema_not_replaced_on_second_call(self, tmp_path):
        """Tests schema_cached stays the same object on the fast path."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        _write_row_group({"val": [1]}, node, "zstd")
        first_schema = node.schema_cached
        # Act
        _write_row_group({"val": [2]}, node, "zstd")
        # Assert
        assert node.schema_cached is first_schema

    def test_creates_nested_output_directory(self, tmp_path):
        """Tests output_dir is created recursively if it does not exist."""
        # Arrange
        deep_dir = tmp_path / "level1" / "level2"
        node = TableNode("T", str(deep_dir), "T")
        # Act
        _write_row_group({"a": [1]}, node, "zstd")
        # Assert
        assert deep_dir.exists()

    def test_written_data_is_readable_by_pyarrow(self, tmp_path):
        """Tests data written to Parquet can be read back with correct values."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        cols = {"sequence_id": [0, 1, 2], "val": [10, 20, 30]}
        _write_row_group(cols, node, "zstd")
        node.parquet_writer.close()
        # Act
        table = pq.read_table(str(tmp_path / "T.parquet"))
        # Assert
        assert table.num_rows == 3
        assert table["val"].to_pylist() == [10, 20, 30]
        assert table["sequence_id"].to_pylist() == [0, 1, 2]

    def test_multiple_row_groups_accumulate_rows(self, tmp_path):
        """Tests two successive calls produce two row groups in the file."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        _write_row_group({"a": [1, 2]}, node, "zstd")
        _write_row_group({"a": [3, 4]}, node, "zstd")
        node.parquet_writer.close()
        # Act
        meta = pq.read_metadata(str(tmp_path / "T.parquet"))
        # Assert
        assert meta.num_row_groups == 2
        assert meta.num_rows == 4

    def test_schema_cast_failure_falls_back_to_inferred_schema(
            self, tmp_path):
        """Tests ArrowInvalid during fast-path cast triggers fallback re-inference."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        node.schema_cached = pa.schema([("val", pa.int64())])
        # Act
        _write_row_group({"val": ["a_string"]}, node, "zstd")
        node.parquet_writer.close()
        # Assert
        table = pq.read_table(str(tmp_path / "T.parquet"))
        assert table.num_rows == 1
        assert table.schema.field("val").type == pa.string()

    def test_missing_column_backfilled_with_nulls_on_fast_path(
            self, tmp_path):
        """Tests a column absent from the second snapshot is filled with nulls."""
        # Arrange
        node = TableNode("T", str(tmp_path), "T")
        _write_row_group({"a": [1, 2], "b": [10, 20]}, node, "zstd")
        # Act
        _write_row_group({"a": [3, 4]}, node, "zstd")
        node.parquet_writer.close()
        # Assert
        table = pq.read_table(str(tmp_path / "T.parquet"))
        assert table.num_rows == 4
        b_vals = table["b"].to_pylist()
        assert b_vals[0] == 10 and b_vals[1] == 20
        assert b_vals[2] is None and b_vals[3] is None


class TestFlushWorker:
    """Tests for the _flush_worker background-thread function."""

    def test_stops_immediately_on_sentinel_alone(self):
        """Tests _flush_worker exits cleanly when only SENTINEL is queued."""
        # Arrange
        q = queue.Queue()
        q.put(_SENTINEL)
        # Act & Assert
        _flush_worker(q, "zstd")

    def test_processes_single_item_then_stops(self, tmp_path):
        """Tests _flush_worker writes a row group before the SENTINEL."""
        # Arrange
        q = queue.Queue()
        node = TableNode("T", str(tmp_path), "T")
        q.put(({"a": [1, 2]}, node))
        q.put(_SENTINEL)
        # Act
        _flush_worker(q, "zstd")
        node.parquet_writer.close()
        # Assert
        assert (tmp_path / "T.parquet").exists()

    def test_processes_multiple_items_before_sentinel(self, tmp_path):
        """Tests _flush_worker processes every item in the queue."""
        # Arrange
        q = queue.Queue()
        node = TableNode("T", str(tmp_path), "T")
        for i in range(3):
            q.put(({"val": [i * 10]}, node))
        q.put(_SENTINEL)
        # Act
        _flush_worker(q, "zstd")
        node.parquet_writer.close()
        # Assert
        meta = pq.read_metadata(str(tmp_path / "T.parquet"))
        assert meta.num_row_groups == 3

    def test_queue_fully_drained_after_worker_stops(self, tmp_path):
        """Tests queue is empty after _flush_worker exits."""
        # Arrange
        q = queue.Queue()
        node = TableNode("T", str(tmp_path), "T")
        q.put(({"x": [1]}, node))
        q.put(_SENTINEL)
        # Act
        _flush_worker(q, "zstd")
        # Assert
        assert q.empty()


class TestFindMessageBoundary:
    """Tests for the _find_message_boundary function."""

    def test_returns_file_size_when_offset_equals_file_size(
            self, tmp_path):
        """Tests file_size is returned immediately when offset is at EOF."""
        # Arrange
        f = tmp_path / "test.gps"
        f.write_bytes(b"x" * 200)
        # Act
        result = _find_message_boundary(str(f), 200)
        # Assert
        assert result == 200

    def test_returns_file_size_when_offset_exceeds_file_size(
            self, tmp_path):
        """Tests file_size is returned when offset is beyond EOF."""
        # Arrange
        f = tmp_path / "test.gps"
        f.write_bytes(b"x" * 100)
        # Act
        result = _find_message_boundary(str(f), 500)
        # Assert
        assert result == 100

    def test_returns_approx_offset_when_no_valid_message(self, tmp_path):
        """Tests approx_offset is returned as fallback when no NovAtel frame found."""
        # Arrange
        f = tmp_path / "noise.gps"
        f.write_bytes(b"\x00" * 1000)
        # Act
        result = _find_message_boundary(str(f), 0)
        # Assert
        assert result == 0

    def test_mid_file_offset_with_noise_data_returns_approx_offset(
            self, tmp_path):
        """Tests mid-file offset fallback with non-NovAtel data."""
        # Arrange
        f = tmp_path / "noise.gps"
        f.write_bytes(b"\xFF" * 500)
        # Act
        result = _find_message_boundary(str(f), 100)
        # Assert
        assert result == 100

    def test_valid_frame_returns_approx_offset_plus_skipped(self, tmp_path):
        """Tests a non-UNKNOWN frame causes early return at approx_offset + skipped."""
        # Arrange
        f = tmp_path / "test.gps"
        f.write_bytes(b"\x00" * 200)
        mock_meta = MagicMock()
        mock_meta.format = "BINARY_FORMAT"
        with patch("nov_gnsspq.writer.parallel.edie.ne") as mock_ne, \
                patch("nov_gnsspq.writer.parallel.edie.ne_oem") as mock_ne_oem:
            mock_ne.HEADER_FORMAT.UNKNOWN = "UNKNOWN_FORMAT_SENTINEL"
            mock_framer = MagicMock()
            mock_framer.__iter__ = MagicMock(
                return_value=iter([(b"\xAA\x44\x12", mock_meta)])
            )
            mock_ne_oem.Framer.return_value = mock_framer
            # Act
            result = _find_message_boundary(str(f), 50)
        # Assert
        assert result == 50
