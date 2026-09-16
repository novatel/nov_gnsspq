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

Unit tests for archive behaviour in run_convert() and the
--archive / --zip CLI flags.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nov_gnsspq.cli.convert import main, run_convert


_REPO_ROOT = Path(__file__).resolve().parents[2]
# The committed sample recording. NOV_GNSSPQ_TEST_GPS overrides it, matching
# test/integration/ and test/writer/test_progress.py.
_SAMPLE_GPS = Path(os.environ.get(
    "NOV_GNSSPQ_TEST_GPS",
    str(_REPO_ROOT / "test" / "resources" / "sample.GPS"),
))


def _mocked_run_convert(output_path, **kwargs):
    """Calls run_convert with PqConverter and stat mocked out."""
    with patch("nov_gnsspq.cli.convert.PqConverter") as mock_gen:
        ctx = MagicMock()
        mock_gen.return_value.__enter__ = MagicMock(return_value=ctx)
        mock_gen.return_value.__exit__ = MagicMock(return_value=False)
        with patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value.st_size = 1024
            run_convert(
                "fake.GPS",
                str(output_path),
                no_banner=True,
                **kwargs)


class TestCliArchiveFlag:
    """Tests for the --archive / --zip CLI flag wiring in main()."""

    def test_no_archive_flag_defaults_to_false(self, tmp_path):
        """Tests that omitting archive flags passes archive=False."""
        # Arrange
        gps = tmp_path / "log.GPS"
        gps.write_bytes(b"x")
        # Act & Assert
        with patch("nov_gnsspq.cli.convert.run_convert") as mock_rc:
            main([str(gps), "-o", str(tmp_path / "out")])
            _, kwargs = mock_rc.call_args
            assert kwargs["archive"] is False

    def test_archive_flag_passes_archive_true(self, tmp_path):
        """Tests that --archive wires archive=True into run_convert."""
        # Arrange
        gps = tmp_path / "log.GPS"
        gps.write_bytes(b"x")
        # Act & Assert
        with patch("nov_gnsspq.cli.convert.run_convert") as mock_rc:
            main([str(gps), "-o", str(tmp_path / "out"), "--archive"])
            _, kwargs = mock_rc.call_args
            assert kwargs["archive"] is True

    def test_zip_flag_is_alias_for_archive(self, tmp_path):
        """Tests that --zip is an alias that wires archive=True."""
        # Arrange
        gps = tmp_path / "log.GPS"
        gps.write_bytes(b"x")
        # Act & Assert
        with patch("nov_gnsspq.cli.convert.run_convert") as mock_rc:
            main([str(gps), "-o", str(tmp_path / "out"), "--zip"])
            _, kwargs = mock_rc.call_args
            assert kwargs["archive"] is True


