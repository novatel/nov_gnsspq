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

ENU position std dev and 3D trace plots derived from INSSTDEV log data.
"""

from typing import TYPE_CHECKING

import logging

_log = logging.getLogger(__name__)


from nov_gnsspq.plot.deps import require_matplotlib, require_plotly

if TYPE_CHECKING:
    import matplotlib.figure
    import plotly.graph_objects


def _prepare_position_accuracy(db) -> dict | None:
    """Extract INSSTDEV ENU accuracy data and compute 3D trace.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        data: Dict with keys ``time_s``, ``north``, ``east``, ``up``,
            ``trace_3d``, or ``None`` if ``INSSTDEV`` is absent.
    """
    import numpy as np

    try:
        df = db.subtables.INSSTDEV.cur_table
    except AttributeError:
        _log.error("No INSSTDEV log found in db.")
        return None

    north = df["latitude_std_dev"].values
    east = df["longitude_std_dev"].values
    up = df["height_std_dev"].values

    return {
        "time_s": df["header_milliseconds"] / 1000.0,
        "north": north,
        "east": east,
        "up": up,
        "trace_3d": np.sqrt(north**2 + east**2 + up**2),
    }


def position_accuracy(db, *, plot: bool = True) -> "matplotlib.figure.Figure | None":
    """Plot estimated position accuracy (East, North, Up std dev + 3D trace).

    Reads from the ``INSSTDEV`` log.  The latitude/longitude/height std
    dev columns are treated as North/East/Up in metres (NovAtel
    convention).  A 3D RMS trace (sqrt(N² + E² + U²)) is overlaid.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        fig: Figure with a single axes showing North, East, Up std dev
            and the 3D trace over GPS time, or ``None`` if ``INSSTDEV``
            is absent.

    Raises:
        ImportError: If ``matplotlib`` is not installed
            (``pip install nov_gnsspq[plot]``).
    """
    require_matplotlib()
    import matplotlib.pyplot as plt

    data = _prepare_position_accuracy(db)
    if data is None:
        return None

    t = data["time_s"]

    fig, ax = plt.subplots(figsize=(12, 4))
    fig.suptitle("Estimated Position Accuracy", fontsize=13)

    ax.plot(t, data["north"], linewidth=0.8, color="#4CAF50", label="North")
    ax.plot(t, data["east"], linewidth=0.8, color="#2196F3", label="East")
    ax.plot(t, data["up"], linewidth=0.8, color="#FF9800", label="Up")
    ax.plot(
        t, data["trace_3d"],
        linewidth=1.1, color="#E91E63", linestyle="--",
        label="3D (trace)", zorder=3,
    )

    ax.set_xlabel("GPS Time (s)")
    ax.set_ylabel("Std Dev (m)")
    ax.set_ylim(bottom=0)
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(axis="y", linewidth=0.4, alpha=0.5)

    fig.tight_layout()
    if not plot:
        return fig
    plt.show()
    plt.close(fig)


def position_accuracy_interactive(
        db) -> "plotly.graph_objects.Figure | None":
    """Build an interactive position accuracy figure using Plotly.

    Single panel showing North, East, Up std dev and the 3D RMS trace
    (sqrt(N² + E² + U²)) over GPS time.  The step-change between float
    and fixed RTK ambiguity solutions is clearly visible.

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

    data = _prepare_position_accuracy(db)
    if data is None:
        return None

    t = data["time_s"]

    _traces = [
        ("North",     data["north"],    "#4CAF50", "solid"),
        ("East",      data["east"],     "#2196F3", "solid"),
        ("Up",        data["up"],       "#FF9800", "solid"),
        ("3D (trace)", data["trace_3d"], "#E91E63", "dash"),
    ]

    fig = go.Figure()
    for name, values, color, dash in _traces:
        width = 1.2 if name == "3D (trace)" else 0.9
        fig.add_trace(go.Scatter(
            x=t, y=values,
            mode="lines", name=name,
            line={"color": color, "width": width, "dash": dash},
            hovertemplate=(
                f"Time: %{{x:.2f}} s<br>"
                f"{name}: %{{y:.4f}} m<extra></extra>"
            ),
        ))

    fig.update_layout(
        title={"text": "Estimated Position Accuracy", "font_size": 13},
        xaxis_title="GPS Time (s)",
        yaxis={"title": "Std Dev (m)", "rangemode": "tozero"},
        height=450,
        hovermode="x unified",
    )

    return fig
