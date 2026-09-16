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

Per-PRN satellite statistics plots from RANGE and SATVIS2 log data.
"""

from typing import TYPE_CHECKING

from collections.abc import Iterable

_SYS_INFO = {
    0: ("GPS",     "G", "#4CAF50"),
    1: ("GLONASS", "R", "#F44336"),
    2: ("SBAS",    "S", "#9E9E9E"),
    3: ("Galileo", "E", "#9C27B0"),
    4: ("BeiDou",  "C", "#2196F3"),
    5: ("QZSS",    "J", "#FF9800"),
    6: ("NavIC",   "N", "#795548"),
}


from nov_gnsspq.plot.deps import require_matplotlib, require_plotly

if TYPE_CHECKING:
    import matplotlib.figure
    import plotly.graph_objects


def _prepare_satellite_stats(
        db,
        prns: Iterable[int] | None = None) -> dict:
    """Extract and aggregate per-PRN RANGE (and optional SATVIS2) data.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.
        prns: Optional iterable of PRN numbers to include.  When
            ``None`` all PRNs in the RANGE log are used.

    Returns:
        data: Dict with keys ``agg`` (aggregated DataFrame) and
            ``elev_df`` (elevation DataFrame or None).
    """
    import pandas as pd

    top_df = db.subtables.RANGE.cur_table
    obs_df = db.subtables.RANGE.subtables.obs.cur_table

    obs = obs_df.merge(
        top_df[["header_milliseconds"]],
        left_on="parent_id",
        right_index=True,
    )
    obs["sys_id"] = (obs["c_status"].values >> 16) & 0x7

    if prns is not None:
        obs = obs[obs["sv_prn"].isin(prns)]

    agg = (
        obs.groupby(["header_milliseconds", "sv_prn", "sys_id"])
        .agg(
            cn0=("C_No", "max"),
            sd_psr=("sd_psr", "mean"),
            sd_adr=("sd_adr", "mean"),
        )
        .reset_index()
    )
    agg["time_s"] = agg["header_milliseconds"] / 1000.0

    elev_df = None
    try:
        sv2top = db.subtables.SATVIS2.cur_table
        sat_vis = (
            db.subtables.SATVIS2
            .subtables.sat_vis_list.cur_table
        )
        sat_id = (
            db.subtables.SATVIS2
            .subtables.sat_vis_list
            .subtables.id.cur_table
        )

        ev = sat_id.merge(
            sat_vis[["parent_id", "elevation"]],
            left_on="parent_id",
            right_index=True,
        )
        ev = ev.merge(
            sv2top[["header_milliseconds"]],
            left_on="parent_id_y",
            right_index=True,
        )
        ev = ev[
            ["prn", "header_milliseconds", "elevation"]
        ].sort_values("header_milliseconds")

        range_times = (
            agg[["header_milliseconds", "sv_prn"]]
            .drop_duplicates()
            .sort_values("header_milliseconds")
        )
        elev_df = pd.merge_asof(
            range_times,
            ev.rename(columns={"prn": "sv_prn"}),
            on="header_milliseconds",
            by="sv_prn",
            direction="nearest",
            tolerance=10_000,
        )
        elev_df["time_s"] = elev_df["header_milliseconds"] / 1000.0
    except AttributeError:
        pass  # SATVIS2 not present

    return {"agg": agg, "elev_df": elev_df}


def satellite_stats(
        db,
        prns: Iterable[int] | None = None,
        *,
        plot: bool = True) -> "matplotlib.figure.Figure | None":
    """Plot per-PRN satellite statistics over time.

    Four panels sharing a GPS-time x-axis:

    1. **C/N0** (dB-Hz) — best signal per epoch per PRN.
    2. **Elevation** (°) — from SATVIS2, forward-filled to RANGE epochs.
    3. **Code noise** — ``sd_psr`` (m), mean across signals per
       epoch/PRN.
    4. **Phase noise** — ``sd_adr`` (cycles), mean across signals per
       epoch/PRN.

    The elevation panel is omitted when ``SATVIS2`` is absent.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.
        prns: Optional iterable of integer PRN numbers to include.  When
            ``None`` all PRNs present in the RANGE log are plotted.

    Returns:
        fig: Figure with three or four panels of per-PRN statistics.

    Raises:
        KeyError: If ``RANGE`` is not present in *db*.
        ImportError: If ``matplotlib`` is not installed
            (``pip install nov_gnsspq[plot]``).
    """
    require_matplotlib()
    import matplotlib.lines as mlines
    import matplotlib.pyplot as plt

    data = _prepare_satellite_stats(db, prns=prns)
    agg = data["agg"]
    elev_df = data["elev_df"]

    n_panels = 4 if elev_df is not None else 3
    fig, axes = plt.subplots(
        n_panels, 1, figsize=(13, 3 * n_panels), sharex=True
    )
    fig.suptitle("Individual Satellite Statistics", fontsize=13)

    ax_cn0 = axes[0]
    ax_elev = axes[1] if elev_df is not None else None
    ax_psr = axes[2] if elev_df is not None else axes[1]
    ax_adr = axes[3] if elev_df is not None else axes[2]

    legend_handles = {}

    for (sv_prn, sys_id), grp in agg.groupby(["sv_prn", "sys_id"]):
        grp = grp.sort_values("time_s")
        const_name, _, color = _SYS_INFO.get(
            int(sys_id), (f"SYS{sys_id}", str(sys_id), "#607D8B")
        )
        kw = {"color": color, "linewidth": 0.7, "alpha": 0.8}

        ax_cn0.plot(grp["time_s"], grp["cn0"], **kw)
        ax_psr.plot(grp["time_s"], grp["sd_psr"], **kw)
        ax_adr.plot(grp["time_s"], grp["sd_adr"], **kw)

        if ax_elev is not None:
            sub_elev = (
                elev_df[elev_df["sv_prn"] == sv_prn]
                .sort_values("time_s")
            )
            if not sub_elev.empty:
                ax_elev.plot(
                    sub_elev["time_s"], sub_elev["elevation"], **kw
                )

        if const_name not in legend_handles:
            legend_handles[const_name] = mlines.Line2D(
                [], [], color=color, linewidth=1.5, label=const_name
            )

    ax_cn0.set_ylabel("C/N0 (dB-Hz)")
    ax_cn0.set_title("Carrier-to-noise Ratio")
    ax_cn0.set_ylim(bottom=0)

    if ax_elev is not None:
        ax_elev.set_ylabel("Elevation (°)")
        ax_elev.set_title("Elevation Angle")
        ax_elev.set_ylim(0, 90)

    ax_psr.set_ylabel("sd_psr (m)")
    ax_psr.set_title("Code Measurement Noise")
    ax_psr.set_ylim(bottom=0)

    ax_adr.set_ylabel("sd_adr (cycles)")
    ax_adr.set_title("Phase Measurement Noise")
    ax_adr.set_ylim(bottom=0)
    ax_adr.set_xlabel("GPS Time (s)")

    for ax in axes:
        ax.grid(axis="y", linewidth=0.3, alpha=0.5)

    if legend_handles:
        fig.legend(
            handles=list(legend_handles.values()),
            loc="upper right",
            bbox_to_anchor=(1.0, 0.99),
            fontsize=8,
            framealpha=0.9,
        )

    fig.tight_layout()
    if not plot:
        return fig
    plt.show()
    plt.close(fig)


def satellite_stats_interactive(
        db,
        prns: Iterable[int] | None = None) -> "plotly.graph_objects.Figure":
    """Build an interactive per-PRN satellite statistics figure.

    Three or four vertically stacked panels sharing a GPS time x-axis:

    1. C/N0 (dB-Hz) — best signal per epoch per PRN.
    2. Elevation (°) — from SATVIS2 when available.
    3. Code measurement noise — mean sd_psr (m).
    4. Phase measurement noise — mean sd_adr (cycles).

    Clicking a constellation name in the legend hides or shows all
    satellites of that constellation across all panels simultaneously.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.
        prns: Optional iterable of integer PRN numbers to include.

    Returns:
        fig: A Plotly Figure with three or four subplots.

    Raises:
        KeyError: If ``RANGE`` is not present in *db*.
        ImportError: If ``plotly`` is not installed
            (``pip install nov_gnsspq[plot]``).
    """
    require_plotly()
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    data = _prepare_satellite_stats(db, prns=prns)
    agg = data["agg"]
    elev_df = data["elev_df"]

    has_elev = elev_df is not None
    n_panels = 4 if has_elev else 3
    panel_titles = (
        ("C/N0", "Elevation", "Code Noise", "Phase Noise")
        if has_elev
        else ("C/N0", "Code Noise", "Phase Noise")
    )
    row_psr = 3 if has_elev else 2
    row_adr = 4 if has_elev else 3

    fig = make_subplots(
        rows=n_panels, cols=1,
        shared_xaxes=True,
        subplot_titles=panel_titles,
        vertical_spacing=0.10,
    )

    seen_consts: set[str] = set()

    for (sv_prn, sys_id), grp in agg.groupby(["sv_prn", "sys_id"]):
        grp = grp.sort_values("time_s")
        const_name, prefix, color = _SYS_INFO.get(
            int(sys_id), (f"SYS{sys_id}", str(sys_id), "#607D8B")
        )
        label = f"{prefix}{int(sv_prn):02d}"
        first_of_const = const_name not in seen_consts
        seen_consts.add(const_name)

        _kw: dict = {
            "mode": "lines",
            "line": {"color": color, "width": 0.7},
            "legendgroup": const_name,
            "name": label,
        }

        fig.add_trace(go.Scatter(
            x=grp["time_s"],
            y=grp["cn0"],
            **_kw,
            showlegend=first_of_const,
            legendgrouptitle_text=(
                const_name if first_of_const else None
            ),
            hovertemplate=(
                f"<b>{label}</b><br>"
                "CN0: %{y:.1f} dB-Hz<extra></extra>"
            ),
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=grp["time_s"],
            y=grp["sd_psr"],
            **_kw,
            showlegend=False,
            hovertemplate=(
                f"<b>{label}</b><br>"
                "sd_psr: %{y:.3f} m<extra></extra>"
            ),
        ), row=row_psr, col=1)

        fig.add_trace(go.Scatter(
            x=grp["time_s"],
            y=grp["sd_adr"],
            **_kw,
            showlegend=False,
            hovertemplate=(
                f"<b>{label}</b><br>"
                "sd_adr: %{y:.4f} cyc<extra></extra>"
            ),
        ), row=row_adr, col=1)

        if has_elev:
            sub_elev = (
                elev_df[elev_df["sv_prn"] == sv_prn]
                .sort_values("time_s")
            )
            if not sub_elev.empty:
                fig.add_trace(go.Scatter(
                    x=sub_elev["time_s"],
                    y=sub_elev["elevation"],
                    **_kw,
                    showlegend=False,
                    hovertemplate=(
                        f"<b>{label}</b><br>"
                        "Elev: %{y:.1f}°<extra></extra>"
                    ),
                ), row=2, col=1)

    fig.update_yaxes(
        title_text="C/N0 (dB-Hz)", rangemode="tozero", row=1, col=1
    )
    if has_elev:
        fig.update_yaxes(
            title_text="Elevation (°)",
            range=[0, 90], row=2, col=1,
        )
    fig.update_yaxes(
        title_text="sd_psr (m)", rangemode="tozero",
        row=row_psr, col=1,
    )
    fig.update_yaxes(
        title_text="sd_adr (cycles)", rangemode="tozero",
        row=row_adr, col=1,
    )
    fig.update_xaxes(title_text="GPS Time (s)", row=row_adr, col=1)

    fig.update_layout(
        title={"text": "Individual Satellite Statistics", "font_size": 13},
        height=250 * n_panels,
        hovermode="x unified",
        legend={
            "groupclick": "toggleitem",
            "font": {"size": 9},
        },
    )

    return fig
