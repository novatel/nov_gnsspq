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

Unit tests for the nov_gnsspq.plot.dashboard_assets module.
"""

# pylint: disable=protected-access


def _import_assets():
    """Imports and returns the CSS and JS asset strings."""
    from nov_gnsspq.plot.dashboard_assets import (  # noqa: PLC0415
        DASHBOARD_CSS,
        DASHBOARD_JS,
    )
    return DASHBOARD_CSS, DASHBOARD_JS


class TestDashboardAssetsExports:
    """Tests for dashboard_assets module-level exports."""

    def test_module_exports_css_string(self):
        """Tests that DASHBOARD_CSS is a non-empty string."""
        # Act
        css, _ = _import_assets()
        # Assert
        assert isinstance(css, str)
        assert len(css) > 0

    def test_module_exports_js_string(self):
        """Tests that DASHBOARD_JS is a non-empty string."""
        # Act
        _, js = _import_assets()
        # Assert
        assert isinstance(js, str)
        assert len(js) > 0


class TestDashboardAssetsCSS:
    """Tests for the DASHBOARD_CSS asset string."""

    def setup_method(self):
        """Sets up the CSS asset string for each test."""
        self.css, _ = _import_assets()

    def test_has_threshold_body_class(self):
        """Tests that the CSS defines the .threshold-body class."""
        # Act & Assert
        assert ".threshold-body" in self.css

    def test_has_threshold_item_class(self):
        """Tests that the CSS defines the .threshold-item class."""
        # Act & Assert
        assert ".threshold-item" in self.css

    def test_has_threshold_panel_class(self):
        """Tests that the CSS defines the .threshold-panel class."""
        # Act & Assert
        assert ".threshold-panel" in self.css

    def test_has_threshold_remove_class(self):
        """Tests that the CSS defines the .threshold-remove class."""
        # Act & Assert
        assert ".threshold-remove" in self.css

    def test_has_threshold_toggle_class(self):
        """Tests that the CSS defines the .threshold-toggle class."""
        # Act & Assert
        assert ".threshold-toggle" in self.css


class TestDashboardAssetsJS:
    """Tests for the DASHBOARD_JS asset string."""

    def setup_method(self):
        """Sets up the JS asset string for each test."""
        _, self.js = _import_assets()

    def test_binary_search_caller_checks_result(self):
        """Tests that callers of _binarySearch check the return value."""
        # Act & Assert
        assert "matchIdx >= 0" in self.js

    def test_binary_search_empty_guard(self):
        """Tests that _binarySearch guards against empty input."""
        # Act & Assert
        assert "if (!arr || !arr.length) return -1" in self.js

    def test_exports_add_threshold(self):
        """Tests that window.addThreshold is exported."""
        # Act & Assert
        assert "window.addThreshold" in self.js

    def test_exports_apply_thresholds(self):
        """Tests that window.applyThresholds is exported."""
        # Act & Assert
        assert "window.applyThresholds" in self.js

    def test_exports_remove_threshold(self):
        """Tests that window.removeThreshold is exported."""
        # Act & Assert
        assert "window.removeThreshold" in self.js

    def test_exports_submit_threshold(self):
        """Tests that window.submitThreshold is exported."""
        # Act & Assert
        assert "window.submitThreshold" in self.js

    def test_exports_tab_activated_hook(self):
        """Tests that window.nov_gnsspq_onTabActivated is exported."""
        # Act & Assert
        assert "window.nov_gnsspq_onTabActivated" in self.js

    def test_exports_toggle_threshold_panel(self):
        """Tests that window.toggleThresholdPanel is exported."""
        # Act & Assert
        assert "window.toggleThresholdPanel" in self.js

    def test_has_binary_search(self):
        """Tests that the _binarySearch helper is defined."""
        # Act & Assert
        assert "_binarySearch" in self.js

    def test_has_on_hover(self):
        """Tests that the _onHover handler is defined."""
        # Act & Assert
        assert "_onHover" in self.js

    def test_has_on_unhover(self):
        """Tests that the _onUnhover handler is defined."""
        # Act & Assert
        assert "_onUnhover" in self.js

    def test_has_original_annotations(self):
        """Tests that originalAnnotations state is present."""
        # Act & Assert
        assert "originalAnnotations" in self.js

    def test_has_original_shapes(self):
        """Tests that originalShapes state is present."""
        # Act & Assert
        assert "originalShapes" in self.js

    def test_has_plotly_hover_listener(self):
        """Tests that a plotly_hover event listener is registered."""
        # Act & Assert
        assert "plotly_hover" in self.js

    def test_has_plotly_relayout_call(self):
        """Tests that Plotly.relayout is called within the JS."""
        # Act & Assert
        assert "Plotly.relayout" in self.js

    def test_has_plotly_unhover_listener(self):
        """Tests that a plotly_unhover event listener is registered."""
        # Act & Assert
        assert "plotly_unhover" in self.js

    def test_has_threshold_state(self):
        """Tests that thresholdState is defined in the JS."""
        # Act & Assert
        assert "thresholdState" in self.js

    def test_hover_line_clears_with_empty_array(self):
        """Tests that hover is cleared via Plotly.Fx.hover(gd, [])."""
        # Act & Assert
        assert "Plotly.Fx.hover(gd, [])" in self.js

    def test_init_stash_reads_layout_directly(self):
        """Tests that _initStash reads gd.layout.shapes."""
        # Act & Assert
        assert "_initStash" in self.js
        assert "gd.layout.shapes" in self.js

    def test_js_syntax_braces_balanced(self):
        """Tests that JS curly braces are balanced."""
        # Act & Assert
        assert self.js.count('{') == self.js.count('}')

    def test_js_syntax_parens_balanced(self):
        """Tests that JS parentheses are balanced."""
        # Act & Assert
        assert self.js.count('(') == self.js.count(')')

    def test_remove_threshold_onclick_uses_window_prefix(self):
        """Tests that removeThreshold onclick uses the window prefix."""
        # Act & Assert
        assert "window.removeThreshold(" in self.js

    def test_shape_color_is_red(self):
        """Tests that threshold shapes use the expected red color."""
        # Act & Assert
        assert "#e05c5c" in self.js

    def test_uses_meta_cross_highlight(self):
        """Tests that cross_highlight meta key is referenced in the JS."""
        # Act & Assert
        assert "cross_highlight" in self.js
