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

Protocol interfaces for the pluggable parallel file-processing engine.

This module has no intra-package imports so users can import these types
without pulling in novatel_edie or pyarrow.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BoundarySplitter(Protocol):
    """Snaps candidate byte offsets to valid record boundaries in a file.

    The engine divides a file into N equal-sized candidate offsets and calls
    ``snap_boundary`` once per interior boundary.  Implementations must be
    picklable -- they are serialised across ``ProcessPoolExecutor`` process
    boundaries.
    """

    def snap_boundary(self, file_path: Path, candidate_offset: int) -> int:
        """Return the nearest valid record boundary at or after the offset.

        Args:
            file_path: Path to the source file.
            candidate_offset: Approximate byte position to start searching
                from.

        Returns:
            A byte offset >= ``candidate_offset`` that aligns to a valid
            record start.  If no boundary exists (e.g. the candidate is past
            the last record), return the end-of-file offset so the engine
            skips the zero-length chunk.
        """


@runtime_checkable
class ChunkProcessor(Protocol):
    """Decodes and stores one byte-range slice of a source file.

    Implementations must be picklable.  Hold configuration state only
    (strings, ints, booleans, Paths) -- no open file handles or locks.
    """

    def process(
            self,
            file_path: Path,
            start_byte: int,
            end_byte: int,
            worker_id: int,
            temp_dir: Path,
            progress: Any = None) -> Any:
        """Process the byte range ``[start_byte, end_byte)`` of ``file_path``.

        Args:
            file_path: Path to the source file.
            start_byte: Inclusive start of the byte range.
            end_byte: Exclusive end of the byte range.
            worker_id: Zero-based worker index assigned by the engine.
            temp_dir: Engine-managed per-worker output directory.  Write all
                intermediate output here.  Internal scratch files are the
                processor's own responsibility to clean up.
            progress: A ``WorkerProgressReporter`` supplied by the engine for
                live per-worker byte progress.  Call ``progress.update(n)``
                with cumulative bytes consumed; processors that do not report
                progress simply ignore it.

        Returns:
            Any value.  Passed verbatim to ``ResultMerger.merge`` as one
            element of ``worker_results``.  Its schema is processor-defined.
        """


@runtime_checkable
class ResultMerger(Protocol):
    """Combines per-worker outputs into a final result.

    Implementations must be picklable.
    """

    def merge(self, worker_results: list[Any], output_dir: Path):
        """Merge worker outputs into the final result under ``output_dir``.

        Args:
            worker_results: Return values from ``ChunkProcessor.process``,
                sorted ascending by ``worker_id`` regardless of completion
                order.
            output_dir: Destination directory for all final output.  The
                engine writes nothing here itself.
        """
