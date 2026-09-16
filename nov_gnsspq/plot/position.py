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

Position fix scatter plot in Web Mercator projection with altitude timeseries.
"""

from typing import TYPE_CHECKING

import logging
import pandas as pd

_log = logging.getLogger(__name__)

_POSITION_TYPE = {
    0:  "None",
    1:  "Fixed Pos",
    2:  "Fixed Height",
    8:  "Doppler Velocity",
    16: "Single",
    17: "PSR Diff",
    18: "WAAS",
    19: "Propagated",
    20: "OmniSTAR",
    32: "L1 Float",
    33: "Iono-Free Float",
    34: "Narrow Float",
    48: "L1 Int",
    49: "Wide Int",
    50: "Narrow Int",
    51: "RTK Direct INS",
    52: "INS SBAS",
    53: "INS PSR SP",
    54: "INS PSR Diff",
    55: "INS RTK Float",
    56: "INS RTK Fixed",
    57: "INS OmniSTAR",
    60: "OmniSTAR HP",
    61: "OmniSTAR XP",
    64: "PPP Converging",
    65: "PPP",
    69: "INS PPP Converging",
    70: "INS PPP",
    77: "PPP Basic Converging",
    78: "PPP Basic",
}

_PALETTE = ['#01adff', '#005198']

_TYPE_PALETTE = [
    "#f44336", "#4CAF50", "#2196F3", "#FF9800", "#9C27B0",
    "#00BCD4", "#E91E63", "#795548", "#607D8B", "#CDDC39",
    "#FF5722", "#3F51B5",
]

_SOLUTION_STATUS = {
    0:  "SOL_COMPUTED",
    1:  "INSUFFICIENT_OBS",
    2:  "NO_CONVERGENCE",
    3:  "SINGULARITY",
    4:  "COV_TRACE",
    5:  "TEST_DIST",
    6:  "COLD_START",
    7:  "V_H_LIMIT",
    8:  "VARIANCE",
    9:  "RESIDUALS",
    13: "INTEGRITY_WARNING",
    18: "PENDING",
    20: "INVALID_FIX",
    21: "UNAUTHORIZED",
    22: "ANTENNA_WARNING",
}

_STATUS_PALETTE = {
    "SOL_COMPUTED":      "#4CAF50",
    "INSUFFICIENT_OBS":  "#f44336",
    "NO_CONVERGENCE":    "#FF9800",
    "COLD_START":        "#9C27B0",
    "PENDING":           "#2196F3",
}
_STATUS_COLOR_DEFAULT = "#9e9e9e"


def _resolve_position_type(series: pd.Series) -> pd.Series:
    """Map raw integer position_type codes to human-readable names.

    Args:
        series: A Series of integer (or string-integer) position type
            codes.

    Returns:
        A Series of position type name strings.
    """
    def _lookup(v: object) -> str:
        """Look up a single position type value.

        Args:
            v: Raw position type value.

        Returns:
            The human-readable name for the position type.
        """
        try:
            return _POSITION_TYPE.get(int(v), str(v))
        except (ValueError, TypeError):
            return str(v)
    return series.map(_lookup)


def _resolve_solution_status(series: pd.Series) -> pd.Series:
    """Map raw integer solution_status codes to human-readable names.

    Args:
        series: A Series of integer (or string-integer) solution status
            codes.

    Returns:
        A Series of solution status name strings.
    """
    def _lookup(v: object) -> str:
        """Look up a single solution status value.

        Args:
            v: Raw solution status value.

        Returns:
            The human-readable name for the solution status.
        """
        try:
            return _SOLUTION_STATUS.get(int(v), str(v))
        except (ValueError, TypeError):
            return str(v)
    return series.map(_lookup)


from nov_gnsspq.plot.deps import require_matplotlib, require_plotly

if TYPE_CHECKING:
    import matplotlib.figure
    import plotly.graph_objects


def _prepare_position(db) -> dict:
    """Extract and decode BESTPOS position data.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        data: Dict with keys ``df`` (position_type decoded) and
            ``time_s``.
    """
    df = db.subtables.BESTPOS.cur_table.copy()
    df = df[(df["latitude"] != 0.0) | (df["longitude"] != 0.0)]
    time_s = df["header_milliseconds"] / 1000.0
    if "position_type" in df.columns:
        df["position_type"] = _resolve_position_type(df["position_type"])
    if "solution_status" in df.columns:
        df["solution_status"] = _resolve_solution_status(df["solution_status"])
    return {"df": df, "time_s": time_s}


def position(db, *, plot: bool = True, osm: bool = False) -> "matplotlib.figure.Figure | None":
    """Plot position fix scatter in Web Mercator and altitude timeseries.

    Points are projected to EPSG:3857 (Web Mercator) and coloured by
    position type.  No basemap is added by default.  To overlay your own
    tile source, call ``contextily.add_basemap`` on the returned axes:

    .. code-block:: python

        import contextily as ctx
        fig = position(db)
        ctx.add_basemap(
            fig.axes[0],
            crs="EPSG:3857",
            source="https://your-internal-tile-server/{z}/{x}/{y}.png",
        )

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        fig: Figure with two panels — position scatter in Web Mercator
            (left) and orthometric height over GPS time (right).

    Raises:
        KeyError: If ``BESTPOS`` is not present in *db*.
        ImportError: If ``matplotlib`` is not installed
            (``pip install nov_gnsspq[plot]``).
    """
    require_matplotlib()
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    import matplotlib.ticker as mticker
    import numpy as np

    data = _prepare_position(db)
    df = data["df"]
    time_s = data["time_s"]

    lon = df["longitude"].values
    lat = df["latitude"].values
    mx = lon * 20037508.34 / 180.0
    my = (
        np.log(np.tan((90.0 + lat) * np.pi / 360.0))
        / (np.pi / 180.0)
    ) * 20037508.34 / 180.0

    fig = plt.figure(figsize=(16, 14))
    fig.suptitle("Position Overview", fontsize=14)
    gs = gridspec.GridSpec(3, 2, figure=fig, height_ratios=[2, 1, 1],
                           hspace=0.45, wspace=0.25)
    ax_map = fig.add_subplot(gs[0, 0])
    ax_alt = fig.add_subplot(gs[0, 1])
    ax_pos_type = fig.add_subplot(gs[1, :])
    ax_pos_status = fig.add_subplot(gs[2, :])

    colors = _TYPE_PALETTE
    if "position_type" in df.columns:
        for i, ft in enumerate(df["position_type"].unique()):
            mask = (df["position_type"] == ft).values
            ax_map.scatter(
                mx[mask], my[mask], s=4,
                color=colors[i % len(colors)],
                label=ft, alpha=0.9, zorder=2,
            )
        ax_map.legend(markerscale=3, fontsize=8)
    else:
        ax_map.scatter(mx, my, s=4, alpha=0.9, zorder=2)

    def _x_to_lon(v, _):
        return f"{v * 180.0 / 20037508.34:.4f}°"

    def _y_to_lat(v, _):
        return (
            f"{(np.degrees(2 * np.arctan(np.exp(v * np.pi / 20037508.34)))- 90.0):.4f}°"
        )

    ax_map.xaxis.set_major_formatter(mticker.FuncFormatter(_x_to_lon))
    ax_map.yaxis.set_major_formatter(mticker.FuncFormatter(_y_to_lat))
    ax_map.set_xlabel("Longitude")
    ax_map.set_ylabel("Latitude")
    ax_map.set_title("Position Scatter")

    ax_alt.plot(
        time_s, df["orthometric_height"],
        linewidth=0.8, color="#01adff",
    )
    ax_alt.set_xlabel("GPS Time (s)")
    ax_alt.set_ylabel("Height (m)")
    ax_alt.set_title("Altitude over Time")

    if "position_type" in df.columns:
        for i, pt in enumerate(df["position_type"].unique()):
            mask = df["position_type"] == pt
            ax_pos_type.scatter(
                time_s[mask], [str(pt)] * int(mask.sum()),
                s=30, marker="s",
                color=_TYPE_PALETTE[i % len(_TYPE_PALETTE)],
                label=str(pt),
            )
        ax_pos_type.legend(markerscale=1.5, fontsize=7, ncol=4,
                           loc="upper right")
    ax_pos_type.set_xlabel("GPS Time (s)")
    ax_pos_type.set_title("Position Type")

    if "solution_status" in df.columns:
        for i, st in enumerate(df["solution_status"].unique()):
            mask = df["solution_status"] == st
            color = _STATUS_PALETTE.get(str(st), _STATUS_COLOR_DEFAULT)
            ax_pos_status.scatter(
                time_s[mask], [str(st)] * int(mask.sum()),
                s=30, marker="s",
                color=color,
                label=str(st),
            )
        ax_pos_status.legend(markerscale=1.5, fontsize=7, ncol=4,
                             loc="upper right")
    ax_pos_status.set_xlabel("GPS Time (s)")
    ax_pos_status.set_title("Position Status")

    # Finalize the figure layout before touching the map axes: tight_layout
    # changes the physical axes size, which changes the equal-aspect data-limit
    # expansion.  Calling it first means apply_aspect() and add_basemap see
    # the same final size, so the tile image covers the axes exactly.
    fig.tight_layout()

    ax_map.set_aspect("equal", adjustable="datalim")
    ax_map.apply_aspect()

    if osm:
        try:
            import contextily as ctx
            ctx.add_basemap(
                ax_map,
                crs="EPSG:3857",
                source=ctx.providers.OpenStreetMap.Mapnik,
                zoom="auto",
            )
            # contextily sets xlim/ylim to the tile boundaries after fetching.
            # Switch to box-adjustable so those limits stay fixed at render
            # time: datalim re-expands limits based on the interactive window
            # size, which would push the limits beyond the tile extent.
            ax_map.set_aspect("equal", adjustable="box")
        except ImportError:
            _log.warning(
                "--osm requires contextily: pip install contextily"
            )

    if not plot:
        return fig
    plt.show()
    plt.close(fig)


def position_interactive(db, *, osm: bool = False) -> "plotly.graph_objects.Figure":
    """Build an interactive position overview figure using Plotly.

    Two vertically stacked panels:

    1. **Position scatter** — geographic scatter coloured by position type.
       When *osm* is True, rendered as a :class:`go.Scattermap` tile map
       using OpenStreetMap; otherwise rendered as a plain lat/lon scatter.
    2. **Altitude timeseries** — orthometric height over GPS time.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.
        osm: When True, overlay OpenStreetMap tiles on the position scatter.
            Default False.

    Returns:
        fig: A Plotly Figure with geographic scatter and altitude panels.

    Raises:
        KeyError: If ``BESTPOS`` is not present in *db*.
        ImportError: If ``plotly`` is not installed
            (``pip install nov_gnsspq[plot]``).
    """
    require_plotly()
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    data = _prepare_position(db)
    df = data["df"]
    time_s = data["time_s"]

    if osm:
        fig = make_subplots(
            rows=4, cols=1,
            specs=[
                [{"type": "map"}],
                [{"type": "xy"}],
                [{"type": "xy"}],
                [{"type": "xy"}],
            ],
            subplot_titles=(
                "Position Scatter", "Altitude over Time",
                "Position Type", "Position Status",
            ),
            row_heights=[0.35, 0.18, 0.27, 0.20],
            vertical_spacing=0.05,
        )

        if "position_type" in df.columns:
            for i, pos_type in enumerate(df["position_type"].unique()):
                mask = df["position_type"] == pos_type
                color = _TYPE_PALETTE[i % len(_TYPE_PALETTE)]
                fig.add_trace(go.Scattermap(
                    lat=df.loc[mask, "latitude"],
                    lon=df.loc[mask, "longitude"],
                    mode="markers",
                    marker={"size": 4, "color": color},
                    name=str(pos_type),
                    legendgroup=f"ptype_{pos_type}",
                    hovertemplate=(
                        f"<b>{pos_type}</b><br>"
                        "Lat: %{lat:.6f}°<br>"
                        "Lon: %{lon:.6f}°"
                        "<extra></extra>"
                    ),
                ), row=1, col=1)
        else:
            fig.add_trace(go.Scattermap(
                lat=df["latitude"],
                lon=df["longitude"],
                mode="markers",
                marker={"size": 4, "color": _TYPE_PALETTE[0]},
                showlegend=False,
                hovertemplate=(
                    "Lat: %{lat:.6f}°<br>"
                    "Lon: %{lon:.6f}°"
                    "<extra></extra>"
                ),
            ), row=1, col=1)

        fig.update_layout(
            map={
                "style": "open-street-map",
                "center": {
                    "lat": float(df["latitude"].mean()),
                    "lon": float(df["longitude"].mean()),
                },
                "zoom": 12,
            },
        )

    else:
        fig = make_subplots(
            rows=4, cols=1,
            subplot_titles=(
                "Position Scatter", "Altitude over Time",
                "Position Type", "Position Status",
            ),
            row_heights=[0.30, 0.18, 0.27, 0.25],
            vertical_spacing=0.08,
        )

        if "position_type" in df.columns:
            for i, pos_type in enumerate(df["position_type"].unique()):
                mask = df["position_type"] == pos_type
                color = _TYPE_PALETTE[i % len(_TYPE_PALETTE)]
                fig.add_trace(go.Scatter(
                    x=df.loc[mask, "longitude"],
                    y=df.loc[mask, "latitude"],
                    mode="markers",
                    marker={"size": 3, "color": color},
                    name=str(pos_type),
                    legendgroup=f"ptype_{pos_type}",
                    hovertemplate=(
                        f"<b>{pos_type}</b><br>"
                        "Lon: %{x:.6f}°<br>"
                        "Lat: %{y:.6f}°"
                        "<extra></extra>"
                    ),
                ), row=1, col=1)
        else:
            fig.add_trace(go.Scatter(
                x=df["longitude"],
                y=df["latitude"],
                mode="markers",
                marker={"size": 3, "color": _TYPE_PALETTE[0]},
                showlegend=False,
                hovertemplate=(
                    "Lon: %{x:.6f}°<br>"
                    "Lat: %{y:.6f}°"
                    "<extra></extra>"
                ),
            ), row=1, col=1)

        fig.update_xaxes(title_text="Longitude (°)", row=1, col=1)
        fig.update_yaxes(
            title_text="Latitude (°)",
            scaleanchor="x",
            scaleratio=1,
            row=1, col=1,
        )

    fig.add_trace(go.Scatter(
        x=time_s, y=df["orthometric_height"],
        mode="lines", name="Height",
        line={"color": "#01adff", "width": 0.9},
        showlegend=False,
        hovertemplate=(
            "Time: %{x:.2f} s<br>"
            "Height: %{y:.3f} m<extra></extra>"
        ),
    ), row=2, col=1)

    fig.update_yaxes(title_text="Height (m)", row=2, col=1)

    if "position_type" in df.columns:
        for i, pos_type in enumerate(df["position_type"].unique()):
            mask = df["position_type"] == pos_type
            color = _TYPE_PALETTE[i % len(_TYPE_PALETTE)]
            fig.add_trace(go.Scatter(
                x=time_s[mask],
                y=[str(pos_type)] * int(mask.sum()),
                mode="markers",
                marker={"symbol": "square", "size": 12, "color": color},
                name=str(pos_type),
                legendgroup=f"ptype_{pos_type}",
                showlegend=False,
                hovertemplate=(
                    f"<b>{pos_type}</b><br>"
                    "Time: %{x:.2f} s<extra></extra>"
                ),
            ), row=3, col=1)

    if "solution_status" in df.columns:
        for i, st in enumerate(df["solution_status"].unique()):
            mask = df["solution_status"] == st
            color = _STATUS_PALETTE.get(str(st), _STATUS_COLOR_DEFAULT)
            fig.add_trace(go.Scatter(
                x=time_s[mask],
                y=[str(st)] * int(mask.sum()),
                mode="markers",
                marker={"symbol": "square", "size": 12, "color": color},
                name=str(st),
                hovertemplate=(
                    f"<b>{st}</b><br>"
                    "Time: %{x:.2f} s<extra></extra>"
                ),
            ), row=4, col=1)

    fig.update_xaxes(title_text="GPS Time (s)", row=4, col=1)

    fig.update_layout(
        title={"text": "Position Overview", "font_size": 14},
        height=1100,
        hovermode="closest",
    )

    return fig
