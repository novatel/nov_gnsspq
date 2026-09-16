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

Unit tests for nov_gnsspq.plot.accuracy.
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

from nov_gnsspq.plot.accuracy import accuracy, accuracy_interactive  # noqa: E402

# pylint: disable=protected-access


def _make_db(*, with_diff_age: bool = False, with_solution_age: bool = False):
    """Returns a minimal mock PqReader for accuracy() tests.

    Args:
        with_diff_age: Include a diff_age column in BESTPOS.
        with_solution_age: Include a solution_age column in BESTPOS.

    Returns:
        db: MagicMock mimicking a PqReader with a BESTPOS subtable.
    """
    n = 5
    df = pd.DataFrame({
        "header_milliseconds": [100_000 + i * 1000 for i in range(n)],
        "latitude_std_dev": [0.01 + i * 0.001 for i in range(n)],
        "longitude_std_dev": [0.02 + i * 0.001 for i in range(n)],
        "height_std_dev": [0.05 + i * 0.001 for i in range(n)],
        "num_svs": [8] * n,
        "num_soln_svs": [6] * n,
    })
    if with_diff_age:
        df["diff_age"] = [0.5 + i * 0.1 for i in range(n)]
    if with_solution_age:
        df["solution_age"] = [1.0 + i * 0.1 for i in range(n)]
    mock_table = MagicMock()
    mock_table.cur_table = df
    db = MagicMock()
    db.subtables.BESTPOS = mock_table
    return db


class TestAccuracyPlotFalse:
    """Tests for accuracy() with plot=False."""

    def test_returns_figure_when_plot_false(self):
        """Tests that plot=False returns a matplotlib Figure."""
        # Arrange
        import matplotlib.figure
        db = _make_db()
        # Act
        fig = accuracy(db, plot=False)
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
                result = accuracy(db)
        # Assert
        assert result is None
        mock_show.assert_called_once()

    def test_diff_age_line_added_when_column_present(self):
        """Tests that a diff_age line appears when the column exists."""
        # Arrange
        db = _make_db(with_diff_age=True)
        # Act
        fig = accuracy(db, plot=False)
        # Collect labels from the second axes (Solution Statistics)
        ax_stats = fig.axes[1]
        labels = [line.get_label() for line in ax_stats.get_lines()]
        import matplotlib.pyplot as plt
        plt.close("all")
        # Assert
        assert any("Differential" in lbl for lbl in labels), (
            f"Expected 'Differential Lag' line, found labels: {labels}"
        )

    def test_solution_age_line_added_when_column_present(self):
        """Tests that a solution_age line appears when the column exists."""
        # Arrange
        db = _make_db(with_solution_age=True)
        # Act
        fig = accuracy(db, plot=False)
        ax_stats = fig.axes[1]
        labels = [line.get_label() for line in ax_stats.get_lines()]
        import matplotlib.pyplot as plt
        plt.close("all")
        # Assert
        assert any("Solution Age" in lbl for lbl in labels), (
            f"Expected 'Solution Age' line, found labels: {labels}"
        )

    def test_no_optional_columns_produces_two_panel_figure(self):
        """Tests that without optional columns the figure has exactly 2 axes."""
        # Arrange
        db = _make_db()
        # Act
        fig = accuracy(db, plot=False)
        import matplotlib.pyplot as plt
        plt.close("all")
        # Assert
        assert len(fig.axes) == 2


class TestAccuracyInteractiveOptionalTraces:
    """Tests for accuracy_interactive optional trace rendering."""

    def test_diff_age_trace_added_when_column_present(self):
        """Tests that Differential Lag trace appears in the interactive figure."""
        # Arrange
        db = _make_db(with_diff_age=True)
        # Act
        fig = accuracy_interactive(db)
        trace_names = [t.name for t in fig.data]
        # Assert
        assert "Differential Lag" in trace_names, (
            f"Expected 'Differential Lag' trace, found: {trace_names}"
        )

    def test_solution_age_trace_added_when_column_present(self):
        """Tests that Solution Age trace appears in the interactive figure."""
        # Arrange
        db = _make_db(with_solution_age=True)
        # Act
        fig = accuracy_interactive(db)
        trace_names = [t.name for t in fig.data]
        # Assert
        assert "Solution Age" in trace_names, (
            f"Expected 'Solution Age' trace, found: {trace_names}"
        )

    def test_no_optional_traces_when_columns_absent(self):
        """Tests that optional traces are absent when columns are not present."""
        # Arrange
        db = _make_db()
        # Act
        fig = accuracy_interactive(db)
        trace_names = [t.name for t in fig.data]
        # Assert
        assert "Differential Lag" not in trace_names
        assert "Solution Age" not in trace_names
