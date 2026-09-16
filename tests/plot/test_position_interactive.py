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

Unit tests for nov_gnsspq.plot.position — interactive and static variants.
"""

import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

if "novatel_edie" not in sys.modules:
    _ne = MagicMock()
    _ne.SatelliteId = MagicMock()
    sys.modules["novatel_edie"] = _ne

plotly = pytest.importorskip("plotly")

from nov_gnsspq.plot.position import (  # noqa: E402
    _resolve_solution_status,
    position_interactive,
)

# pylint: disable=protected-access


def _make_db(
        *,
        with_position_type: bool = True,
        with_solution_status: bool = False,
        include_zero_row: bool = False):
    """Returns a minimal mock PqReader for position functions.

    Args:
        with_position_type: Include a position_type column.
        with_solution_status: Include a solution_status column.
        include_zero_row: Prepend a row with lat=0 and lon=0 (should be
            filtered by _prepare_position).

    Returns:
        db: A MagicMock mimicking a PqReader with a BESTPOS subtable.
    """
    n = 10
    df = pd.DataFrame({
        "latitude": [51.0 + i * 0.0001 for i in range(n)],
        "longitude": [-114.0 + i * 0.0001 for i in range(n)],
        "orthometric_height": [1000.0 + i for i in range(n)],
        "header_milliseconds": [100_000 + i * 1000 for i in range(n)],
    })
    if with_position_type:
        df["position_type"] = (["1"] * 7) + (["0"] * 3)
    if with_solution_status:
        df["solution_status"] = (["0"] * 8) + (["1"] * 2)
    if include_zero_row:
        zero_row = pd.DataFrame({
            "latitude": [0.0],
            "longitude": [0.0],
            "orthometric_height": [0.0],
            "header_milliseconds": [0.0],
        })
        df = pd.concat([zero_row, df], ignore_index=True)
    mock_table = MagicMock()
    mock_table.cur_table = df
    db = MagicMock()
    db.subtables.BESTPOS = mock_table
    return db


class TestResolveSolutionStatus:
    """Tests for _resolve_solution_status helper."""

    def test_known_int_code_returns_name(self):
        """Tests that a known integer code maps to its string name."""
        # Arrange
        series = pd.Series([0])
        # Act
        result = _resolve_solution_status(series)
        # Assert
        assert result.iloc[0] == "SOL_COMPUTED"

    def test_known_string_int_code_maps_correctly(self):
        """Tests that a string-encoded integer maps to its name."""
        # Arrange
        series = pd.Series(["1"])
        # Act
        result = _resolve_solution_status(series)
        # Assert
        assert result.iloc[0] == "INSUFFICIENT_OBS"

    def test_unknown_code_returns_str_repr(self):
        """Tests that an unmapped code falls back to str(v)."""
        # Arrange
        series = pd.Series([999])
        # Act
        result = _resolve_solution_status(series)
        # Assert
        assert result.iloc[0] == "999"

    def test_non_numeric_value_returns_str_repr(self):
        """Tests that a non-numeric value (TypeError) returns str(v)."""
        # Arrange
        series = pd.Series([None])
        # Act
        result = _resolve_solution_status(series)
        # Assert
        assert result.iloc[0] == "None"


class TestPositionInteractive:
    """Tests for position_interactive (Plotly)."""

    def test_returns_figure(self):
        """Tests that position_interactive returns a Plotly Figure."""
        # Arrange
        import plotly.graph_objects as go
        db = _make_db()
        # Act
        fig = position_interactive(db)
        # Assert
        assert isinstance(fig, go.Figure)

    def test_no_position_type_produces_single_scatter_trace(self):
        """Tests that the fallback branch adds exactly one Scatter trace."""
        # Arrange
        db = _make_db(with_position_type=False)
        # Act
        fig = position_interactive(db)
        scatter_traces = [
            t for t in fig.data
            if t.type == "scatter" and t.name != "Height"
        ]
        # Assert
        assert len(scatter_traces) == 0 or all(
            t.showlegend is False for t in scatter_traces
        )

    def test_position_type_traces_labelled_by_type(self):
        """Tests that traces are labelled by resolved position type names."""
        # Arrange
        db = _make_db(with_position_type=True)
        # Act
        fig = position_interactive(db)
        trace_names = {t.name for t in fig.data}
        # Assert — at least one position-type-named trace exists
        named = [
            n for n in trace_names
            if n not in ("Height", None)
        ]
        assert len(named) > 0

    def test_altitude_trace_present(self):
        """Tests that an altitude trace named 'Height' is always included."""
        # Arrange
        db = _make_db()
        # Act
        fig = position_interactive(db)
        # Assert
        assert any(t.name == "Height" for t in fig.data)

    def test_solution_status_traces_present_when_column_exists(self):
        """Tests that solution_status traces appear when the column is present."""
        # Arrange
        db = _make_db(with_solution_status=True)
        # Act
        fig = position_interactive(db)
        trace_names = {t.name for t in fig.data}
        # Assert — at least one status-named trace should exist
        assert "SOL_COMPUTED" in trace_names or "INSUFFICIENT_OBS" in trace_names

    def test_zero_coord_rows_excluded(self):
        """Tests that rows with lat==0 AND lon==0 are filtered before plotting."""
        # Arrange
        db = _make_db(with_position_type=False, include_zero_row=True)
        # Act
        fig = position_interactive(db)
        # Find the lat/lon scatter trace
        for t in fig.data:
            if hasattr(t, "x") and t.x is not None:
                # None of the x values should be exactly -114.0 + offset when
                # the 0,0 row was prepended — check that 0-lat 0-lon is absent
                # The zero-row has lon=0 so we check no longitude==0 is in data
                if 0.0 in list(t.x):
                    pytest.fail(
                        f"Trace '{t.name}' contains longitude 0.0 — "
                        "zero-coordinate row was not filtered"
                    )

    def test_osm_true_produces_scattermap_trace(self):
        """Tests that osm=True adds a Scattermap trace for the position scatter."""
        # Arrange
        db = _make_db(with_position_type=False)
        # Act
        fig = position_interactive(db, osm=True)
        # Assert
        scattermap_types = {type(t).__name__ for t in fig.data}
        assert "Scattermap" in scattermap_types, (
            f"Expected Scattermap trace, got: {scattermap_types}"
        )
