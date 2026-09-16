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

Conversion progress-tracking types and helpers.

Defines the public ``ConversionProgress`` status object and ``ConversionPhase``
enum that conversion routines emit to a user-supplied ``progress_callback``,
plus small internal helpers used to throttle emissions and report per-worker
byte progress across process boundaries.
"""

import dataclasses
import enum
import logging
import time
from typing import Callable, Optional

import novatel_edie as ne
import novatel_edie.oem as ne_oem

_log = logging.getLogger(__name__)


# novatel_edie exposes no public accessor for a record's source byte
# length, so it is derived per record type below. Replace this with the
# upstream accessor if one is added.
def _message_byte_len(
        message: ne_oem.Message | ne_oem.Response
        | ne_oem.UnknownMessage | ne.UnknownBytes) -> int:
    """Return the source byte length of a record yielded by FileParser iteration.

    Args:
        message: A record yielded by ``FileParser.__iter__``.

    Returns:
        The record's source byte length.
    """
    if isinstance(message, ne_oem.Message):
        return message.header.length
    if isinstance(message, ne_oem.UnknownMessage):
        return len(message.payload)
    if isinstance(message, ne.UnknownBytes):
        return len(message.data)
    # ne_oem.Response carries no usable on-wire byte length, just ignore them
    return 0


class ConversionPhase(enum.Enum):
    """Coarse stage of a conversion run.

    Attributes:
        - INITIALIZING: Pre-decode work (hashing, boundary computation).
        - DECODING: The main message-decoding work.
        - MERGING: Parallel-only post-process that merges per-worker output.
        - DONE: Conversion finished successfully.
    """

    INITIALIZING = "initializing"
    DECODING = "decoding"
    MERGING = "merging"
    DONE = "done"


@dataclasses.dataclass(frozen=True)
class ConversionProgress:
    """Immutable snapshot of conversion progress.

    Emitted periodically (and on phase changes / completion) to a
    ``progress_callback``.  ``workers_total`` / ``workers_done`` are populated
    only in parallel mode and are ``None`` for single-threaded conversion.

    Attributes:
        - phase: Current ConversionPhase.
        - bytes_processed: Bytes of the source file decoded so far.
        - total_bytes: Total size of the source file in bytes.
        - workers_total: Number of parallel workers, or None.
        - workers_done: Number of finished parallel workers, or None.
    """

    phase: ConversionPhase
    bytes_processed: int
    total_bytes: int
    workers_total: Optional[int] = None
    workers_done: Optional[int] = None

    @property
    def fraction(self) -> float:
        """Fraction of the file processed, clamped to ``[0.0, 1.0]``.

        Returns:
            ``bytes_processed / total_bytes`` clamped to 1.0.  When
            ``total_bytes`` is unknown (``<= 0``) returns 1.0 once the run is
            DONE, otherwise 0.0.
        """
        if self.total_bytes <= 0:
            return 1.0 if self.phase is ConversionPhase.DONE else 0.0
        return min(1.0, self.bytes_processed / self.total_bytes)

    @property
    def percent(self) -> float:
        """Progress as a percentage in ``[0.0, 100.0]``."""
        return self.fraction * 100.0


# Type of a user-supplied progress callback.  Called with one
# ``ConversionProgress`` per emission; its return value is ignored.
ProgressCallback = Callable[[ConversionProgress], None]


class _ProgressThrottle:
    """Rate-limits emissions to at most one per ``min_interval`` seconds.

    Uses ``time.monotonic`` so it is unaffected by wall-clock changes.
    """

    def __init__(self, min_interval: float = 0.1):
        """Initialize the throttle.

        Args:
            min_interval: Minimum seconds between ``ready()`` returning True.
        """
        self._min_interval = min_interval
        self._last: float | None = None

    def ready(self) -> bool:
        """Return True at most once per ``min_interval``; resets the timer.

        Returns:
            True if at least ``min_interval`` has elapsed since the last True.
        """
        now = time.monotonic()
        if self._last is None or now - self._last >= self._min_interval:
            self._last = now
            return True
        return False


class ProgressTracker:
    """Builds ``ConversionProgress`` snapshots and fans them out to observers.

    Bundles a ``_ProgressThrottle`` and the fixed progress denominators
    (``total_bytes`` and ``workers_total``) with a list of observer callbacks
    so call sites no longer manage throttling or rebuild the snapshot fields by
    hand:

        - ``emit`` is rate-limited -- use it for the steady stream of in-loop
          updates.
        - ``force_emit`` always fires -- use it for phase changes and
          completion.

    Observers are any callables accepting a ``ConversionProgress``. The console
    progress bar is registered as one observer (see ``BarObserver``) and the
    user's ``progress_callback`` as another, so a single ``emit`` updates both.
    Both methods do nothing when there are no observers, and an observer that
    raises is logged and swallowed so a faulty one can never abort a conversion
    or starve the others.

    Attributes:
        - total_bytes: Source file size used as the progress denominator.
        - workers_total: Parallel worker count reported on each snapshot, or
            None for single-threaded conversion. May be reassigned once the
            final worker count is known.

    Public API:
        - add_callback()
        - emit()
        - force_emit()
    """

    def __init__(
            self,
            callbacks: ProgressCallback | list[ProgressCallback] | None = None,
            total_bytes: int = 0,
            workers_total: Optional[int] = None,
            min_interval: float = 0.1):
        """Initialize the tracker.

        Args:
            callbacks: A single progress callback, an iterable of callbacks, or
                None.
            total_bytes: Total source file size in bytes.
            workers_total: Parallel worker count, or None for single-threaded.
            min_interval: Minimum seconds between throttled ``emit`` calls.
        """
        self._callbacks: list = []
        self.total_bytes = total_bytes
        self.workers_total = workers_total
        self._throttle = _ProgressThrottle(min_interval)
        if callbacks is not None:
            if callable(callbacks):
                self.add_callback(callbacks)
            else:
                for cb in callbacks:
                    self.add_callback(cb)

    def add_callback(self, callback: ProgressCallback):
        """Register an additional observer.

        Args:
            callback: Callable invoked with each ``ConversionProgress``.
        """
        self._callbacks.append(callback)

    def remove_callback(self, callback: ProgressCallback):
        """Unregister a previously added observer.

        A no-op if the callback is not currently registered. Used to detach a
        transient observer (e.g. a per-run console bar) so a reused tracker does
        not accumulate stale observers across runs.

        Args:
            callback: The observer to remove.
        """
        try:
            self._callbacks.remove(callback)
        except ValueError:
            pass

    def emit(
            self,
            phase: ConversionPhase,
            bytes_processed: int,
            workers_done: Optional[int] = None):
        """Emit a snapshot if the throttle interval has elapsed.

        Args:
            phase: Current ConversionPhase.
            bytes_processed: Bytes decoded so far.
            workers_done: Finished parallel worker count, or None.
        """
        if not self._callbacks or not self._throttle.ready():
            return
        self._dispatch(phase, bytes_processed, workers_done)

    def force_emit(
            self,
            phase: ConversionPhase,
            bytes_processed: int,
            workers_done: Optional[int] = None):
        """Emit a snapshot unconditionally (phase change / completion).

        Args:
            phase: Current ConversionPhase.
            bytes_processed: Bytes decoded so far.
            workers_done: Finished parallel worker count, or None.
        """
        if not self._callbacks:
            return
        self._dispatch(phase, bytes_processed, workers_done)

    def _dispatch(
            self,
            phase: ConversionPhase,
            bytes_processed: int,
            workers_done: Optional[int]):
        """Build one ConversionProgress and invoke every observer (errors logged).

        Args:
            phase: Current ConversionPhase.
            bytes_processed: Bytes decoded so far.
            workers_done: Finished parallel worker count, or None.
        """
        progress = ConversionProgress(
            phase=phase,
            bytes_processed=bytes_processed,
            total_bytes=self.total_bytes,
            workers_total=self.workers_total,
            workers_done=workers_done,
        )
        for callback in self._callbacks:
            try:
                callback(progress)
            except Exception:  # pylint: disable=broad-exception-caught
                _log.exception("progress callback raised; ignoring")


class BarObserver:
    """ProgressTracker observer that drives a tqdm-style bar by byte count.

    Holds a live progress-bar handle and, on each ``ConversionProgress``, sets
    the bar position to ``bytes_processed`` (clamped to ``total_bytes``). The
    bar is duck-typed -- only ``n`` and ``refresh()`` are used -- so this module
    needs no tqdm import. ``close`` detaches it so a later event (e.g. a
    post-decode ``DONE``) leaves the already-closed bar untouched.
    """

    def __init__(self, bar):
        """Initialize the observer.

        Args:
            bar: A tqdm-style progress bar exposing ``n`` and ``refresh()``.
        """
        self._bar = bar
        self._closed = False

    def __call__(self, progress: ConversionProgress):
        """Set the bar position from a progress snapshot.

        Args:
            progress: The latest ConversionProgress.
        """
        if self._closed:
            return
        n = progress.bytes_processed
        if progress.total_bytes > 0 and n > progress.total_bytes:
            n = progress.total_bytes
        self._bar.n = n
        self._bar.refresh()

    def close(self):
        """Detach from further events (bar lifecycle has ended)."""
        self._closed = True


class WorkerProgressReporter:
    """Picklable handle a worker process uses to report bytes consumed.

    Created by the engine, serialised across the ``ProcessPoolExecutor``
    boundary, and used by the worker to push ``(worker_id, bytes_consumed)``
    onto a shared progress queue.  Puts are time-throttled so the queue never
    floods, and capped at the worker's slice size.

    Constructed without a queue it is an inert null object whose ``update`` does
    nothing -- so workers can always call ``update`` without a ``None`` check.
    """

    def __init__(
            self,
            progress_queue=None,
            worker_id: int = 0,
            slice_size: int = 0,
            min_interval: float = 0.1):
        """Initialize the reporter.

        Args:
            progress_queue: A ``multiprocessing.Manager().Queue()`` proxy, or
                None for an inert reporter that drops every update.
            worker_id: Index of the worker this reporter belongs to.
            slice_size: Byte length of the worker's slice (an upper bound).
            min_interval: Minimum seconds between queue puts.
        """
        self._queue = progress_queue
        self._worker_id = worker_id
        self._slice_size = slice_size
        self._throttle = _ProgressThrottle(min_interval)
        self._last_sent = -1

    def update(self, bytes_consumed: int, final: bool = False):
        """Report cumulative bytes consumed within this worker's slice.

        Throttled by time and de-duplicated; a no-op when there is no queue.
        A ``final`` update bypasses the throttle so the terminal byte count is
        never dropped. Failures to enqueue are ignored (progress reporting must
        never disrupt decoding).

        Args:
            bytes_consumed: Cumulative bytes decoded so far in this slice.
            final: When True, send even if the throttle interval has not
                elapsed (used to flush the last update as a worker finishes).
        """
        if self._queue is None:
            return
        capped = min(bytes_consumed, self._slice_size)
        if capped == self._last_sent:
            return
        if not final and not self._throttle.ready():
            return
        self._last_sent = capped
        try:
            self._queue.put_nowait((self._worker_id, capped))
        except Exception:  # pylint: disable=broad-exception-caught
            pass
