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

Unit tests for the static position() matplotlib function.
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

from nov_gnsspq.plot.position import position  # noqa: E402

# pylint: disable=protected-access


def _make_db(*, with_solution_status: bool = False):
    """Returns a minimal mock PqReader for position() tests.

    Args:
        with_solution_status: Include a solution_status column.

    Returns:
        db: MagicMock mimicking a PqReader with BESTPOS subtable.
    """
    n = 5
    df = pd.DataFrame({
        "latitude": [51.0 + i * 0.001 for i in range(n)],
        "longitude": [-114.0 + i * 0.001 for i in range(n)],
        "orthometric_height": [1000.0 + i for i in range(n)],
        "header_milliseconds": [100_000 + i * 1000 for i in range(n)],
        "position_type": ["1"] * n,
    })
    if with_solution_status:
        df["solution_status"] = ["0"] * n
    mock_table = MagicMock()
    mock_table.cur_table = df
    db = MagicMock()
    db.subtables.BESTPOS = mock_table
    return db


class TestPositionPlotFalse:
    """Tests for position() with plot=False (returns figure without showing)."""

    def test_returns_figure_when_plot_false(self):
        """Tests that plot=False returns a matplotlib Figure."""
        # Arrange
        import matplotlib.figure
        db = _make_db()
        # Act
        fig = position(db, plot=False)
        # Assert
        assert isinstance(fig, matplotlib.figure.Figure)
        import matplotlib.pyplot as plt
        plt.close("all")

    def test_returns_none_when_plot_true(self):
        """Tests that plot=True calls plt.show/close and returns None."""
        # Arrange
        db = _make_db()
        # Act
        with patch("matplotlib.pyplot.show") as mock_show:
            with patch("matplotlib.pyplot.close"):
                result = position(db)
        # Assert
        assert result is None
        mock_show.assert_called_once()

    def test_solution_status_subplot_populated_when_column_present(self):
        """Tests that solution_status subplot gets scatter artists when the
        solution_status column is present in BESTPOS."""
        # Arrange
        db = _make_db(with_solution_status=True)
        # Act
        fig = position(db, plot=False)
        # Assert — the figure has at least 4 axes (map, alt, pos_type, pos_status)
        assert len(fig.axes) >= 4
        import matplotlib.pyplot as plt
        plt.close("all")

    def test_zero_coord_row_excluded_from_figure(self):
        """Tests that a row with lat==0 AND lon==0 is excluded from the plot."""
        # Arrange
        import matplotlib.pyplot as plt
        n = 4
        df = pd.DataFrame({
            "latitude":  [0.0, 51.0, 51.001, 51.002],
            "longitude": [0.0, -114.0, -114.001, -114.002],
            "orthometric_height": [0.0, 1000.0, 1001.0, 1002.0],
            "header_milliseconds": [0.0, 100_000.0, 101_000.0, 102_000.0],
        })
        mock_table = MagicMock()
        mock_table.cur_table = df
        db = MagicMock()
        db.subtables.BESTPOS = mock_table
        # Act
        fig = position(db, plot=False)
        ax_map = fig.axes[0]
        # Collect all x-data from the map axes
        all_x = []
        for coll in ax_map.collections:
            offsets = coll.get_offsets()
            if len(offsets):
                all_x.extend(offsets[:, 0].tolist())
        plt.close("all")
        # Assert — no zero-longitude point (Web Mercator of lon=0 is 0.0)
        assert 0.0 not in all_x, (
            "Zero-coordinate row should be filtered before plotting"
        )

    def test_osm_logs_warning_when_contextily_absent(self):
        """Tests that osm=True logs a warning and returns a figure when contextily
        is not installed (the ImportError is caught, not re-raised)."""
        # Arrange
        import sys as _sys
        from unittest.mock import patch
        # Use sys.modules to get the module object — importing via
        # `import nov_gnsspq.plot.position` returns the function (not the
        # module) because __init__.py overwrites the package attribute.
        position_module = _sys.modules["nov_gnsspq.plot.position"]
        db = _make_db()
        # Remove contextily from sys.modules so the import inside position()
        # actually executes — then prevent re-import by injecting None as a
        # sentinel (which makes "import contextily" raise ImportError).
        saved = _sys.modules.pop("contextily", _sys.modules.get("contextily"))
        _sys.modules["contextily"] = None  # type: ignore[assignment]
        try:
            # Act — patch the logger object directly so the assertion is
            # independent of pytest's log capture (which can be disrupted by
            # setup_logging() calls in CLI tests earlier in the full suite).
            with patch.object(position_module._log, "warning") as mock_warn:
                fig = position(db, plot=False, osm=True)
        finally:
            # Restore original state
            if saved is None:
                _sys.modules.pop("contextily", None)
            else:
                _sys.modules["contextily"] = saved
        import matplotlib.pyplot as plt
        plt.close("all")
        # Assert — function returns a figure even when contextily is absent
        assert fig is not None
        assert mock_warn.called
        assert "contextily" in mock_warn.call_args[0][0].lower()
