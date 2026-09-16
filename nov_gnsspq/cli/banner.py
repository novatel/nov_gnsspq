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

Shared CLI banner machinery for nov_gnsspq subcommands.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

WORDMARK = (
    r"   ____ _____  ______________  ____ _",
    r"  / __  / __ \/ ___/ ___/ __ \/ __  /",
    r" / /_/ / / / (__  |__  ) /_/ / /_/ /",
    r" \__, /_/ /_/____/____/ .___/\__, /",
    r"/____/               /_/       /_/",
)

RULE = "─" * 72
_COL_WIDTH = 40


@dataclass
class ConvertBannerInfo:
    """Data container for the convert subcommand startup banner."""

    input_path: Path
    output_path: Path
    file_size_mb: float
    writer: str
    writer_selection: str
    workers: int
    threshold_mb: int
    edie_version: str
    nov_gnsspq_version: str
    message_count: int = -1
    message_types: list[str] = field(default_factory=list)


@dataclass
class ReconstructBannerInfo:
    """Data container for the reconstruct subcommand startup banner."""

    db_path: Path
    original_gps: Path
    mode: str
    nov_gnsspq_version: str
    edie_version: str


@dataclass
class PlotBannerInfo:
    """Data container for the plot subcommand startup banner."""

    plots: list[str]
    out_dir: Path | None
    html: bool
    nov_gnsspq_version: str


def print_convert_banner(
        info: ConvertBannerInfo,
        stream: TextIO = sys.stdout):
    """Print the nov_gnsspq convert startup banner to *stream*.

    Args:
        info: Populated ConvertBannerInfo with run metadata.
        stream: Output stream to write the banner to.
    """
    def p(s=""):
        print(s, file=stream)

    badge_top, badge_mid, badge_bot = _badge("CONVERT")

    wm_width = max(len(line) for line in WORDMARK)
    wm = [line.ljust(wm_width) for line in WORDMARK]
    gap = "    "

    p()
    p(f"{wm[0]}{gap}{badge_top}")
    p(f"{wm[1]}{gap}{badge_mid}")
    p(f"{wm[2]}{gap}{badge_bot}")
    p(
        f"{wm[3]}{gap}v{info.nov_gnsspq_version}"
        f" · edie {info.edie_version}"
        f" · mode decode & store"
    )
    p(f"{wm[4]}{gap}decode once. query forever.")
    p()
    p(f"  {RULE}")

    in_name = _truncate(info.input_path.name, _COL_WIDTH)
    out_name = _truncate(info.output_path.name, _COL_WIDTH)
    msg_count_str = (
        f"{info.message_count:,}" if info.message_count >= 0 else "?"
    )
    msgs_preview = ", ".join(info.message_types[:4])
    if len(info.message_types) > 4:
        msgs_preview += f", +{len(info.message_types) - 4} more"
    if not msgs_preview:
        msgs_preview = "—"

    sel = info.writer_selection
    writer_visible = f"{info.writer} ({sel})" if sel else info.writer

    p(
        f"  {'input  ':<9}{in_name:<{_COL_WIDTH}}"
        f"  {info.file_size_mb:,.1f} MB · {msg_count_str} messages"
    )
    p(f"  {'output ':<9}{out_name:<{_COL_WIDTH}}  parquet + zstd l3")
    p(
        f"  {'writer ':<9}{writer_visible:<{_COL_WIDTH}}"
        f"  {info.workers} workers · threshold {info.threshold_mb} MB"
    )
    p(
        f"  {'decode ':<9}{f'edie {info.edie_version}':<{_COL_WIDTH}}"
        f"  {msgs_preview}"
    )

    p(f"  {RULE}")
    p()
    p(
        "  [i] this runs once."
        " all subsequent queries read directly from parquet."
    )
    p()
    stream.flush()


