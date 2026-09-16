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

Unit tests for nov_gnsspq CLI plot command argument parsing.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

if "novatel_edie" not in sys.modules:
    _ne = MagicMock()
    _ne.SatelliteId = MagicMock()
    sys.modules["novatel_edie"] = _ne

from nov_gnsspq.cli.plot import main, run_plot  # noqa: E402

# pylint: disable=protected-access


class TestPlotCliOsmFlag:
    """Tests for the --osm flag wiring in main() and run_plot()."""

    def test_osm_flag_passes_osm_true_to_run_plot(self, tmp_path):
        """Tests that --osm sets osm=True in the run_plot call."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        # Act & Assert
        with patch("nov_gnsspq.cli.plot.run_plot", return_value={}) as mock_rp:
            main([str(db), "--plot", "position", "--osm"])
            _, kwargs = mock_rp.call_args
            assert kwargs.get("osm") is True

    def test_osm_flag_absent_passes_osm_false(self, tmp_path):
        """Tests that omitting --osm leaves osm=False in the run_plot call."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        # Act & Assert
        with patch("nov_gnsspq.cli.plot.run_plot", return_value={}) as mock_rp:
            main([str(db), "--plot", "position"])
            _, kwargs = mock_rp.call_args
            assert kwargs.get("osm", False) is False


class TestRunPlotOsmRouting:
    """Tests for osm kwarg routing to position plot functions inside run_plot."""

    def _make_db(self, tmp_path):
        """Creates a minimal mock database directory."""
        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq

        db = tmp_path / "db"
        db.mkdir()
        pq.write_table(
            pa.table({"log": pa.array([], type=pa.string()),
                      "sequence_id": pa.array([], type=pa.int64())}),
            db / "db.parquet",
        )
        return db

    def test_osm_true_passed_to_position_static_fn(self, tmp_path, tmp_path_factory):
        """Tests that osm=True is forwarded as kwarg to the position plot fn."""
        # Arrange
        db_path = self._make_db(tmp_path)
        out_dir = tmp_path_factory.mktemp("out")
        mock_fig = MagicMock()
        with patch("nov_gnsspq.cli.plot._load_plot_fn") as mock_loader:
            mock_fn = MagicMock(return_value=mock_fig)
            mock_loader.return_value = mock_fn
            # Act
            run_plot(db_path, plots=["position"], out_dir=out_dir, osm=True)
        # Assert — position fn called with osm=True
        _, kwargs = mock_fn.call_args
        assert kwargs.get("osm") is True

    def test_osm_kwarg_absent_for_non_position_plots(self, tmp_path,
                                                      tmp_path_factory):
        """Tests that osm kwarg is NOT forwarded for non-position plot names."""
        # Arrange
        db_path = self._make_db(tmp_path)
        out_dir = tmp_path_factory.mktemp("out2")
        mock_fig = MagicMock()
        with patch("nov_gnsspq.cli.plot._load_plot_fn") as mock_loader:
            mock_fn = MagicMock(return_value=mock_fig)
            mock_loader.return_value = mock_fn
            # Act
            run_plot(db_path, plots=["signal"], out_dir=out_dir, osm=True)
        # Assert — called without osm kwarg
        _, kwargs = mock_fn.call_args
        assert "osm" not in kwargs
