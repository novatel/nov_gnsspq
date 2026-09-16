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

Colored logging formatter and setup helper for nov_gnsspq.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import re
import sys

_RESET = "\033[0m"

# Hexagon Primary Sky - #01ADFF / RGB(1, 173, 255)
_HEX_SKY = "\033[38;2;1;173;255m"

_LEVEL_COLORS = {
    logging.DEBUG:    "\033[36m",    # cyan
    logging.INFO:     "\033[32m",    # green
    logging.WARNING:  "\033[33m",    # yellow
    logging.ERROR:    "\033[31m",    # red
    logging.CRITICAL: "\033[1;31m",  # bold red
}

# Matches the [prefix] tag embedded in log messages
_PREFIX_RE = re.compile(r"(\[[^\]]+\])")

_FORMAT = "%(asctime)s  %(levelname)-8s  %(message)s"
_DATE_FMT = "%H:%M:%S"


def _enable_windows_ansi():
    if sys.platform != "win32":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.wintypes.DWORD()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except OSError:
        pass


class ColoredFormatter(logging.Formatter):
    """Logging formatter that colorizes level names and [prefix] tags."""

    def __init__(self, fmt: str = _FORMAT, datefmt: str = _DATE_FMT):
        """Initializes ColoredFormatter with format and date format strings.

        Args:
            fmt: Log record format string.
            datefmt: Date/time format string.
        """
        super().__init__(fmt=fmt, datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:
        """Formats a log record with colorized level name and prefix tags.

        Args:
            record: The log record to format.

        Returns:
            formatted: The formatted log string with ANSI color codes.
        """
        color = _LEVEL_COLORS.get(record.levelno, "")
        copy = logging.makeLogRecord(record.__dict__)
        copy.levelname = f"{color}{record.levelname}{_RESET}"
        # Interpolate %s args first, then colorize any [bracket-tag]
        copy.msg = _PREFIX_RE.sub(
            rf"{_HEX_SKY}\1{_RESET}", copy.getMessage())
        copy.args = None  # getMessage() already consumed args
        return super().format(copy)


def setup_logging(
        level: int = logging.INFO,
        *,
        logger_name: str = "nov_gnsspq"):
    """Configures colored console logging for nov_gnsspq.

    Call once at application startup::

        from nov_gnsspq import setup_logging
        setup_logging()              # INFO and above (default)
        setup_logging(logging.DEBUG) # includes auto-tune and routing details

    Args:
        level: Minimum log level to display. Defaults to ``logging.INFO``.
        logger_name: Logger hierarchy to configure. Defaults to
            ``"nov_gnsspq"`` which covers all sub-loggers
            (``nov_gnsspq.writer.parallel.engine``, etc.).
    """
    _enable_windows_ansi()
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return  # already configured - don't add duplicate handlers
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColoredFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
