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

Tests for ParallelEngineError and default-implementation conformance.
"""
import inspect
import pickle

import pytest

from nov_gnsspq.exceptions import ParallelEngineError
from nov_gnsspq.writer.parallel.edie import EdieChunkProcessor, EdieFramerSplitter
from nov_gnsspq.writer.parallel.merger import ParquetMerger


# pylint: disable=protected-access


class TestParallelEngineError:
    """Tests for the ParallelEngineError exception class."""

    def test_is_exception_subclass(self):
        """Tests that ParallelEngineError is a subclass of Exception."""
        # Act
        err = ParallelEngineError("msg", worker_id=0, byte_range=(0, 1))
        # Assert
        assert isinstance(err, Exception)

    def test_is_picklable(self):
        """Tests that ParallelEngineError survives a pickle round-trip."""
        # Arrange
        err = ParallelEngineError("boom", worker_id=2, byte_range=(0, 99))
        # Act
        restored = pickle.loads(pickle.dumps(err))
        # Assert
        assert restored.worker_id == 2
        assert restored.byte_range == (0, 99)

    def test_stores_byte_range(self):
        """Tests that byte_range is stored on the exception."""
        # Act
        err = ParallelEngineError("msg", worker_id=0, byte_range=(500, 1000))
        # Assert
        assert err.byte_range == (500, 1000)

    def test_stores_worker_id(self):
        """Tests that worker_id is stored on the exception."""
        # Act
        err = ParallelEngineError("msg", worker_id=3, byte_range=(0, 100))
        # Assert
        assert err.worker_id == 3

    def test_supports_exception_chaining(self):
        """Tests that ParallelEngineError supports PEP 3134 exception chaining."""
        # Arrange
        cause = ValueError("root cause")
        # Act & Assert
        try:
            raise ParallelEngineError(
                "wrap", worker_id=1, byte_range=(0, 10)) from cause
        except ParallelEngineError as e:
            assert e.__cause__ is cause


class TestEdieFramerSplitterConformance:
    """Tests for EdieFramerSplitter protocol conformance."""

    def test_has_snap_boundary(self):
        """Tests that EdieFramerSplitter exposes a callable snap_boundary."""
        # Act
        s = EdieFramerSplitter()
        # Assert
        assert callable(getattr(s, "snap_boundary", None))

    def test_is_picklable(self):
        """Tests that EdieFramerSplitter survives a pickle round-trip."""
        # Act
        s = EdieFramerSplitter()
        restored = pickle.loads(pickle.dumps(s))
        # Assert
        assert isinstance(restored, EdieFramerSplitter)

    def test_returns_file_size_when_offset_beyond_end(self, tmp_path):
        """Tests snap_boundary returns EOF offset when candidate >= file size."""
        # Arrange
        f = tmp_path / "tiny.GPS"
        f.write_bytes(b"x" * 100)
        s = EdieFramerSplitter()
        # Act
        result = s.snap_boundary(f, candidate_offset=100)
        # Assert
        assert result == 100

    def test_returns_int(self, tmp_path):
        """Tests that snap_boundary always returns an int."""
        # Arrange
        f = tmp_path / "tiny.GPS"
        f.write_bytes(b"x" * 100)
        s = EdieFramerSplitter()
        # Act
        result = s.snap_boundary(f, candidate_offset=0)
        # Assert
        assert isinstance(result, int)

    def test_snap_boundary_signature(self):
        """Tests that snap_boundary has the expected parameter names."""
        # Act
        sig = inspect.signature(EdieFramerSplitter.snap_boundary)
        params = list(sig.parameters)
        # Assert
        assert params == ["self", "file_path", "candidate_offset"]


class TestEdieChunkProcessorConformance:
    """Tests for EdieChunkProcessor protocol conformance."""

    def test_has_process(self):
        """Tests that EdieChunkProcessor exposes a callable process method."""
        # Act
        p = EdieChunkProcessor()
        # Assert
        assert callable(getattr(p, "process", None))

    def test_is_picklable_with_defaults(self):
        """Tests that EdieChunkProcessor with defaults survives a pickle round-trip."""
        # Act
        p = EdieChunkProcessor()
        restored = pickle.loads(pickle.dumps(p))
        # Assert
        assert isinstance(restored, EdieChunkProcessor)

    def test_is_picklable_with_explicit_args(self):
        """Tests that EdieChunkProcessor with explicit args survives a pickle round-trip."""
        # Arrange
        p = EdieChunkProcessor(chunk_size=50_000, compression="snappy")
        # Act
        restored = pickle.loads(pickle.dumps(p))
        # Assert
        assert restored._compression == "snappy"

    def test_process_signature(self):
        """Tests that process has the expected parameter names."""
        # Act
        sig = inspect.signature(EdieChunkProcessor.process)
        params = list(sig.parameters)
        # Assert
        assert params == [
            "self", "file_path", "start_byte",
            "end_byte", "worker_id", "temp_dir", "progress",
        ]


class TestParquetMergerConformance:
    """Tests for ParquetMerger protocol conformance."""

    def test_has_merge(self):
        """Tests that ParquetMerger exposes a callable merge method."""
        # Act
        m = ParquetMerger()
        # Assert
        assert callable(getattr(m, "merge", None))

    def test_is_picklable_with_defaults(self):
        """Tests that ParquetMerger with defaults survives a pickle round-trip."""
        # Act
        m = ParquetMerger()
        restored = pickle.loads(pickle.dumps(m))
        # Assert
        assert isinstance(restored, ParquetMerger)

    def test_is_picklable_with_explicit_compression(self):
        """Tests that ParquetMerger with explicit compression survives a pickle round-trip."""
        # Arrange
        m = ParquetMerger(compression="snappy")
        # Act
        restored = pickle.loads(pickle.dumps(m))
        # Assert
        assert restored._compression == "snappy"

    def test_merge_signature(self):
        """Tests that merge has the expected parameter names."""
        # Act
        sig = inspect.signature(ParquetMerger.merge)
        params = list(sig.parameters)
        # Assert
        assert params == ["self", "worker_results", "output_dir"]


class TestPublicExports:
    """Tests that public symbols are importable from nov_gnsspq.writer."""

    def test_boundary_splitter_importable_from_writer(self):
        """Tests that BoundarySplitter is importable from nov_gnsspq.writer."""
        # Act & Assert
        from nov_gnsspq.writer import BoundarySplitter  # noqa: F401

    def test_chunk_processor_importable_from_writer(self):
        """Tests that ChunkProcessor is importable from nov_gnsspq.writer."""
        # Act & Assert
        from nov_gnsspq.writer import ChunkProcessor  # noqa: F401

    def test_parallel_file_engine_importable_from_writer(self):
        """Tests that ParallelFileEngine is importable from nov_gnsspq.writer."""
        # Act & Assert
        from nov_gnsspq.writer import ParallelFileEngine  # noqa: F401

    def test_result_merger_importable_from_writer(self):
        """Tests that ResultMerger is importable from nov_gnsspq.writer."""
        # Act & Assert
        from nov_gnsspq.writer import ResultMerger  # noqa: F401

    def test_worker_result_importable_from_writer(self):
        """Tests that WorkerResult is importable from nov_gnsspq.writer."""
        # Act & Assert
        from nov_gnsspq.writer import WorkerResult  # noqa: F401
