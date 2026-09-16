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

Integration tests for ParallelFileEngine using stub components.
"""
import json
import pickle
from pathlib import Path

import pytest

from nov_gnsspq.exceptions import ParallelEngineError
from nov_gnsspq.writer.parallel.engine import ParallelFileEngine


# ---------------------------------------------------------------------------
# Stub components (module-level for ProcessPoolExecutor picklability)
# ---------------------------------------------------------------------------

class PassthroughSplitter:
    """Stub splitter: returns the candidate offset unchanged."""

    def snap_boundary(self, file_path, candidate_offset):
        """Returns candidate_offset unchanged."""
        return candidate_offset


class JsonChunkProcessor:
    """Stub processor: writes a JSON file per chunk, returns a result dict."""

    def process(self, file_path, start_byte, end_byte, worker_id, temp_dir,
                progress=None):
        """Processes a chunk by writing a JSON result file."""
        temp_dir = Path(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        data = {"worker_id": worker_id, "bytes": end_byte - start_byte}
        out = temp_dir / "result.json"
        out.write_text(json.dumps(data))
        return {
            "worker_id": worker_id,
            "path": str(out),
            "bytes": end_byte - start_byte,
        }


class JsonMerger:
    """Stub merger: concatenates all worker result dicts into combined.json."""

    def merge(self, worker_results, output_dir):
        """Merges worker results into combined.json."""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "combined.json").write_text(
            json.dumps(worker_results)
        )


class BrokenProcessor:
    """Stub processor that always raises."""

    def process(self, *args, **kwargs):
        """Always raises ValueError."""
        raise ValueError("processor failed deliberately")


# pylint: disable=protected-access


class TestParallelFileEngineOrchestration:
    """Tests for ParallelFileEngine end-to-end orchestration."""

    @pytest.fixture
    def source_file(self, tmp_path):
        """Provides a 10 000-byte binary source file."""
        f = tmp_path / "source.bin"
        f.write_bytes(b"x" * 10_000)
        return f

    def test_chunks_cover_full_file(self, source_file, tmp_path):
        """Tests that the sum of chunk byte ranges equals the file size."""
        # Arrange
        out = tmp_path / "out"
        engine = ParallelFileEngine(
            splitter=PassthroughSplitter(),
            processor=JsonChunkProcessor(),
            merger=JsonMerger(),
            num_workers=4,
        )
        # Act
        engine.run(source_file, out)
        results = json.loads((out / "combined.json").read_text())
        total_bytes = sum(r["bytes"] for r in results)
        # Assert
        assert total_bytes == source_file.stat().st_size

    def test_correct_number_of_workers(self, source_file, tmp_path):
        """Tests that the merger receives exactly num_workers results."""
        # Arrange
        out = tmp_path / "out"
        engine = ParallelFileEngine(
            splitter=PassthroughSplitter(),
            processor=JsonChunkProcessor(),
            merger=JsonMerger(),
            num_workers=3,
        )
        # Act
        engine.run(source_file, out)
        results = json.loads((out / "combined.json").read_text())
        # Assert
        assert len(results) == 3

    def test_results_sorted_by_worker_id(self, source_file, tmp_path):
        """Tests that the merger receives results sorted ascending by worker_id."""
        # Arrange
        out = tmp_path / "out"
        engine = ParallelFileEngine(
            splitter=PassthroughSplitter(),
            processor=JsonChunkProcessor(),
            merger=JsonMerger(),
            num_workers=3,
        )
        # Act
        engine.run(source_file, out)
        results = json.loads((out / "combined.json").read_text())
        worker_ids = [r["worker_id"] for r in results]
        # Assert
        assert worker_ids == sorted(worker_ids)

    def test_run_creates_output(self, source_file, tmp_path):
        """Tests that engine.run writes combined.json for a simple binary file."""
        # Arrange
        out = tmp_path / "out"
        engine = ParallelFileEngine(
            splitter=PassthroughSplitter(),
            processor=JsonChunkProcessor(),
            merger=JsonMerger(),
            num_workers=2,
        )
        # Act
        engine.run(source_file, out)
        # Assert
        assert (out / "combined.json").exists()


class TestParallelFileEngineDefaults:
    """Tests for ParallelFileEngine default component resolution."""

    def test_custom_merger_replaces_default(self):
        """Tests that a custom merger replaces the default ParquetMerger."""
        # Act
        engine = ParallelFileEngine(merger=JsonMerger())
        # Assert
        assert isinstance(engine._merger, JsonMerger)

    def test_custom_processor_replaces_default(self):
        """Tests that a custom processor replaces the default EdieChunkProcessor."""
        # Act
        engine = ParallelFileEngine(processor=JsonChunkProcessor())
        # Assert
        assert isinstance(engine._processor, JsonChunkProcessor)

    def test_custom_splitter_replaces_default(self):
        """Tests that a custom splitter replaces the default EdieFramerSplitter."""
        # Act
        engine = ParallelFileEngine(splitter=PassthroughSplitter())
        # Assert
        assert isinstance(engine._splitter, PassthroughSplitter)

    def test_defaults_are_edie_parquet(self):
        """Tests that None components resolve to EDIE+Parquet defaults."""
        # Arrange
        from nov_gnsspq.writer.parallel.edie import (
            EdieChunkProcessor,
            EdieFramerSplitter,
        )
        from nov_gnsspq.writer.parallel.merger import ParquetMerger
        # Act
        engine = ParallelFileEngine()
        # Assert
        assert isinstance(engine._splitter, EdieFramerSplitter)
        assert isinstance(engine._processor, EdieChunkProcessor)
        assert isinstance(engine._merger, ParquetMerger)


class TestParallelFileEngineErrorHandling:
    """Tests for ParallelFileEngine error propagation."""

    @pytest.fixture
    def source_file(self, tmp_path):
        """Provides a 10 000-byte binary source file."""
        f = tmp_path / "source.bin"
        f.write_bytes(b"x" * 10_000)
        return f

    def test_parallel_engine_error_chains_original(self, source_file, tmp_path):
        """Tests that the original processor exception is chained as __cause__."""
        # Arrange
        engine = ParallelFileEngine(
            splitter=PassthroughSplitter(),
            processor=BrokenProcessor(),
            merger=JsonMerger(),
            num_workers=2,
        )
        # Act & Assert
        with pytest.raises(ParallelEngineError) as exc_info:
            engine.run(source_file, tmp_path / "out")
        assert exc_info.value.__cause__ is not None

    def test_parallel_engine_error_has_worker_id(self, source_file, tmp_path):
        """Tests that the raised ParallelEngineError carries an integer worker_id."""
        # Arrange
        engine = ParallelFileEngine(
            splitter=PassthroughSplitter(),
            processor=BrokenProcessor(),
            merger=JsonMerger(),
            num_workers=2,
        )
        # Act & Assert
        with pytest.raises(ParallelEngineError) as exc_info:
            engine.run(source_file, tmp_path / "out")
        assert isinstance(exc_info.value.worker_id, int)

    def test_worker_failure_raises_parallel_engine_error(
            self, source_file, tmp_path):
        """Tests that a failing processor raises ParallelEngineError."""
        # Arrange
        engine = ParallelFileEngine(
            splitter=PassthroughSplitter(),
            processor=BrokenProcessor(),
            merger=JsonMerger(),
            num_workers=2,
        )
        # Act & Assert
        with pytest.raises(ParallelEngineError):
            engine.run(source_file, tmp_path / "out")


class TestStubsArePicklable:
    """Tests that stubs are picklable for use with ProcessPoolExecutor."""

    def test_json_chunk_processor_picklable(self):
        """Tests that JsonChunkProcessor can be pickled."""
        # Act & Assert
        assert pickle.dumps(JsonChunkProcessor())

    def test_json_merger_picklable(self):
        """Tests that JsonMerger can be pickled."""
        # Act & Assert
        assert pickle.dumps(JsonMerger())

    def test_passthrough_splitter_picklable(self):
        """Tests that PassthroughSplitter can be pickled."""
        # Act & Assert
        assert pickle.dumps(PassthroughSplitter())


class TestParallelFileEngineComputeBoundaries:
    """Tests for ParallelFileEngine._compute_boundaries."""

    def _engine_with_file(self, gps_file, tmp_path, num_workers=2):
        """Returns a ParallelFileEngine configured with stub components."""
        return ParallelFileEngine(
            splitter=PassthroughSplitter(),
            processor=JsonChunkProcessor(),
            merger=JsonMerger(),
            num_workers=num_workers,
        )

    def test_boundaries_are_strictly_increasing(self, tmp_path):
        """Tests that all boundary values are strictly increasing."""
        # Arrange
        f = tmp_path / "test.gps"
        f.write_bytes(b"x" * 1000)
        engine = self._engine_with_file(f, tmp_path, num_workers=3)
        # Act
        boundaries = engine._compute_boundaries(f, f.stat().st_size, 3)
        # Assert
        for i in range(1, len(boundaries)):
            assert boundaries[i] > boundaries[i - 1]

    def test_first_boundary_is_zero(self, tmp_path):
        """Tests that the first boundary is always zero."""
        # Arrange
        f = tmp_path / "test.gps"
        f.write_bytes(b"x" * 1000)
        engine = self._engine_with_file(f, tmp_path, num_workers=2)
        # Act
        boundaries = engine._compute_boundaries(f, f.stat().st_size, 2)
        # Assert
        assert boundaries[0] == 0

    def test_last_boundary_is_file_size(self, tmp_path):
        """Tests that the last boundary equals the file size."""
        # Arrange
        f = tmp_path / "test.gps"
        f.write_bytes(b"x" * 1000)
        engine = self._engine_with_file(f, tmp_path, num_workers=2)
        file_size = f.stat().st_size
        # Act
        boundaries = engine._compute_boundaries(f, file_size, 2)
        # Assert
        assert boundaries[-1] == file_size

    def test_no_duplicate_boundaries(self, tmp_path):
        """Tests that no two adjacent boundaries are identical."""
        # Arrange
        f = tmp_path / "test.gps"
        f.write_bytes(b"x" * 1000)
        engine = self._engine_with_file(f, tmp_path, num_workers=4)
        # Act
        boundaries = engine._compute_boundaries(f, f.stat().st_size, 4)
        # Assert
        for i in range(1, len(boundaries)):
            assert boundaries[i] != boundaries[i - 1]

    def test_one_worker_produces_two_boundaries(self, tmp_path):
        """Tests that a single worker yields exactly two boundaries."""
        # Arrange
        f = tmp_path / "test.gps"
        f.write_bytes(b"x" * 1000)
        engine = self._engine_with_file(f, tmp_path, num_workers=1)
        # Act
        boundaries = engine._compute_boundaries(f, f.stat().st_size, 1)
        # Assert
        assert len(boundaries) == 2