def print_reconstruct_banner(
        info: ReconstructBannerInfo,
        stream: TextIO = sys.stdout):
    """Print the nov_gnsspq reconstruct startup banner to *stream*.

    Args:
        info: Populated ReconstructBannerInfo with run metadata.
        stream: Output stream to write the banner to.
    """
    def p(s=""):
        print(s, file=stream)

    badge_top, badge_mid, badge_bot = _badge("RECONSTRUCT")

    wm_width = max(len(line) for line in WORDMARK)
    wm = [line.ljust(wm_width) for line in WORDMARK]
    gap = "    "

    p()
    p(f"{wm[0]}{gap}{badge_top}")
    p(f"{wm[1]}{gap}{badge_mid}")
    p(f"{wm[2]}{gap}{badge_bot}")
    p(
        f"{wm[3]}{gap}v{info.nov_gnsspq_version}"
        f" · edie {info.edie_version}"
        f" · mode {info.mode}"
    )
    p(f"{wm[4]}{gap}reconstruct. compare. verify.")
    p()
    p(f"  {RULE}")

    db_name = _truncate(info.db_path.name, _COL_WIDTH)
    gps_name = _truncate(info.original_gps.name, _COL_WIDTH)

    p(f"  {'database':<9}{db_name:<{_COL_WIDTH}}")
    p(f"  {'original':<9}{gps_name:<{_COL_WIDTH}}")
    p(f"  {'mode':<9}{info.mode}")

    p(f"  {RULE}")
    p()
    stream.flush()


def print_plot_banner(
        info: PlotBannerInfo,
        stream: TextIO = sys.stdout):
    """Print the nov_gnsspq plot startup banner to *stream*.

    Args:
        info: Populated PlotBannerInfo with run metadata.
        stream: Output stream to write the banner to.
    """
    def p(s=""):
        print(s, file=stream)

    badge_top, badge_mid, badge_bot = _badge("PLOT")

    wm_width = max(len(line) for line in WORDMARK)
    wm = [line.ljust(wm_width) for line in WORDMARK]
    gap = "    "

    fmt = "HTML (interactive dashboard)" if info.html else "PNG (static)"

    p()
    p(f"{wm[0]}{gap}{badge_top}")
    p(f"{wm[1]}{gap}{badge_mid}")
    p(f"{wm[2]}{gap}{badge_bot}")
    p(f"{wm[3]}{gap}v{info.nov_gnsspq_version} · {fmt}")
    p(f"{wm[4]}{gap}visualise. explore. export.")
    p()
    p(f"  {RULE}")

    plots_preview = ", ".join(info.plots[:5])
    if len(info.plots) > 5:
        plots_preview += f", +{len(info.plots) - 5} more"

    out_str = (
        _truncate(str(info.out_dir), _COL_WIDTH)
        if info.out_dir
        else "(interactive)"
    )
    out_suffix = (
        "→ dashboard.html" if info.html and info.out_dir
        else "→ *.png" if info.out_dir
        else "plt.show() / browser"
    )

    p(
        f"  {'plots':<9}{plots_preview:<{_COL_WIDTH}}"
        f"  {len(info.plots)} selected"
    )
    p(f"  {'output':<9}{out_str:<{_COL_WIDTH}}  {out_suffix}")
    p(f"  {'format':<9}{fmt}")

    p(f"  {RULE}")
    p()
    stream.flush()


def _badge(label: str) -> tuple[str, str, str]:
    """Renders a three-line box badge around *label*.

    Args:
        label: Text to display inside the badge.

    Returns:
        A tuple of (top_border, middle_row, bottom_border) strings.
    """
    inner = f"  {label}    "
    w = len(inner)
    return ("┌" + "─" * w + "┐", "│" + inner + "│", "└" + "─" * w + "┘")


def _truncate(s: str, n: int) -> str:
    """Truncates *s* to at most *n* characters, appending an ellipsis.

    Args:
        s: The string to truncate.
        n: Maximum character length.

    Returns:
        The original string if short enough, otherwise a truncated version
        ending with an ellipsis character.
    """
    return s if len(s) <= n else s[: n - 1] + "…"
