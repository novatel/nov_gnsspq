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

Unit tests for plot=False save-mode parameter across all modified plot modules.

Each plot function gained a ``plot: bool = True`` keyword argument:
  - ``plot=False`` returns the figure for caller-controlled saving.
  - ``plot=True`` (default) calls ``plt.show()``/``plt.close()`` and returns
    ``None``.

These tests verify that contract for attitude_accuracy, imu, position_accuracy,
signal, tracking, and satellite_stats.
"""

import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

if "novatel_edie" not in sys.modules:
    _ne = MagicMock()
    _ne.SatelliteId = MagicMock()
    sys.modules["novatel_edie"] = _ne

mpl = pytest.importorskip("matplotlib")
import matplotlib
matplotlib.use("Agg")  # headless backend — must be set before pyplot import
import matplotlib.figure  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _close_all():
    """Close all open matplotlib figures."""
    import matplotlib.pyplot as plt
    plt.close("all")


def _make_insstdev_db():
    """Mock PqReader with minimal INSSTDEV data."""
    n = 4
    df = pd.DataFrame({
        "header_milliseconds": [i * 1000 for i in range(n)],
        "latitude_std_dev":  [0.01] * n,
        "longitude_std_dev": [0.02] * n,
        "height_std_dev":    [0.03] * n,
    })
    mock_table = MagicMock()
    mock_table.cur_table = df
    db = MagicMock()
    db.subtables.INSSTDEV = mock_table
    return db


def _make_range_db():
    """Mock PqReader with minimal RANGE data for signal/tracking tests.

    Uses multiple epochs and multiple observations per PRN so that std()
    calls produce valid (non-NaN) values.
    """
    # 2 epochs × 3 PRNs = 6 observations
    obs_df = pd.DataFrame({
        "parent_id": [0, 0, 0, 1, 1, 1],
        "sv_prn":    [1, 2, 3, 1, 2, 3],
        "signal_type": [0] * 6,
        "system_type": [0] * 6,
        "C_No":      [40.0, 38.0, 42.0, 41.0, 37.0, 43.0],
        "sd_psr":    [0.1] * 6,
        "sd_adr":    [0.01] * 6,
        "c_status": [0] * 6,
    })
    top_df = pd.DataFrame({
        "sequence_id": [0, 1],
        "header_milliseconds": [0.0, 1000.0],
    })
    mock_range = MagicMock()
    mock_range.cur_table = top_df
    mock_range.subtables.obs.cur_table = obs_df
    db = MagicMock()
    db.subtables.RANGE = mock_range
    return db


# ---------------------------------------------------------------------------
# attitude_accuracy
# ---------------------------------------------------------------------------


class TestAttitudeAccuracyPlotFalse:
    """Tests for attitude_accuracy() plot=False contract."""

    def _make_db(self):
        """Mock PqReader for attitude_accuracy."""
        n = 4
        df = pd.DataFrame({
            "header_milliseconds": [i * 1000 for i in range(n)],
            "roll_std_dev":     [0.1] * n,
            "pitch_std_dev":    [0.2] * n,
            "azimuth_std_dev":  [0.3] * n,
        })
        mock_table = MagicMock()
        mock_table.cur_table = df
        db = MagicMock()
        db.subtables.INSSTDEV = mock_table
        return db

    def test_returns_figure_when_plot_false(self):
        """Tests that plot=False returns a matplotlib Figure."""
        # Arrange
        from nov_gnsspq.plot.attitude_accuracy import attitude_accuracy
        db = self._make_db()
        # Act
        fig = attitude_accuracy(db, plot=False)
        _close_all()
        # Assert
        assert isinstance(fig, matplotlib.figure.Figure)

    def test_returns_none_when_plot_true(self):
        """Tests that plot=True calls plt.show and returns None."""
        # Arrange
        from nov_gnsspq.plot.attitude_accuracy import attitude_accuracy
        db = self._make_db()
        # Act
        with patch("matplotlib.pyplot.show") as mock_show:
            with patch("matplotlib.pyplot.close"):
                result = attitude_accuracy(db)
        # Assert
        assert result is None
        mock_show.assert_called_once()


# ---------------------------------------------------------------------------
# imu
# ---------------------------------------------------------------------------


class TestImuPlotFalse:
    """Tests for imu() plot=False contract."""

    def _make_db(self):
        """Mock PqReader for imu with RAWIMUSX subtable."""
        n = 4
        df = pd.DataFrame({
            "header_milliseconds": [i * 1000 for i in range(n)],
            "z_accel_output": [0.0] * n,
            "y_accel_output": [0.0] * n,
            "x_accel_output": [0.0] * n,
            "z_gyro_output": [0.0] * n,
            "y_gyro_output": [0.0] * n,
            "x_gyro_output": [0.0] * n,
        })
        mock_table = MagicMock()
        mock_table.cur_table = df
        db = MagicMock()
        db.subtables.RAWIMUSX = mock_table
        return db

    def test_returns_figure_when_plot_false(self):
        """Tests that plot=False returns a matplotlib Figure."""
        # Arrange
        from nov_gnsspq.plot.imu import imu
        db = self._make_db()
        # Act
        fig = imu(db, plot=False)
        _close_all()
        # Assert
        assert isinstance(fig, matplotlib.figure.Figure)

    def test_returns_none_when_plot_true(self):
        """Tests that plot=True calls plt.show and returns None."""
        # Arrange
        from nov_gnsspq.plot.imu import imu
        db = self._make_db()
        # Act
        with patch("matplotlib.pyplot.show") as mock_show:
            with patch("matplotlib.pyplot.close"):
                result = imu(db)
        # Assert
        assert result is None
        mock_show.assert_called_once()


# ---------------------------------------------------------------------------
# position_accuracy
# ---------------------------------------------------------------------------


class TestPositionAccuracyPlotFalse:
    """Tests for position_accuracy() plot=False contract."""

    def test_returns_figure_when_plot_false(self):
        """Tests that plot=False returns a matplotlib Figure."""
        # Arrange
        from nov_gnsspq.plot.position_accuracy import position_accuracy
        db = _make_insstdev_db()
        # Act
        fig = position_accuracy(db, plot=False)
        _close_all()
        # Assert
        assert isinstance(fig, matplotlib.figure.Figure)

    def test_returns_none_when_plot_true(self):
        """Tests that plot=True calls plt.show and returns None."""
        # Arrange
        from nov_gnsspq.plot.position_accuracy import position_accuracy
        db = _make_insstdev_db()
        # Act
        with patch("matplotlib.pyplot.show") as mock_show:
            with patch("matplotlib.pyplot.close"):
                result = position_accuracy(db)
        # Assert
        assert result is None
        mock_show.assert_called_once()


# ---------------------------------------------------------------------------
# signal
# ---------------------------------------------------------------------------


class TestSignalPlotFalse:
    """Tests for signal() plot=False contract."""

    def test_returns_figure_when_plot_false(self):
        """Tests that plot=False returns a matplotlib Figure."""
        # Arrange
        from nov_gnsspq.plot.signal import signal
        db = _make_range_db()
        # Act
        fig = signal(db, plot=False)
        _close_all()
        # Assert
        assert isinstance(fig, matplotlib.figure.Figure)

    def test_returns_none_when_plot_true(self):
        """Tests that plot=True calls plt.show and returns None."""
        # Arrange
        from nov_gnsspq.plot.signal import signal
        db = _make_range_db()
        # Act
        with patch("matplotlib.pyplot.show") as mock_show:
            with patch("matplotlib.pyplot.close"):
                result = signal(db)
        # Assert
        assert result is None
        mock_show.assert_called_once()


# ---------------------------------------------------------------------------
# tracking
# ---------------------------------------------------------------------------


class TestTrackingPlotFalse:
    """Tests for tracking() plot=False contract — both early-return and normal paths."""

    def _make_tracking_db(self):
        """Mock PqReader for tracking with RANGE data."""
        n = 4
        obs_df = pd.DataFrame({
            "parent_id": list(range(n)),
            "system_type": [0, 1, 0, 2],
            "sv_prn": [1, 2, 3, 4],
            "channel_status_raw": [0] * n,
        })
        top_df = pd.DataFrame({
            "sequence_id": list(range(n)),
            "header_milliseconds": [i * 1000 for i in range(n)],
        })
        mock_obs = MagicMock()
        mock_obs.cur_table = obs_df
        mock_range = MagicMock()
        mock_range.cur_table = top_df
        mock_range.subtables.obs.cur_table = obs_df
        db = MagicMock()
        db.subtables.RANGE = mock_range
        return db

    def test_returns_figure_when_plot_false(self):
        """Tests that plot=False returns a matplotlib Figure (normal path)."""
        # Arrange
        from nov_gnsspq.plot.tracking import tracking
        db = self._make_tracking_db()
        # Act
        fig = tracking(db, plot=False)
        _close_all()
        # Assert
        assert isinstance(fig, matplotlib.figure.Figure)

    def test_returns_none_when_plot_true(self):
        """Tests that plot=True calls plt.show and returns None."""
        # Arrange
        from nov_gnsspq.plot.tracking import tracking
        db = self._make_tracking_db()
        # Act
        with patch("matplotlib.pyplot.show") as mock_show:
            with patch("matplotlib.pyplot.close"):
                result = tracking(db)
        # Assert
        assert result is None
        mock_show.assert_called_once()


# ---------------------------------------------------------------------------
# satellite_stats
# ---------------------------------------------------------------------------


class TestSatelliteStatsPlotFalse:
    """Tests for satellite_stats() plot=False contract."""

    def _make_db(self):
        """Mock PqReader with RANGE data for satellite_stats.

        Uses multiple epochs per PRN so groupby aggregates produce valid values.
        """
        # 2 epochs × 2 PRNs = 4 observations
        obs_df = pd.DataFrame({
            "parent_id":   [0, 0, 1, 1],
            "sv_prn":      [1, 2, 1, 2],
            "system_type": [0] * 4,
            "signal_type": [0] * 4,
            "C_No":        [40.0, 38.0, 41.0, 39.0],
            "sd_psr":      [0.1] * 4,
            "sd_adr":      [0.01] * 4,
            "c_status": [0] * 4,
        })
        top_df = pd.DataFrame({
            "sequence_id": [0, 1],
            "header_milliseconds": [0.0, 1000.0],
        })
        mock_range = MagicMock()
        mock_range.cur_table = top_df
        mock_range.subtables.obs.cur_table = obs_df
        db = MagicMock()
        db.subtables.RANGE = mock_range
        # No SATVIS2 subtable
        db.subtables.SATVIS2 = None
        return db

    def test_returns_figure_when_plot_false(self):
        """Tests that plot=False returns a matplotlib Figure."""
        # Arrange
        from nov_gnsspq.plot.satellite_stats import satellite_stats
        db = self._make_db()
        # Act
        fig = satellite_stats(db, plot=False)
        _close_all()
        # Assert
        assert isinstance(fig, matplotlib.figure.Figure)

    def test_returns_none_when_plot_true(self):
        """Tests that plot=True calls plt.show and returns None."""
        # Arrange
        from nov_gnsspq.plot.satellite_stats import satellite_stats
        db = self._make_db()
        # Act
        with patch("matplotlib.pyplot.show") as mock_show:
            with patch("matplotlib.pyplot.close"):
                result = satellite_stats(db)
        # Assert
        assert result is None
        mock_show.assert_called_once()
