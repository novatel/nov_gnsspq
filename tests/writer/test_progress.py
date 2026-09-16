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

Unit and integration tests for conversion progress tracking:
nov_gnsspq.writer.progress, the _message_byte_len helper, single-threaded
GPSWriter callbacks, the parallel engine's byte aggregation, and the
PqConverter integration.
"""
import queue as _queue
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from nov_gnsspq import PqConverter
from nov_gnsspq.writer.parallel.engine import (ParallelFileEngine,
                                               _engine_dispatch_worker)
from nov_gnsspq.writer.progress import (BarObserver, ConversionPhase,
                                        ConversionProgress, ProgressTracker,
                                        WorkerProgressReporter,
                                        _message_byte_len, _ProgressThrottle)
from nov_gnsspq.writer.standard import GPSWriter

# pylint: disable=protected-access

_REPO_ROOT = Path(__file__).resolve().parents[1]
GPS_FILE = os.environ.get(
    "NOV_GNSSPQ_TEST_GPS",
    str(_REPO_ROOT / "resources" / "sample.GPS"),
)

class TestConversionProgress:
    """Tests for the ConversionProgress dataclass."""

    @pytest.mark.parametrize(
        "phase, bytes_processed, total_bytes, attr, expected",
        [
            (ConversionPhase.DECODING, 25, 100, "fraction", 0.25),
            (ConversionPhase.DECODING, 150, 100, "fraction", 1.0),
            (ConversionPhase.DECODING, 0, 0, "fraction", 0.0),
            (ConversionPhase.DONE, 0, 0, "fraction", 1.0),
            (ConversionPhase.DECODING, 1, 4, "percent", 25.0),
            (ConversionPhase.DECODING, 1, 4, "workers_total", None),
            (ConversionPhase.DECODING, 1, 4, "workers_done", None),
        ],
        ids=[
            "fraction_normal",
            "fraction_clamped_to_one",
            "fraction_zero_total_not_done_is_zero",
            "fraction_zero_total_done_is_one",
            "percent",
            "worker_fields_total_default_none",
            "worker_fields_done_default_none",
        ],
    )
    def test_derived_properties(
            self, phase, bytes_processed, total_bytes, attr, expected):
        """Tests derived ConversionProgress properties for various inputs."""
        # Arrange
        p = ConversionProgress(phase, bytes_processed, total_bytes)
        # Act & Assert
        assert getattr(p, attr) == expected

class TestProgressThrottle:
    """Tests for the _ProgressThrottle rate limiter."""

    def test_first_call_is_ready(self):
        """Tests the first ready() call returns True."""
        # Arrange
        throttle = _ProgressThrottle(min_interval=1000.0)
        # Act & Assert
        assert throttle.ready() is True

    def test_rapid_second_call_is_not_ready(self):
        """Tests a rapid second call is throttled."""
        # Arrange
        throttle = _ProgressThrottle(min_interval=1000.0)
        throttle.ready()
        # Act & Assert
        assert throttle.ready() is False

    def test_zero_interval_always_ready(self):
        """Tests a zero interval lets every call through."""
        # Arrange
        throttle = _ProgressThrottle(min_interval=0.0)
        # Act & Assert
        assert throttle.ready() is True
        assert throttle.ready() is True

class TestProgressTracker:
    """Tests for the ProgressTracker emit / force_emit wrapper."""

    def test_force_emit_builds_progress_with_stored_fields(self):
        """Tests force_emit fills total_bytes / workers_total from the tracker."""
        # Arrange
        events = []
        tracker = ProgressTracker(events.append, 200, workers_total=4)
        # Act
        tracker.force_emit(ConversionPhase.DECODING, 50, workers_done=1)
        # Assert
        assert len(events) == 1
        evt = events[0]
        assert evt.phase is ConversionPhase.DECODING
        assert evt.bytes_processed == 50
        assert evt.total_bytes == 200
        assert evt.workers_total == 4
        assert evt.workers_done == 1

    def test_force_emit_always_fires(self):
        """Tests force_emit fires even when the throttle is not ready."""
        # Arrange
        events = []
        tracker = ProgressTracker(events.append, 100)
        # Act
        with patch.object(tracker._throttle, "ready", return_value=False):
            tracker.force_emit(ConversionPhase.DECODING, 1)
            tracker.force_emit(ConversionPhase.DECODING, 2)
        # Assert
        assert [e.bytes_processed for e in events] == [1, 2]

    def test_emit_is_throttled(self):
        """Tests emit is suppressed when the throttle reports not ready."""
        # Arrange
        events = []
        tracker = ProgressTracker(events.append, 100)
        # Act
        with patch.object(
                tracker._throttle, "ready", side_effect=[True, False]):
            tracker.emit(ConversionPhase.DECODING, 1)
            tracker.emit(ConversionPhase.DECODING, 2)
        # Assert
        assert [e.bytes_processed for e in events] == [1]

    def test_emit_fires_when_throttle_ready(self):
        """Tests emit fires every time the throttle reports ready."""
        # Arrange
        events = []
        tracker = ProgressTracker(events.append, 100)
        # Act
        with patch.object(tracker._throttle, "ready", return_value=True):
            tracker.emit(ConversionPhase.DECODING, 1)
            tracker.emit(ConversionPhase.DECODING, 2)
        # Assert
        assert [e.bytes_processed for e in events] == [1, 2]

    def test_none_callback_is_noop(self):
        """Tests emit / force_emit do nothing when no callback is supplied."""
        # Arrange
        tracker = ProgressTracker(None, 100)
        # Act & Assert
        tracker.force_emit(ConversionPhase.DONE, 100)  # must not raise

    def test_callback_exception_is_swallowed(self):
        """Tests a raising callback does not propagate out of the tracker."""
        # Arrange
        def _boom(_progress):
            raise ValueError("observer blew up")
        tracker = ProgressTracker(_boom, 100)
        # Act & Assert
        tracker.force_emit(ConversionPhase.DECODING, 1)  # must not raise

    def test_workers_total_reassignable(self):
        """Tests workers_total can be updated before a later emit."""
        # Arrange
        events = []
        tracker = ProgressTracker(events.append, 100)
        # Act
        tracker.force_emit(ConversionPhase.INITIALIZING, 0)
        tracker.workers_total = 8
        tracker.force_emit(ConversionPhase.DONE, 100, workers_done=8)
        # Assert
        assert events[0].workers_total is None
        assert events[1].workers_total == 8

    def test_multiple_observers_all_receive(self):
        """Tests a tracker built from a list fans out to every observer."""
        # Arrange
        a, b = [], []
        tracker = ProgressTracker([a.append, b.append], 100)
        # Act
        tracker.force_emit(ConversionPhase.DECODING, 10)
        # Assert
        assert len(a) == 1
        assert len(b) == 1

    def test_add_callback_registers_extra_observer(self):
        """Tests add_callback wires in an additional observer."""
        # Arrange
        a, b = [], []
        tracker = ProgressTracker(a.append, 100)
        # Act
        tracker.add_callback(b.append)
        tracker.force_emit(ConversionPhase.DECODING, 5)
        # Assert
        assert len(a) == 1
        assert len(b) == 1

    def test_one_observer_raising_does_not_block_others(self):
        """Tests a raising observer is isolated from the others."""
        # Arrange
        good = []

        def _bad(_progress):
            raise ValueError("boom")
        tracker = ProgressTracker([_bad, good.append], 100)
        # Act
        tracker.force_emit(ConversionPhase.DECODING, 5)  # must not raise
        # Assert
        assert len(good) == 1

class _FakeBar:
    """Minimal tqdm-style bar double recording position and refreshes."""

    def __init__(self):
        """Initializes a bar at position zero."""
        self.n = 0
        self.refreshed = 0

    def refresh(self):
        """Records a refresh call."""
        self.refreshed += 1


class TestBarObserver:
    """Tests for the BarObserver tqdm bridge."""

    def test_sets_position_from_bytes(self):
        """Tests the bar position is set from bytes_processed."""
        # Arrange
        bar = _FakeBar()
        # Act
        BarObserver(bar)(ConversionProgress(ConversionPhase.DECODING, 30, 100))
        # Assert
        assert bar.n == 30
        assert bar.refreshed == 1

    def test_clamps_to_total(self):
        """Tests the bar position is clamped to total_bytes."""
        # Arrange
        bar = _FakeBar()
        # Act
        BarObserver(bar)(
            ConversionProgress(ConversionPhase.DECODING, 150, 100))
        # Assert
        assert bar.n == 100

    def test_close_detaches(self):
        """Tests a closed observer ignores further events."""
        # Arrange
        bar = _FakeBar()
        obs = BarObserver(bar)
        # Act
        obs.close()
        obs(ConversionProgress(ConversionPhase.DONE, 100, 100))
        # Assert
        assert bar.n == 0
        assert bar.refreshed == 0

class _FakeQueue:
    """Minimal queue double recording put_nowait calls."""

    def __init__(self):
        """Initializes an empty record list."""
        self.items = []

    def put_nowait(self, item):
        """Records an enqueued item."""
        self.items.append(item)


class TestWorkerProgressReporter:
    """Tests for the picklable WorkerProgressReporter."""

    def test_first_update_enqueues_worker_id_and_bytes(self):
        """Tests the first update enqueues (worker_id, bytes)."""
        # Arrange
        q = _FakeQueue()
        reporter = WorkerProgressReporter(q, 2, 100)
        # Act
        with patch.object(reporter._throttle, "ready", return_value=True):
            reporter.update(40)
        # Assert
        assert q.items == [(2, 40)]

    def test_caps_at_slice_size(self):
        """Tests reported bytes are capped at the slice size."""
        # Arrange
        q = _FakeQueue()
        reporter = WorkerProgressReporter(q, 0, 100)
        # Act
        with patch.object(reporter._throttle, "ready", return_value=True):
            reporter.update(999)
        # Assert
        assert q.items == [(0, 100)]

    def test_duplicate_value_not_re_enqueued(self):
        """Tests an unchanged value is not enqueued twice."""
        # Arrange
        q = _FakeQueue()
        reporter = WorkerProgressReporter(q, 0, 100)
        # Act
        with patch.object(reporter._throttle, "ready", return_value=True):
            reporter.update(50)
            reporter.update(50)
        # Assert
        assert q.items == [(0, 50)]

    def test_update_dropped_when_throttle_not_ready(self):
        """Tests an update is dropped when the throttle reports not ready."""
        # Arrange
        q = _FakeQueue()
        reporter = WorkerProgressReporter(q, 0, 100)
        # Act
        with patch.object(
                reporter._throttle, "ready", side_effect=[True, False]):
            reporter.update(10)
            reporter.update(20)
        # Assert
        assert q.items == [(0, 10)]

    def test_final_update_bypasses_throttle(self):
        """Tests a final update is enqueued even within the throttle interval."""
        # Arrange
        q = _FakeQueue()
        reporter = WorkerProgressReporter(q, 0, 100)
        # Act
        with patch.object(reporter._throttle, "ready", return_value=False):
            reporter.update(10)              # throttled -> dropped
            reporter.update(20, final=True)  # final -> enqueued anyway
        # Assert
        assert q.items == [(0, 20)]

    def test_null_reporter_without_queue_is_noop(self):
        """Tests a reporter built without a queue silently drops updates."""
        # Arrange
        reporter = WorkerProgressReporter()
        # Act & Assert
        reporter.update(123)  # must not raise


class TestEngineProgressHelpers:
    """Tests for ParallelFileEngine progress helper methods."""

    def test_drain_progress_queue_keeps_latest_per_worker(self):
        """Tests draining records the latest value for each worker."""
        # Arrange
        q = _queue.Queue()
        q.put((0, 50))
        q.put((1, 30))
        q.put((0, 70))
        bytes_by_worker = [0, 0]
        # Act
        ParallelFileEngine._drain_progress_queue(q, bytes_by_worker)
        # Assert
        assert bytes_by_worker == [70, 30]

    def test_dispatch_forwards_progress_to_processor(self):
        """Tests _engine_dispatch_worker hands the reporter to process, so the
        processor's update() calls reach the queue."""
        # Arrange
        q = _FakeQueue()
        reporter = WorkerProgressReporter(q, worker_id=3, slice_size=100)

        class _P:
            def process(self, file_path, start_byte, end_byte, worker_id,
                        temp_dir, progress=None):
                progress.update(40, final=True)
                return "ok"

        # Act
        result = _engine_dispatch_worker(_P(), "f", 0, 100, 3, "tmp", reporter)
        # Assert
        assert result == "ok"
        assert q.items == [(3, 40)]

