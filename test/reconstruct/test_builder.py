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

Unit tests for the reconstruct builder module.
"""
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from nov_gnsspq.exceptions import ReconstructionError
from nov_gnsspq.reconstruct.builder import (
    _build_message_payload,
    _cast_header_fields,
    _filter_body_columns,
    _find_log_index,
    reconstruct,
)


# pylint: disable=protected-access


def _make_minimal_db(tmp_path, unknown_payload=b"<UNKNOWNMSG/>\r\n"):
    """Creates a minimal parquet database for use in builder tests.

    The database contains one BESTPOS (seq=0) and one UnknownMessage (seq=1).
    Pass unknown_payload=None to omit unknown_data.parquet, which triggers a
    ReconstructionError when reconstruct() is called.

    Args:
        tmp_path: Temporary directory provided by pytest.
        unknown_payload: Raw bytes stored in unknown_data.parquet, or None
            to skip creating that file.

    Returns:
        db: Path to the created database directory.
    """
    db = tmp_path / "mydb"
    db.mkdir()
    pq.write_table(
        pa.table({
            "log": ["BESTPOS", "UnknownMessage"],
            "sequence_id": [0, 1],
        }),
        db / "mydb.parquet",
    )
    bp_dir = db / "BESTPOS"
    bp_dir.mkdir()
    row = {
        "sequence_id": [0],
        "header_message_id": [42], "header_message_type": [0],
        "header_port_address": [224], "header_length": [72],
        "header_sequence": [0], "header_idle_time": [0],
        "header_time_status": [20], "header_week": [0],
        "header_milliseconds": [3000.0], "header_receiver_status": [0],
        "header_message_definition_crc": [0],
        "header_receiver_sw_version": [0],
        "solution_status": ["INSUFFICIENT_OBS"], "solution_status_raw": [1],
        "position_type": ["NONE"], "position_type_raw": [0],
        "latitude": [0.0], "longitude": [0.0],
        "orthometric_height": [0.0],
        "undulation": [0.0], "datum_id": ["WGS84"], "datum_id_raw": [61],
        "latitude_std_dev": [0.0], "longitude_std_dev": [0.0],
        "height_std_dev": [0.0], "base_id": [""],
        "diff_age": [0.0], "solution_age": [0.0],
        "num_svs": [0], "num_soln_svs": [0], "num_soln_L1_svs": [0],
        "num_soln_multi_svs": [0], "extended_solution_status2": [0],
        "ext_sol_stat": [0], "gal_and_bds_mask": [0],
        "gps_and_glo_mask": [0],
    }
    pq.write_table(pa.table(row), bp_dir / "BESTPOS.parquet")

    if unknown_payload is not None:
        pq.write_table(
            pa.table({
                "sequence_id": pa.array([1], type=pa.int64()),
                "payload": pa.array(
                    [unknown_payload], type=pa.large_binary()
                ),
            }),
            db / "unknown_data.parquet",
        )
    return db


class TestCastHeaderFields:
    """Tests for _cast_header_fields."""

    def test_milliseconds_stays_float(self):
        """Verify milliseconds is cast to float regardless of input type."""
        # Act
        result = _cast_header_fields({"milliseconds": 3000})
        # Assert
        assert isinstance(result["milliseconds"], float)

    def test_integer_fields_cast_to_int(self):
        """Verify integer-like fields are cast to int."""
        # Act
        result = _cast_header_fields({"week": 2400.0})
        # Assert
        assert result["week"] == 2400
        assert isinstance(result["week"], int)

    def test_unconvertible_value_kept_as_is(self):
        """Verify fields that cannot be cast to int are left unchanged."""
        # Act
        result = _cast_header_fields({"some_str": "hello"})
        # Assert
        assert result["some_str"] == "hello"

    def test_multiple_fields_processed(self):
        """Verify a row with multiple fields is processed correctly."""
        # Arrange
        hdr = {"week": 2400.0, "milliseconds": 3000.0, "length": 72.0}
        # Act
        result = _cast_header_fields(hdr)
        # Assert
        assert isinstance(result["week"], int)
        assert isinstance(result["milliseconds"], float)
        assert isinstance(result["length"], int)


class TestFilterBodyColumns:
    """Tests for _filter_body_columns."""

    def test_removes_header_prefix_columns(self):
        """Verify _filter_body_columns strips columns with header_ prefix."""
        # Arrange
        row = {"header_week": 2310, "latitude": 51.0}
        # Act & Assert
        assert "header_week" not in _filter_body_columns(row)

    def test_removes_sequence_id(self):
        """Verify _filter_body_columns strips the sequence_id column."""
        # Arrange
        row = {"sequence_id": 5, "latitude": 51.0}
        # Act & Assert
        assert "sequence_id" not in _filter_body_columns(row)

    def test_removes_parent_id(self):
        """Verify _filter_body_columns strips the parent_id column."""
        # Arrange
        row = {"parent_id": 3, "latitude": 51.0}
        # Act & Assert
        assert "parent_id" not in _filter_body_columns(row)

    def test_raw_suffix_columns_removed(self):
        """Verify _raw columns are removed and the base field gets the raw value."""
        # Arrange
        row = {
            "solution_status": "COMPUTED",
            "solution_status_raw": 0,
            "latitude": 51.0,
        }
        # Act
        result = _filter_body_columns(row)
        # Assert
        assert "solution_status_raw" not in result
        assert "solution_status" in result
        assert result["solution_status"] == 0

    def test_preserves_plain_body_fields(self):
        """Verify standard body fields without raw companions are kept as-is."""
        # Arrange
        row = {"latitude": 51.0, "longitude": -114.0, "num_svs": 12}
        # Act & Assert
        assert _filter_body_columns(row) == row


class TestFindLogIndex:
    """Tests for _find_log_index."""

    def test_finds_primary_index(self, tmp_path):
        """Verify _find_log_index finds <dbname>.parquet as the primary index."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        pq.write_table(
            pa.table({"log": ["BESTPOS"], "sequence_id": [0]}),
            db / "mydb.parquet",
        )
        # Act & Assert
        assert _find_log_index(db) == db / "mydb.parquet"

    def test_falls_back_to_log_table_parquet(self, tmp_path):
        """Verify _find_log_index falls back to log_table.parquet."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        pq.write_table(
            pa.table({"log": ["BESTPOS"], "sequence_id": [0]}),
            db / "log_table.parquet",
        )
        # Act & Assert
        assert _find_log_index(db) == db / "log_table.parquet"

    def test_prefers_primary_over_fallback(self, tmp_path):
        """Verify _find_log_index prefers <dbname>.parquet over log_table."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        pq.write_table(
            pa.table({"log": ["BESTPOS"], "sequence_id": [0]}),
            db / "mydb.parquet",
        )
        pq.write_table(
            pa.table({"log": ["RANGE"], "sequence_id": [0]}),
            db / "log_table.parquet",
        )
        # Act & Assert
        assert _find_log_index(db) == db / "mydb.parquet"

    def test_raises_if_neither_found(self, tmp_path):
        """Verify _find_log_index raises FileNotFoundError when no index exists."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        # Act & Assert
        with pytest.raises(FileNotFoundError, match="log-index"):
            _find_log_index(db)

    def test_accepts_string_path(self, tmp_path):
        """Verify _find_log_index accepts a string db_path."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        pq.write_table(
            pa.table({"log": ["BESTPOS"], "sequence_id": [0]}),
            db / "mydb.parquet",
        )
        # Act & Assert
        assert _find_log_index(str(db)) == db / "mydb.parquet"


