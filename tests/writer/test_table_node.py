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

Unit tests for the TableNode data structure.
"""
import pytest

from nov_gnsspq.writer.parallel.edie import TableNode


# pylint: disable=protected-access


class TestTableNode:
    """Tests for the TableNode class."""

    @pytest.fixture()
    def example_node(self):
        """Provides a simple TableNode for testing."""
        return TableNode("BESTPOS", "/output/BESTPOS", "BESTPOS")

    def test_init_sets_safe_path(self, example_node):
        """Tests init stores the safe_path attribute."""
        # Assert
        assert example_node.safe_path == "BESTPOS"

    def test_init_sets_output_dir(self, example_node):
        """Tests init stores the output_dir attribute."""
        # Assert
        assert example_node.output_dir == "/output/BESTPOS"

    def test_init_sets_log_type(self, example_node):
        """Tests init stores the log_type attribute."""
        # Assert
        assert example_node.log_type == "BESTPOS"

    def test_init_cols_empty(self, example_node):
        """Tests cols starts as an empty dict."""
        # Assert
        assert example_node.cols == {}

    def test_init_subtables_empty(self, example_node):
        """Tests subtables starts as an empty dict."""
        # Assert
        assert example_node.subtables == {}

    def test_init_last_seq_id_none(self, example_node):
        """Tests last_seq_id starts as None."""
        # Assert
        assert example_node.last_seq_id is None

    def test_init_last_parent_id_none(self, example_node):
        """Tests last_parent_id starts as None."""
        # Assert
        assert example_node.last_parent_id is None

    def test_init_row_count_zero(self, example_node):
        """Tests row_count starts at zero."""
        # Assert
        assert example_node.row_count == 0

    def test_init_parquet_writer_none(self, example_node):
        """Tests parquet_writer starts as None."""
        # Assert
        assert example_node.parquet_writer is None

    def test_init_schema_cached_none(self, example_node):
        """Tests schema_cached starts as None."""
        # Assert
        assert example_node.schema_cached is None

    def test_slots_prevents_arbitrary_attributes(self, example_node):
        """Tests __slots__ prevents setting undefined attributes."""
        # Act & Assert
        with pytest.raises(AttributeError):
            example_node.undefined_field = "value"

    def test_all_declared_slots_settable(self, example_node):
        """Tests every declared slot can be written."""
        # Act & Assert
        example_node.cols = {"a": [1]}
        example_node.subtables = {}
        example_node.last_seq_id = 5
        example_node.last_parent_id = 3
        example_node.safe_path = "new_path"
        example_node.output_dir = "/new/dir"
        example_node.log_type = "RANGE"
        example_node.row_count = 10
        example_node.parquet_writer = None
        example_node.schema_cached = None

    def test_cols_can_hold_column_lists(self, example_node):
        """Tests cols dict stores column data correctly."""
        # Act
        example_node.cols["sequence_id"] = [0, 1, 2]
        example_node.cols["lat"] = [51.0, 52.0, 53.0]
        # Assert
        assert example_node.cols["sequence_id"] == [0, 1, 2]
        assert example_node.cols["lat"] == [51.0, 52.0, 53.0]

    def test_subtables_can_hold_child_nodes(self, example_node):
        """Tests subtables can hold nested TableNode instances."""
        # Arrange
        child = TableNode("obs", "/output/BESTPOS/obs", "obs")
        # Act
        example_node.subtables["obs"] = child
        # Assert
        assert example_node.subtables["obs"] is child

    def test_row_count_can_be_incremented(self, example_node):
        """Tests row_count can be updated."""
        # Act
        example_node.row_count += 5
        # Assert
        assert example_node.row_count == 5

    def test_last_seq_id_tracks_last_written_id(self, example_node):
        """Tests last_seq_id can be set and read."""
        # Act
        example_node.last_seq_id = 42
        # Assert
        assert example_node.last_seq_id == 42

    def test_last_parent_id_tracks_parent(self, example_node):
        """Tests last_parent_id can be set and read."""
        # Act
        example_node.last_parent_id = 7
        # Assert
        assert example_node.last_parent_id == 7

    def test_multiple_nodes_independent(self):
        """Tests two nodes do not share state."""
        # Arrange
        node_a = TableNode("A", "/a", "A")
        node_b = TableNode("B", "/b", "B")
        # Act
        node_a.cols["x"] = [1]
        # Assert
        assert "x" not in node_b.cols
