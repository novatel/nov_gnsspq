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

Standalone HTML dashboard builder for interactive Plotly figures.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import base64
import re as _re
from pathlib import Path

from nov_gnsspq.plot.dashboard_assets import DASHBOARD_CSS, DASHBOARD_JS

if TYPE_CHECKING:
    import plotly.graph_objects


_LOGO_PATH = Path(__file__).parent / "_nov_gnsspq_logomark.png"
_SAFE_NAME = _re.compile(r'^[A-Za-z0-9_-]+$')

_THRESHOLD_PANEL_TEMPLATE = """\
  <div class="threshold-panel">
    <button class="threshold-toggle" id="threshold-toggle-{name}"
      onclick="toggleThresholdPanel('{name}')">Thresholds &#9656;</button>
    <div class="threshold-body" id="threshold-body-{name}">
      <form class="threshold-form" id="threshold-form-{name}"
        onsubmit="event.preventDefault(); submitThreshold('{name}')">
        <label><input type="radio" name="axis" value="H" checked> H</label>
        <label><input type="radio" name="axis" value="V"> V</label>
        <input type="number" step="any" id="threshold-value-{name}"
          placeholder="value" style="width:90px">
        <input type="text" id="threshold-label-{name}"
          placeholder="label (optional)" style="width:120px">
        <button type="submit" class="threshold-add-btn">Add</button>
      </form>
      <div class="threshold-list" id="threshold-list-{name}"></div>
    </div>
  </div>"""

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont,
             "Segoe UI", Roboto, sans-serif; background: #fafafa; }}
    header {{ display: flex; align-items: center; gap: 12px;
              background: #1e2532; color: #fff;
              padding: 8px 16px; }}
    header img {{ height: 32px; width: auto; flex-shrink: 0; }}
    header span {{ font-size: 14px; font-weight: 600;
                   letter-spacing: 0.02em; }}
    .tab-bar {{ display: flex; flex-wrap: wrap; background: #1e2532;
                padding: 0 12px; gap: 2px;
                border-bottom: 2px solid #384052; }}
    .tab-btn {{ padding: 9px 18px; border: none;
                background: transparent; color: #8892a4;
                cursor: pointer; font-size: 13px;
                border-bottom: 3px solid transparent;
                margin-bottom: -2px;
                transition: color 0.15s, border-color 0.15s; }}
    .tab-btn:hover {{ color: #cdd5e0; }}
    .tab-btn.active {{ color: #fff; border-bottom-color: #4a9ff5;
                       font-weight: 600; }}
    .tab-panel {{ display: none; padding: 0; width: 100%; }}
    .tab-panel.active {{ display: block; width: 100%; }}
    <!--nov_gnsspq_CSS-->
  </style>
</head>
<body>
  <header>
    {logo_tag}
    <span>nov_gnsspq — Interactive Plots</span>
  </header>
  <div class="tab-bar">
    {tab_buttons}
  </div>
{panels}
  <script>
    function showTab(id) {{
      document.querySelectorAll('.tab-btn')
        .forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel')
        .forEach(p => p.classList.remove('active'));
      document.getElementById('btn-' + id).classList.add('active');
      document.getElementById('panel-' + id).classList.add('active');
      window.dispatchEvent(new Event('resize'));
      if (window.nov_gnsspq_onTabActivated)
        window.nov_gnsspq_onTabActivated(id);
    }}
  </script>
  <script><!--nov_gnsspq_JS--></script>
</body>
</html>
"""


def _logo_img_tag() -> str:
    """Return an inline <img> tag with the nov_gnsspq logomark as a data URI.

    Returns:
        An ``<img>`` tag string, or an empty string if the logomark
        file cannot be found or read.
    """
    try:
        data = _LOGO_PATH.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return (
            f'<img src="data:image/png;base64,{b64}" '
            f'alt="nov_gnsspq" />'
        )
    except OSError:
        return ""


def build_tabbed_html(
        figures: dict[str, "go.Figure"],
        title: str = "nov_gnsspq -- Interactive Plots") -> str:
    """Build a standalone HTML page with one tab per Plotly figure.

    The nov_gnsspq logomark is embedded as a base64 data URI so the output
    file is fully self-contained.  The Plotly JS bundle is likewise
    included once (from the first figure).  Each tab panel contains a
    collapsible threshold line editor and, for figures that opt in via
    ``meta={'cross_highlight': True}`` on scatter traces, cross-subplot
    hover highlighting is wired automatically.

    Args:
        figures: Ordered mapping of plot names to Plotly figures.
            Tab order follows insertion order.
        title: Browser tab title.

    Returns:
        html: Self-contained HTML string suitable for writing to a
            ``.html`` file or serving directly.
    """
    names = list(figures.keys())
    for _n in names:
        if not _SAFE_NAME.match(_n):
            raise ValueError(
                f"Figure name {_n!r} contains characters that are not "
                f"safe for use in HTML attributes and JavaScript strings. "
                f"Use only letters, digits, underscores, and hyphens."
            )

    btn_parts = []
    for i, name in enumerate(names):
        label = name.replace("_", " ").title()
        active_cls = " active" if i == 0 else ""
        btn_parts.append(
            f'<button class="tab-btn{active_cls}" '
            f'id="btn-{name}" '
            f'onclick="showTab(\'{name}\')">'
            f'{label}</button>'
        )
    tab_buttons_html = "\n    ".join(btn_parts)

    panel_parts = []
    for i, name in enumerate(names):
        fig = figures[name]
        fig.update_layout(autosize=True)
        fig_html = fig.to_html(
            full_html=False,
            include_plotlyjs=(i == 0),
            div_id=f"plot-{name}",
            config={"responsive": True, "displayModeBar": True},
        )
        active_cls = " active" if i == 0 else ""
        threshold_panel = _THRESHOLD_PANEL_TEMPLATE.format(name=name)
        panel_parts.append(
            f'  <div class="tab-panel{active_cls}" '
            f'id="panel-{name}" '
            f'data-tab-id="{name}">\n'
            f'{threshold_panel}\n'
            f'{fig_html}\n  </div>'
        )
    panels_html = "\n".join(panel_parts)

    html = _HTML_TEMPLATE.format(
        title=title,
        logo_tag=_logo_img_tag(),
        tab_buttons=tab_buttons_html,
        panels=panels_html,
    )
    html = html.replace("<!--nov_gnsspq_CSS-->", DASHBOARD_CSS)
    html = html.replace(
        "<script><!--nov_gnsspq_JS--></script>",
        f"<script>{DASHBOARD_JS}</script>")
    return html
