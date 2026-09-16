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

IMU accelerometer and gyroscope timeseries plots from RAWIMU* log data.
"""

from typing import TYPE_CHECKING

import logging

_log = logging.getLogger(__name__)

_IMU_VARIANTS = ["RAWIMUSX", "RAWIMUX", "RAWIMUS", "RAWIMU"]
_AXIS_COLORS = {"x": "#F44336", "y": "#4CAF50", "z": "#2196F3"}


from nov_gnsspq.plot.deps import require_matplotlib, require_plotly

if TYPE_CHECKING:
    import matplotlib.figure
    import plotly.graph_objects


def _prepare_imu(db) -> dict | None:
    """Locate the first available RAWIMU* log and extract IMU data.

    Tries RAWIMUSX ->' RAWIMUX ->' RAWIMUS ->' RAWIMU in order.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        data: Dict with keys ``df``, ``t``, ``xlabel``, ``log_name``,
            or ``None`` if no RAWIMU* log is found.
    """
    df = None
    log_name = None
    for variant in _IMU_VARIANTS:
        try:
            df = getattr(db.subtables, variant).cur_table
            log_name = variant
            break
        except AttributeError:
            continue

    if df is None:
        _log.error(
            "No RAWIMU* log found in db. "
            "Tried: %s", ", ".join(_IMU_VARIANTS)
        )
        return None

    time_col = (
        "gps_seconds"
        if "gps_seconds" in df.columns
        else "header_milliseconds"
    )
    t = (
        df[time_col]
        if time_col == "gps_seconds"
        else df[time_col] / 1000.0
    )
    xlabel = (
        "GPS Seconds"
        if time_col == "gps_seconds"
        else "GPS Time (s)"
    )
    return {"df": df, "t": t, "xlabel": xlabel, "log_name": log_name}


def imu(db, *, plot: bool = True) -> "matplotlib.figure.Figure | None":
    """Plot IMU accelerometer and gyroscope data from a RAWIMU* log.

    Tries RAWIMUSX ->' RAWIMUX ->' RAWIMUS ->' RAWIMU in order and uses the
    first one present in *db*.  Uses ``gps_seconds`` as the time axis
    (the IMU-internal timestamp) rather than the header milliseconds.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        fig: Figure with two subplots -- accelerometer (top) and
            gyroscope (bottom), or ``None`` if no RAWIMU* log is found.

    Raises:
        ImportError: If ``matplotlib`` is not installed
            (``pip install nov_gnsspq[plot]``).
    """
    require_matplotlib()
    import matplotlib.pyplot as plt

    data = _prepare_imu(db)
    if data is None:
        return None

    df = data["df"]
    t = data["t"]
    xlabel = data["xlabel"]
    log_name = data["log_name"]

    fig, (ax_accel, ax_gyro) = plt.subplots(
        2, 1, figsize=(12, 7), sharex=True
    )
    fig.suptitle(f"IMU Data -- {log_name}", fontsize=14)

    for axis, color in _AXIS_COLORS.items():
        col = f"accel_{axis}"
        if col in df.columns:
            ax_accel.plot(
                t, df[col], linewidth=0.6,
                color=color, label=axis.upper(),
            )

    ax_accel.set_ylabel("Acceleration (m/s²)")
    ax_accel.set_title("Accelerometer")
    ax_accel.legend(loc="upper right", fontsize=8)

    for axis, color in _AXIS_COLORS.items():
        col = f"gyro_{axis}"
        if col in df.columns:
            ax_gyro.plot(
                t, df[col], linewidth=0.6,
                color=color, label=axis.upper(),
            )

    ax_gyro.set_ylabel("Angular Rate (rad/s)")
    ax_gyro.set_title("Gyroscope")
    ax_gyro.legend(loc="upper right", fontsize=8)
    ax_gyro.set_xlabel(xlabel)

    fig.tight_layout()
    if not plot:
        return fig
    plt.show()
    plt.close(fig)


def imu_interactive(db) -> "plotly.graph_objects.Figure | None":
    """Build an interactive IMU figure using Plotly.

    Two vertically stacked panels sharing a time x-axis:

    1. Accelerometer -- X, Y, Z axes in m/s².
    2. Gyroscope -- X, Y, Z axes in rad/s.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        fig: A Plotly Figure, or ``None`` if no RAWIMU* log is found.

    Raises:
        ImportError: If ``plotly`` is not installed
            (``pip install nov_gnsspq[plot]``).
    """
    require_plotly()
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    data = _prepare_imu(db)
    if data is None:
        return None

    df = data["df"]
    t = data["t"]
    xlabel = data["xlabel"]
    log_name = data["log_name"]

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=("Accelerometer", "Gyroscope"),
        vertical_spacing=0.10,
    )

    for axis, color in _AXIS_COLORS.items():
        accel_col = f"accel_{axis}"
        gyro_col = f"gyro_{axis}"

        if accel_col in df.columns:
            fig.add_trace(go.Scatter(
                x=t, y=df[accel_col],
                mode="lines",
                name=axis.upper(),
                line={"color": color, "width": 0.7},
                legendgroup=axis,
                hovertemplate=(
                    f"Time: %{{x:.2f}} s<br>"
                    f"Accel {axis.upper()}: %{{y:.6f}} m/s²"
                    "<extra></extra>"
                ),
            ), row=1, col=1)

        if gyro_col in df.columns:
            fig.add_trace(go.Scatter(
                x=t, y=df[gyro_col],
                mode="lines",
                name=axis.upper(),
                line={"color": color, "width": 0.7},
                legendgroup=axis,
                showlegend=False,
                hovertemplate=(
                    f"Time: %{{x:.2f}} s<br>"
                    f"Gyro {axis.upper()}: %{{y:.6f}} rad/s"
                    "<extra></extra>"
                ),
            ), row=2, col=1)

    fig.update_yaxes(title_text="Acceleration (m/s²)", row=1, col=1)
    fig.update_yaxes(title_text="Angular Rate (rad/s)", row=2, col=1)
    fig.update_xaxes(title_text=xlabel, row=2, col=1)

    fig.update_layout(
        title={"text": f"IMU Data -- {log_name}", "font_size": 14},
        height=600,
        hovermode="x unified",
    )

    return fig
