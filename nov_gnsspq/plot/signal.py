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

CN0 per satellite and satellite count plots from RANGE log data.
"""

from typing import TYPE_CHECKING

_POOR_MAX = 20
_WARNING_MAX = 30
_GOOD_MAX = 60  # above this may indicate spoofing or severe multipath

_QUALITY_BANDS = [
    (0,            _POOR_MAX,    "rgba(244,67,54,0.10)",  "Poor (<20 dB-Hz)"),
    (_POOR_MAX,    _WARNING_MAX, "rgba(255,152,0,0.10)",  "Warning (20--30 dB-Hz)"),
    (_WARNING_MAX, _GOOD_MAX,   "rgba(76,175,80,0.07)",  "Good (30--60 dB-Hz)"),
]


from nov_gnsspq.plot.deps import require_matplotlib, require_plotly

if TYPE_CHECKING:
    import matplotlib.figure
    import plotly.graph_objects


def _prepare_signal(db) -> dict:
    """Extract and aggregate RANGE signal quality data.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        data: Dict with keys ``merged`` (DataFrame with ``time_s``),
            ``svs`` (sorted PRN list), ``means``, ``stds``,
            and ``count_per_epoch`` (DataFrame or None).
    """
    import numpy as np

    top_df = db.subtables.RANGE.cur_table
    obs_df = db.subtables.RANGE.subtables.obs.cur_table

    merged = obs_df.merge(
        top_df[["header_milliseconds"]],
        left_on="parent_id",
        right_index=True,
    )
    merged["time_s"] = merged["header_milliseconds"] / 1000.0

    svs: list = []
    means = np.array([])
    stds = np.array([])
    if "sv_prn" in merged.columns and "C_No" in merged.columns:
        grouped = merged.groupby("sv_prn")["C_No"]
        svs = sorted(grouped.groups.keys())
        means = np.array([grouped.get_group(sv).mean() for sv in svs])
        stds = np.array([grouped.get_group(sv).std() for sv in svs])

    count_per_epoch = None
    if "sv_prn" in merged.columns:
        count_per_epoch = (
            merged.groupby("header_milliseconds")["sv_prn"]
            .nunique()
            .reset_index(name="sat_count")
        )
        count_per_epoch["time_s"] = (
            count_per_epoch["header_milliseconds"] / 1000.0
        )

    return {
        "merged": merged,
        "svs": svs,
        "means": means,
        "stds": stds,
        "count_per_epoch": count_per_epoch,
    }


def signal(db, *, plot: bool = True) -> "matplotlib.figure.Figure | None":
    """Plot signal quality (CN0) and satellite count from RANGE data.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        fig: Figure with two panels -- mean CN0 bar chart per satellite
            (left) and satellite count over time (right).

    Raises:
        KeyError: If ``RANGE`` is not present in *db*.
        ImportError: If ``matplotlib`` is not installed
            (``pip install nov_gnsspq[plot]``).
    """
    require_matplotlib()
    import matplotlib.pyplot as plt
    import numpy as np

    data = _prepare_signal(db)
    svs = data["svs"]
    means = data["means"]
    stds = data["stds"]
    count_per_epoch = data["count_per_epoch"]

    fig, (ax_cn0, ax_count) = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle("Signal Quality", fontsize=14)

    if svs:
        from matplotlib.transforms import blended_transform_factory

        x = np.arange(len(svs))
        y_max = max(
            float((means + stds).max()), _GOOD_MAX
        ) * 1.08

        ax_cn0.axhspan(
            0, _POOR_MAX, color="#F44336", alpha=0.10, zorder=0
        )
        ax_cn0.axhspan(
            _POOR_MAX, _WARNING_MAX, color="#FF9800", alpha=0.10, zorder=0
        )
        ax_cn0.axhspan(
            _WARNING_MAX, _GOOD_MAX, color="#4CAF50", alpha=0.08, zorder=0
        )
        ax_cn0.axhspan(
            _GOOD_MAX, y_max, color="#9C27B0", alpha=0.10, zorder=0
        )

        for y, col in [
            (_POOR_MAX, "#F44336"),
            (_WARNING_MAX, "#FF9800"),
            (_GOOD_MAX, "#9C27B0"),
        ]:
            ax_cn0.axhline(
                y, color=col, linewidth=0.8, linestyle="--", zorder=1
            )

        trans = blended_transform_factory(
            ax_cn0.transAxes, ax_cn0.transData
        )
        label_specs = [
            (_POOR_MAX / 2,                  "Poor",         "#c62828"),
            ((_POOR_MAX + _WARNING_MAX) / 2, "Warning",      "#e65100"),
            ((_WARNING_MAX + _GOOD_MAX) / 2, "Good",         "#1b5e20"),
            ((_GOOD_MAX + y_max) / 2,        "Warning\n(high)", "#6a1b9a"),
        ]
        for y_pos, label, color in label_specs:
            ax_cn0.text(
                1.02, y_pos, label, transform=trans,
                color=color, fontsize=7, va="center", ha="left",
                style="italic", clip_on=False,
            )

        ax_cn0.bar(
            x, means, yerr=stds, capsize=3,
            color="#4CAF50", alpha=0.85, zorder=2,
        )
        ax_cn0.set_xticks(x)
        ax_cn0.set_xticklabels(
            [str(sv) for sv in svs], rotation=45, fontsize=8
        )
        ax_cn0.set_xlabel("Satellite PRN")
        ax_cn0.set_ylabel("Carrier-to-noise Ratio (dB-Hz)")
        ax_cn0.set_ylim(0, y_max)
        ax_cn0.set_title("Mean CN0 per Satellite (±1sigma)")
    else:
        ax_cn0.text(
            0.5, 0.5, "sv_prn / C_No columns not found",
            ha="center", va="center", transform=ax_cn0.transAxes,
        )

    if count_per_epoch is not None:
        ax_count.plot(
            count_per_epoch["time_s"],
            count_per_epoch["sat_count"],
            linewidth=0.8, color="#FF9800",
        )
        ax_count.set_xlabel("GPS Time (s)")
        ax_count.set_ylabel("Satellite Count")
        ax_count.set_title("Satellites Tracked over Time")

    fig.tight_layout()
    if not plot:
        return fig
    plt.show()
    plt.close(fig)


def signal_interactive(db) -> "plotly.graph_objects.Figure":
    """Build an interactive signal quality figure using Plotly.

    Three vertically stacked panels:

    1. **CN0 over time** -- one trace per satellite PRN with horizontal
       quality band fills.  Individual satellites can be toggled via the
       legend.
    2. **Mean CN0 summary** -- horizontal bar chart of per-PRN mean CN0
       with ±1sigma error bars, colour-coded by quality level.
    3. **Satellite count** -- total unique PRNs tracked per epoch.

    Args:
        db: A :class:`~nov_gnsspq.reader.frontend.PqReader` instance.

    Returns:
        fig: A Plotly Figure with three subplots.

    Raises:
        KeyError: If ``RANGE`` is not present in *db*.
        ImportError: If ``plotly`` is not installed
            (``pip install nov_gnsspq[plot]``).
    """
    require_plotly()
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    data = _prepare_signal(db)
    _ = data["merged"]
    svs = data["svs"]
    means = data["means"]
    stds = data["stds"]
    count_per_epoch = data["count_per_epoch"]

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=False,
        subplot_titles=(
            "Mean CN0 per Satellite (±1sigma)",
            "Satellites Tracked",
        ),
        vertical_spacing=0.20,
        row_heights=[0.65, 0.35],
    )

    # --- Panel 1: mean CN0 bar chart ---
    if svs:
        prn_labels = [f"PRN {int(p)}" for p in svs]
        bar_colors = [
            "#F44336" if m < _POOR_MAX
            else "#FF9800" if m < _WARNING_MAX
            else "#4CAF50" if m <= _GOOD_MAX
            else "#9C27B0"
            for m in means
        ]

        fig.add_trace(go.Bar(
            x=prn_labels, y=means,
            error_y={
                "type": "data", "array": stds,
                "visible": True, "thickness": 1.2, "width": 3,
            },
            marker_color=bar_colors,
            name="Mean CN0",
            showlegend=False,
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Mean: %{y:.1f} dB-Hz<br>"
                "sigma: %{error_y.array:.1f} dB-Hz"
                "<extra></extra>"
            ),
        ), row=1, col=1)

        y_max = max(float(means.max()) * 1.2, _GOOD_MAX * 1.2)

        for y0, y1, fill_color, _ in _QUALITY_BANDS:
            fig.add_hrect(
                y0=y0, y1=y1,
                fillcolor=fill_color,
                line_width=0,
                row=1, col=1,
            )
        fig.add_hrect(
            y0=_GOOD_MAX, y1=y_max,
            fillcolor="rgba(156,39,176,0.10)",
            line_width=0,
            row=1, col=1,
        )

        for y_val, color, label in [
            (_POOR_MAX,    "#F44336", "Poor"),
            (_WARNING_MAX, "#FF9800", "Warning"),
            (_GOOD_MAX,    "#9C27B0", "High warning"),
        ]:
            fig.add_hline(
                y=y_val, line_dash="dash",
                line_color=color, line_width=0.8,
                annotation_text=label,
                annotation_position="right",
                annotation={"font_size": 9, "font_color": color},
                row=1, col=1,
            )

        fig.update_yaxes(
            title_text="CN0 (dB-Hz)",
            range=[0, y_max],
            row=1, col=1,
        )

    # --- Panel 2: satellite count ---
    if count_per_epoch is not None:
        mean_count = count_per_epoch["sat_count"].mean()

        fig.add_trace(go.Scatter(
            x=count_per_epoch["time_s"],
            y=count_per_epoch["sat_count"],
            mode="lines", name="Satellites",
            line={"color": "#FF9800", "width": 1.0},
            fill="tozeroy",
            fillcolor="rgba(255,152,0,0.12)",
            showlegend=False,
            hovertemplate=(
                "Time: %{x:.2f} s<br>"
                "Count: %{y}<extra></extra>"
            ),
        ), row=2, col=1)

        fig.add_hline(
            y=mean_count, line_dash="dot",
            line_color="#FF9800", line_width=0.8,
            annotation_text=f"avg {mean_count:.1f}",
            annotation_position="right",
            annotation={"font_size": 9},
            row=2, col=1,
        )
        fig.update_yaxes(
            title_text="Satellites", rangemode="tozero", row=2, col=1
        )
        fig.update_xaxes(title_text="GPS Time (s)", row=2, col=1)

    fig.update_layout(
        title={"text": "Signal Quality -- Interactive", "font_size": 15},
        height=600,
        hovermode="closest",
        margin={"r": 120},
    )

    return fig