class TestRunConvertArchive:
    """Tests for the archive parameter of run_convert()."""

    def test_archive_failure_raises_and_does_not_swallow_error(self, tmp_path):
        """Tests that an OSError from zip_database propagates out of run_convert."""
        # Act & Assert
        with patch(
                "nov_gnsspq.cli.convert.zip_database",
                side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                _mocked_run_convert(tmp_path / "out", archive=True)

    def test_archive_not_called_when_generator_raises(self, tmp_path):
        """Tests that zip_database is not called if the conversion itself fails."""
        # Act & Assert
        with patch("nov_gnsspq.cli.convert.PqConverter") as mock_gen:
            mock_gen.return_value.__enter__ = MagicMock(
                side_effect=RuntimeError("boom"))
            with patch("nov_gnsspq.cli.convert.zip_database") as mock_zip:
                with pytest.raises(RuntimeError):
                    run_convert(
                        "fake.GPS",
                        str(tmp_path / "out"),
                        no_banner=True,
                        archive=True)
                mock_zip.assert_not_called()

    def test_archive_false_does_not_call_zip_database(self, tmp_path):
        """Tests that zip_database is not called when archive=False."""
        # Act & Assert
        with patch("nov_gnsspq.cli.convert.zip_database") as mock_zip:
            _mocked_run_convert(tmp_path / "out", archive=False)
            mock_zip.assert_not_called()

    def test_archive_true_calls_zip_database_with_output_path(self, tmp_path):
        """Tests that zip_database is called with the output Path when archive=True."""
        # Arrange
        out = tmp_path / "out"
        # Act & Assert
        with patch("nov_gnsspq.cli.convert.zip_database") as mock_zip:
            _mocked_run_convert(out, archive=True)
            mock_zip.assert_called_once_with(out)


class TestMainInputValidation:
    """Tests for input path validation in the convert CLI main() function."""

    def test_missing_input_file_exits_with_error(self, tmp_path):
        """Verify main() exits with an error when the input file does not exist."""
        # Act & Assert
        with pytest.raises(SystemExit) as exc:
            main(["nonexistent_input.GPS", "-o", str(tmp_path / "out")])
        assert exc.value.code != 0

    def test_parallel_flag_passes_parallel_true(self, tmp_path):
        """Verify --parallel sets parallel=True in run_convert."""
        # Arrange
        gps = tmp_path / "log.GPS"
        gps.write_bytes(b"x")
        # Act & Assert
        with patch("nov_gnsspq.cli.convert.run_convert") as mock_rc:
            main([str(gps), "-o", str(tmp_path / "out"), "--parallel"])
            _, kwargs = mock_rc.call_args
            assert kwargs["parallel"] is True

    def test_no_parallel_flag_passes_parallel_false(self, tmp_path):
        """Verify --no-parallel sets parallel=False in run_convert."""
        # Arrange
        gps = tmp_path / "log.GPS"
        gps.write_bytes(b"x")
        # Act & Assert
        with patch("nov_gnsspq.cli.convert.run_convert") as mock_rc:
            main([str(gps), "-o", str(tmp_path / "out"), "--no-parallel"])
            _, kwargs = mock_rc.call_args
            assert kwargs["parallel"] is False

    def test_overwrite_flag_passes_overwrite_true(self, tmp_path):
        """Verify --overwrite sets overwrite=True in run_convert."""
        # Arrange
        gps = tmp_path / "log.GPS"
        gps.write_bytes(b"x")
        # Act & Assert
        with patch("nov_gnsspq.cli.convert.run_convert") as mock_rc:
            main([str(gps), "-o", str(tmp_path / "out"), "--overwrite"])
            _, kwargs = mock_rc.call_args
            assert kwargs.get("overwrite") is True

    def test_database_exists_error_exits_with_parser_error(self, tmp_path):
        """Verify DatabaseExistsError from run_convert causes parser.error exit."""
        # Arrange
        from nov_gnsspq.exceptions import DatabaseExistsError
        gps = tmp_path / "log.GPS"
        gps.write_bytes(b"x")
        # Act & Assert
        with patch(
            "nov_gnsspq.cli.convert.run_convert",
            side_effect=DatabaseExistsError("already exists"),
        ):
            with pytest.raises(SystemExit) as exc:
                main([str(gps), "-o", str(tmp_path / "out")])
        assert exc.value.code != 0


class TestRunConvertBannerEdgeCases:
    """Tests for edge cases in run_convert banner path."""

    @patch("nov_gnsspq.cli.convert.PqConverter")
    @patch("nov_gnsspq.cli.convert._auto_tune",
           return_value={"workers": 2, "chunk_size": 50_000, "est_messages": 100})
    @patch("nov_gnsspq.cli.convert.print_convert_banner")
    @patch("pathlib.Path.stat")
    def test_package_not_found_uses_question_mark(
            self, mock_stat, mock_banner, mock_tune, mock_gen):
        """Verify edie version shows '?' when novatel_edie is not installed."""
        # Arrange
        import importlib.metadata
        mock_stat.return_value.st_size = 10 * 1024 * 1024
        ctx = MagicMock()
        mock_gen.return_value.__enter__ = MagicMock(return_value=ctx)
        mock_gen.return_value.__exit__ = MagicMock(return_value=False)
        # Act
        with patch(
            "nov_gnsspq.cli.convert.importlib.metadata.version",
            side_effect=importlib.metadata.PackageNotFoundError,
        ):
            run_convert("fake.GPS", "fake_out")
        # Assert
        call_info = mock_banner.call_args[0][0]
        assert call_info.edie_version == "?"

    @patch("nov_gnsspq.cli.convert.print_convert_banner")
    @patch("nov_gnsspq.cli.convert.PqConverter")
    @patch(
        "nov_gnsspq.cli.convert._auto_tune",
        return_value={"workers": 2, "chunk_size": 50_000, "est_messages": 100},
    )
    @patch("pathlib.Path.stat")
    def test_reconfigure_os_error_is_suppressed(
            self, mock_stat, mock_tune, mock_gen, mock_banner):
        """Verify OSError from stream.reconfigure is silently ignored."""
        # Arrange — mock sys.stdout so reconfigure raises OSError
        mock_stat.return_value.st_size = 10 * 1024 * 1024
        ctx = MagicMock()
        mock_gen.return_value.__enter__ = MagicMock(return_value=ctx)
        mock_gen.return_value.__exit__ = MagicMock(return_value=False)
        mock_stdout = MagicMock()
        mock_stdout.reconfigure.side_effect = OSError("not supported")
        # Act & Assert — should not raise
        with patch("nov_gnsspq.cli.convert.sys.stdout", mock_stdout):
            run_convert("fake.GPS", "fake_out")


@pytest.mark.skipif(
    not _SAMPLE_GPS.exists(),
    reason=f"GPS recording not found at {_SAMPLE_GPS}",
)
class TestRunConvertArchiveIntegration:
    """Integration tests for run_convert archive behaviour against a real GPS fixture."""

    def test_gnsspq_and_dir_both_exist_after_convert(self, tmp_path):
        """Tests that both the output directory and .gnsspq archive exist after conversion."""
        # Arrange
        out = tmp_path / "test_db"
        # Act
        run_convert(str(_SAMPLE_GPS), str(out), no_banner=True, archive=True)
        # Assert
        assert out.is_dir(), "original output directory must be preserved"
        assert (tmp_path / "test_db.gnsspq").exists(), \
            "gnsspq archive must be created"
