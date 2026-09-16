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

Public API for converting NovAtel GPS logs into a nov_gnsspq Parquet database.
"""

import json
import os
import zipfile
from pathlib import Path
from typing import Iterable

import novatel_edie as ne
import novatel_edie.oem as ne_oem
import pyarrow as pa
import pyarrow.parquet as pq
from nov_gnsspq.compat.telemetry import start_as_auto_span, telemetry

from nov_gnsspq.exceptions import DatabaseExistsError, WriteError
from nov_gnsspq.reader.schema import (HEADER_PREFIX, METADATA_FILENAME,
                                      SCHEMA_VERSION, SEQUENCE_ID_COL,
                                      WRITER_VERSION)
from nov_gnsspq.writer.parallel import ParallelGPSWriter
from nov_gnsspq.writer.parallel.edie import (_w_add_entry,
                                             _w_close_all_writers,
                                             _w_flush_all,
                                             _w_maybe_flush_subtree)
from nov_gnsspq.writer.parallel.engine import PARALLEL_MIN_BYTES
from nov_gnsspq.writer.progress import ProgressCallback, ProgressTracker
from nov_gnsspq.writer.standard import GPSWriter

tracer = telemetry.get_tracer(__name__)


def zip_database(output_dir: str | Path) -> Path:
    """Compress a nov_gnsspq Parquet database directory into a ``.gnsspq`` archive.

    The archive is written to
    ``{output_dir.parent}/{output_dir.name}.gnsspq``, overwriting any
    existing file at that path, and unpacks to a directory with the same
    name as *output_dir*. The file is a standard zip archive with a
    ``.gnsspq`` extension. The original directory is preserved.

    Args:
        output_dir: Path to the database directory produced by PqConverter.

    Returns:
        zip_path: Path to the created ``.gnsspq`` archive.
    """
    output_dir = Path(output_dir)
    zip_path = output_dir.parent / f"{output_dir.name}.gnsspq"
    with zipfile.ZipFile(
            zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(output_dir.rglob("*")):
            if file.is_file():
                zf.write(file, file.relative_to(output_dir.parent))
    return zip_path


class PqConverter:
    """Convert NovAtel GPS log records into a nov_gnsspq Parquet database.

    Three write methods are available depending on the use case:
        1. write_to_db(source) -- simplest option.
            Pass a file path and the database is written in one call. Best
            for single-file scripts.
        2. consume(source) -- context manager mode.
            Accepts a file path, a ``FileParser``, or any iterable.
            Call it multiple times inside a single ``with`` block to merge
            several recordings into one database, or feed it a live stream of
            messages.
        3. write(record) -- single-record control.
            Requires a context manager.  Use when you need to inspect,
            filter, or transform each message before it is stored.

    Attributes:
        - _output_dir: Resolved output directory Path.
        - _writer: Active GPSWriter or ParallelGPSWriter, or None.

    Public API:
        - consume()
        - write()
        - write_to_db()
    """

    @start_as_auto_span(tracer=tracer)
    def __init__(
            self,
            output_dir: str | Path,
            overwrite: bool = False,
            parallel: bool | None = None,
            archive: bool = False,
            progress_callback: ProgressCallback | None = None):
        """Initializes PqConverter with output configuration.

        Args:
            output_dir: Directory to write the database into.
            overwrite: If True, allow writing into a directory that already
                contains a database. Default False.
            parallel: Force parallel (True) or standard (False) writer.
                If None, the writer is chosen automatically based on file
                size.
            archive: If True, compress the output database directory into a
                ``.gnsspq`` archive at ``{output_dir}.gnsspq`` after writing.
                The original directory is preserved.
            progress_callback: Optional callable invoked with periodic
                ``ConversionProgress`` snapshots during file conversion.
                Applies to file-path / ``FileParser`` sources; streaming
                (record-by-record) mode does not emit progress.
        """
        self._output_dir = Path(output_dir)
        self._overwrite = overwrite
        self._archive = archive
        self._open = False
        self._parallel = parallel
        self._progress_callback = progress_callback
        self._writer: GPSWriter | ParallelGPSWriter | None = None
        # Used only in streaming (non-FileParser) mode:
        self._tables: dict = {}
        self._sequence_id: int = 0
        self._log_table_cols: dict = {
            "log": [],
            SEQUENCE_ID_COL: [],
        }
        self._unknown_cols: dict = {
            SEQUENCE_ID_COL: [],
            "payload": [],
        }

    # Public Methods

    @start_as_auto_span(tracer=tracer)
    def consume(self, source: str | Path | Iterable):
        """Add all records from source to the database.

        Accepts a file path, a ``FileParser``, or any iterable of GPS
        records.  File paths and ``FileParser`` instances use the
        optimised ``GPSWriter`` or ``ParallelGPSWriter`` internally.
        Any other iterable falls back to streaming mode.

        Call multiple times inside one ``with`` block to merge several
        recordings into a single database.  Call repeatedly on a live
        parser to drain messages as they arrive.

        Args:
            source: File path, FileParser, or any iterable of GPS records.

        Raises:
            RuntimeError: If called outside a ``with`` block.
        """
        if not self._open:
            raise RuntimeError(
                "PqConverter must be used as a context "
                "manager. Use `with PqConverter(...) as db:`."
            )
        file_path = self._extract_file_path(source)
        if file_path is not None:
            self._run_file_writer(file_path)
            return

        # Streaming path: iterate and accumulate.
        for record in source:
            self._write_record(record)

    @start_as_auto_span(tracer=tracer)
    def write(self, record):
        """Add a single GPS record to the database.

        Use this method when you need to inspect, filter, or transform
        records before storing them -- for example to keep only certain
        log types or decimate a high-rate IMU stream.

        Warning:
            Filtering or modifying records means the database no longer
            represents the original binary file exactly.  Binary
            reconstruction (``nov_gnsspq reconstruct``) compares the
            database against the source file message-by-message; if
            messages are missing or altered, the reconstruction check
            will report mismatches or fail entirely.  Only use
            ``write()`` with filtering when you do not need byte-exact
            reconstruction.

        Args:
            record: A single GPS record (Message, UnknownMessage, etc.).

        Raises:
            RuntimeError: If called outside a ``with`` block.
        """
        if not self._open:
            raise RuntimeError(
                "PqConverter must be used as a context "
                "manager."
            )
        self._write_record(record)

    @start_as_auto_span(tracer=tracer)
    def write_to_db(self, source):
        """Write all records from source to the database in one call.

        The simplest way to convert a single file -- no context manager
        required.  Equivalent to opening a ``with`` block, calling
        ``consume(source)``, and closing.

        Args:
            source: File path or FileParser to read records from.
        """
        metadata_path = self._output_dir / METADATA_FILENAME
        if metadata_path.exists() and not self._overwrite:
            raise DatabaseExistsError(
                f"{self._output_dir} already contains a nov_gnsspq "
                "database. Pass overwrite=True to replace it."
            )
        self._output_dir.mkdir(parents=True, exist_ok=True)
        file_path = self._extract_file_path(source)
        if file_path is not None:
            self._run_file_writer(file_path)
        if self._archive:
            zip_database(self._output_dir)

    # Private Methods

    @staticmethod
    def _extract_file_path(source) -> str | None:
        """Returns file path if source is a string, Path, or FileParser.

        Checks common attribute names on ``FileParser`` instances to
        locate the underlying path. If no path attribute is accessible,
        returns None so the caller falls back to streaming mode.

        Args:
            source: The input source to inspect.

        Returns:
            path: Absolute file path string, or None if not determinable.
        """
        # Direct string/Path -- always use file mode
        if isinstance(source, (str, Path)):
            return str(source)
        # FileParser -- try common attribute names for the underlying path
        if isinstance(source, ne_oem.FileParser):
            for attr in ("file_path", "_file_path", "filename", "path"):
                val = getattr(source, attr, None)
                if isinstance(val, (str, Path)):
                    return str(val)
            # FileParser detected but path not accessible -- fall through
        return None

    def _finalize(self):
        """Flushes remaining buffers and writes metadata (streaming mode).

        Writes ``log_table.parquet``, ``unknown_data.parquet`` (when
        applicable), and ``_metadata.json`` to the output directory.
        """
        out = str(self._output_dir)
        _w_flush_all(self._tables, "zstd")
        _w_close_all_writers(self._tables)
        # Write log_table
        if self._log_table_cols["log"]:
            pq.write_table(
                pa.table(self._log_table_cols),
                os.path.join(out, "log_table.parquet"),
                compression="zstd",
            )
        # Write unknown_data
        if self._unknown_cols[SEQUENCE_ID_COL]:
            pq.write_table(
                pa.table(self._unknown_cols),
                os.path.join(out, "unknown_data.parquet"),
                compression="zstd",
            )
        # Write _metadata.json
        meta = {
            "total_message_count": self._sequence_id,
            "schema_version": SCHEMA_VERSION,
            "writer_version": WRITER_VERSION,
        }
        with open(os.path.join(out, METADATA_FILENAME), "w",
                  encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    def _run_file_writer(self, file_path: str):
        """Delegates to GPSWriter or ParallelGPSWriter and executes write.

        Chooses the writer based on the ``parallel`` flag or file size
        when ``parallel`` is None.

        Args:
            file_path: Absolute path to the GPS log file.

        Raises:
            WriteError: If an OS-level error occurs during writing.
        """
        out = str(self._output_dir)
        file_size = os.path.getsize(file_path)
        tracker = ProgressTracker(self._progress_callback, file_size)

        try:
            if self._parallel is None:
                if file_size >= PARALLEL_MIN_BYTES:
                    self._writer = ParallelGPSWriter(
                        file_path,
                        out,
                        tracker=tracker,
                    )
                else:
                    self._writer = GPSWriter(
                        file_path,
                        out,
                        tracker=tracker,
                    )
            else:
                if self._parallel:
                    self._writer = ParallelGPSWriter(
                        file_path,
                        out,
                        tracker=tracker,
                    )
                elif not self._parallel:
                    self._writer = GPSWriter(
                        file_path,
                        out,
                        tracker=tracker,
                    )
            self._writer.write_to_db()
        except OSError as exc:
            raise WriteError(str(exc)) from exc

    def _write_record(self, record):
        """Processes a single message in streaming mode.

        Dispatches to the appropriate accumulation buffer based on record
        type, then periodically flushes to bound memory usage.

        Args:
            record: A GPS record (Message, UnknownMessage, UnknownBytes,
                etc.).
        """
        out = str(self._output_dir)

        if isinstance(record, ne_oem.Message):
            log_type = record.name
            message_dict = record.to_dict()
            header_dict = message_dict.pop("header", {})
            prefixed_header = {
                f"{HEADER_PREFIX}{k}": v
                for k, v in header_dict.items()
            }
            message_dict.update(prefixed_header)
            _w_add_entry(
                message_dict,
                self._tables,
                log_type,
                None,   # parent_id
                out,    # parent_output_dir
                out,    # output_folder
            )
            # Flush buffers periodically to bound memory usage
            for node in self._tables.values():
                _w_maybe_flush_subtree(
                    node, chunk_size=50_000, compression="zstd"
                )
            self._log_table_cols["log"].append(log_type)
            self._log_table_cols[SEQUENCE_ID_COL].append(
                self._sequence_id
            )

        elif isinstance(record, (ne_oem.UnknownMessage, ne.UnknownBytes)):
            try:
                if isinstance(record, ne_oem.UnknownMessage):
                    payload = record.payload
                else:
                    payload = record.data
            except (TypeError, RuntimeError):
                payload = None
            self._unknown_cols[SEQUENCE_ID_COL].append(
                self._sequence_id
            )
            self._unknown_cols["payload"].append(payload)
            self._log_table_cols["log"].append("UNKNOWN")
            self._log_table_cols[SEQUENCE_ID_COL].append(
                self._sequence_id
            )

        self._sequence_id += 1

    # Dunder Methods

    def __enter__(self) -> "PqConverter":
        """Opens the database context and prepares the output directory.

        Returns:
            self: The generator instance.

        Raises:
            DatabaseExistsError: If the output directory already contains
                a nov_gnsspq database and overwrite is False.
        """
        metadata_path = self._output_dir / METADATA_FILENAME
        if metadata_path.exists() and not self._overwrite:
            raise DatabaseExistsError(
                f"{self._output_dir} already contains a nov_gnsspq "
                "database. Pass overwrite=True to replace it."
            )
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._open = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Closes the database context and finalizes streaming writes.

        Args:
            exc_type: Exception type, if any.
            exc_val: Exception value, if any.
            exc_tb: Exception traceback, if any.
        """
        self._open = False
        if exc_type is not None:
            return  # don't finalize on exception
        if self._writer is None:
            # Streaming mode -- finalize manually
            self._finalize()
        if self._archive:
            zip_database(self._output_dir)
