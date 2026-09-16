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

Unit tests for the reconstruct CLI module.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nov_gnsspq.cli.reconstruct import main
from nov_gnsspq.reconstruct.types import BothResults, VerificationResult

sys.path.insert(0, str(Path(__file__).parent))

# pylint: disable=protected-access


class TestCLIArgParsing:
    """Tests for CLI argument parsing."""

    def test_calls_verify_with_correct_args(self, tmp_path):
        """Tests main passes --no-report flag correctly to verify."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "real.GPS"
        gps.write_bytes(b"dummy")
        mock_result = MagicMock()
        mock_result.mismatch_count = 0
        # Act & Assert
        with patch(
            "nov_gnsspq.cli.reconstruct.verify",
            return_value=mock_result,
        ) as mock_verify:
            main([str(db), str(gps), "--no-report"])
            mock_verify.assert_called_once()
            call_kwargs = mock_verify.call_args[1]
            assert call_kwargs["no_report"] is True

    def test_db_not_found_exits_code_2(self, tmp_path):
        """Tests main exits with code 2 when the database path does not exist."""
        # Arrange
        gps = tmp_path / "real.GPS"
        gps.write_bytes(b"dummy")
        # Act & Assert
        with pytest.raises(SystemExit) as exc:
            main(["nonexistent_db/", str(gps)])
        assert exc.value.code == 2

    def test_gps_not_found_exits_code_2(self, tmp_path):
        """Tests main exits with code 2 when the GPS file does not exist."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        # Act & Assert
        with pytest.raises(SystemExit) as exc:
            main([str(db), "nonexistent.GPS"])
        assert exc.value.code == 2

    def test_missing_args_exits(self):
        """Tests main raises SystemExit when no arguments are provided."""
        # Act & Assert
        with pytest.raises(SystemExit):
            main([])

    def test_nconvert_not_found_exits_code_2(self, tmp_path):
        """Tests main exits with code 2 when the nconvert path does not exist."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "real.GPS"
        gps.write_bytes(b"dummy")
        # Act & Assert
        with pytest.raises(SystemExit) as exc:
            main([str(db), str(gps), "--nconvert", "nonexistent_nconvert.exe"])
        assert exc.value.code == 2


class TestCLIMode:
    """Tests for CLI mode argument handling."""

    def test_default_mode_is_both(self, tmp_path):
        """Tests main uses 'both' as the default comparison mode."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "real.GPS"
        gps.write_bytes(b"dummy")
        mock_result = MagicMock()
        # Act & Assert
        with patch(
            "nov_gnsspq.cli.reconstruct.verify",
            return_value=mock_result,
        ) as mock_verify:
            main([str(db), str(gps), "--no-report"])
            call_kwargs = mock_verify.call_args[1]
            assert call_kwargs["mode"] == "both"

    def test_mode_and_nconvert_mutually_exclusive(self, tmp_path):
        """Tests main exits with code 2 when both --mode and --nconvert given."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "real.GPS"
        gps.write_bytes(b"dummy")
        nconvert = tmp_path / "nconvert.exe"
        nconvert.write_bytes(b"dummy")
        # Act & Assert
        with pytest.raises(SystemExit) as exc:
            main([
                str(db), str(gps),
                "--mode", "field",
                "--nconvert", str(nconvert),
            ])
        assert exc.value.code == 2

    def test_mode_binary_passed_to_verify(self, tmp_path):
        """Tests main passes mode='binary' to verify correctly."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "real.GPS"
        gps.write_bytes(b"dummy")
        mock_result = MagicMock()
        # Act & Assert
        with patch(
            "nov_gnsspq.cli.reconstruct.verify",
            return_value=mock_result,
        ) as mock_verify:
            main([str(db), str(gps), "--mode", "binary", "--no-report"])
            call_kwargs = mock_verify.call_args[1]
            assert call_kwargs["mode"] == "binary"

    def test_mode_field_passed_to_verify(self, tmp_path):
        """Tests main passes mode='field' to verify correctly."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "real.GPS"
        gps.write_bytes(b"dummy")
        mock_result = MagicMock()
        # Act & Assert
        with patch(
            "nov_gnsspq.cli.reconstruct.verify",
            return_value=mock_result,
        ) as mock_verify:
            main([str(db), str(gps), "--mode", "field", "--no-report"])
            call_kwargs = mock_verify.call_args[1]
            assert call_kwargs["mode"] == "field"

    def test_log_types_flag_passes_set_to_verify(self, tmp_path):
        """Tests --log-types passes a set of type names to verify."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "real.GPS"
        gps.write_bytes(b"dummy")
        mock_result = MagicMock()
        # Act & Assert
        with patch(
            "nov_gnsspq.cli.reconstruct.verify",
            return_value=mock_result,
        ) as mock_verify:
            main([str(db), str(gps), "--no-report",
                  "--log-types", "BESTPOS", "BESTVEL"])
            call_kwargs = mock_verify.call_args[1]
            assert call_kwargs["log_types"] == {"BESTPOS", "BESTVEL"}

    def test_log_types_omitted_passes_none_to_verify(self, tmp_path):
        """Tests that omitting --log-types passes log_types=None to verify."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "real.GPS"
        gps.write_bytes(b"dummy")
        mock_result = MagicMock()
        # Act & Assert
        with patch(
            "nov_gnsspq.cli.reconstruct.verify",
            return_value=mock_result,
        ) as mock_verify:
            main([str(db), str(gps), "--no-report"])
            call_kwargs = mock_verify.call_args[1]
            assert call_kwargs["log_types"] is None

class TestCLIEdieVersion:
    """Tests for the edie version fallback in the reconstruct CLI."""

    def test_package_not_found_sets_unknown_version(self, tmp_path):
        """Verify edie version shows 'unknown' when novatel_edie is not installed."""
        # Arrange
        import importlib.metadata
        db = tmp_path / "mydb"
        db.mkdir()
        gps = tmp_path / "real.GPS"
        gps.write_bytes(b"dummy")
        mock_result = MagicMock()
        # Act & Assert
        with patch(
            "nov_gnsspq.cli.reconstruct.verify",
            return_value=mock_result,
        ):
            with patch(
                "nov_gnsspq.cli.reconstruct.importlib.metadata.version",
                side_effect=importlib.metadata.PackageNotFoundError,
            ):
                with patch(
                    "nov_gnsspq.cli.reconstruct.print_reconstruct_banner"
                ) as mock_banner:
                    main([str(db), str(gps), "--no-report"])
                    banner_info = mock_banner.call_args[0][0]
                    assert banner_info.edie_version == "unknown"



class TestVerify:
    """Tests for the verify function integration via CLI paths."""

    def test_mode_binary_returns_verification_result(self, tmp_path):
        """Tests verify returns a VerificationResult for mode='binary'."""
        # Arrange
        from test_builder import _make_minimal_db
        from nov_gnsspq.reconstruct.builder import reconstruct as _reconstruct
        db = _make_minimal_db(tmp_path)
        orig = tmp_path / "orig.GPS"
        _reconstruct(db, orig)
        from nov_gnsspq.reconstruct import verify
        # Act
        result = verify(db, orig, mode="binary", no_report=True)
        # Assert
        assert isinstance(result, VerificationResult)

    def test_mode_both_returns_both_results(self, tmp_path):
        """Tests verify returns a BothResults for mode='both'."""
        # Arrange
        from test_builder import _make_minimal_db
        from nov_gnsspq.reconstruct.builder import reconstruct as _reconstruct
        db = _make_minimal_db(tmp_path)
        orig = tmp_path / "orig.GPS"
        _reconstruct(db, orig)
        from nov_gnsspq.reconstruct import verify
        # Act
        result = verify(db, orig, mode="both", no_report=True)
        # Assert
        assert isinstance(result, BothResults)
        assert isinstance(result.field, VerificationResult)
        assert isinstance(result.binary, VerificationResult)

    def test_mode_field_returns_verification_result(self, tmp_path):
        """Tests verify returns a VerificationResult for mode='field'."""
        # Arrange
        from test_builder import _make_minimal_db
        from nov_gnsspq.reconstruct.builder import reconstruct as _reconstruct
        db = _make_minimal_db(tmp_path)
        orig = tmp_path / "orig.GPS"
        _reconstruct(db, orig)
        from nov_gnsspq.reconstruct import verify
        # Act
        result = verify(db, orig, mode="field", no_report=True)
        # Assert
        assert isinstance(result, VerificationResult)