class TestPqConverterProgressIntegration:
    """End-to-end progress callbacks via the public PqConverter API."""

    def test_callback_receives_progress_and_reaches_done(self, tmp_path):
        """Tests PqConverter forwards progress and reaches DONE at 100%."""
        # Arrange
        events = []
        # Act
        with PqConverter(
                str(tmp_path / "db"),
                overwrite=True,
                parallel=False,
                progress_callback=events.append) as db:
            db.consume(GPS_FILE)
        # Assert
        assert events
        assert all(isinstance(e, ConversionProgress) for e in events)
        assert events[-1].phase is ConversionPhase.DONE
        assert events[-1].fraction == 1.0

    def test_parallel_reports_byte_progress_and_phases(
            self, tmp_path, monkeypatch):
        """Tests parallel conversion emits byte progress, MERGING, then DONE."""
        # Arrange
        # Force the parallel path even though the sample file is small.
        monkeypatch.setattr(
            "nov_gnsspq.writer.parallel.PARALLEL_MIN_BYTES", 1)
        events = []
        # Act
        with PqConverter(
                str(tmp_path / "pdb"),
                overwrite=True,
                parallel=True,
                progress_callback=events.append) as db:
            db.consume(GPS_FILE)
        # Assert
        assert events
        phases = [e.phase for e in events]
        assert ConversionPhase.DECODING in phases
        assert ConversionPhase.MERGING in phases
        assert events[-1].phase is ConversionPhase.DONE
        assert events[-1].fraction == 1.0
        # Worker counts are populated in parallel mode.
        decoding = [e for e in events if e.phase is ConversionPhase.DECODING]
        assert decoding
        assert all(e.workers_total is not None for e in decoding)
        # Progress is expressed in bytes of the file, monotonically rising.
        fractions = [e.fraction for e in events]
        assert fractions == sorted(fractions)
