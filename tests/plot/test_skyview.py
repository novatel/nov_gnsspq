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

Unit tests for nov_gnsspq.plot.skyview.
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
plotly = pytest.importorskip("plotly")

from nov_gnsspq.plot.skyview import (  # noqa: E402
    _prepare_skyview,
    skyview,
    skyview_interactive,
)

# pylint: disable=protected-access


def _make_db_with_satvis2():
    """Returns a mock PqReader with a SATVIS2 subtable."""
    n = 5
    top_df = pd.DataFrame({
        "sequence_id": list(range(n)),
        "header_milliseconds": [100_000 + i * 1000 for i in range(n)],
    })
    sat_df = pd.DataFrame({
        "parent_id": list(range(n)),
        "system_type": ["0"] * n,
        "prn": [1] * n,
        "elevation": [45.0] * n,
        "azimuth": [90.0] * n,
        "header_milliseconds": [100_000 + i * 1000 for i in range(n)],
    })
    mock_sat_table = MagicMock()
    mock_sat_table.cur_table = sat_df
    mock_satvis2 = MagicMock()
    mock_satvis2.cur_table = top_df
    mock_satvis2.subtables.sat_vis_list.cur_table = sat_df

    db = MagicMock()
    db.subtables.SATVIS2 = mock_satvis2
    return db


def _make_db_no_satvis2():
    """Returns a mock PqReader with SATVIS2 attribute access raising AttributeError."""
    db = MagicMock()
    # Accessing .SATVIS2 raises AttributeError (absent log)
    del db.subtables.SATVIS2
    return db


class TestPrepareSkyview:
    """Tests for _prepare_skyview."""

    def test_returns_none_when_satvis2_absent(self):
        """Tests that _prepare_skyview returns None when SATVIS2 is absent."""
        # Arrange
        db = MagicMock(spec=[])
        db.subtables = MagicMock(spec=[])
        # Act
        result = _prepare_skyview(db)
        # Assert
        assert result is None


class TestSkyviewNoneGuard:
    """Tests that skyview() and skyview_interactive() handle missing SATVIS2."""

    def test_skyview_returns_none_when_no_satvis2(self):
        """Tests that skyview() returns None gracefully when SATVIS2 is absent."""
        # Arrange
        db = MagicMock()
        with patch(
            "nov_gnsspq.plot.skyview._prepare_skyview", return_value=None
        ):
            # Act
            result = skyview(db, plot=False)
        # Assert
        assert result is None

    def test_skyview_interactive_returns_none_when_no_satvis2(self):
        """Tests that skyview_interactive() returns None when SATVIS2 is absent."""
        # Arrange
        db = MagicMock()
        with patch(
            "nov_gnsspq.plot.skyview._prepare_skyview", return_value=None
        ):
            # Act
            result = skyview_interactive(db)
        # Assert
        assert result is None


class TestSkyviewPlotFalse:
    """Tests for skyview() with plot=False."""

    def test_returns_figure_when_plot_false(self):
        """Tests that plot=False returns a matplotlib Figure when data is available."""
        # Arrange
        import matplotlib.figure
        n = 5
        merged_df = pd.DataFrame({
            "system_type": ["0"] * n,
            "prn": [1] * n,
            "elevation": [45.0] * n,
            "azimuth": [90.0] * n,
            "header_milliseconds": [100_000 + i * 1000 for i in range(n)],
        })
        fake_data = {"merged": merged_df}
        db = MagicMock()
        with patch(
            "nov_gnsspq.plot.skyview._prepare_skyview", return_value=fake_data
        ):
            # Act
            fig = skyview(db, plot=False)
        # Assert
        assert isinstance(fig, matplotlib.figure.Figure)
        import matplotlib.pyplot as plt
        plt.close("all")

    def test_returns_none_when_plot_true(self):
        """Tests that plot=True calls plt.show/close and returns None."""
        # Arrange
        n = 5
        merged_df = pd.DataFrame({
            "system_type": ["0"] * n,
            "prn": [1] * n,
            "elevation": [45.0] * n,
            "azimuth": [90.0] * n,
            "header_milliseconds": [100_000 + i * 1000 for i in range(n)],
        })
        fake_data = {"merged": merged_df}
        db = MagicMock()
        with patch(
            "nov_gnsspq.plot.skyview._prepare_skyview", return_value=fake_data
        ):
            with patch("matplotlib.pyplot.show") as mock_show:
                with patch("matplotlib.pyplot.close"):
                    result = skyview(db)
        # Assert
        assert result is None
        mock_show.assert_called_once()