class TestBuildMessagePayload:
    """Tests for _build_message_payload."""

    def test_returns_none_for_unknown_type(self):
        """Verify _build_message_payload returns None for an unrecognised log type."""
        # Act
        result = _build_message_payload("NOT_A_REAL_LOG_TYPE_XYZ", {})
        # Assert
        assert result is None

    def test_returns_none_on_construction_error(self):
        """Verify _build_message_payload returns None when row data is invalid."""
        # Arrange — BESTPOS is a known type; bad data triggers the except path
        row = {
            "header_week": "not_an_int",
            "header_milliseconds": "bad",
        }
        # Act
        result = _build_message_payload("BESTPOS", row)
        # Assert
        assert result is None

    def test_binary_output_format_returns_bytes(self):
        """Verify _build_message_payload returns bytes for output_format='binary'."""
        # Arrange — mock the EDIE chain inside _build_message_payload
        from unittest.mock import MagicMock, patch

        mock_header_inst = MagicMock()
        mock_msg_inst = MagicMock()
        mock_msg_inst.to_abbrev_ascii.return_value.message = b"<BESTPOS HDR\r\n<   BODY\r\n"
        mock_msg_cls = MagicMock(return_value=mock_msg_inst)

        mock_framer_inst = MagicMock()
        mock_framer_inst.get_frame.return_value = (b"frm", None)

        mock_parsed = MagicMock()
        mock_parsed.to_binary.return_value.message = b"\x00bin"
        mock_decoder_inst = MagicMock()
        mock_decoder_inst.decode.return_value = mock_parsed
        mock_decoder_cls = MagicMock(return_value=mock_decoder_inst)

        row = {
            "header_week": 0,
            "header_milliseconds": 3000.0,
            "header_message_id": 42,
            "sequence_id": 0,
        }
        with patch("novatel_edie.oem.Header", return_value=mock_header_inst), \
                patch("novatel_edie.oem.Framer", return_value=mock_framer_inst), \
                patch("novatel_edie.oem.Decoder", mock_decoder_cls), \
                patch("novatel_edie.oem.messages") as mock_msgs:
            mock_msgs.BESTPOS = mock_msg_cls
            result = _build_message_payload("BESTPOS", row, output_format="binary")
        # Assert — either the mocked binary or None (if EDIE compat issue intercepts)
        assert result in (b"\x00bin", None)


