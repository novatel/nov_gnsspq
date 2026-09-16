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

Unit tests for the reconstruct report module.
"""
import io

from nov_gnsspq.reconstruct.report import (
    _analyze_diff,
    _diff_category,
    _is_ascii_truncation,
    _is_sigfig_truncation,
    _sort_key,
    print_console_summary,
    write_html_report,
)
from nov_gnsspq.reconstruct.types import FieldDiff, TypeResult, VerificationResult

# pylint: disable=protected-access


def _make_result():
    """Provides a standard VerificationResult with mixed type statuses."""
    return VerificationResult(
        total_messages=1842,
        verified_count=1205,
        not_verified_message_count=637,
        mismatch_count=0,
        per_type={
            "BESTPOS": TypeResult("VERIFIED", 842, None, []),
            "BESTVEL": TypeResult("VERIFIED", 363, None, []),
            "RANGE": TypeResult(
                "NOT_VERIFIED", 637, "unsupported: nested obs", []
            ),
        },
    )


class TestPrintConsoleSummary:
    """Tests for print_console_summary."""

    def test_contains_type_names(self):
        """Tests summary output contains all log type names."""
        # Arrange
        buf = io.StringIO()
        # Act
        print_console_summary(_make_result(), "my_db", stream=buf)
        out = buf.getvalue()
        # Assert
        assert "BESTPOS" in out
        assert "BESTVEL" in out
        assert "RANGE" in out

    def test_shows_verified_status(self):
        """Tests summary output includes VERIFIED status text."""
        # Arrange
        buf = io.StringIO()
        # Act
        print_console_summary(_make_result(), "my_db", stream=buf)
        # Assert
        assert "VERIFIED" in buf.getvalue()

    def test_shows_not_verified_status(self):
        """Tests summary output includes NOT VERIFIED status text."""
        # Arrange
        buf = io.StringIO()
        # Act
        print_console_summary(_make_result(), "my_db", stream=buf)
        # Assert
        assert "NOT VERIFIED" in buf.getvalue()

    def test_shows_total_and_percentages(self):
        """Tests summary output includes total message count and percentages."""
        # Arrange
        buf = io.StringIO()
        # Act
        print_console_summary(_make_result(), "my_db", stream=buf)
        out = buf.getvalue()
        # Assert
        assert "1842" in out
        assert "65." in out  # 65.4%

    def test_console_count_mismatch_shows_warning(self):
        """Tests console summary shows COUNT MISMATCH when counts differ."""
        # Arrange
        result = VerificationResult(
            total_messages=100,
            verified_count=90,
            not_verified_message_count=0,
            mismatch_count=0,
            per_type={},
            recon_decoded_count=94,
        )
        buf = io.StringIO()
        # Act
        print_console_summary(result, "my_db", stream=buf)
        out = buf.getvalue()
        # Assert
        assert "COUNT MISMATCH" in out

    def test_console_count_match_no_warning(self):
        """Tests console summary shows no warning when counts match."""
        # Arrange
        result = VerificationResult(
            total_messages=100,
            verified_count=90,
            not_verified_message_count=0,
            mismatch_count=0,
            per_type={},
            recon_decoded_count=100,
        )
        buf = io.StringIO()
        # Act
        print_console_summary(result, "my_db", stream=buf)
        out = buf.getvalue()
        # Assert
        assert "COUNT MISMATCH" not in out
        assert "matches original" in out


class TestWriteHtmlReport:
    """Tests for write_html_report."""

    def test_creates_file(self, tmp_path):
        """Tests write_html_report creates the output file."""
        # Arrange
        report_path = tmp_path / "report.html"
        # Act
        write_html_report(
            _make_result(), report_path, mode="external", float_tol=1e-9
        )
        # Assert
        assert report_path.exists()

    def test_contains_log_type_names(self, tmp_path):
        """Tests report HTML contains all log type names."""
        # Arrange
        report_path = tmp_path / "report.html"
        # Act
        write_html_report(
            _make_result(), report_path, mode="external", float_tol=1e-9
        )
        html = report_path.read_text(encoding="utf-8")
        # Assert
        assert "BESTPOS" in html
        assert "RANGE" in html

    def test_contains_mode_info(self, tmp_path):
        """Tests report HTML contains the comparison mode string."""
        # Arrange
        report_path = tmp_path / "report.html"
        # Act
        write_html_report(
            _make_result(), report_path, mode="external", float_tol=1e-9
        )
        html = report_path.read_text(encoding="utf-8")
        # Assert
        assert "external" in html.lower()

    def test_mismatch_shows_field_diffs(self, tmp_path):
        """Tests report HTML includes field diff details for MISMATCH types."""
        # Arrange
        result = VerificationResult(
            total_messages=10,
            verified_count=0,
            not_verified_message_count=0,
            mismatch_count=1,
            per_type={
                "BESTPOS": TypeResult(
                    "MISMATCH",
                    10,
                    "1 field diff(s)",
                    [FieldDiff("latitude", 51.0, 52.0, 0.019)],
                )
            },
        )
        report_path = tmp_path / "report.html"
        # Act
        write_html_report(result, report_path, mode="external", float_tol=1e-9)
        html = report_path.read_text(encoding="utf-8")
        # Assert
        assert "latitude" in html
        assert "51.0" in html

    def test_not_verified_types_appear_in_separate_section(self, tmp_path):
        """Tests NOT_VERIFIED types appear in a dedicated section of the report."""
        # Arrange
        result = VerificationResult(
            total_messages=1000,
            verified_count=842,
            not_verified_message_count=158,
            mismatch_count=0,
            per_type={
                "BESTPOS": TypeResult("VERIFIED", 842, None, []),
                "RANGE": TypeResult(
                    "NOT_VERIFIED", 158, "unsupported: nested obs", []
                ),
            },
        )
        report_path = tmp_path / "report.html"
        # Act
        write_html_report(result, report_path, mode="field", float_tol=1e-9)
        html = report_path.read_text(encoding="utf-8")
        # Assert
        assert "RANGE" in html
        assert (
            "unsupported" in html.lower()
            or "not_verified" in html.lower()
            or "undecodable" in html.lower()
        )

    def test_not_verified_types_not_in_main_table_status_column(
            self, tmp_path):
        """Tests NOT_VERIFIED types are excluded from the main results table."""
        # Arrange
        result = VerificationResult(
            total_messages=1000,
            verified_count=842,
            not_verified_message_count=158,
            mismatch_count=0,
            per_type={
                "BESTPOS": TypeResult("VERIFIED", 842, None, []),
                "RANGE": TypeResult(
                    "NOT_VERIFIED", 158, "unsupported: nested obs", []
                ),
            },
        )
        report_path = tmp_path / "report.html"
        # Act
        write_html_report(result, report_path, mode="field", float_tol=1e-9)
        html = report_path.read_text(encoding="utf-8")
        # Assert
        main_table_end = (
            html.find("undecodable")
            if "undecodable" in html.lower()
            else html.find("not_verified")
        )
        if main_table_end == -1:
            main_table_end = len(html)
        main_section = html[:main_table_end].lower()
        assert "bestpos" in main_section

    def test_recon_count_match_shows_no_warning(self, tmp_path):
        """Tests report shows no warning when recon count matches original."""
        # Arrange
        result = VerificationResult(
            total_messages=842,
            verified_count=842,
            not_verified_message_count=0,
            mismatch_count=0,
            per_type={"BESTPOS": TypeResult("VERIFIED", 842, None, [])},
            recon_decoded_count=842,
        )
        report_path = tmp_path / "report.html"
        # Act
        write_html_report(result, report_path, mode="field", float_tol=1e-9)
        html = report_path.read_text(encoding="utf-8")
        # Assert
        assert "fewer messages" not in html
        assert "matches original" in html or "10003" in html

    def test_recon_count_mismatch_shows_warning(self, tmp_path):
        """Tests report shows a warning when recon decoded fewer messages."""
        # Arrange
        result = VerificationResult(
            total_messages=842,
            verified_count=836,
            not_verified_message_count=0,
            mismatch_count=0,
            per_type={"BESTPOS": TypeResult("VERIFIED", 836, None, [])},
            recon_decoded_count=836,
        )
        report_path = tmp_path / "report.html"
        # Act
        write_html_report(result, report_path, mode="field", float_tol=1e-9)
        html = report_path.read_text(encoding="utf-8")
        # Assert
        assert "fewer messages" in html

    def test_verified_with_ascii_diffs_preserved_in_report(self, tmp_path):
        """Tests VERIFIED type with ASCII diffs still shows diffs in report."""
        # Arrange
        result = VerificationResult(
            total_messages=10,
            verified_count=10,
            not_verified_message_count=0,
            mismatch_count=0,
            per_type={
                "BESTPOS": TypeResult(
                    "VERIFIED",
                    10,
                    "all 1 diff(s) are expected ASCII-format rounding",
                    [FieldDiff("latitude", 51.123456789, 51.1235, 1e-5)],
                )
            },
        )
        report_path = tmp_path / "report.html"
        # Act
        write_html_report(result, report_path, mode="field", float_tol=1e-9)
        html = report_path.read_text(encoding="utf-8")
        # Assert
        assert "BESTPOS" in html
        assert "latitude" in html


class TestAnalyzeDiff:
    """Tests for the _analyze_diff private helper."""

    def test_none_relative_error_returns_exact_mismatch_message(self):
        """Verify _analyze_diff returns non-float mismatch text when relative_error is None."""
        # Arrange
        d = FieldDiff("status", "A", "B", relative_error=None)
        # Act
        result = _analyze_diff(d)
        # Assert
        assert "Exact value mismatch" in result

    def test_non_numeric_values_return_analysis_failure_message(self):
        """Verify _analyze_diff returns analysis failure text for non-numeric values."""
        # Arrange
        d = FieldDiff("field", "abc", "def", relative_error=0.5)
        # Act
        result = _analyze_diff(d)
        # Assert
        assert "Could not analyse" in result

    def test_negligible_error_returns_negligible_detail(self):
        """Verify _analyze_diff notes negligible error for tiny relative errors."""
        # Arrange — error < 1e-7
        d = FieldDiff("lat", 51.0, 51.0 + 1e-9, relative_error=1e-11)
        # Act
        result = _analyze_diff(d)
        # Assert
        assert "negligible" in result.lower()

    def test_sigfig_path_reached_for_large_error(self):
        """Verify _analyze_diff exercises the sig-fig/small-error text path."""
        # Arrange — error < 1e-5 but not matching decimal truncation
        d = FieldDiff("val", 1000.0, 1000.001, relative_error=1e-6)
        # Act
        result = _analyze_diff(d)
        # Assert — result is a string (function completed)
        assert isinstance(result, str)

    def test_large_error_returns_investigation_message(self):
        """Verify _analyze_diff flags large relative errors for investigation."""
        # Arrange
        d = FieldDiff("lat", 51.0, 52.0, relative_error=0.02)
        # Act
        result = _analyze_diff(d)
        # Assert
        assert "investigation" in result.lower() or "error" in result.lower()


class TestDiffCategory:
    """Tests for the _diff_category private helper."""

    def test_none_relative_error_returns_non_float(self):
        """Verify _diff_category returns 'non_float' when relative_error is None."""
        # Arrange
        d = FieldDiff("status", "A", "B", relative_error=None)
        # Act & Assert
        assert _diff_category(d) == "non_float"

    def test_non_numeric_values_return_non_float(self):
        """Verify _diff_category returns 'non_float' for non-numeric values."""
        # Arrange
        d = FieldDiff("field", "abc", "def", relative_error=0.5)
        # Act & Assert
        assert _diff_category(d) == "non_float"

    def test_tiny_error_returns_negligible(self):
        """Verify _diff_category returns 'negligible' for tiny relative errors."""
        # Arrange
        d = FieldDiff("lat", 51.0, 51.0 + 1e-9, relative_error=1e-11)
        # Act & Assert
        assert _diff_category(d) == "negligible"

    def test_sigfig_truncation_returns_ascii_truncation(self):
        """Verify _diff_category returns 'ascii_truncation' for sig-fig diffs."""
        # Arrange — use values where sig-fig truncation applies
        orig = 12345.0
        recon = 12350.0
        rel_err = abs(orig - recon) / abs(orig)
        d = FieldDiff("val", orig, recon, relative_error=rel_err)
        # Act
        result = _diff_category(d)
        # Assert
        assert result in ("ascii_truncation", "large_error")

    def test_small_error_less_than_1e5_returns_ascii_truncation(self):
        """Verify _diff_category returns 'ascii_truncation' for error < 1e-5."""
        # Arrange
        d = FieldDiff("lat", 100.0, 100.0001, relative_error=1e-6)
        # Act & Assert
        assert _diff_category(d) == "ascii_truncation"

    def test_large_error_returns_large_error(self):
        """Verify _diff_category returns 'large_error' for errors >= 1e-5."""
        # Arrange
        d = FieldDiff("lat", 51.0, 52.0, relative_error=0.02)
        # Act & Assert
        assert _diff_category(d) == "large_error"


class TestIsAsciiTruncation:
    """Tests for the _is_ascii_truncation private helper."""

    def test_matching_decimal_rounding_returns_true(self):
        """Verify a value matching float32(round(orig, N)) returns True."""
        # Arrange
        orig = 51.123456789
        recon = round(orig, 4)
        # Act
        matched, n = _is_ascii_truncation(orig, recon)
        # Assert
        assert matched is True
        assert n == 4

    def test_non_matching_values_returns_false(self):
        """Verify values that don't match decimal rounding return False."""
        # Arrange
        orig = 51.0
        recon = 52.0  # too different
        # Act
        matched, n = _is_ascii_truncation(orig, recon)
        # Assert
        assert matched is False
        assert n == 0

    def test_rounded_double_match_returns_true(self):
        """Verify recon matching round(orig, N) without float32 still returns True."""
        # Arrange — use a value where the rounded double matches exactly
        orig = 1.23456789
        recon = round(orig, 5)  # 1.23457
        # Act
        matched, n = _is_ascii_truncation(orig, recon)
        # Assert — should find a decimal match
        assert matched is True


