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

Unit tests for nov_gnsspq.plot.dashboard.build_tabbed_html.
"""

import sys
from unittest.mock import MagicMock

import pytest

if "novatel_edie" not in sys.modules:
    _ne = MagicMock()
    _ne.SatelliteId = MagicMock()
    sys.modules["novatel_edie"] = _ne

plotly = pytest.importorskip("plotly")
import plotly.graph_objects as go  # noqa: E402

from nov_gnsspq.plot.dashboard import build_tabbed_html  # noqa: E402

# pylint: disable=protected-access


def _make_figures(names=("position", "signal")):
    """Returns a dict of empty Plotly figures keyed by name."""
    return {n: go.Figure() for n in names}


class TestDashboardAssetEmbedding:
    """Tests for asset embedding in build_tabbed_html output."""

    def test_css_embedded_in_head(self):
        """Tests that CSS is embedded in the HTML head."""
        # Act
        html = build_tabbed_html(_make_figures())
        # Assert
        assert ".threshold-panel" in html

    def test_css_marker_consumed(self):
        """Tests that the CSS marker is not present in the final output."""
        # Act
        html = build_tabbed_html(_make_figures())
        # Assert
        assert "<!--nov_gnsspq_CSS-->" not in html

    def test_js_embedded_in_page(self):
        """Tests that JS functions are embedded in the HTML page."""
        # Act
        html = build_tabbed_html(_make_figures())
        # Assert
        assert "window.addThreshold" in html
        assert "window.applyThresholds" in html

    def test_js_has_tab_activated_hook(self):
        """Tests that the tab-activated hook is embedded in the page."""
        # Act
        html = build_tabbed_html(_make_figures())
        # Assert
        assert "nov_gnsspq_onTabActivated" in html

    def test_plotly_bundle_included_once(self):
        """Tests that the Plotly bundle appears exactly once for multi-tab."""
        # Act
        html = build_tabbed_html(_make_figures(("tab1", "tab2", "tab3")))
        count = html.count("window.PlotlyConfig")
        # Assert
        assert count == 1, (
            f"Expected Plotly bundle exactly once, found {count} times"
        )


class TestDashboardTabAttributes:
    """Tests for tab attribute correctness in build_tabbed_html output."""

    def test_show_tab_calls_activated_hook(self):
        """Tests that showTab calls nov_gnsspq_onTabActivated."""
        # Act
        html = build_tabbed_html(_make_figures())
        show_tab_pos = html.find("function showTab")
        hook_pos = html.find("nov_gnsspq_onTabActivated(id)")
        # Assert
        assert show_tab_pos != -1, "showTab function not found in HTML"
        assert hook_pos > show_tab_pos, (
            "nov_gnsspq_onTabActivated call not inside showTab body"
        )

    def test_tab_panels_have_data_tab_id(self):
        """Tests that tab panels carry correct data-tab-id attributes."""
        # Act
        html = build_tabbed_html(_make_figures(("alpha", "beta")))
        # Assert
        assert 'data-tab-id="alpha"' in html
        assert 'data-tab-id="beta"' in html


class TestDashboardThresholdPanel:
    """Tests for threshold panel injection in build_tabbed_html output."""

    def test_single_figure_still_works(self):
        """Tests that a single-figure dashboard renders threshold elements."""
        # Act
        html = build_tabbed_html({"only": go.Figure()})
        # Assert
        assert "threshold-toggle-only" in html
        assert 'data-tab-id="only"' in html

    def test_threshold_form_has_axis_inputs(self):
        """Tests that the threshold form contains H and V axis inputs."""
        # Act
        html = build_tabbed_html(_make_figures(("pos",)))
        # Assert
        assert 'name="axis"' in html
        assert 'value="H"' in html
        assert 'value="V"' in html

    def test_threshold_form_has_label_input(self):
        """Tests that the threshold form contains a label input field."""
        # Act
        html = build_tabbed_html(_make_figures(("pos",)))
        # Assert
        assert 'id="threshold-label-pos"' in html

    def test_threshold_form_has_value_input(self):
        """Tests that the threshold form contains a value input field."""
        # Act
        html = build_tabbed_html(_make_figures(("pos",)))
        # Assert
        assert 'id="threshold-value-pos"' in html

    def test_threshold_list_div_present(self):
        """Tests that the threshold list div is injected per tab."""
        # Act
        html = build_tabbed_html(_make_figures(("pos",)))
        # Assert
        assert 'id="threshold-list-pos"' in html

    def test_threshold_panel_injected_per_tab(self):
        """Tests that threshold toggle buttons are injected for each tab."""
        # Act
        html = build_tabbed_html(_make_figures(("pos", "sig")))
        # Assert
        assert "threshold-toggle-pos" in html
        assert "threshold-toggle-sig" in html
