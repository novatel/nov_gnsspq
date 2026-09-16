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

Unit tests for the ParallelGPSWriter class in nov_gnsspq.writer.parallel.
"""
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from nov_gnsspq.exceptions import ParallelEngineError
from nov_gnsspq.reader.schema import METADATA_FILENAME, SEQUENCE_ID_COL
from nov_gnsspq.writer.parallel import ParallelGPSWriter
from nov_gnsspq.writer.parallel.engine import PARALLEL_MIN_BYTES


# pylint: disable=protected-access


class TestParallelGPSWriterInit:
    """Tests for the ParallelGPSWriter constructor."""

    @pytest.fixture()
    def gps_file(self, tmp_path):
        """Provides a small fake GPS file."""
        f = tmp_path / "test.gps"
        f.write_bytes(b"x" * 1000)
        return f

    def test_stores_input_file(self, gps_file, tmp_path):
        """Tests input_file is stored on the instance."""
        # Act
        pw = ParallelGPSWriter(str(gps_file), str(tmp_path / "out"))
        # Assert
        assert pw.input_file == str(gps_file)

    def test_stores_output_folder(self, gps_file, tmp_path):
        """Tests output_folder is stored on the instance."""
        # Arrange
        out = str(tmp_path / "out")
        # Act
        pw = ParallelGPSWriter(str(gps_file), out)
        # Assert
        assert pw.output_folder == out

    def test_default_compression_is_zstd(self, gps_file, tmp_path):
        """Tests the default compression codec is 'zstd'."""
        # Act
        pw = ParallelGPSWriter(str(gps_file), str(tmp_path / "out"))
        # Assert
        assert pw.compression == "zstd"

    def test_custom_compression(self, gps_file, tmp_path):
        """Tests a custom compression codec is stored."""
        # Act
        pw = ParallelGPSWriter(
            str(gps_file), str(tmp_path / "out"), compression="snappy")
        # Assert
        assert pw.compression == "snappy"

    def test_explicit_num_workers_stored(self, gps_file, tmp_path):
        """Tests an explicit num_workers overrides the auto-tune result."""
        # Act
        pw = ParallelGPSWriter(
            str(gps_file), str(tmp_path / "out"), num_workers=3)
        # Assert
        assert pw._num_workers == 3

    def test_auto_tune_workers_when_num_workers_none(self, gps_file, tmp_path):
        """Tests _num_workers is set from auto-tune when not supplied."""
        # Act
        pw = ParallelGPSWriter(str(gps_file), str(tmp_path / "out"))
        # Assert
        assert pw._num_workers >= 2

    def test_explicit_chunk_size_stored(self, gps_file, tmp_path):
        """Tests an explicit chunk_size overrides auto-tune."""
        # Act
        pw = ParallelGPSWriter(
            str(gps_file), str(tmp_path / "out"), chunk_size=55_555)
        # Assert
        assert pw._chunk_size == 55_555

    def test_auto_tune_chunk_size_when_none(self, gps_file, tmp_path):
        """Tests _chunk_size is set by auto-tune when not supplied."""
        # Act
        pw = ParallelGPSWriter(str(gps_file), str(tmp_path / "out"))
        # Assert
        assert pw._chunk_size > 0


class TestWriteToDbSmallFileFallback:
    """Tests for write_to_db delegating to GPSWriter for small files."""

    @pytest.fixture()
    def gps_file(self, tmp_path):
        """Provides a small fake GPS file below the parallel threshold."""
        f = tmp_path / "test.gps"
        f.write_bytes(b"x" * 1000)
        return f

    def test_small_file_delegates_to_gps_writer(self, gps_file, tmp_path):
        """Tests a file below 50 MB is processed by the single-threaded GPSWriter."""
        # Arrange
        out = str(tmp_path / "out")
        pw = ParallelGPSWriter(str(gps_file), out)
        # Act & Assert
        with patch("nov_gnsspq.writer.parallel.GPSWriter") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            pw.write_to_db()
        mock_cls.assert_called_once()
        mock_instance.write_to_db.assert_called_once()

    def test_small_file_passes_compression_to_fallback_writer(
            self, gps_file, tmp_path):
        """Tests compression is forwarded to the fallback GPSWriter."""
        # Arrange
        out = str(tmp_path / "out")
        pw = ParallelGPSWriter(str(gps_file), out, compression="snappy")
        # Act & Assert
        with patch("nov_gnsspq.writer.parallel.GPSWriter") as mock_cls:
            mock_cls.return_value = MagicMock()
            pw.write_to_db()
        call_kwargs = mock_cls.call_args
        assert (
            call_kwargs.kwargs.get("compression") == "snappy"
            or "snappy" in str(call_kwargs)
        )

class TestWriteToDbParallelPath:
    """Tests for write_to_db parallel execution with mocked workers."""

    @pytest.fixture()
    def large_gps_file(self, tmp_path):
        """Provides a fake GPS file that exceeds the parallel threshold."""
        f = tmp_path / "large.gps"
        f.write_bytes(b"x" * (PARALLEL_MIN_BYTES + 1))
        return f

    def _make_worker_result(
            self,
            worker_id: int,
            worker_dir: str,
            total_messages: int) -> dict:
        """Builds a minimal worker result dict."""
        log_path = os.path.join(
            worker_dir, f"log_table_w{worker_id}.parquet")
        unknown_path = os.path.join(
            worker_dir, f"unknown_w{worker_id}.parquet")
        pq.write_table(
            pa.table({
                "log": pa.array([], type=pa.string()),
                SEQUENCE_ID_COL: pa.array([], type=pa.int64()),
            }),
            log_path,
        )
        pq.write_table(
            pa.schema([
                (SEQUENCE_ID_COL, pa.int64()),
                ("payload", pa.binary()),
            ]).empty_table(),
            unknown_path,
        )
        return {
            "worker_id": worker_id,
            "total_messages": total_messages,
            "worker_output_dir": worker_dir,
            "table_tree": {},
            "log_table_path": log_path,
            "unknown_path": unknown_path,
        }

    def test_large_file_spawns_worker_processes(
            self, large_gps_file, tmp_path):
        """Tests write_to_db delegates to engine.run for large files."""
        # Arrange
        out = str(tmp_path / "out_large")
        pw = ParallelGPSWriter(str(large_gps_file), out, num_workers=2)
        # Act & Assert
        with patch.object(pw._engine, "run") as mock_run:
            mock_run.side_effect = lambda *a, **kw: None
            with patch.object(
                    pw._engine, "_last_actual_workers", 2, create=True):
                with patch(
                        "nov_gnsspq.writer.parallel.GPSWriter"
                        "._compute_sha256",
                        return_value="abc"):
                    try:
                        pw.write_to_db()
                    except Exception:
                        pass
        mock_run.assert_called_once()

    def test_metadata_written_after_parallel_merge(
            self, large_gps_file, tmp_path):
        """Tests _metadata.json is written after engine.run completes."""
        # Arrange
        out = tmp_path / "out_meta"
        pw = ParallelGPSWriter(
            str(large_gps_file), str(out), num_workers=2)
        db_name = out.name
        log_parquet = out / f"{db_name}.parquet"

        def fake_run(file_path, output_dir):
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            pq.write_table(
                pa.table({
                    "log": pa.array(
                        ["BESTPOS"] * 7, type=pa.string()),
                    SEQUENCE_ID_COL: pa.array(
                        list(range(7)), type=pa.int64()),
                }),
                str(log_parquet),
            )
            pw._engine._last_actual_workers = 2

        # Act
        with patch.object(pw._engine, "run", side_effect=fake_run):
            with patch(
                    "nov_gnsspq.writer.parallel.GPSWriter._compute_sha256",
                    return_value="deadbeef"):
                pw.write_to_db()

        # Assert
        with open(out / METADATA_FILENAME) as f:
            meta = json.load(f)
        assert meta["sha256"] == "deadbeef"
        assert meta["total_message_count"] == 7
        assert meta["parallel_workers"] == 2


class TestWriteToDbWorkerFailure:
    """Tests for the exception-propagation path when a worker fails."""

    @pytest.fixture()
    def large_gps_file(self, tmp_path):
        """Provides a fake GPS file that exceeds the parallel threshold."""
        f = tmp_path / "large.gps"
        f.write_bytes(b"x" * (PARALLEL_MIN_BYTES + 1))
        return f

    def test_worker_exception_raises_parallel_engine_error(
            self, large_gps_file, tmp_path):
        """Tests a failing engine.run propagates ParallelEngineError."""
        # Arrange
        out = str(tmp_path / "out_fail")
        pw = ParallelGPSWriter(str(large_gps_file), out, num_workers=1)
        # Act & Assert
        with patch.object(
                pw._engine,
                "run",
                side_effect=ParallelEngineError(
                    "worker 0 failed", worker_id=0, byte_range=(0, 100)
                )):
            with patch(
                    "nov_gnsspq.writer.parallel.GPSWriter._compute_sha256",
                    return_value="abc"):
                with pytest.raises(
                        ParallelEngineError, match="worker 0 failed"):
                    pw.write_to_db()


