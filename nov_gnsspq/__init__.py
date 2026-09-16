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

Package initialization for nov_gnsspq.
"""

from importlib.metadata import PackageNotFoundError, version

from nov_gnsspq.exceptions import (DatabaseExistsError, FieldNotFoundError,
                                   InvalidDatabaseError, ReconstructionError,
                                   WriteError)
from nov_gnsspq.logging import setup_logging
from nov_gnsspq.reader.frontend import FieldValue, LogSubtable, LogTable, PqReader
from nov_gnsspq.validate import ValidationResult, compare
from nov_gnsspq.writer.generator import PqConverter
from nov_gnsspq.writer.progress import (ConversionPhase, ConversionProgress,
                                        ProgressCallback)

__all__ = [
    "DatabaseExistsError",
    "FieldNotFoundError",
    "InvalidDatabaseError",
    "ReconstructionError",
    "WriteError",
    "setup_logging",
    "ConversionPhase",
    "ConversionProgress",
    "FieldValue",
    "LogSubtable",
    "LogTable",
    "PqConverter",
    "PqReader",
    "ProgressCallback",
    "ValidationResult",
    "compare",
]

try:
    __version__ = version("nov_gnsspq")
except PackageNotFoundError:
    __version__ = "0.0.0"