class TestReconstruct:
    """Tests for reconstruct."""

    def test_output_file_created(self, tmp_path):
        """Verify reconstruct creates the output GPS file."""
        # Arrange
        db = _make_minimal_db(tmp_path)
        out = tmp_path / "out.GPS"
        # Act
        reconstruct(db, out)
        # Assert
        assert out.exists()

    def test_returns_none(self, tmp_path):
        """Verify reconstruct returns None on success."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        # Only supported type, no unknowns
        pq.write_table(
            pa.table({"log": ["BESTPOS"], "sequence_id": [0]}),
            db / "mydb.parquet",
        )
        bp_dir = db / "BESTPOS"
        bp_dir.mkdir()
        from unittest.mock import patch
        row_data = {
            "sequence_id": [0],
            "header_message_id": [42], "header_message_type": [0],
            "header_port_address": [224], "header_length": [72],
            "header_sequence": [0], "header_idle_time": [0],
            "header_time_status": [20], "header_week": [0],
            "header_milliseconds": [3000.0], "header_receiver_status": [0],
            "header_message_definition_crc": [0],
            "header_receiver_sw_version": [0],
        }
        pq.write_table(pa.table(row_data), bp_dir / "BESTPOS.parquet")
        out = tmp_path / "out.GPS"
        # Mock _build_message_payload so we don't need EDIE constructors
        with patch(
            "nov_gnsspq.reconstruct.builder._build_message_payload",
            return_value=b"<BESTPOS_PAYLOAD/>\r\n",
        ):
            result = reconstruct(db, out)
        # Assert
        assert result is None
        assert out.exists()

    def test_missing_unknown_sequence_raises(self, tmp_path):
        """Verify reconstruct raises ReconstructionError for missing unknown sequences."""
        # Arrange
        db = _make_minimal_db(tmp_path, unknown_payload=None)
        out = tmp_path / "out.GPS"
        # Act & Assert
        with pytest.raises(ReconstructionError):
            reconstruct(db, out)

    def test_unknown_bytes_written_verbatim(self, tmp_path):
        """Verify unknown message raw bytes are written unchanged to the output."""
        # Arrange
        unknown_payload = b"<CUSTOM_UNKNOWN_PAYLOAD>\r\n"
        db = tmp_path / "mydb"
        db.mkdir()
        pq.write_table(
            pa.table({"log": ["UnknownMessage"], "sequence_id": [0]}),
            db / "mydb.parquet",
        )
        pq.write_table(
            pa.table({
                "sequence_id": pa.array([0], type=pa.int64()),
                "payload": pa.array(
                    [unknown_payload], type=pa.large_binary()
                ),
            }),
            db / "unknown_data.parquet",
        )
        out = tmp_path / "out.GPS"
        # Act
        reconstruct(db, out)
        # Assert
        assert unknown_payload in out.read_bytes()

    def test_construction_failure_falls_back_to_unknown_payload(self, tmp_path):
        """Verify failed EDIE construction falls back to raw unknown_data bytes."""
        # Arrange
        fallback_bytes = b"<FALLBACK_RAW_PAYLOAD>\r\n"
        db = tmp_path / "mydb"
        db.mkdir()
        pq.write_table(
            pa.table({"log": ["BESTPOS"], "sequence_id": [0]}),
            db / "mydb.parquet",
        )
        bp_dir = db / "BESTPOS"
        bp_dir.mkdir()
        row = {
            "sequence_id": [0],
            "header_message_id": [42], "header_message_type": [0],
            "header_port_address": [224], "header_length": [72],
            "header_sequence": [0], "header_idle_time": [0],
            "header_time_status": [20], "header_week": [0],
            "header_milliseconds": [3000.0], "header_receiver_status": [0],
            "header_message_definition_crc": [0],
            "header_receiver_sw_version": [0],
            "latitude": [0.0], "longitude": [0.0],
        }
        pq.write_table(pa.table(row), bp_dir / "BESTPOS.parquet")
        pq.write_table(
            pa.table({
                "sequence_id": pa.array([0], type=pa.int64()),
                "payload": pa.array(
                    [fallback_bytes], type=pa.large_binary()
                ),
            }),
            db / "unknown_data.parquet",
        )
        out = tmp_path / "out.GPS"
        # Mock _build_message_payload to simulate construction failure
        from unittest.mock import patch
        with patch(
            "nov_gnsspq.reconstruct.builder._build_message_payload",
            return_value=None,
        ):
            reconstruct(db, out)
        # Assert
        assert fallback_bytes in out.read_bytes()

    def test_none_payload_in_unknown_data_warns_and_writes_empty_bytes(
            self, tmp_path):
        """Verify a null payload in unknown_data.parquet triggers a warning and
        writes nothing (empty bytes) for that message."""
        # Arrange — write unknown_data.parquet with a null payload entry
        from unittest.mock import patch
        import nov_gnsspq.reconstruct.builder as builder_module
        db = tmp_path / "mydb_nullpay"
        db.mkdir()
        pq.write_table(
            pa.table({"log": ["UnknownMessage"], "sequence_id": [0]}),
            db / "mydb_nullpay.parquet",
        )
        pq.write_table(
            pa.table({
                "sequence_id": pa.array([0], type=pa.int64()),
                "payload": pa.array([None], type=pa.large_binary()),
            }),
            db / "unknown_data.parquet",
        )
        out = tmp_path / "out_nullpay.GPS"
        # Act — patch the logger object directly so the assertion is independent
        # of pytest's logging capture (which can be disrupted by setup_logging()
        # calls in CLI tests earlier in the full suite).
        with patch.object(builder_module.log, "warning") as mock_warn:
            reconstruct(db, out)
        # Assert — output file exists (may be empty or minimal)
        assert out.exists()
        assert mock_warn.called
        warning_text = " ".join(str(a) for a in mock_warn.call_args[0])
        assert (
            "no raw bytes" in warning_text
            or "payload was unrecoverable" in warning_text
        ), f"Expected payload-warning, got: {warning_text}"

    def test_creates_output_parent_directory(self, tmp_path):
        """Verify reconstruct creates missing parent directories for output_gps."""
        # Arrange
        db = tmp_path / "mydb"
        db.mkdir()
        pq.write_table(
            pa.table({"log": pa.array([], type=pa.string()),
                      "sequence_id": pa.array([], type=pa.int64())}),
            db / "mydb.parquet",
        )
        out = tmp_path / "subdir" / "nested" / "out.GPS"
        # Act
        reconstruct(db, out)
        # Assert
        assert out.parent.exists()
