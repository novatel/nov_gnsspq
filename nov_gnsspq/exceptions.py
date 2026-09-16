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

Public exceptions raised by nov_gnsspq.
"""


class DatabaseExistsError(Exception):
    """Raised when the output directory already contains a nov_gnsspq database.

    Pass ``overwrite=True`` to PqConverter to suppress.
    """


class FieldNotFoundError(Exception):
    """Raised when a field is not found in a table or any of its subtables."""


class InvalidDatabaseError(Exception):
    """Raised when a path is not a valid nov_gnsspq database."""


class ParallelEngineError(Exception):
    """Raised when a worker process in ParallelFileEngine fails.

    Attributes:
        - worker_id: Integer id of the worker that failed.
        - byte_range: ``(start_byte, end_byte)`` slice assigned to that worker.
    """

    def __init__(
            self,
            message: str,
            worker_id: int,
            byte_range: tuple):
        """Initializes ParallelEngineError with failure context.

        Args:
            message: Human-readable description of the failure.
            worker_id: Integer id of the worker that failed.
            byte_range: ``(start_byte, end_byte)`` slice assigned to
                that worker.
        """
        super().__init__(message, worker_id, byte_range)
        self.worker_id = worker_id
        self.byte_range = byte_range


class WriteError(Exception):
    """Raised when an I/O error occurs during Parquet writes."""


class ReconstructionError(Exception):
    """Raised when reconstruction cannot proceed due to missing data."""
