#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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

Position accuracy timeseries plots derived from BESTPOS log data.
"""

from typing import TYPE_CHECKING

from nov_gnsspq.plot.deps import require_matplotlib, require_plotly

if TYPE_CHECKING:
    import matplotlib.figure
    import plotly.graph_objects


def _prepare_accuracy(db) -> dict:
    """Extract and summarise BESTPOS accuracy data.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        data: Dict with keys ``df``, ``time_s``, ``mean_lat``,
            ``mean_lon``, ``mean_hgt``.
    """
    df = db.subtables.BESTPOS.cur_table
    time_s = df["header_milliseconds"] / 1000.0
    return {
        "df": df,
        "time_s": time_s,
        "mean_lat": df["latitude_std_dev"].mean(),
        "mean_lon": df["longitude_std_dev"].mean(),
        "mean_hgt": df["height_std_dev"].mean(),
    }


def accuracy(db, *, plot: bool = True) -> "matplotlib.figure.Figure | None":
    """Plot position accuracy estimates and satellite counts from BESTPOS.

    Produces a two-panel figure sharing the GPS time axis:

    1. Position std dev -- ``latitude_std_dev``, ``longitude_std_dev``, and
       ``height_std_dev`` over time.
    2. Satellites -- total tracked (``num_svs``) and used in solution
       (``num_soln_svs``) over time.

    The figure suptitle shows mean std dev values for quick reference.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        fig: Three-panel matplotlib Figure with accuracy timeseries.

    Raises:
        KeyError: If ``BESTPOS`` is not present in *db*.
        ImportError: If ``matplotlib`` is not installed
            (``pip install nov_gnsspq[plot]``).
    """
    require_matplotlib()
    import matplotlib.pyplot as plt

    data = _prepare_accuracy(db)
    df = data["df"]
    time_s = data["time_s"]
    mean_lat = data["mean_lat"]
    mean_lon = data["mean_lon"]
    mean_hgt = data["mean_hgt"]

    fig, (ax_std, ax_svs) = plt.subplots(
        2, 1, figsize=(10, 7), sharex=True
    )

    fig.suptitle(
        f"Position Accuracy Estimates -- "
        f"Lat sigma: {mean_lat:.2f} m, "
        f"Lon sigma: {mean_lon:.2f} m, "
        f"Hgt sigma: {mean_hgt:.2f} m",
        fontsize=13,
    )

    ax_std.plot(
        time_s, df["latitude_std_dev"],
        linewidth=0.8, color="#F44336", label="Latitude",
    )
    ax_std.plot(
        time_s, df["longitude_std_dev"],
        linewidth=0.8, color="#2196F3", label="Longitude",
    )
    ax_std.plot(
        time_s, df["height_std_dev"],
        linewidth=0.8, color="#4CAF50", label="Height",
    )
    ax_std.set_ylabel("Std Dev (m)")
    ax_std.set_title("Position Std Dev")
    ax_std.set_ylim(bottom=0)
    ax_std.legend(fontsize=8)

    ax_svs.plot(
        time_s, df["num_svs"],
        linewidth=0.8, color="#2196F3", label="Satellites Tracked",
        drawstyle="steps-post",
    )
    ax_svs.plot(
        time_s, df["num_soln_svs"],
        linewidth=0.8, color="#FF9800", label="Satellites Used In Solution",
        drawstyle="steps-post",
    )
    if "diff_age" in df.columns:
        ax_svs.plot(
            time_s, df["diff_age"],
            linewidth=0.8, color="#f44336", label="Differential Lag",
        )
    if "solution_age" in df.columns:
        ax_svs.plot(
            time_s, df["solution_age"],
            linewidth=0.8, color="#4CAF50", label="Solution Age",
        )
    ax_svs.set_ylabel("Count / Age (s)")
    ax_svs.set_title("Solution Statistics")
    ax_svs.set_xlabel("GPS Time (s)")
    ax_svs.legend(fontsize=8)

    fig.tight_layout()
    if not plot:
        return fig
    plt.show()
    plt.close(fig)


def accuracy_interactive(db) -> "plotly.graph_objects.Figure":
    """Build an interactive position accuracy figure using Plotly.

    Two vertically stacked panels sharing a GPS time x-axis:

    1. Position std dev -- latitude, longitude, and height sigma.
    2. Satellite counts -- total tracked and used in solution.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        fig: A Plotly Figure with three subplots.

    Raises:
        KeyError: If ``BESTPOS`` is not present in *db*.
        ImportError: If ``plotly`` is not installed
            (``pip install nov_gnsspq[plot]``).
    """
    require_plotly()
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    data = _prepare_accuracy(db)
    df = data["df"]
    time_s = data["time_s"]
    mean_lat = data["mean_lat"]
    mean_lon = data["mean_lon"]
    mean_hgt = data["mean_hgt"]

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=(
            "Position Std Dev",
            "Solution Statistics",
        ),
        vertical_spacing=0.12,
    )

    fig.add_trace(go.Scatter(
        x=time_s, y=df["latitude_std_dev"],
        mode="lines", name="Latitude",
        line={"color": "#F44336", "width": 0.9},
        hovertemplate=(
            "Time: %{x:.2f} s<br>"
            "Lat sigma: %{y:.4f} m<extra></extra>"
        ),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=time_s, y=df["longitude_std_dev"],
        mode="lines", name="Longitude",
        line={"color": "#2196F3", "width": 0.9},
        hovertemplate=(
            "Time: %{x:.2f} s<br>"
            "Lon sigma: %{y:.4f} m<extra></extra>"
        ),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=time_s, y=df["height_std_dev"],
        mode="lines", name="Height",
        line={"color": "#4CAF50", "width": 0.9},
        hovertemplate=(
            "Time: %{x:.2f} s<br>"
            "Hgt sigma: %{y:.4f} m<extra></extra>"
        ),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=time_s, y=df["num_svs"],
        mode="lines", name="Satellites Tracked",
        line={"color": "#2196F3", "width": 0.9, "shape": "hv"},
        hovertemplate=(
            "Time: %{x:.2f} s<br>"
            "Tracked: %{y}<extra></extra>"
        ),
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=time_s, y=df["num_soln_svs"],
        mode="lines", name="Satellites Used In Solution",
        line={"color": "#FF9800", "width": 0.9, "shape": "hv"},
        hovertemplate=(
            "Time: %{x:.2f} s<br>"
            "Used: %{y}<extra></extra>"
        ),
    ), row=2, col=1)

    if "diff_age" in df.columns:
        fig.add_trace(go.Scatter(
            x=time_s, y=df["diff_age"],
            mode="lines", name="Differential Lag",
            line={"color": "#f44336", "width": 0.9},
            hovertemplate=(
                "Time: %{x:.2f} s<br>"
                "Diff Lag: %{y:.2f} s<extra></extra>"
            ),
        ), row=2, col=1)

    if "solution_age" in df.columns:
        fig.add_trace(go.Scatter(
            x=time_s, y=df["solution_age"],
            mode="lines", name="Solution Age",
            line={"color": "#4CAF50", "width": 0.9},
            hovertemplate=(
                "Time: %{x:.2f} s<br>"
                "Sol Age: %{y:.2f} s<extra></extra>"
            ),
        ), row=2, col=1)

    fig.update_yaxes(
        title_text="Std Dev (m)", rangemode="tozero", row=1, col=1
    )
    fig.update_yaxes(
        title_text="Count / Age (s)", rangemode="tozero", row=2, col=1
    )
    fig.update_xaxes(title_text="GPS Time (s)", row=2, col=1)

    fig.update_layout(
        title={
            "text": (
                f"Position Accuracy -- "
                f"Lat sigma: {mean_lat:.2f} m, "
                f"Lon sigma: {mean_lon:.2f} m, "
                f"Hgt sigma: {mean_hgt:.2f} m"
            ),
            "font_size": 13,
        },
        height=500,
        hovermode="x unified",
    )

    return fig
