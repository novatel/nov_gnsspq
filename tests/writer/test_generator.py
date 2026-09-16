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

Unit tests for the PqConverter public API in nov_gnsspq.writer.generator.
"""
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nov_gnsspq.exceptions import DatabaseExistsError, WriteError
from nov_gnsspq.reader.schema import METADATA_FILENAME, SEQUENCE_ID_COL
from nov_gnsspq.writer.generator import PqConverter


# pylint: disable=protected-access


@pytest.fixture()
def gps_file(tmp_path):
    """Provides a tiny fake GPS file on disk."""
    f = tmp_path / "recording.gps"
    f.write_bytes(b"dummy")
    return f


@pytest.fixture()
def open_generator(tmp_path):
    """Provides an already-entered PqConverter for streaming tests."""
    with PqConverter(tmp_path / "stream_out") as gen:
        yield gen


class TestPqConverterInit:
    """Tests for the PqConverter constructor."""

    def test_stores_output_dir_as_path(self, tmp_path):
        """Tests output_dir is stored as a Path object."""
        # Act
        gen = PqConverter(tmp_path / "out")
        # Assert
        assert isinstance(gen._output_dir, Path)

    def test_string_path_converted_to_path(self, tmp_path):
        """Tests a string output_dir is converted to Path."""
        # Act
        gen = PqConverter(str(tmp_path / "out"))
        # Assert
        assert isinstance(gen._output_dir, Path)

    def test_default_overwrite_false(self, tmp_path):
        """Tests overwrite defaults to False."""
        # Act
        gen = PqConverter(tmp_path / "out")
        # Assert
        assert gen._overwrite is False

    def test_default_parallel_false(self, tmp_path):
        """Tests parallel defaults to None."""
        # Act
        gen = PqConverter(tmp_path / "out")
        # Assert
        assert gen._parallel is None

    def test_custom_flags_stored(self, tmp_path):
        """Tests custom constructor flags are stored correctly."""
        # Act
        gen = PqConverter(
            tmp_path / "out",
            overwrite=True,
            parallel=True,
        )
        # Assert
        assert gen._overwrite is True
        assert gen._parallel is True

    def test_not_open_before_enter(self, tmp_path):
        """Tests _open is False before __enter__ is called."""
        # Act
        gen = PqConverter(tmp_path / "out")
        # Assert
        assert gen._open is False

    def test_tables_start_empty(self, tmp_path):
        """Tests internal streaming tables start empty."""
        # Act
        gen = PqConverter(tmp_path / "out")
        # Assert
        assert gen._tables == {}

    def test_sequence_id_starts_at_zero(self, tmp_path):
        """Tests the streaming sequence counter starts at zero."""
        # Act
        gen = PqConverter(tmp_path / "out")
        # Assert
        assert gen._sequence_id == 0


class TestContextManager:
    """Tests for PqConverter __enter__ and __exit__ behaviour."""

    def test_enter_creates_output_directory(self, tmp_path):
        """Tests __enter__ creates the output directory."""
        # Arrange
        out = tmp_path / "new_db"
        # Act & Assert
        with PqConverter(out):
            assert out.exists()

    def test_enter_creates_nested_output_directory(self, tmp_path):
        """Tests __enter__ creates parent directories recursively."""
        # Arrange
        out = tmp_path / "level1" / "level2" / "db"
        # Act & Assert
        with PqConverter(out):
            assert out.exists()

    def test_enter_returns_self(self, tmp_path):
        """Tests __enter__ returns the generator instance."""
        # Arrange
        gen = PqConverter(tmp_path / "out")
        # Act
        result = gen.__enter__()
        gen.__exit__(None, None, None)
        # Assert
        assert result is gen

    def test_enter_sets_open_flag(self, tmp_path):
        """Tests _open is True inside the context."""
        # Act & Assert
        with PqConverter(tmp_path / "out") as gen:
            assert gen._open is True

    def test_exit_clears_open_flag(self, tmp_path):
        """Tests _open is False after __exit__."""
        # Arrange
        gen = PqConverter(tmp_path / "out")
        # Act
        with gen:
            pass
        # Assert
        assert gen._open is False

    def test_enter_raises_database_exists_error_when_metadata_present(
            self, tmp_path):
        """Tests DatabaseExistsError is raised when _metadata.json exists."""
        # Arrange
        out = tmp_path / "existing_db"
        out.mkdir()
        (out / METADATA_FILENAME).write_text("{}")
        # Act & Assert
        with pytest.raises(DatabaseExistsError, match="already contains"):
            with PqConverter(out):
                pass

    def test_enter_allows_overwrite_when_flag_set(self, tmp_path):
        """Tests no error is raised when overwrite=True and metadata exists."""
        # Arrange
        out = tmp_path / "existing_db"
        out.mkdir()
        (out / METADATA_FILENAME).write_text("{}")
        # Act & Assert
        with PqConverter(out, overwrite=True) as gen:
            assert gen._open is True

    def test_exit_skips_finalize_on_exception(self, tmp_path):
        """Tests __exit__ does not call _finalize when an exception occurred."""
        # Arrange
        gen = PqConverter(tmp_path / "out")
        with patch.object(gen, "_finalize") as mock_finalize:
            try:
                with gen:
                    raise ValueError("simulated error")
            except ValueError:
                pass
        # Assert
        mock_finalize.assert_not_called()

    def test_exit_calls_finalize_in_streaming_mode(self, tmp_path):
        """Tests __exit__ calls _finalize when no file-writer was used."""
        # Arrange
        gen = PqConverter(tmp_path / "out")
        with patch.object(gen, "_finalize") as mock_finalize:
            # Act
            with gen:
                pass
        # Assert
        mock_finalize.assert_called_once()

    def test_exit_skips_finalize_when_file_writer_used(
            self, tmp_path, gps_file):
        """Tests __exit__ does not call _finalize when a file-writer was assigned."""
        # Arrange
        with patch("nov_gnsspq.writer.generator.GPSWriter") as mock_cls:
            mock_cls.return_value = MagicMock()
            gen = PqConverter(tmp_path / "out")
            with patch.object(gen, "_finalize") as mock_finalize:
                # Act
                with gen:
                    gen._run_file_writer(str(gps_file))
        # Assert
        mock_finalize.assert_not_called()


class TestConsumeMethod:
    """Tests for the PqConverter consume() public method."""

    def test_raises_when_not_open(self, tmp_path):
        """Tests RuntimeError is raised when consume is called outside context."""
        # Arrange
        gen = PqConverter(tmp_path / "out")
        # Act & Assert
        with pytest.raises(RuntimeError, match="context manager"):
            gen.consume("some/path.gps")

    def test_string_path_triggers_file_writer(self, tmp_path, gps_file):
        """Tests a string path delegates to the file-writer path."""
        # Arrange
        with patch("nov_gnsspq.writer.generator.GPSWriter") as mock_cls:
            mock_writer = MagicMock()
            mock_cls.return_value = mock_writer
            # Act
            with PqConverter(tmp_path / "out") as gen:
                gen.consume(str(gps_file))
        # Assert
        mock_writer.write_to_db.assert_called_once()

    def test_path_object_triggers_file_writer(self, tmp_path, gps_file):
        """Tests a Path object delegates to the file-writer path."""
        # Arrange
        with patch("nov_gnsspq.writer.generator.GPSWriter") as mock_cls:
            mock_cls.return_value = MagicMock()
            # Act
            with PqConverter(tmp_path / "out") as gen:
                gen.consume(gps_file)
        # Assert
        mock_cls.return_value.write_to_db.assert_called_once()

    def test_iterable_uses_streaming_mode(self, tmp_path):
        """Tests consuming a plain iterable uses the streaming write path."""
        # Arrange
        with PqConverter(tmp_path / "out") as gen:
            with patch.object(gen, "_write_record") as mock_write:
                # Act
                gen.consume(iter(["a", "b", "c"]))
        # Assert
        assert mock_write.call_count == 3

    def test_file_parser_with_accessible_path_triggers_file_writer(
            self, tmp_path, gps_file):
        """Tests a FileParser with a readable path attr uses the file writer."""
        # Arrange
        import novatel_edie.oem as ne_oem
        parser = MagicMock(spec=ne_oem.FileParser)
        parser.file_path = str(gps_file)
        with patch("nov_gnsspq.writer.generator.GPSWriter") as mock_cls:
            mock_cls.return_value = MagicMock()
            # Act
            with PqConverter(tmp_path / "out") as gen:
                gen.consume(parser)
        # Assert
        mock_cls.return_value.write_to_db.assert_called_once()

    def test_file_parser_without_path_falls_back_to_streaming(self, tmp_path):
        """Tests a FileParser without a path attribute falls back to streaming."""
        # Arrange
        import novatel_edie.oem as ne_oem
        parser = MagicMock(spec=ne_oem.FileParser)
        del parser.file_path
        del parser._file_path
        del parser.filename
        del parser.path
        items = [MagicMock(), MagicMock()]
        parser.__iter__ = MagicMock(return_value=iter(items))
        with PqConverter(tmp_path / "out") as gen:
            with patch.object(gen, "_write_record") as mock_write:
                # Act
                gen.consume(parser)
        # Assert
        assert mock_write.call_count == 2


class TestWriteMethod:
    """Tests for the PqConverter single-record write() method."""

    def test_raises_when_not_open(self, tmp_path):
        """Tests RuntimeError is raised when write is called outside context."""
        # Arrange
        gen = PqConverter(tmp_path / "out")
        # Act & Assert
        with pytest.raises(RuntimeError, match="context manager"):
            gen.write("record")

    def test_delegates_to_write_record(self, open_generator):
        """Tests write() calls _write_record with the given record."""
        # Arrange
        with patch.object(open_generator, "_write_record") as mock_wr:
            # Act
            open_generator.write("fake_record")
        # Assert
        mock_wr.assert_called_once_with("fake_record")


class TestExtractFilePath:
    """Tests for the PqConverter._extract_file_path static method."""

    def test_string_source_returns_string(self):
        """Tests a string source returns itself."""
        # Act
        result = PqConverter._extract_file_path("data/file.gps")
        # Assert
        assert result == "data/file.gps"

    def test_path_object_returns_string(self):
        """Tests a Path source returns its string representation."""
        # Act
        result = PqConverter._extract_file_path(Path("data/file.gps"))
        # Assert
        assert result == str(Path("data/file.gps"))

    def test_file_parser_with_file_path_attr(self, tmp_path, gps_file):
        """Tests a FileParser with .file_path returns that path."""
        # Arrange
        import novatel_edie.oem as ne_oem
        parser = MagicMock(spec=ne_oem.FileParser)
        parser.file_path = str(gps_file)
        # Act
        result = PqConverter._extract_file_path(parser)
        # Assert
        assert result == str(gps_file)

    def test_file_parser_without_path_attr_returns_none(self):
        """Tests a FileParser without any known path attribute returns None."""
        # Arrange
        import novatel_edie.oem as ne_oem
        parser = MagicMock(spec=ne_oem.FileParser)
        for attr in ("file_path", "_file_path", "filename", "path"):
            try:
                delattr(parser, attr)
            except AttributeError:
                pass
        # Act
        result = PqConverter._extract_file_path(parser)
        # Assert
        assert result is None

    def test_arbitrary_iterable_returns_none(self):
        """Tests an arbitrary iterable (not str/Path/FileParser) returns None."""
        # Act
        result = PqConverter._extract_file_path([1, 2, 3])
        # Assert
        assert result is None

    def test_none_source_returns_none(self):
        """Tests None source returns None."""
        # Act
        result = PqConverter._extract_file_path(None)
        # Assert
        assert result is None


class TestRunFileWriter:
    """Tests for the PqConverter._run_file_writer internal method."""

    def test_default_mode_uses_gps_writer(self, tmp_path, gps_file):
        """Tests GPSWriter is used by default (parallel=False)."""
        # Arrange
        gen = PqConverter(tmp_path / "out")
        gen._output_dir.mkdir(parents=True, exist_ok=True)
        gen._open = True
        with patch("nov_gnsspq.writer.generator.GPSWriter") as mock_cls:
            mock_cls.return_value = MagicMock()
            # Act
            gen._run_file_writer(str(gps_file))
        # Assert
        mock_cls.assert_called()
        mock_cls.return_value.write_to_db.assert_called_once()

    def test_parallel_flag_uses_parallel_writer(self, tmp_path, gps_file):
        """Tests ParallelGPSWriter is used when parallel=True."""
        # Arrange
        gen = PqConverter(tmp_path / "out", parallel=True)
        gen._output_dir.mkdir(parents=True, exist_ok=True)
        gen._open = True
        with patch(
                "nov_gnsspq.writer.generator.ParallelGPSWriter") as mock_cls:
            mock_cls.return_value = MagicMock()
            # Act
            gen._run_file_writer(str(gps_file))
        # Assert
        mock_cls.assert_called()
        mock_cls.return_value.write_to_db.assert_called_once()

    def test_os_error_from_writer_wrapped_in_write_error(
            self, tmp_path, gps_file):
        """Tests an OSError raised inside the writer is re-raised as WriteError."""
        # Arrange
        gen = PqConverter(tmp_path / "out")
        gen._output_dir.mkdir(parents=True, exist_ok=True)
        gen._open = True
        with patch("nov_gnsspq.writer.generator.GPSWriter") as mock_cls:
            mock_cls.side_effect = OSError("disk full")
            # Act & Assert
            with pytest.raises(WriteError, match="disk full"):
                gen._run_file_writer(str(gps_file))


class TestWriteRecord:
    """Tests for the PqConverter._write_record streaming method."""

    def test_known_message_accumulates_in_tables(self, tmp_path):
        """Tests a ne.Message is added to _tables under its log_type."""
        # Arrange
        class FakeMsg:
            name = "BESTPOS"
            def to_dict(self): return {"header": {"week": 2200}, "lat": 51.0}

        gen = PqConverter(tmp_path / "out")
        gen._output_dir.mkdir()
        with patch("nov_gnsspq.writer.generator.ne") as mock_ne, \
                patch("nov_gnsspq.writer.generator.ne_oem") as mock_ne_oem:
            mock_ne_oem.Message = FakeMsg
            mock_ne_oem.UnknownMessage = type("UM", (), {})
            mock_ne.UnknownBytes = type("UB", (), {})
            # Act
            gen._write_record(FakeMsg())
        # Assert
        assert "BESTPOS" in gen._tables

    def test_known_message_appended_to_log_table(self, tmp_path):
        """Tests the log type is recorded in _log_table_cols."""
        # Arrange
        class FakeMsg:
            name = "RANGE"
            def to_dict(self): return {"header": {}, "data": 1}

        gen = PqConverter(tmp_path / "out")
        gen._output_dir.mkdir()
        with patch("nov_gnsspq.writer.generator.ne") as mock_ne, \
                patch("nov_gnsspq.writer.generator.ne_oem") as mock_ne_oem:
            mock_ne_oem.Message = FakeMsg
            mock_ne_oem.UnknownMessage = type("UM", (), {})
            mock_ne.UnknownBytes = type("UB", (), {})
            # Act
            gen._write_record(FakeMsg())
        # Assert
        assert gen._log_table_cols["log"] == ["RANGE"]

    def test_sequence_id_increments_after_each_record(self, tmp_path):
        """Tests _sequence_id increments by one per record written."""
        # Arrange
        class FakeMsg:
            name = "T"
            def to_dict(self): return {"header": {}}

        gen = PqConverter(tmp_path / "out")
        gen._output_dir.mkdir()
        with patch("nov_gnsspq.writer.generator.ne") as mock_ne, \
                patch("nov_gnsspq.writer.generator.ne_oem") as mock_ne_oem:
            mock_ne_oem.Message = FakeMsg
            mock_ne_oem.UnknownMessage = type("UM", (), {})
            mock_ne.UnknownBytes = type("UB", (), {})
            # Act
            gen._write_record(FakeMsg())
            gen._write_record(FakeMsg())
        # Assert
        assert gen._sequence_id == 2

    def test_unknown_message_stored_in_unknown_cols(self, tmp_path):
        """Tests ne.UnknownMessage payload is stored in _unknown_cols."""
        # Arrange
        class FakeUnknown:
            payload = b"\xAA\xBB"

        gen = PqConverter(tmp_path / "out")
        gen._output_dir.mkdir()
        with patch("nov_gnsspq.writer.generator.ne") as mock_ne, \
                patch("nov_gnsspq.writer.generator.ne_oem") as mock_ne_oem:
            mock_ne_oem.Message = type("Msg", (), {})
            mock_ne_oem.UnknownMessage = FakeUnknown
            mock_ne.UnknownBytes = type("UB", (), {})
            # Act
            gen._write_record(FakeUnknown())
        # Assert
        assert gen._unknown_cols["payload"] == [b"\xAA\xBB"]
        assert gen._log_table_cols["log"] == ["UNKNOWN"]

    def test_unknown_bytes_stored_in_unknown_cols(self, tmp_path):
        """Tests ne.UnknownBytes payload is stored in _unknown_cols."""
        # Arrange
        class FakeUB:
            data = b"\xCC"

        gen = PqConverter(tmp_path / "out")
        gen._output_dir.mkdir()
        with patch("nov_gnsspq.writer.generator.ne") as mock_ne, \
                patch("nov_gnsspq.writer.generator.ne_oem") as mock_ne_oem:
            mock_ne_oem.Message = type("Msg", (), {})
            mock_ne_oem.UnknownMessage = type("UM", (), {})
            mock_ne.UnknownBytes = FakeUB
            # Act
            gen._write_record(FakeUB())
        # Assert
        assert gen._unknown_cols["payload"] == [b"\xCC"]


class TestFinalize:
    """Tests for the PqConverter._finalize method (streaming mode only)."""

    def test_finalize_writes_metadata_json(self, tmp_path):
        """Tests _finalize writes a _metadata.json with message count."""
        # Arrange
        gen = PqConverter(tmp_path / "finalize_out")
        gen._output_dir.mkdir()
        gen._sequence_id = 5
        # Act
        gen._finalize()
        meta_path = gen._output_dir / METADATA_FILENAME
        # Assert
        assert meta_path.exists()
        with open(meta_path) as f:
            meta = json.load(f)
        assert meta["total_message_count"] == 5
        assert "schema_version" in meta
        assert "writer_version" in meta

    def test_finalize_writes_log_table_when_messages_present(self, tmp_path):
        """Tests _finalize writes log_table.parquet when log entries exist."""
        # Arrange
        import pyarrow.parquet as pq
        gen = PqConverter(tmp_path / "finalize_log")
        gen._output_dir.mkdir()
        gen._log_table_cols = {"log": ["BESTPOS"], SEQUENCE_ID_COL: [0]}
        gen._sequence_id = 1
        # Act
        gen._finalize()
        log_path = gen._output_dir / "log_table.parquet"
        # Assert
        assert log_path.exists()
        table = pq.read_table(str(log_path))
        assert table.num_rows == 1

    def test_finalize_skips_log_table_when_no_messages(self, tmp_path):
        """Tests _finalize does not write log_table.parquet when log is empty."""
        # Arrange
        gen = PqConverter(tmp_path / "finalize_empty")
        gen._output_dir.mkdir()
        # Act
        gen._finalize()
        # Assert
        assert not (gen._output_dir / "log_table.parquet").exists()

    def test_finalize_writes_unknown_table_when_unknowns_present(
            self, tmp_path):
        """Tests _finalize writes unknown_data.parquet when unknowns exist."""
        # Arrange
        import pyarrow.parquet as pq
        gen = PqConverter(tmp_path / "finalize_unk")
        gen._output_dir.mkdir()
        gen._unknown_cols = {SEQUENCE_ID_COL: [0], "payload": [b"\xff"]}
        gen._sequence_id = 1
        # Act
        gen._finalize()
        unk_path = gen._output_dir / "unknown_data.parquet"
        # Assert
        assert unk_path.exists()
        table = pq.read_table(str(unk_path))
        assert table.num_rows == 1

    def test_finalize_skips_unknown_table_when_empty(self, tmp_path):
        """Tests _finalize does not write unknown_data.parquet when empty."""
        # Arrange
        gen = PqConverter(tmp_path / "finalize_nounk")
        gen._output_dir.mkdir()
        # Act
        gen._finalize()
        # Assert
        assert not (gen._output_dir / "unknown_data.parquet").exists()

    def test_context_manager_exit_calls_finalize_in_streaming_mode(
            self, tmp_path):
        """Tests exiting the context manager writes _metadata.json."""
        # Arrange
        out = tmp_path / "ctx_finalize"
        # Act
        with PqConverter(out):
            pass
        # Assert
        assert (out / METADATA_FILENAME).exists()


class TestWriteToDbMethod:
    """Tests for the PqConverter.write_to_db() passthrough method."""

    def test_calls_run_file_writer_for_file_path(
            self, tmp_path, gps_file):
        """Tests write_to_db() delegates to _run_file_writer for a file path."""
        # Arrange
        gen = PqConverter(tmp_path / "out")
        gen._output_dir.mkdir(parents=True, exist_ok=True)
        gen._open = True
        with patch.object(gen, "_run_file_writer") as mock_run:
            # Act
            gen.write_to_db(str(gps_file))
        # Assert
        mock_run.assert_called_once_with(str(gps_file))

    def test_does_nothing_for_non_file_source(self, tmp_path):
        """Tests write_to_db() is a no-op when source has no extractable path."""
        # Arrange
        gen = PqConverter(tmp_path / "out")
        gen._output_dir.mkdir(parents=True, exist_ok=True)
        gen._open = True
        with patch.object(gen, "_run_file_writer") as mock_run:
            # Act
            gen.write_to_db([1, 2, 3])
        # Assert
        mock_run.assert_not_called()


class TestRunFileWriterLargeFile:
    """Tests for the large-file branch in PqConverter._run_file_writer."""

    def test_null_parallel_large_file_auto_selects_parallel_writer(
            self, tmp_path, gps_file):
        """Tests parallel=None + large file auto-selects ParallelGPSWriter."""
        # Arrange
        from nov_gnsspq.writer.parallel.engine import PARALLEL_MIN_BYTES
        gen = PqConverter(tmp_path / "out", parallel=None)
        gen._output_dir.mkdir(parents=True, exist_ok=True)
        gen._open = True
        with patch(
                "nov_gnsspq.writer.generator.os.path.getsize",
                return_value=PARALLEL_MIN_BYTES):
            with patch(
                    "nov_gnsspq.writer.generator.ParallelGPSWriter"
            ) as mock_parallel:
                mock_parallel.return_value = MagicMock()
                with patch(
                        "nov_gnsspq.writer.generator.GPSWriter"
                ) as mock_gps:
                    mock_gps.return_value = MagicMock()
                    # Act
                    gen._run_file_writer(str(gps_file))
        # Assert
        mock_parallel.assert_called()
        mock_parallel.return_value.write_to_db.assert_called_once()
        mock_gps.return_value.write_to_db.assert_not_called()

    def test_explicit_false_parallel_always_uses_gps_writer(
            self, tmp_path, gps_file):
        """Tests parallel=False always forces GPSWriter regardless of file size."""
        # Arrange
        from nov_gnsspq.writer.parallel.engine import PARALLEL_MIN_BYTES
        gen = PqConverter(tmp_path / "out", parallel=False)
        gen._output_dir.mkdir(parents=True, exist_ok=True)
        gen._open = True
        with patch(
                "nov_gnsspq.writer.generator.os.path.getsize",
                return_value=PARALLEL_MIN_BYTES):
            with patch(
                    "nov_gnsspq.writer.generator.ParallelGPSWriter"
            ) as mock_parallel:
                mock_parallel.return_value = MagicMock()
                with patch(
                        "nov_gnsspq.writer.generator.GPSWriter"
                ) as mock_gps:
                    mock_gps.return_value = MagicMock()
                    # Act
                    gen._run_file_writer(str(gps_file))
        # Assert
        mock_parallel.assert_not_called()
        mock_gps.assert_called()
        mock_gps.return_value.write_to_db.assert_called_once()
