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

Polar sky view plots of satellite tracks from SATVIS2 log data.
"""

from typing import TYPE_CHECKING

import logging

log = logging.getLogger(__name__)

_SYS_INFO = {
    "0": ("GPS",     "G", "#4CAF50"),
    "1": ("GLONASS", "R", "#F44336"),
    "2": ("SBAS",    "S", "#9E9E9E"),
    "5": ("BeiDou",  "C", "#2196F3"),
    "6": ("QZSS",    "J", "#FF9800"),
    "7": ("Galileo", "E", "#9C27B0"),
}


from nov_gnsspq.plot.deps import require_matplotlib, require_plotly

if TYPE_CHECKING:
    import matplotlib.figure
    import plotly.graph_objects


def _prepare_skyview(db) -> dict:
    """Extract and merge SATVIS2 satellite track data.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        data: Dict with key ``merged`` -- the joined DataFrame containing
            ``system_type``, ``prn``, ``elevation``, ``azimuth``, and
            ``header_milliseconds``, or ``None`` if SATVIS2 is not present.
    """
    try:
        sv2top = db.subtables.SATVIS2.cur_table
    except AttributeError:
        return None
    sat_vis = (
        db.subtables.SATVIS2
        .subtables.sat_vis_list.cur_table
    )
    sat_id = (
        db.subtables.SATVIS2
        .subtables.sat_vis_list
        .subtables.id.cur_table
    )

    merged = sat_id.merge(
        sat_vis[["parent_id", "elevation", "azimuth"]],
        left_on="parent_id",
        right_index=True,
        suffixes=("_id", "_vis"),
    )
    merged = merged.merge(
        sv2top[["system_type", "header_milliseconds"]],
        left_on="parent_id_vis",
        right_index=True,
    )
    return {"merged": merged}


def skyview(db, *, plot: bool = True) -> "matplotlib.figure.Figure | None":
    """Plot a polar sky view of satellite tracks from a SATVIS2 table.

    Each unique satellite (constellation + PRN) is drawn as an arc on a
    polar plot.  The centre is zenith (elevation 90°) and the outer edge
    is the horizon (elevation 0°).  Azimuth 0° is North, increasing
    clockwise.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance that
            contains a ``SATVIS2`` table with the standard NovAtel
            subtable hierarchy.

    Returns:
        fig: Polar figure with one arc per tracked satellite.

    Raises:
        KeyError: If ``SATVIS2`` is not present in *db*.
        ImportError: If ``matplotlib`` is not installed
            (``pip install nov_gnsspq[plot]``).
    """
    require_matplotlib()
    import matplotlib.pyplot as plt
    import numpy as np

    data = _prepare_skyview(db)
    if data is None:
        log.warning("skyview: SATVIS2 log not found in database, skipping")
        return None
    merged = data["merged"]

    fig, ax = plt.subplots(
        subplot_kw={"projection": "polar"}, figsize=(10, 10)
    )

    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_ylim(0, 90)
    ax.set_yticks([0, 30, 60, 90])
    ax.set_yticklabels(["90°", "60°", "30°", "0°"], fontsize=7)

    legend_handles = {}
    total_sats = 0

    for sys_type in sorted(merged["system_type"].unique()):
        sys_type_str = str(sys_type)
        const_name, prefix, color = _SYS_INFO.get(
            sys_type_str,
            (f"SYS{sys_type_str}", sys_type_str, "#607D8B"),
        )

        subset = merged[merged["system_type"] == sys_type]
        for prn in sorted(subset["prn"].unique()):
            sat_data = (
                subset[subset["prn"] == prn]
                .sort_values("header_milliseconds")
            )

            azimuths = sat_data["azimuth"].values.astype(float)
            elevations = sat_data["elevation"].values.astype(float)
            theta = np.deg2rad(azimuths)
            r = 90.0 - elevations

            line, = ax.plot(
                theta, r, color=color, linewidth=1.0, alpha=0.8
            )

            peak_idx = int(np.argmin(r))
            r_lbl = min(r[peak_idx] + 4.0, 83.0)
            ax.text(
                theta[peak_idx], r_lbl,
                f"{prefix}{int(prn):02d}",
                fontsize=5.5, color=color,
                ha="center", va="center", clip_on=True,
            )

            total_sats += 1
            if const_name not in legend_handles:
                legend_handles[const_name] = line

    if legend_handles:
        ax.legend(
            handles=list(legend_handles.values()),
            labels=list(legend_handles.keys()),
            loc="upper right",
            bbox_to_anchor=(1.3, 1.1),
            fontsize=8,
            framealpha=0.8,
        )

    ax.set_title(
        f"Sky View -- {total_sats} satellites tracked", pad=15
    )
    fig.tight_layout()
    if not plot:
        return fig
    plt.show()
    plt.close(fig)


def skyview_interactive(db) -> "plotly.graph_objects.Figure":
    """Build an interactive polar sky view figure using Plotly.

    Each satellite is drawn as an arc on a polar plot using
    ``go.Scatterpolar``.  North is at top, azimuth increases clockwise.
    The outer edge represents the horizon (0° elevation); the centre is
    zenith (90°).  Hovering over a track shows the PRN, constellation,
    and current elevation and azimuth.  Constellations can be toggled
    via the legend.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        fig: A Plotly Figure with a polar subplot.

    Raises:
        KeyError: If ``SATVIS2`` is not present in *db*.
        ImportError: If ``plotly`` is not installed
            (``pip install nov_gnsspq[plot]``).
    """
    require_plotly()
    import plotly.graph_objects as go

    data = _prepare_skyview(db)
    if data is None:
        log.warning("skyview: SATVIS2 log not found in database, skipping")
        return None
    merged = data["merged"]

    fig = go.Figure()

    seen_consts: set[str] = set()
    total_sats = 0

    for sys_type in sorted(merged["system_type"].unique()):
        sys_type_str = str(sys_type)
        const_name, prefix, color = _SYS_INFO.get(
            sys_type_str,
            (f"SYS{sys_type_str}", sys_type_str, "#607D8B"),
        )

        subset = merged[merged["system_type"] == sys_type]
        for prn in sorted(subset["prn"].unique()):
            sat_data = (
                subset[subset["prn"] == prn]
                .sort_values("header_milliseconds")
            )

            azimuths = sat_data["azimuth"].values.astype(float)
            elevations = sat_data["elevation"].values.astype(float)
            r = 90.0 - elevations

            label = f"{prefix}{int(prn):02d}"
            first_of_const = const_name not in seen_consts
            seen_consts.add(const_name)
            total_sats += 1

            fig.add_trace(go.Scatterpolar(
                r=r,
                theta=azimuths,
                mode="lines",
                name=label,
                line={"color": color, "width": 1.0},
                legendgroup=const_name,
                legendgrouptitle_text=(
                    const_name if first_of_const else None
                ),
                showlegend=first_of_const,
                hovertemplate=(
                    f"<b>{label} ({const_name})</b><br>"
                    "Azimuth: %{theta:.1f}°<br>"
                    "Elevation: %{customdata:.1f}°"
                    "<extra></extra>"
                ),
                customdata=elevations,
            ))

    fig.update_layout(
        title={
            "text": f"Sky View -- {total_sats} satellites tracked",
            "font_size": 14,
        },
        polar={
            "radialaxis": {
                "range": [0, 90],
                "tickvals": [0, 30, 60, 90],
                "ticktext": ["90°", "60°", "30°", "0°"],
                "tickfont": {"size": 9},
            },
            "angularaxis": {
                "direction": "clockwise",
                "rotation": 90,
                "tickmode": "array",
                "tickvals": [0, 45, 90, 135, 180, 225, 270, 315],
                "ticktext": ["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
            },
        },
        height=650,
        showlegend=True,
        legend={
            "groupclick": "toggleitem",
            "font": {"size": 9},
        },
    )

    return fig