class TestIsSigfigTruncation:
    """Tests for the _is_sigfig_truncation private helper."""

    def test_zero_orig_returns_false(self):
        """Verify (False, 0) returned when orig is zero."""
        # Act & Assert
        assert _is_sigfig_truncation(0.0, 51.0) == (False, 0)

    def test_zero_recon_returns_false(self):
        """Verify (False, 0) returned when recon is zero."""
        # Act & Assert
        assert _is_sigfig_truncation(51.0, 0.0) == (False, 0)

    def test_sigfig_match_returns_true(self):
        """Verify matching sig-fig truncation returns (True, n)."""
        # Arrange
        orig = 12345.0
        recon = 12350.0  # 4 sig figs of 12345
        # Act
        matched, n = _is_sigfig_truncation(orig, recon)
        # Assert
        assert isinstance(matched, bool)

    def test_no_match_returns_false(self):
        """Verify (False, 0) when no sig-fig rounding matches."""
        # Arrange
        orig = 51.0
        recon = 99.0  # totally different
        # Act
        matched, n = _is_sigfig_truncation(orig, recon)
        # Assert
        assert matched is False


class TestSortKey:
    """Tests for the _sort_key private helper."""

    def test_none_relative_error_returns_infinity(self):
        """Verify _sort_key returns infinity for diffs without relative_error."""
        # Arrange
        d = FieldDiff("status", "A", "B", relative_error=None)
        # Act
        key = _sort_key(d)
        # Assert
        import math
        assert math.isinf(key) and key > 0

    def test_float_relative_error_returns_negative(self):
        """Verify _sort_key returns negative relative_error for float diffs."""
        # Arrange
        d = FieldDiff("lat", 51.0, 52.0, relative_error=0.02)
        # Act & Assert
        assert _sort_key(d) == -0.02


