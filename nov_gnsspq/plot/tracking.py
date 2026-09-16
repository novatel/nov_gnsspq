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

Satellite and observation count timeseries plots from RANGE log data.
"""

from typing import TYPE_CHECKING

_SYS_ID = {
    0: "GPS",
    1: "GLONASS",
    2: "SBAS",
    3: "Galileo",
    4: "BeiDou",
    5: "QZSS",
    6: "NavIC",
}

_SYS_COLORS = {
    "Total":   "#E91E63",
    "GPS":     "#4CAF50",
    "GLONASS": "#2196F3",
    "Galileo": "#00BCD4",
    "BeiDou":  "#795548",
    "QZSS":    "#9C27B0",
    "SBAS":    "#FF9800",
    "NavIC":   "#607D8B",
}


from nov_gnsspq.plot.deps import require_matplotlib, require_plotly

if TYPE_CHECKING:
    import matplotlib.figure
    import plotly.graph_objects


def _prepare_tracking(db) -> dict | None:
    """Extract and aggregate RANGE tracking data by constellation.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        data: Dict with keys ``total`` (DataFrame), ``t_total``
            (Series), and ``per_const`` (dict of constellation data),
            or ``None`` if required columns are absent.
    """
    top_df = db.subtables.RANGE.cur_table
    obs_df = db.subtables.RANGE.subtables.obs.cur_table

    if (
        "header_milliseconds" not in top_df.columns
        or "sv_prn" not in obs_df.columns
    ):
        return None

    merged = obs_df.merge(
        top_df[["header_milliseconds"]],
        left_on="parent_id",
        right_index=True,
    )

    if "c_status" in merged.columns:
        merged["sys_id"] = (merged["c_status"].values >> 16) & 0x7
        merged["constellation"] = merged["sys_id"].map(
            lambda x: _SYS_ID.get(x, f"Unknown({x})")
        )
    else:
        merged["constellation"] = "Unknown"

    total = merged.groupby("header_milliseconds").agg(
        sat_count=("sv_prn", "nunique"),
        obs_count=("sv_prn", "count"),
    ).reset_index()
    t_total = total["header_milliseconds"] / 1000.0

    per_const = {}
    for const in sorted(merged["constellation"].unique()):
        sub = merged[merged["constellation"] == const]
        per_epoch = sub.groupby("header_milliseconds").agg(
            sat_count=("sv_prn", "nunique"),
            obs_count=("sv_prn", "count"),
        ).reset_index()
        t = per_epoch["header_milliseconds"] / 1000.0
        per_const[const] = {
            "t": t,
            "sat_count": per_epoch["sat_count"],
            "obs_count": per_epoch["obs_count"],
            "avg_sats": per_epoch["sat_count"].mean(),
        }

    return {"total": total, "t_total": t_total, "per_const": per_const}


def tracking(db, *, plot: bool = True) -> "matplotlib.figure.Figure | None":
    """Plot satellite and observation counts over time by constellation.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        fig: Figure with two subplots — satellite count per constellation
            (top) and total observations per epoch (bottom).

    Raises:
        KeyError: If ``RANGE`` is not present in *db*.
        ImportError: If ``matplotlib`` is not installed
            (``pip install nov_gnsspq[plot]``).
    """
    require_matplotlib()
    import matplotlib.pyplot as plt

    data = _prepare_tracking(db)

    fig, (ax_sats, ax_obs) = plt.subplots(
        2, 1, figsize=(12, 7), sharex=True
    )

    if data is None:
        for ax in (ax_sats, ax_obs):
            ax.text(
                0.5, 0.5, "Required columns not found",
                ha="center", va="center", transform=ax.transAxes,
            )
        fig.tight_layout()
        if not plot:
            return fig
        plt.show()
        plt.close(fig)
        return None

    total = data["total"]
    t_total = data["t_total"]
    per_const = data["per_const"]

    avg_total = total["sat_count"].mean()
    title_parts = [f"{avg_total:.1f} total"]

    for const, sub in per_const.items():
        avg = sub["avg_sats"]
        color = _SYS_COLORS.get(const)
        ax_sats.plot(
            sub["t"], sub["sat_count"],
            linewidth=0.7, color=color,
            label=f"{const} (avg {avg:.1f})", zorder=2,
        )
        ax_obs.plot(
            sub["t"], sub["obs_count"],
            linewidth=0.7, color=color, label=const, zorder=2,
        )
        title_parts.append(f"{avg:.1f} {const}")

    ax_sats.plot(
        t_total, total["sat_count"],
        linewidth=1.2, color=_SYS_COLORS["Total"],
        label=f"Total (avg {avg_total:.1f})", zorder=3,
    )
    ax_obs.plot(
        t_total, total["obs_count"],
        linewidth=1.2, color=_SYS_COLORS["Total"],
        label="Total", zorder=3,
    )

    fig.suptitle("Avg. " + ", ".join(title_parts), fontsize=11)

    ax_sats.set_ylabel("Num Sats")
    ax_sats.set_title("Satellites Tracked per Constellation")
    ax_sats.legend(loc="upper right", fontsize=7, ncol=2)

    ax_obs.set_ylabel("Observations")
    ax_obs.set_title("Observations per Epoch")
    ax_obs.legend(loc="upper right", fontsize=7, ncol=2)
    ax_obs.set_xlabel("GPS Time (s)")

    fig.tight_layout()
    if not plot:
        return fig
    plt.show()
    plt.close(fig)


def tracking_interactive(db) -> "plotly.graph_objects.Figure | None":
    """Build an interactive tracking figure using Plotly.

    Two vertically stacked panels sharing a GPS time x-axis:

    1. Satellite count per constellation over time, with a total line.
    2. Observation count per constellation over time, with a total line.

    Clicking a constellation in the legend hides it from both panels
    simultaneously.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        fig: A Plotly Figure, or ``None`` if required columns are absent.

    Raises:
        KeyError: If ``RANGE`` is not present in *db*.
        ImportError: If ``plotly`` is not installed
            (``pip install nov_gnsspq[plot]``).
    """
    require_plotly()
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    data = _prepare_tracking(db)
    if data is None:
        return None

    total = data["total"]
    t_total = data["t_total"]
    per_const = data["per_const"]

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=(
            "Satellites Tracked per Constellation",
            "Observations per Epoch",
        ),
        vertical_spacing=0.10,
    )

    for const, sub in per_const.items():
        color = _SYS_COLORS.get(const, "#607D8B")
        avg = sub["avg_sats"]

        fig.add_trace(go.Scatter(
            x=sub["t"], y=sub["sat_count"],
            mode="lines",
            name=f"{const} (avg {avg:.1f})",
            line={"color": color, "width": 0.8},
            legendgroup=const,
            hovertemplate=(
                f"<b>{const}</b><br>"
                "Time: %{x:.2f} s<br>"
                "Sats: %{y}<extra></extra>"
            ),
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=sub["t"], y=sub["obs_count"],
            mode="lines",
            name=const,
            line={"color": color, "width": 0.8},
            legendgroup=const,
            showlegend=False,
            hovertemplate=(
                f"<b>{const}</b><br>"
                "Time: %{x:.2f} s<br>"
                "Obs: %{y}<extra></extra>"
            ),
        ), row=2, col=1)

    avg_total = total["sat_count"].mean()
    fig.add_trace(go.Scatter(
        x=t_total, y=total["sat_count"],
        mode="lines",
        name=f"Total (avg {avg_total:.1f})",
        line={"color": _SYS_COLORS["Total"], "width": 1.2},
        legendgroup="Total",
        hovertemplate=(
            "Total<br>"
            "Time: %{x:.2f} s<br>"
            "Sats: %{y}<extra></extra>"
        ),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=t_total, y=total["obs_count"],
        mode="lines",
        name="Total",
        line={"color": _SYS_COLORS["Total"], "width": 1.2},
        legendgroup="Total",
        showlegend=False,
        hovertemplate=(
            "Total<br>"
            "Time: %{x:.2f} s<br>"
            "Obs: %{y}<extra></extra>"
        ),
    ), row=2, col=1)

    fig.update_yaxes(
        title_text="Satellites", rangemode="tozero", row=1, col=1
    )
    fig.update_yaxes(
        title_text="Observations", rangemode="tozero", row=2, col=1
    )
    fig.update_xaxes(title_text="GPS Time (s)", row=2, col=1)

    fig.update_layout(
        title={
            "text": f"Tracking -- avg {avg_total:.1f} total sats",
            "font_size": 11,
        },
        height=600,
        hovermode="x unified",
        legend={"font": {"size": 9}},
    )

    return fig
