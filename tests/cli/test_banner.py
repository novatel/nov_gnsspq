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

Unit tests for nov_gnsspq/cli/banner.py and run_convert banner behaviour.
"""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nov_gnsspq.cli.banner import ConvertBannerInfo, print_convert_banner
from nov_gnsspq.cli.convert import run_convert


# pylint: disable=protected-access


def _make_info(**overrides) -> ConvertBannerInfo:
    """Builds a ConvertBannerInfo with sensible test defaults."""
    defaults = dict(
        input_path=Path("recordings/TEST_FILE_ONE.GPS"),
        output_path=Path("output_db"),
        file_size_mb=263.4,
        writer="Parallel",
        writer_selection="auto",
        workers=4,
        threshold_mb=50,
        edie_version="2.0.4",
        nov_gnsspq_version="1.0.0",
        message_count=-1,
        message_types=["BESTPOS", "RANGE", "GPSEPHEM"],
    )
    defaults.update(overrides)
    return ConvertBannerInfo(**defaults)


def _render(info: ConvertBannerInfo | None = None) -> str:
    """Renders a ConvertBannerInfo to a string via print_convert_banner."""
    buf = io.StringIO()
    print_convert_banner(info or _make_info(), stream=buf)
    return buf.getvalue()


class TestBannerContent:
    """Tests for the core content rendered by print_convert_banner."""

    def test_callout_present(self):
        """Tests that the one-time-cost callout line appears in the output."""
        # Act & Assert
        assert "this runs once" in _render()

    def test_convert_verb_present(self):
        """Tests that the CONVERT verb is present in the banner."""
        # Act & Assert
        assert "CONVERT" in _render()

    def test_edie_version_present(self):
        """Tests that the edie version string appears in the output."""
        # Act & Assert
        assert "edie 2.0.4" in _render()

    def test_input_filename_present(self):
        """Tests that the input filename appears in the banner."""
        # Act & Assert
        assert "TEST_FILE_ONE.GPS" in _render()

    def test_no_ansi_codes(self):
        """Tests that the rendered output contains no ANSI escape codes."""
        # Act & Assert
        assert "\033" not in _render()

    def test_output_name_present(self):
        """Tests that the output path name appears in the banner."""
        # Act & Assert
        assert "output_db" in _render()

    def test_tagline_present(self):
        """Tests that the product tagline appears in the banner."""
        # Act & Assert
        assert "decode once. query forever." in _render()

    def test_wordmark_fragment_present(self):
        """Tests that the ASCII wordmark fragment appears in the output."""
        # Arrange
        out = _render()
        # Act & Assert
        assert "_______" in out or "\\____" in out

    def test_writer_name_present(self):
        """Tests that the writer name appears in the banner."""
        # Act & Assert
        assert "Parallel" in _render()


class TestMessageCount:
    """Tests for the message count field in the banner."""

    def test_known_count_shown_formatted(self):
        """Tests that a known message count is rendered with thousands separator."""
        # Act & Assert
        assert "12,345" in _render(_make_info(message_count=12345))

    def test_unknown_count_shows_question_mark(self):
        """Tests that an unknown message count (-1) renders as '?'."""
        # Act & Assert
        assert "?" in _render(_make_info(message_count=-1))


class TestMessageTypes:
    """Tests for the message types field in the banner."""

    def test_empty_types_shows_dash(self):
        """Tests that an empty message type list renders a dash placeholder."""
        # Act & Assert
        assert "—" in _render(_make_info(message_types=[]))

    def test_overflow_shows_plus_more(self):
        """Tests that more than 4 message types renders a '+N more' suffix."""
        # Arrange
        types = ["A", "B", "C", "D", "E", "F"]
        # Act & Assert
        assert "+2 more" in _render(_make_info(message_types=types))

    def test_types_shown(self):
        """Tests that provided message type names appear in the output."""
        # Arrange
        out = _render(_make_info(message_types=["BESTPOS", "RANGE"]))
        # Act & Assert
        assert "BESTPOS" in out
        assert "RANGE" in out


class TestRunConvertNoBanner:
    """Tests for banner suppression and invocation in run_convert."""

    @patch("nov_gnsspq.cli.convert.print_convert_banner")
    @patch("nov_gnsspq.cli.convert.PqConverter")
    def test_no_banner_skips_print(self, mock_gen, mock_banner):
        """Tests that no_banner=True prevents print_convert_banner from being called."""
        # Arrange
        ctx = MagicMock()
        mock_gen.return_value.__enter__ = MagicMock(return_value=ctx)
        mock_gen.return_value.__exit__ = MagicMock(return_value=False)
        # Act
        run_convert("fake.GPS", "fake_out", no_banner=True)
        # Assert
        mock_banner.assert_not_called()

    @patch("nov_gnsspq.cli.convert.print_convert_banner")
    @patch("nov_gnsspq.cli.convert.PqConverter")
    @patch(
        "nov_gnsspq.cli.convert._auto_tune",
        return_value={
            "workers": 4,
            "chunk_size": 50_000,
            "est_messages": 500,
        })
    @patch("pathlib.Path.stat")
    def test_banner_called_by_default(
            self, mock_stat, mock_tune, mock_gen, mock_banner):
        """Tests that print_convert_banner is called once when no_banner is omitted."""
        # Arrange
        mock_stat.return_value.st_size = 10 * 1024 * 1024
        ctx = MagicMock()
        mock_gen.return_value.__enter__ = MagicMock(return_value=ctx)
        mock_gen.return_value.__exit__ = MagicMock(return_value=False)
        # Act
        run_convert("fake.GPS", "fake_out")
        # Assert
        mock_banner.assert_called_once()


class TestTruncation:
    """Tests for long filename truncation in the banner."""

    def test_long_input_filename_truncated(self):
        """Tests that filenames exceeding the display width are truncated with ellipsis."""
        # Arrange
        long = Path("a" * 50 + ".GPS")
        # Act & Assert
        assert "…" in _render(_make_info(input_path=long))

    def test_short_filename_not_truncated(self):
        """Tests that short filenames are rendered without truncation."""
        # Act & Assert
        assert "…" not in _render(_make_info(input_path=Path("short.GPS")))


class TestWriterSelectionLabel:
    """Tests for the writer-selection label rendered beside the writer name."""

    def test_auto_shown_when_auto_selected(self):
        """Tests that '(auto)' appears when writer_selection is 'auto'."""
        # Act & Assert
        assert "(auto)" in _render(_make_info(writer_selection="auto"))

    def test_no_label_when_selection_empty(self):
        """Tests that no selection label is shown when writer_selection is empty."""
        # Arrange
        out = _render(_make_info(writer_selection=""))
        # Act & Assert
        assert "(auto)" not in out
        assert "(user specified)" not in out

    def test_standard_writer_shown(self):
        """Tests that the Standard writer name appears when it is selected."""
        # Act & Assert
        assert "Standard" in _render(_make_info(writer="Standard"))

    def test_user_specified_shown_when_explicit(self):
        """Tests that '(user specified)' appears for an explicit writer selection."""
        # Act & Assert
        assert "(user specified)" in _render(
            _make_info(writer_selection="user specified"))


class TestPrintPlotBanner:
    """Tests for print_plot_banner."""

    def _render_plot(self, **kwargs) -> str:
        """Render a PlotBannerInfo to a string via print_plot_banner."""
        from nov_gnsspq.cli.banner import PlotBannerInfo, print_plot_banner
        defaults = dict(
            plots=["position", "skyview"],
            out_dir=None,
            html=False,
            nov_gnsspq_version="1.0.0",
        )
        defaults.update(kwargs)
        buf = io.StringIO()
        print_plot_banner(PlotBannerInfo(**defaults), stream=buf)
        return buf.getvalue()

    def test_plot_verb_present(self):
        """Verify PLOT label appears in the banner."""
        # Act & Assert
        assert "PLOT" in self._render_plot()

    def test_plot_names_appear(self):
        """Verify selected plot names appear in the banner."""
        # Act & Assert
        out = self._render_plot(plots=["position", "skyview"])
        assert "position" in out
        assert "skyview" in out

    def test_version_appears(self):
        """Verify the nov_gnsspq version appears in the banner."""
        # Act & Assert
        assert "1.0.0" in self._render_plot()

    def test_static_format_shown_when_not_html(self):
        """Verify PNG format label appears when html=False."""
        # Act & Assert
        assert "PNG" in self._render_plot(html=False)

    def test_html_format_shown_when_html_true(self):
        """Verify HTML format label appears when html=True."""
        # Act & Assert
        assert "HTML" in self._render_plot(html=True)

    def test_out_dir_shown_when_provided(self, tmp_path):
        """Verify the output path (possibly truncated) appears instead of 'interactive'."""
        # Arrange
        out_dir = tmp_path / "plots"
        out_dir.mkdir()
        # Act & Assert — the banner should not show "(interactive)" when an out_dir is set
        assert "interactive" not in self._render_plot(out_dir=out_dir)

    def test_interactive_shown_when_no_out_dir(self):
        """Verify 'interactive' label appears when no output directory given."""
        # Act & Assert
        assert "interactive" in self._render_plot(out_dir=None)

    def test_plot_count_shown(self):
        """Verify the number of selected plots appears in the banner."""
        # Act & Assert
        assert "3 selected" in self._render_plot(
            plots=["a", "b", "c"])

    def test_overflow_plots_shown_as_plus_more(self):
        """Verify more than 5 plots renders a '+N more' suffix."""
        # Act & Assert
        assert "+1 more" in self._render_plot(
            plots=["a", "b", "c", "d", "e", "f"])

    def test_dashboard_suffix_when_html_with_out_dir(self, tmp_path):
        """Verify dashboard.html suffix appears when html=True and out_dir set."""
        # Act & Assert
        assert "dashboard.html" in self._render_plot(
            html=True, out_dir=tmp_path)

    def test_png_suffix_when_not_html_with_out_dir(self, tmp_path):
        """Verify *.png suffix appears when html=False and out_dir set."""
        # Act & Assert
        assert "*.png" in self._render_plot(html=False, out_dir=tmp_path)
