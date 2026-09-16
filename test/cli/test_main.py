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

Unit tests for the nov_gnsspq CLI dispatcher (nov_gnsspq/cli/__init__.py).
"""
import sys
from unittest.mock import patch

import pytest

from nov_gnsspq.cli import main


# pylint: disable=protected-access


class TestMain:
    """Tests for the main() CLI dispatcher."""

    def test_no_args_exits_zero(self):
        """Verify main() exits 0 when called with no arguments."""
        # Act & Assert
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 0

    def test_help_flag_exits_zero(self):
        """Verify main() exits 0 for --help."""
        # Act & Assert
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0

    def test_short_help_flag_exits_zero(self):
        """Verify main() exits 0 for -h."""
        # Act & Assert
        with pytest.raises(SystemExit) as exc:
            main(["-h"])
        assert exc.value.code == 0

    def test_usage_text_printed_for_no_args(self, capsys):
        """Verify main() prints usage text when called with no arguments."""
        # Act
        with pytest.raises(SystemExit):
            main([])
        # Assert
        assert "commands" in capsys.readouterr().out

    def test_convert_dispatches_to_convert_main(self):
        """Verify main() calls convert_main with remaining args for 'convert'."""
        # Arrange
        with patch("nov_gnsspq.cli.convert.main") as mock_fn:
            # Act
            main(["convert", "some_arg"])
            # Assert
            mock_fn.assert_called_once_with(["some_arg"])

    def test_plot_dispatches_to_plot_main(self):
        """Verify main() calls plot_main with remaining args for 'plot'."""
        # Arrange
        with patch("nov_gnsspq.cli.plot.main") as mock_fn:
            # Act
            main(["plot", "--help"])
            # Assert
            mock_fn.assert_called_once_with(["--help"])

    def test_reconstruct_dispatches_to_reconstruct_main(self):
        """Verify main() calls reconstruct_main with remaining args for 'reconstruct'."""
        # Arrange
        with patch("nov_gnsspq.cli.reconstruct.main") as mock_fn:
            # Act
            main(["reconstruct", "db/", "orig.GPS"])
            # Assert
            mock_fn.assert_called_once_with(["db/", "orig.GPS"])

    def test_unknown_command_exits_one(self):
        """Verify main() exits 1 for an unrecognised command."""
        # Act & Assert
        with pytest.raises(SystemExit) as exc:
            main(["unknown_cmd_xyz"])
        assert exc.value.code == 1

    def test_unknown_command_writes_error_to_stderr(self, capsys):
        """Verify main() writes an error message to stderr for unknown commands."""
        # Act
        with pytest.raises(SystemExit):
            main(["unknown_cmd_xyz"])
        # Assert
        assert "unknown command" in capsys.readouterr().err

    def test_argv_none_reads_from_sys_argv(self):
        """Verify main() reads from sys.argv when argv is None."""
        # Arrange
        with patch.object(sys, "argv", ["gnsspq", "--help"]):
            # Act & Assert
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0
