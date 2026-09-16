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

Generic parallel file-processing engine, shared infrastructure utilities,
and the module-level worker dispatch wrapper required for multiprocessing
picklability.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import queue as _queue
import shutil
import tempfile
from pathlib import Path
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from typing import Any

from tqdm import tqdm

from nov_gnsspq.writer.parallel.edie import (EdieChunkProcessor,
                                             EdieFramerSplitter)
from nov_gnsspq.writer.parallel.merger import ParquetMerger
from nov_gnsspq.writer.parallel.protocols import (BoundarySplitter,
                                                  ChunkProcessor, ResultMerger)
from nov_gnsspq.writer.progress import (BarObserver, ConversionPhase,
                                        ProgressTracker, WorkerProgressReporter)

_log = logging.getLogger(__name__)

_500_MB = 500 * 1024 * 1024
_1_GB = 1_024 * 1_024 * 1_024

PARALLEL_MIN_BYTES = 50 * 1024 * 1024


def _auto_tune(input_file: str) -> dict[str, Any]:
    """Estimate worker count and chunk size from file size.

    Args:
        input_file: Path to the input GPS file.

    Returns:
        Dict with keys ``workers``, ``chunk_size``, and ``est_messages``.
    """
    cpu = os.cpu_count() or 4
    file_bytes = os.path.getsize(input_file)
    est_messages = max(1, file_bytes // 500)
    workers = min(max(2, cpu - 1), 8)

    raw_chunk = est_messages // max(1, workers * 8)
    chunk_size = max(20_000, min(200_000, raw_chunk))

    if file_bytes > _1_GB:
        chunk_size = max(chunk_size, 200_000)

    return {
        "workers": workers,
        "chunk_size": chunk_size,
        "est_messages": est_messages,
    }


def _engine_dispatch_worker(
        processor: ChunkProcessor,
        file_path: Path,
        start_byte: int,
        end_byte: int,
        worker_id: int,
        temp_dir: Path,
        progress: WorkerProgressReporter | None = None) -> Any:
    """Module-level wrapper so ProcessPoolExecutor can pickle the call.

    Args:
        processor: A picklable ``ChunkProcessor`` instance.
        file_path: Source file path.
        start_byte: Inclusive start byte.
        end_byte: Exclusive end byte.
        worker_id: Worker index.
        temp_dir: Engine-managed per-worker output directory.
        progress: Per-worker byte-progress reporter passed through to
            ``process``; processors may ignore it.

    Returns:
        Whatever ``processor.process`` returns.
    """
    return processor.process(
        file_path, start_byte, end_byte, worker_id, temp_dir,
        progress=progress)


class ParallelFileEngine:
    """Generic parallel file-processing engine with pluggable components.

    Splits a source file into byte-range slices, dispatches one worker
    process per slice via ``ProcessPoolExecutor``, sorts results by
    ``worker_id``, then calls the merger.

    Callers that want EDIE+Parquet behaviour can instantiate with no
    arguments; all three components default to the built-in
    implementations.

    Attributes:
        - _last_actual_workers: Number of workers used in the most recent
            ``run()`` call. Set after each successful run.

    Public API:
        - run()
    """

    def __init__(
            self,
            splitter: BoundarySplitter | None = None,
            processor: ChunkProcessor | None = None,
            merger: ResultMerger | None = None,
            num_workers: int | None = None,
            tracker: ProgressTracker | None = None):
        """Initializes ParallelFileEngine with pluggable pipeline components.

        Args:
            splitter: Snaps candidate offsets to valid record boundaries.
                Defaults to ``EdieFramerSplitter()``.
            processor: Decodes and stores one byte-range slice.
                Defaults to ``EdieChunkProcessor()``.
            merger: Combines per-worker outputs into the final result.
                Defaults to ``ParquetMerger()``.
            num_workers: Worker count. ``None`` = auto-tuned in ``run()``
                via ``clamp(cpu_count - 1, 2, 8)``.
            tracker: Pre-configured ProgressTracker that receives periodic
                ConversionProgress snapshots during the DECODING and MERGING
                phases. Defaults to an inert tracker with no observers.
        """
        self._splitter = (
            splitter if splitter is not None else EdieFramerSplitter()
        )
        self._processor = (
            processor if processor is not None else EdieChunkProcessor()
        )
        self._merger = merger if merger is not None else ParquetMerger()
        self._num_workers = num_workers
        self._last_actual_workers: int = 0
        self._tracker = tracker if tracker is not None else ProgressTracker()

    def run(self, file_path: Path | str, output_dir: Path | str):
        """Split, dispatch workers, sort results, and merge.

        Args:
            file_path: Path to the source file.
            output_dir: Destination directory for all final output.

        Raises:
            ParallelEngineError: If any worker process raises an exception.
        """
        from nov_gnsspq.exceptions import ParallelEngineError

        file_path = Path(file_path)
        output_dir = Path(output_dir)
        file_size = os.path.getsize(file_path)

        num_workers = self._num_workers
        if num_workers is None:
            cpu = os.cpu_count() or 4
            num_workers = min(max(2, cpu - 1), 8)

        boundaries = self._compute_boundaries(
            file_path, file_size, num_workers)
        actual_workers = len(boundaries) - 1
        self._last_actual_workers = actual_workers
        slice_sizes = [
            boundaries[k + 1] - boundaries[k] for k in range(actual_workers)
        ]

        self._tracker.total_bytes = file_size
        self._tracker.workers_total = actual_workers

        tmp_base = Path(tempfile.mkdtemp(prefix="_pfe_workers_"))
        manager = None
        try:
            output_dir.mkdir(parents=True, exist_ok=True)

            manager = multiprocessing.Manager()
            progress_queue = manager.Queue()

            results_by_id: dict = {}
            bytes_by_worker = [0] * actual_workers
            done_count = 0

            with ProcessPoolExecutor(max_workers=actual_workers) as executor:
                futures = {}
                for k in range(actual_workers):
                    reporter = WorkerProgressReporter(
                        progress_queue, k, slice_sizes[k])
                    futures[executor.submit(
                        _engine_dispatch_worker,
                        self._processor,
                        file_path,
                        boundaries[k],
                        boundaries[k + 1],
                        k,
                        tmp_base / f"w{k}",
                        reporter,
                    )] = k

                pending = set(futures)
                with tqdm(
                        total=file_size,
                        desc="Decoding",
                        unit="B",
                        unit_scale=True,
                        ncols=100) as pbar:
                    bar = BarObserver(pbar)
                    self._tracker.add_callback(bar)
                    self._tracker.force_emit(
                        ConversionPhase.DECODING, 0, workers_done=0)
                    while pending:
                        finished, pending = wait(
                            pending,
                            timeout=0.1,
                            return_when=FIRST_COMPLETED,
                        )
                        self._drain_progress_queue(
                            progress_queue, bytes_by_worker)
                        for future in finished:
                            wid = futures[future]
                            try:
                                results_by_id[wid] = future.result()
                            except Exception as exc:  # pylint: disable=broad-exception-caught
                                raise ParallelEngineError(
                                    f"Worker {wid} failed: {exc}",
                                    worker_id=wid,
                                    byte_range=(
                                        boundaries[wid],
                                        boundaries[wid + 1],
                                    ),
                                ) from exc
                            bytes_by_worker[wid] = slice_sizes[wid]
                            done_count += 1
                        total_done = min(sum(bytes_by_worker), file_size)
                        # Always emit on a worker completion
                        if finished:
                            self._tracker.force_emit(
                                ConversionPhase.DECODING, total_done,
                                workers_done=done_count)
                        else:
                            self._tracker.emit(
                                ConversionPhase.DECODING, total_done,
                                workers_done=done_count)
                    bar.close()
                    self._tracker.remove_callback(bar)

            self._tracker.force_emit(
                ConversionPhase.MERGING, file_size,
                workers_done=actual_workers)

            results = [results_by_id[k] for k in range(actual_workers)]
            self._merger.merge(results, output_dir)
        finally:
            if manager is not None:
                manager.shutdown()
            shutil.rmtree(str(tmp_base), ignore_errors=True)

    @staticmethod
    def _drain_progress_queue(
            progress_queue,
            bytes_by_worker: list[int]):
        """Drain pending ``(worker_id, bytes)`` updates into ``bytes_by_worker``.

        Args:
            progress_queue: Shared manager queue fed by worker reporters.
            bytes_by_worker: Per-worker cumulative byte counts (mutated in
                place). Reported values are already capped at each worker's
                slice size by the reporter.
        """
        while True:
            try:
                wid, consumed = progress_queue.get_nowait()
            except _queue.Empty:
                break
            # Per-worker counts only ever advance, and a completed worker is
            # pinned to its full slice size by the caller. Take the max so a
            # late-arriving or out-of-order queued update can never drag a
            # worker's byte count -- and thus aggregate progress -- backwards.
            bytes_by_worker[wid] = max(bytes_by_worker[wid], consumed)

    def _compute_boundaries(
            self,
            file_path: Path,
            file_size: int,
            num_workers: int) -> list[int]:
        """Divide file into num_workers byte-range slices at valid boundaries.

        Args:
            file_path: Source file path (passed to
                ``splitter.snap_boundary``).
            file_size: Total byte size of the source file.
            num_workers: Requested number of slices.

        Returns:
            Deduplicated list of byte offsets with at least two entries:
            ``[0, ..., file_size]``.
        """
        n = num_workers
        approx = [int(file_size * k / n) for k in range(n + 1)]
        boundaries = [0]
        for i in range(1, n):
            b = self._splitter.snap_boundary(file_path, approx[i])
            b = max(b, boundaries[-1] + 1)
            b = min(b, file_size)
            boundaries.append(b)
        boundaries.append(file_size)

        deduped = [boundaries[0]]
        for b in boundaries[1:]:
            if b > deduped[-1]:
                deduped.append(b)
        return deduped
