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

Unit tests for nov_gnsspq.reconstruct.verify().
"""
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from nov_gnsspq.reconstruct import verify
from nov_gnsspq.reconstruct.types import BothResults, VerificationResult


# pylint: disable=protected-access

_MODULE = "nov_gnsspq.reconstruct"


def _make_verification_result() -> VerificationResult:
    """Build a minimal VerificationResult for use in verify() tests."""
    return VerificationResult(
        total_messages=10,
        verified_count=10,
        not_verified_message_count=0,
        mismatch_count=0,
        per_type={},
    )


class TestVerifyField:
    """Tests for verify() in field mode."""

    @patch(f"{_MODULE}.write_html_report")
    @patch(f"{_MODULE}.print_console_summary")
    @patch(f"{_MODULE}.compare_field_level")
    @patch(f"{_MODULE}.reconstruct")
    def test_mode_field_returns_verification_result(
            self, mock_recon, mock_cfl, mock_summary, mock_report, tmp_path):
        """Verify verify() returns a VerificationResult for mode='field'."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "orig.GPS"
        gps.write_bytes(b"dummy")
        mock_cfl.return_value = _make_verification_result()
        # Act
        result = verify(db, gps, mode="field", no_report=True)
        # Assert
        assert isinstance(result, VerificationResult)

    @patch(f"{_MODULE}.write_html_report")
    @patch(f"{_MODULE}.print_console_summary")
    @patch(f"{_MODULE}.compare_field_level")
    @patch(f"{_MODULE}.reconstruct")
    def test_mode_field_calls_compare_field_level(
            self, mock_recon, mock_cfl, mock_summary, mock_report, tmp_path):
        """Verify verify() calls compare_field_level in field mode."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "orig.GPS"
        gps.write_bytes(b"dummy")
        mock_cfl.return_value = _make_verification_result()
        # Act
        verify(db, gps, mode="field", no_report=True)
        # Assert
        mock_cfl.assert_called_once()

    @patch(f"{_MODULE}.write_html_report")
    @patch(f"{_MODULE}.print_console_summary")
    @patch(f"{_MODULE}.compare_field_level")
    @patch(f"{_MODULE}.reconstruct")
    def test_mode_field_writes_report_by_default(
            self, mock_recon, mock_cfl, mock_summary, mock_report, tmp_path):
        """Verify verify() writes the HTML report unless no_report=True."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "orig.GPS"
        gps.write_bytes(b"dummy")
        mock_cfl.return_value = _make_verification_result()
        # Act
        verify(db, gps, mode="field")
        # Assert
        mock_report.assert_called_once()

    @patch(f"{_MODULE}.write_html_report")
    @patch(f"{_MODULE}.print_console_summary")
    @patch(f"{_MODULE}.compare_field_level")
    @patch(f"{_MODULE}.reconstruct")
    def test_mode_field_no_report_skips_html(
            self, mock_recon, mock_cfl, mock_summary, mock_report, tmp_path):
        """Verify verify() skips HTML report when no_report=True."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "orig.GPS"
        gps.write_bytes(b"dummy")
        mock_cfl.return_value = _make_verification_result()
        # Act
        verify(db, gps, mode="field", no_report=True)
        # Assert
        mock_report.assert_not_called()


class TestVerifyBinary:
    """Tests for verify() in binary mode."""

    @patch(f"{_MODULE}.write_html_report")
    @patch(f"{_MODULE}.print_console_summary")
    @patch(f"{_MODULE}.compare_binary")
    @patch(f"{_MODULE}.reconstruct")
    def test_mode_binary_returns_verification_result(
            self, mock_recon, mock_cb, mock_summary, mock_report, tmp_path):
        """Verify verify() returns a VerificationResult for mode='binary'."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "orig.GPS"
        gps.write_bytes(b"dummy")
        mock_cb.return_value = _make_verification_result()
        # Act
        result = verify(db, gps, mode="binary", no_report=True)
        # Assert
        assert isinstance(result, VerificationResult)

    @patch(f"{_MODULE}.write_html_report")
    @patch(f"{_MODULE}.print_console_summary")
    @patch(f"{_MODULE}.compare_binary")
    @patch(f"{_MODULE}.reconstruct")
    def test_mode_binary_calls_compare_binary(
            self, mock_recon, mock_cb, mock_summary, mock_report, tmp_path):
        """Verify verify() calls compare_binary in binary mode."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "orig.GPS"
        gps.write_bytes(b"dummy")
        mock_cb.return_value = _make_verification_result()
        # Act
        verify(db, gps, mode="binary", no_report=True)
        # Assert
        mock_cb.assert_called_once()

    @patch(f"{_MODULE}.write_html_report")
    @patch(f"{_MODULE}.print_console_summary")
    @patch(f"{_MODULE}.compare_binary")
    @patch(f"{_MODULE}.reconstruct")
    def test_mode_binary_no_report_skips_html(
            self, mock_recon, mock_cb, mock_summary, mock_report, tmp_path):
        """Verify verify() skips HTML report when no_report=True in binary mode."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "orig.GPS"
        gps.write_bytes(b"dummy")
        mock_cb.return_value = _make_verification_result()
        # Act
        verify(db, gps, mode="binary", no_report=True)
        # Assert
        mock_report.assert_not_called()

    @patch(f"{_MODULE}.write_html_report")
    @patch(f"{_MODULE}.print_console_summary")
    @patch(f"{_MODULE}.compare_binary")
    @patch(f"{_MODULE}.reconstruct")
    def test_mode_binary_writes_report_by_default(
            self, mock_recon, mock_cb, mock_summary, mock_report, tmp_path):
        """Verify verify() calls write_html_report by default in binary mode."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "orig.GPS"
        gps.write_bytes(b"dummy")
        mock_cb.return_value = _make_verification_result()
        # Act
        verify(db, gps, mode="binary")
        # Assert
        mock_report.assert_called_once()


class TestVerifyBoth:
    """Tests for verify() in both mode."""

    @patch(f"{_MODULE}.write_html_report")
    @patch(f"{_MODULE}.print_console_summary")
    @patch(f"{_MODULE}.compare_binary")
    @patch(f"{_MODULE}.compare_field_level")
    @patch(f"{_MODULE}.reconstruct")
    def test_mode_both_returns_both_results(
            self, mock_recon, mock_cfl, mock_cb, mock_summary, mock_report,
            tmp_path):
        """Verify verify() returns a BothResults for mode='both'."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "orig.GPS"
        gps.write_bytes(b"dummy")
        mock_cfl.return_value = _make_verification_result()
        mock_cb.return_value = _make_verification_result()
        # Act
        result = verify(db, gps, mode="both", no_report=True)
        # Assert
        assert isinstance(result, BothResults)
        assert isinstance(result.field, VerificationResult)
        assert isinstance(result.binary, VerificationResult)

    @patch(f"{_MODULE}.write_html_report")
    @patch(f"{_MODULE}.print_console_summary")
    @patch(f"{_MODULE}.compare_binary")
    @patch(f"{_MODULE}.compare_field_level")
    @patch(f"{_MODULE}.reconstruct")
    def test_mode_both_writes_two_reports(
            self, mock_recon, mock_cfl, mock_cb, mock_summary, mock_report,
            tmp_path):
        """Verify verify() writes two HTML reports in both mode."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "orig.GPS"
        gps.write_bytes(b"dummy")
        mock_cfl.return_value = _make_verification_result()
        mock_cb.return_value = _make_verification_result()
        # Act
        verify(db, gps, mode="both")
        # Assert
        assert mock_report.call_count == 2

    @patch(f"{_MODULE}.write_html_report")
    @patch(f"{_MODULE}.print_console_summary")
    @patch(f"{_MODULE}.compare_binary")
    @patch(f"{_MODULE}.compare_field_level")
    @patch(f"{_MODULE}.reconstruct")
    def test_mode_both_no_report_skips_html(
            self, mock_recon, mock_cfl, mock_cb, mock_summary, mock_report,
            tmp_path):
        """Verify verify() skips HTML reports when no_report=True in both mode."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "orig.GPS"
        gps.write_bytes(b"dummy")
        mock_cfl.return_value = _make_verification_result()
        mock_cb.return_value = _make_verification_result()
        # Act
        verify(db, gps, mode="both", no_report=True)
        # Assert
        mock_report.assert_not_called()


