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

Multi-process GPS-to-Parquet writer backed by ParallelFileEngine.
"""

from __future__ import annotations

import json
import logging
import os

import pyarrow.parquet as pq

from nov_gnsspq.reader.schema import (METADATA_FILENAME, SCHEMA_VERSION,
                                      WRITER_VERSION)
from nov_gnsspq.writer.parallel.edie import (EdieChunkProcessor,
                                             EdieFramerSplitter)
from nov_gnsspq.writer.parallel.engine import (PARALLEL_MIN_BYTES,
                                               ParallelFileEngine, _auto_tune)
from nov_gnsspq.writer.parallel.merger import ParquetMerger
from nov_gnsspq.writer.progress import (ConversionPhase, ProgressTracker)
from nov_gnsspq.writer.standard import GPSWriter

_log = logging.getLogger(__name__)


class ParallelGPSWriter:
    """Parallel GPS-to-Parquet writer that distributes work across processes.

    Splits the input file into N byte-range slices aligned to NovAtel message
    boundaries, spawns one worker process per slice via ProcessPoolExecutor,
    then merges the per-worker Parquet outputs with correct sequence_id and
    parent_id offsetting.

    Falls back to single-threaded GPSWriter for files smaller than 50 MB.

    Attributes:
        - input_file: Absolute path to the .GPS input file.
        - output_folder: Directory for the output Parquet tree.
        - compression: Parquet compression codec.
        - log_prefix: Logger prefix string for this instance.

    Public API:
        - write_to_db()
    """

    def __init__(
            self,
            input_file: str,
            output_folder: str,
            num_workers: int | None = None,
            chunk_size: int | None = None,
            compression: str = "zstd",
            tracker: ProgressTracker | None = None):
        """Initialise ParallelGPSWriter and auto-tune worker parameters.

        Args:
            input_file: Absolute path to .GPS input file.
            output_folder: Directory for the output Parquet tree.
            num_workers: Parallel process count (default: cpu_count - 1,
                max 8).
            chunk_size: Row flush threshold per worker (None = auto).
            compression: Parquet compression codec (default 'zstd').
            tracker: Pre-configured ProgressTracker that receives
                periodic ConversionProgress snapshots. Defaults to an
                inert tracker with no observers.
        """
        self.input_file = input_file
        self.output_folder = output_folder
        self.compression = compression
        self._tracker = tracker if tracker is not None else ProgressTracker()
        self.log_prefix = "nov_gnsspq_convert-parallel"

        tune = _auto_tune(input_file)
        self._chunk_size = (
            chunk_size if chunk_size is not None else tune["chunk_size"]
        )
        self._num_workers = (
            num_workers if num_workers is not None else tune["workers"]
        )
        self._est_messages = tune["est_messages"]

        self._engine = ParallelFileEngine(
            splitter=EdieFramerSplitter(),
            processor=EdieChunkProcessor(
                chunk_size=self._chunk_size,
                compression=compression,
            ),
            merger=ParquetMerger(compression=compression),
            num_workers=self._num_workers,
            tracker=self._tracker,
        )

        _log.debug(
            "[%s] auto-tune: workers=%s, chunk_size=%s, "
            "est_messages=%s, compression=%s",
            self.log_prefix,
            self._num_workers,
            f"{self._chunk_size:,}",
            f"{self._est_messages:,}",
            compression,
        )

    def write_to_db(self):
        """Parse the GPS file in parallel and write all tables to Parquet.

        Raises:
            ParallelEngineError: If any worker process raises an exception.
        """
        file_size = os.path.getsize(self.input_file)

        if file_size < PARALLEL_MIN_BYTES:
            _log.debug(
                "[%s] small file — delegating to single-threaded GPSWriter",
                self.log_prefix,
            )
            GPSWriter(
                self.input_file,
                self.output_folder,
                chunk_size=self._chunk_size,
                compression=self.compression,
                tracker=self._tracker,
            ).write_to_db()
            return

        os.makedirs(self.output_folder, exist_ok=True)

        self._tracker.total_bytes = file_size
        self._tracker.workers_total = self._num_workers
        self._tracker.force_emit(ConversionPhase.INITIALIZING, 0, workers_done=0)
        _log.info("[%s] computing SHA-256 ...", self.log_prefix)
        sha256 = GPSWriter._compute_sha256(  # pylint: disable=protected-access
            self.input_file)

        self._engine.run(self.input_file, self.output_folder)

        db_name = os.path.basename(self.output_folder)
        log_table = pq.read_table(
            os.path.join(self.output_folder, f"{db_name}.parquet")
        )
        total_messages = len(log_table)
        actual_workers = self._engine._last_actual_workers  # pylint: disable=protected-access

        meta = {
            "source_filename": os.path.basename(self.input_file),
            "file_size": file_size,
            "sha256": sha256,
            "total_message_count": total_messages,
            "schema_version": SCHEMA_VERSION,
            "writer_version": WRITER_VERSION,
            "parallel_workers": actual_workers,
        }
        with open(
                os.path.join(self.output_folder, METADATA_FILENAME),
                "w",
                encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        self._tracker.workers_total = actual_workers
        self._tracker.force_emit(
            ConversionPhase.DONE, file_size, workers_done=actual_workers)

        _log.info(
            "[%s] done. total_messages=%s",
            self.log_prefix,
            f"{total_messages:,}",
        )
