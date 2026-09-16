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

Attitude accuracy timeseries plots derived from INSSTDEV log data.
"""

from typing import TYPE_CHECKING

import logging

from nov_gnsspq.plot.deps import require_matplotlib, require_plotly

if TYPE_CHECKING:
    import matplotlib.figure
    import plotly.graph_objects


_log = logging.getLogger(__name__)


def _prepare_attitude_accuracy(db) -> dict | None:
    """Extract INSSTDEV attitude accuracy data.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        data: Dict with keys ``df`` and ``time_s``, or ``None`` if
            ``INSSTDEV`` is absent.
    """
    try:
        df = db.subtables.INSSTDEV.cur_table
    except AttributeError:
        _log.error("No INSSTDEV log found in db.")
        return None
    return {
        "df": df,
        "time_s": df["header_milliseconds"] / 1000.0,
    }


def attitude_accuracy(db, *, plot: bool = True) -> "matplotlib.figure.Figure | None":
    """Plot estimated attitude accuracy (roll, pitch, heading std dev).

    Reads the ``roll_std_dev``, ``pitch_std_dev``, and
    ``azimuth_std_dev`` columns from the ``INSSTDEV`` log.  These are
    the standard deviations computed by the GNSS/INS Kalman filter and
    are expressed in degrees.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        fig: Figure with two subplots — roll & pitch std dev (top) and
            heading std dev (bottom), or ``None`` if ``INSSTDEV`` is
            absent.

    Raises:
        ImportError: If ``matplotlib`` is not installed
            (``pip install nov_gnsspq[plot]``).
    """
    require_matplotlib()
    import matplotlib.pyplot as plt

    data = _prepare_attitude_accuracy(db)
    if data is None:
        return None

    df = data["df"]
    t = data["time_s"]

    fig, (ax_rp, ax_hdg) = plt.subplots(
        2, 1, figsize=(12, 6), sharex=True
    )
    fig.suptitle("Estimated Attitude Accuracy", fontsize=13)

    ax_rp.plot(
        t, df["roll_std_dev"],
        linewidth=0.8, color="#4CAF50", label="Roll",
    )
    ax_rp.plot(
        t, df["pitch_std_dev"],
        linewidth=0.8, color="#2196F3", label="Pitch",
    )
    ax_rp.set_ylabel("Std Dev (°)")
    ax_rp.set_ylim(bottom=0)
    ax_rp.legend(fontsize=8, loc="upper right")
    ax_rp.set_title("Roll & Pitch")
    ax_rp.grid(axis="y", linewidth=0.4, alpha=0.5)

    ax_hdg.plot(
        t, df["azimuth_std_dev"],
        linewidth=0.8, color="#FF9800", label="Heading",
    )
    ax_hdg.set_ylabel("Std Dev (°)")
    ax_hdg.set_ylim(bottom=0)
    ax_hdg.legend(fontsize=8, loc="upper right")
    ax_hdg.set_title("Heading (Azimuth)")
    ax_hdg.set_xlabel("GPS Time (s)")
    ax_hdg.grid(axis="y", linewidth=0.4, alpha=0.5)

    fig.tight_layout()
    if not plot:
        return fig
    plt.show()
    plt.close(fig)


def attitude_accuracy_interactive(db) -> "plotly.graph_objects.Figure | None":
    """Build an interactive attitude accuracy figure using Plotly.

    Two vertically stacked panels sharing a GPS time x-axis:

    1. Roll and pitch std dev.
    2. Heading (azimuth) std dev.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        fig: A Plotly Figure, or ``None`` if ``INSSTDEV`` is absent.

    Raises:
        ImportError: If ``plotly`` is not installed
            (``pip install nov_gnsspq[plot]``).
    """
    require_plotly()
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    data = _prepare_attitude_accuracy(db)
    if data is None:
        return None

    df = data["df"]
    t = data["time_s"]

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=("Roll & Pitch", "Heading (Azimuth)"),
        vertical_spacing=0.10,
    )

    fig.add_trace(go.Scatter(
        x=t, y=df["roll_std_dev"],
        mode="lines", name="Roll",
        line={"color": "#4CAF50", "width": 0.9},
        hovertemplate=(
            "Time: %{x:.2f} s<br>"
            "Roll σ: %{y:.4f}°<extra></extra>"
        ),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=t, y=df["pitch_std_dev"],
        mode="lines", name="Pitch",
        line={"color": "#2196F3", "width": 0.9},
        hovertemplate=(
            "Time: %{x:.2f} s<br>"
            "Pitch σ: %{y:.4f}°<extra></extra>"
        ),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=t, y=df["azimuth_std_dev"],
        mode="lines", name="Heading",
        line={"color": "#FF9800", "width": 0.9},
        showlegend=False,
        hovertemplate=(
            "Time: %{x:.2f} s<br>"
            "Heading σ: %{y:.4f}°<extra></extra>"
        ),
    ), row=2, col=1)

    fig.update_yaxes(
        title_text="Std Dev (°)", rangemode="tozero", row=1, col=1
    )
    fig.update_yaxes(
        title_text="Std Dev (°)", rangemode="tozero", row=2, col=1
    )
    fig.update_xaxes(title_text="GPS Time (s)", row=2, col=1)

    fig.update_layout(
        title={"text": "Estimated Attitude Accuracy", "font_size": 13},
        height=500,
        hovermode="x unified",
    )

    return fig