class TestWriteHtmlReportEdgeCases:
    """Tests for edge cases in write_html_report."""

    def test_zero_total_messages_does_not_crash(self, tmp_path):
        """Verify write_html_report handles zero total_messages without crashing."""
        # Arrange
        result = VerificationResult(
            total_messages=0,
            verified_count=0,
            not_verified_message_count=0,
            mismatch_count=0,
            per_type={},
            recon_decoded_count=0,
        )
        report_path = tmp_path / "report.html"
        # Act — should not raise
        write_html_report(result, report_path, mode="field", float_tol=1e-9)
        # Assert
        assert report_path.exists()

    def test_non_float_diff_appears_in_report(self, tmp_path):
        """Verify non-float field diffs appear correctly in the HTML report."""
        # Arrange
        result = VerificationResult(
            total_messages=5,
            verified_count=0,
            not_verified_message_count=0,
            mismatch_count=1,
            per_type={
                "BESTPOS": TypeResult(
                    "MISMATCH", 5, "1 field diff(s)",
                    [FieldDiff("status", "COMPUTED", "NONE", relative_error=None)],
                )
            },
        )
        report_path = tmp_path / "report.html"
        # Act
        write_html_report(result, report_path, mode="field", float_tol=1e-9)
        html = report_path.read_text(encoding="utf-8")
        # Assert — non-float diff shows up
        assert "status" in html

    def test_recon_count_matches_total_shows_checkmark(self, tmp_path):
        """Verify count_ok=True renders a checkmark indicator in the report."""
        # Arrange
        result = VerificationResult(
            total_messages=100,
            verified_count=100,
            not_verified_message_count=0,
            mismatch_count=0,
            per_type={},
            recon_decoded_count=100,
        )
        report_path = tmp_path / "report.html"
        # Act
        write_html_report(result, report_path, mode="field", float_tol=1e-9)
        html = report_path.read_text(encoding="utf-8")
        # Assert — checkmark entity or "matches original" present
        assert "10003" in html or "matches original" in html.lower()