class TestVerifyDefaultPaths:
    """Tests for verify() default path handling."""

    @patch(f"{_MODULE}.write_html_report")
    @patch(f"{_MODULE}.print_console_summary")
    @patch(f"{_MODULE}.compare_field_level")
    @patch(f"{_MODULE}.reconstruct")
    def test_default_output_gps_in_cwd(
            self, mock_recon, mock_cfl, mock_summary, mock_report, tmp_path):
        """Verify verify() uses reconstructed.GPS in cwd when output_gps is None."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "orig.GPS"
        gps.write_bytes(b"dummy")
        mock_cfl.return_value = _make_verification_result()
        # Act
        verify(db, gps, mode="field", no_report=True)
        # Assert — reconstruct called with a Path ending in reconstructed.GPS
        recon_call_path = mock_recon.call_args[0][1]
        assert Path(recon_call_path).name == "reconstructed.GPS"

    @patch(f"{_MODULE}.write_html_report")
    @patch(f"{_MODULE}.print_console_summary")
    @patch(f"{_MODULE}.compare_field_level")
    @patch(f"{_MODULE}.reconstruct")
    def test_default_report_path_in_cwd(
            self, mock_recon, mock_cfl, mock_summary, mock_report, tmp_path):
        """Verify verify() uses reconstruction_report.html in cwd when report is None."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "orig.GPS"
        gps.write_bytes(b"dummy")
        mock_cfl.return_value = _make_verification_result()
        # Act
        verify(db, gps, mode="field")
        # Assert
        report_path = mock_report.call_args[0][1]
        assert "reconstruction_report" in str(report_path)
