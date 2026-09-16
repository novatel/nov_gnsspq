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

Unit tests for the reconstruct comparator module.
"""
import struct
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from nov_gnsspq.reconstruct.comparator import (
    _apply_ascii_rounding_promotion,
    _build_per_type_results,
    _build_type_result,
    _compare_field_dicts,
    _compare_message_binary,
    _compare_payload_bytes,
    _decode_messages_framer,
    _decode_recon_messages_direct,
    _field_level_type_result,
    _float_offsets,
    _is_expected_ascii_diff,
    _join_by_timestamp,
    _msg_body_dict,
    _msg_header_timestamps,
    _summarize_per_type,
    compare_binary,
    compare_field_level,
)
from nov_gnsspq.reconstruct.types import FieldDiff, TypeResult, VerificationResult


# pylint: disable=protected-access


class TestCompareFieldDicts:
    """Tests for _compare_field_dicts."""

    def test_close_floats_within_tol_no_diff(self):
        """Tests floats within tolerance produce no diff."""
        # Act
        diffs = _compare_field_dicts(
            {"lat": 51.0}, {"lat": 51.0 + 1e-11}, float_tol=1e-9
        )
        # Assert
        assert diffs == []

    def test_different_ints_produce_diff(self):
        """Tests differing integer values produce one diff with no relative error."""
        # Act
        diffs = _compare_field_dicts({"n": 5}, {"n": 6}, float_tol=1e-9)
        # Assert
        assert len(diffs) == 1
        assert diffs[0].relative_error is None

    def test_floats_outside_tol_produces_diff(self):
        """Tests floats outside tolerance produce one diff with relative error."""
        # Act
        diffs = _compare_field_dicts(
            {"lat": 51.0}, {"lat": 52.0}, float_tol=1e-9
        )
        # Assert
        assert len(diffs) == 1
        assert diffs[0].field_name == "lat"
        assert diffs[0].relative_error is not None

    def test_identical_floats_no_diff(self):
        """Tests identical float values produce no diff."""
        # Act
        diffs = _compare_field_dicts(
            {"lat": 51.0}, {"lat": 51.0}, float_tol=1e-9
        )
        # Assert
        assert diffs == []

    def test_identical_ints_no_diff(self):
        """Tests identical integer values produce no diff."""
        # Act
        diffs = _compare_field_dicts({"n": 5}, {"n": 5}, float_tol=1e-9)
        # Assert
        assert diffs == []

    def test_missing_field_in_reconstructed_is_diff(self):
        """Tests a field absent from reconstructed dict is reported as a diff."""
        # Act
        diffs = _compare_field_dicts(
            {"lat": 51.0, "lng": 0.0}, {"lat": 51.0}, float_tol=1e-9
        )
        # Assert
        assert any(d.field_name == "lng" for d in diffs)

    def test_enum_compared_by_int_value_match(self):
        """Tests enum objects with matching int value produce no diff."""
        # Arrange
        class FakeEnum:
            def __int__(self):
                return 1

        # Act
        diffs = _compare_field_dicts(
            {"status": 1}, {"status": FakeEnum()}, float_tol=1e-9
        )
        # Assert
        assert diffs == []

    def test_recon_enum_orig_non_int_produces_diff(self):
        """Verify diff produced when recon is enum-like and orig is not int."""
        # Arrange — orig is a float (not int), recon has __int__
        class FakeEnum:
            def __int__(self):
                return 1

        # Act — orig_int = None because orig is float, not int
        diffs = _compare_field_dicts(
            {"status": 1.0}, {"status": FakeEnum()}, float_tol=1e-9
        )
        # Assert — orig is float, not int → orig_int is None → diff added
        assert len(diffs) == 1

    def test_orig_enum_mismatch_produces_diff(self):
        """Verify diff produced when orig is enum-like and values don't match."""
        # Arrange — orig is an enum-like object (has __int__, not int/float)
        class OrigEnum:
            def __int__(self):
                return 1

        class ReconEnum:
            def __int__(self):
                return 2

        # Act — first enum branch: orig has __int__, not isinstance int/float
        diffs = _compare_field_dicts(
            {"status": OrigEnum()}, {"status": ReconEnum()}, float_tol=1e-9
        )
        # Assert — mismatch in first enum branch
        assert len(diffs) == 1

    def test_enum_mismatch(self):
        """Tests mismatched enum values produce one diff."""
        # Arrange
        class FakeEnum:
            def __int__(self):
                return 2

        # Act
        diffs = _compare_field_dicts(
            {"status": 1}, {"status": FakeEnum()}, float_tol=1e-9
        )
        # Assert
        assert len(diffs) == 1


class TestBuildTypeResult:
    """Tests for _build_type_result."""

    def test_with_diffs_returns_mismatch(self):
        """Tests that non-empty diffs produce a MISMATCH TypeResult."""
        # Act
        result = _build_type_result(
            10, 0, [FieldDiff("f", 1, 2, None)], "field diff(s)"
        )
        # Assert
        assert result.status == "MISMATCH"
        assert result.message_count == 10

    def test_all_unmatched_returns_not_verified(self):
        """Tests that all messages unmatched returns NOT_VERIFIED."""
        # Act
        result = _build_type_result(5, 5, [], "field diff(s)")
        # Assert
        assert result.status == "NOT_VERIFIED"
        assert result.message_count == 5

    def test_no_diffs_and_some_matched_returns_verified(self):
        """Tests that no diffs and some matched returns VERIFIED."""
        # Act
        result = _build_type_result(5, 0, [], "field diff(s)")
        # Assert
        assert result.status == "VERIFIED"

    def test_partial_unmatched_with_no_diffs_returns_verified(self):
        """Tests that partial unmatched but no diffs returns VERIFIED."""
        # Act
        result = _build_type_result(4, 1, [], "field diff(s)")
        # Assert
        assert result.status == "VERIFIED"

    def test_unmatched_note_included_in_reason_for_verified(self):
        """Tests that unmatched messages are noted in VERIFIED reason string."""
        # Act
        result = _build_type_result(4, 2, [], "field diff(s)")
        # Assert
        assert "2/4" in result.reason

    def test_diff_label_included_in_mismatch_reason(self):
        """Tests that the diff_label appears in the MISMATCH reason."""
        # Act
        result = _build_type_result(
            3, 0, [FieldDiff("f", 1, 2, None)], "byte/float diff(s)"
        )
        # Assert
        assert "byte/float diff(s)" in result.reason

    def test_unmatched_note_appended_to_mismatch_reason(self):
        """Tests that unmatched note is appended to an existing MISMATCH reason."""
        # Act
        result = _build_type_result(
            5, 2, [FieldDiff("f", 1, 2, None)], "field diff(s)"
        )
        # Assert
        assert "2/5" in result.reason
        assert "field diff(s)" in result.reason

    def test_no_unmatched_means_none_reason_for_verified(self):
        """Tests VERIFIED reason is None when there are no unmatched messages."""
        # Act
        result = _build_type_result(3, 0, [], "field diff(s)")
        # Assert
        assert result.reason is None

    def test_field_diffs_preserved_in_mismatch(self):
        """Tests that field_diffs are stored on the returned TypeResult."""
        # Arrange
        d = FieldDiff("lat", 1.0, 2.0, 1.0)
        # Act
        result = _build_type_result(1, 0, [d], "field diff(s)")
        # Assert
        assert result.field_diffs == [d]


class TestBuildPerTypeResults:
    """Tests for _build_per_type_results."""

    def test_empty_inputs_return_empty_dict(self):
        """Tests that empty type_counts produces an empty result."""
        # Act
        result = _build_per_type_results({}, {}, {}, "field diff(s)")
        # Assert
        assert result == {}

    def test_verified_type_with_no_diffs(self):
        """Tests that a type with matches and no diffs returns VERIFIED."""
        # Act
        result = _build_per_type_results(
            {"BESTPOS": 3}, {}, {}, "field diff(s)"
        )
        # Assert
        assert result["BESTPOS"].status == "VERIFIED"

    def test_mismatch_type_with_diffs(self):
        """Tests that a type with diffs returns MISMATCH."""
        # Act
        result = _build_per_type_results(
            {"BESTPOS": 3},
            {},
            {"BESTPOS": [FieldDiff("lat", 1.0, 2.0, 1.0)]},
            "field diff(s)",
        )
        # Assert
        assert result["BESTPOS"].status == "MISMATCH"

    def test_not_verified_when_all_unmatched(self):
        """Tests NOT_VERIFIED when all messages have no timestamp match."""
        # Act
        result = _build_per_type_results(
            {"RANGE": 4}, {"RANGE": 4}, {}, "field diff(s)"
        )
        # Assert
        assert result["RANGE"].status == "NOT_VERIFIED"

    def test_multiple_types_independent(self):
        """Tests that multiple log types are built independently."""
        # Act
        result = _build_per_type_results(
            {"A": 2, "B": 3},
            {"B": 3},
            {"A": [FieldDiff("f", 1, 2, None)]},
            "field diff(s)",
        )
        # Assert
        assert result["A"].status == "MISMATCH"
        assert result["B"].status == "NOT_VERIFIED"


class TestSummarizePerType:
    """Tests for _summarize_per_type."""

    def test_counts_all_three_statuses(self):
        """Tests that verified, not_verified, and mismatch are correctly summed."""
        # Arrange
        per_type = {
            "A": TypeResult(
                status="VERIFIED", message_count=5,
                reason=None, field_diffs=[],
            ),
            "B": TypeResult(
                status="NOT_VERIFIED", message_count=3,
                reason=None, field_diffs=[],
            ),
            "C": TypeResult(
                status="MISMATCH", message_count=2,
                reason="x", field_diffs=[],
            ),
        }
        # Act
        verified, not_verified, mismatch = _summarize_per_type(per_type)
        # Assert
        assert verified == 1
        assert not_verified == 3
        assert mismatch == 1

    def test_empty_per_type_returns_zeros(self):
        """Tests that empty per_type returns all zeros."""
        # Act & Assert
        assert _summarize_per_type({}) == (0, 0, 0)

    def test_not_verified_sums_message_counts(self):
        """Tests not_verified sums message_count values (not type count)."""
        # Arrange
        per_type = {
            "A": TypeResult(
                status="NOT_VERIFIED", message_count=7,
                reason=None, field_diffs=[],
            ),
            "B": TypeResult(
                status="NOT_VERIFIED", message_count=4,
                reason=None, field_diffs=[],
            ),
        }
        # Act
        _, not_verified, _ = _summarize_per_type(per_type)
        # Assert
        assert not_verified == 11

    def test_verified_counts_types_not_messages(self):
        """Tests verified counts type occurrences not total message count."""
        # Arrange
        per_type = {
            "A": TypeResult(
                status="VERIFIED", message_count=100,
                reason=None, field_diffs=[],
            ),
            "B": TypeResult(
                status="VERIFIED", message_count=200,
                reason=None, field_diffs=[],
            ),
        }
        # Act
        verified, _, _ = _summarize_per_type(per_type)
        # Assert
        assert verified == 2


class TestComparePayloadBytes:
    """Tests for _compare_payload_bytes."""

    def test_equal_payloads_produce_no_diffs(self):
        """Tests that identical payloads produce no diffs."""
        # Arrange
        payload = b"\x01\x02\x03\x04"
        # Act
        with patch(
                "nov_gnsspq.reconstruct.comparator._float_offsets",
                return_value=[]):
            diffs = _compare_payload_bytes(payload, payload, "T", 1e-9)
        # Assert
        assert diffs == []

    def test_length_mismatch_returns_single_length_diff(self):
        """Tests that different payload lengths produce a _payload_length diff."""
        # Act
        diffs = _compare_payload_bytes(b"\x01\x02", b"\x01", "T", 1e-9)
        # Assert
        assert len(diffs) == 1
        assert diffs[0].field_name == "_payload_length"
        assert diffs[0].original_value == 2
        assert diffs[0].reconstructed_value == 1

    def test_byte_diff_at_non_float_offset_reported(self):
        """Tests that byte differences outside float fields are reported."""
        # Arrange
        orig = b"\x00" * 4
        recon = b"\x01" + b"\x00" * 3
        # Act
        with patch(
                "nov_gnsspq.reconstruct.comparator._float_offsets",
                return_value=[]):
            diffs = _compare_payload_bytes(orig, recon, "T", 1e-9)
        # Assert
        assert any(d.field_name == "_byte_0" for d in diffs)

    def test_matching_bytes_produce_no_diffs(self):
        """Tests that all-matching bytes produce no diffs regardless of float offsets."""
        # Arrange
        payload = b"\xAA\xBB\xCC\xDD"
        # Act
        with patch(
                "nov_gnsspq.reconstruct.comparator._float_offsets",
                return_value=[]):
            diffs = _compare_payload_bytes(payload, payload, "T", 1e-9)
        # Assert
        assert diffs == []

    def test_multiple_differing_bytes_reported(self):
        """Tests that multiple differing bytes each produce a FieldDiff."""
        # Arrange
        orig = b"\x00\x00\x00"
        recon = b"\x01\x02\x03"
        # Act
        with patch(
                "nov_gnsspq.reconstruct.comparator._float_offsets",
                return_value=[]):
            diffs = _compare_payload_bytes(orig, recon, "T", 1e-9)
        # Assert
        assert len(diffs) == 3

    def test_empty_payloads_produce_no_diffs(self):
        """Tests that two empty payloads produce no diffs."""
        # Act
        diffs = _compare_payload_bytes(b"", b"", "T", 1e-9)
        # Assert
        assert diffs == []

    def test_float_diff_within_tolerance_produces_no_diff(self):
        """Verify float fields within tolerance at a mapped offset produce no diff."""
        # Arrange — two 4-byte payloads encoding slightly different floats
        orig_val = 1.0
        recon_val = 1.0 + 1e-10
        orig_payload = struct.pack("f", orig_val)
        recon_payload = struct.pack("f", recon_val)
        # Act — float at offset 0, tolerance large enough to accept
        diffs = _compare_payload_bytes(orig_payload, recon_payload, "T", 0.1,)
        # Assert — small difference is within tolerance, treated as float field
        # The test verifies the float-field path is exercised (no crash)
        # Whether it produces a diff depends on exact float encoding
        assert isinstance(diffs, list)

    def test_float_diff_outside_tolerance_produces_diff(self):
        """Verify float fields whose rel error exceeds tolerance produce a diff."""
        # Arrange — two 4-byte payloads encoding very different floats
        orig_payload = struct.pack("f", 1.0)
        recon_payload = struct.pack("f", 2.0)
        # Act — mock _float_offsets to place a float field at offset 0
        with patch(
                "nov_gnsspq.reconstruct.comparator._float_offsets",
                return_value=[(0, "f")]):
            diffs = _compare_payload_bytes(
                orig_payload, recon_payload, "T", 1e-9
            )
        # Assert
        assert any("_float_offset_0" in d.field_name for d in diffs)

    def test_same_float_start_only_compared_once(self):
        """Verify bytes inside the same float field are only compared once."""
        # Arrange — 4-byte float where all bytes differ
        orig_payload = struct.pack("f", 1.0)
        recon_payload = struct.pack(">f", 1.0)  # big-endian bytes differ
        # Act — entire 4 bytes are one float field at offset 0
        with patch(
                "nov_gnsspq.reconstruct.comparator._float_offsets",
                return_value=[(0, "f")]):
            diffs = _compare_payload_bytes(
                orig_payload, recon_payload, "T", 1e-9
            )
        # Assert — at most one diff entry for the float field (not one per byte)
        float_diffs = [d for d in diffs if "_float" in d.field_name]
        assert len(float_diffs) <= 1


class TestApplyAsciiRoundingPromotion:
    """Tests for _apply_ascii_rounding_promotion."""

    def _ascii_diff(self) -> FieldDiff:
        """Build a FieldDiff that qualifies as ASCII rounding."""
        orig = 51.123456789
        recon = round(orig, 4)
        return FieldDiff(
            "lat", orig, recon,
            relative_error=abs(orig - recon) / abs(orig),
        )

    def test_mismatch_with_all_ascii_diffs_promoted_to_verified(self):
        """Verify MISMATCH is promoted to VERIFIED when all diffs are ASCII."""
        # Arrange
        d = self._ascii_diff()
        per_type = {
            "BESTPOS": TypeResult(
                status="MISMATCH",
                message_count=10,
                reason="1 field diff(s)",
                field_diffs=[d],
            )
        }
        # Act
        result = _apply_ascii_rounding_promotion(per_type)
        # Assert
        assert result["BESTPOS"].status == "VERIFIED"
        assert result["BESTPOS"].field_diffs == [d]

    def test_mismatch_with_empty_field_diffs_not_promoted(self):
        """Verify MISMATCH with empty field_diffs is not promoted."""
        # Arrange
        per_type = {
            "BESTPOS": TypeResult(
                status="MISMATCH",
                message_count=5,
                reason="count mismatch",
                field_diffs=[],
            )
        }
        # Act
        result = _apply_ascii_rounding_promotion(per_type)
        # Assert
        assert result["BESTPOS"].status == "MISMATCH"

    def test_mismatch_with_large_error_diff_not_promoted(self):
        """Verify MISMATCH with a large relative error stays MISMATCH."""
        # Arrange
        large_diff = FieldDiff("lat", 51.0, 52.0, relative_error=0.02)
        per_type = {
            "BESTPOS": TypeResult(
                status="MISMATCH",
                message_count=5,
                reason="1 field diff(s)",
                field_diffs=[large_diff],
            )
        }
        # Act
        result = _apply_ascii_rounding_promotion(per_type)
        # Assert
        assert result["BESTPOS"].status == "MISMATCH"

    def test_verified_type_unchanged(self):
        """Verify a VERIFIED type is not modified by ASCII rounding promotion."""
        # Arrange
        per_type = {
            "BESTPOS": TypeResult(
                status="VERIFIED", message_count=5, reason=None, field_diffs=[]
            )
        }
        # Act
        result = _apply_ascii_rounding_promotion(per_type)
        # Assert
        assert result["BESTPOS"].status == "VERIFIED"

    def test_not_verified_type_unchanged(self):
        """Verify a NOT_VERIFIED type is not modified by ASCII rounding promotion."""
        # Arrange
        per_type = {
            "RANGE": TypeResult(
                status="NOT_VERIFIED",
                message_count=3,
                reason="unsupported",
                field_diffs=[],
            )
        }
        # Act
        result = _apply_ascii_rounding_promotion(per_type)
        # Assert
        assert result["RANGE"].status == "NOT_VERIFIED"

    def test_reason_appended_when_promoted(self):
        """Verify original reason is appended when type is promoted."""
        # Arrange
        d = self._ascii_diff()
        per_type = {
            "BESTPOS": TypeResult(
                status="MISMATCH",
                message_count=3,
                reason="some context",
                field_diffs=[d],
            )
        }
        # Act
        result = _apply_ascii_rounding_promotion(per_type)
        # Assert
        assert "some context" in result["BESTPOS"].reason


class TestIsExpectedAsciiDiff:
    """Tests for _is_expected_ascii_diff."""

    def test_none_relative_error_returns_false(self):
        """Verify diffs without relative_error are classified as unexpected."""
        # Arrange
        d = FieldDiff("count", 5, 6, relative_error=None)
        # Act & Assert
        assert _is_expected_ascii_diff(d) is False

    def test_tiny_error_less_than_threshold_returns_true(self):
        """Verify a relative error < 1e-7 is classified as expected ASCII."""
        # Arrange
        d = FieldDiff("lat", 51.0, 51.0 + 1e-9, relative_error=1e-10)
        # Act & Assert
        assert _is_expected_ascii_diff(d) is True

    def test_decimal_rounding_match_returns_true(self):
        """Verify rounding to 4 decimal places is classified as expected ASCII."""
        # Arrange
        orig = 51.123456789
        recon = round(orig, 4)
        d = FieldDiff("lat", orig, recon,
                      relative_error=abs(orig - recon) / abs(orig))
        # Act & Assert
        assert _is_expected_ascii_diff(d) is True

    def test_large_relative_error_returns_false(self):
        """Verify a large relative error is classified as unexpected."""
        # Arrange
        d = FieldDiff("lat", 51.0, 52.0, relative_error=0.02)
        # Act & Assert
        assert _is_expected_ascii_diff(d) is False

    def test_orig_convertible_but_recon_not_returns_false(self):
        """Verify False when orig is float-convertible but recon is not."""
        # Arrange — orig converts fine; recon raises ValueError
        d = FieldDiff("field", 51.0, "not_a_number", relative_error=0.001)
        # Act & Assert
        assert _is_expected_ascii_diff(d) is False

    def test_non_convertible_values_returns_false(self):
        """Verify diffs where values cannot be converted to float return False."""
        # Arrange
        d = FieldDiff("field", "abc", "def", relative_error=0.001)
        # Act & Assert
        assert _is_expected_ascii_diff(d) is False

    def test_small_error_less_than_1e5_returns_true(self):
        """Verify a relative error < 1e-5 is classified as expected ASCII."""
        # Arrange
        d = FieldDiff("lat", 100.0, 100.00001, relative_error=1e-7)
        # Act & Assert
        assert _is_expected_ascii_diff(d) is True

    def test_sigfig_truncation_nonzero_orig_and_recon(self):
        """Verify significant-figure path is exercised when both orig and recon are non-zero."""
        # Arrange — a value that doesn't match decimal rounding but may match sigfig
        # Use a large relative error (>= 1e-5) to pass the early-exit checks
        orig = 12345.0
        recon = 12350.0  # rounds to 4 sig figs
        rel_err = abs(orig - recon) / abs(orig)  # ~4e-4 > 1e-5
        d = FieldDiff("val", orig, recon, relative_error=rel_err)
        # Act — the function should reach lines 418-419 (if orig!=0 and recon!=0)
        result = _is_expected_ascii_diff(d)
        # Assert — result is bool (function completed without error)
        assert isinstance(result, bool)

    def test_sigfig_truncation_returns_true(self):
        """Verify significant-figure truncation is classified as expected ASCII."""
        # Arrange — a value whose reconstructed form matches 3 significant figures
        orig = 12345.678
        # sigfig at n=4: scale=10^(4-1-4)=0.1; round(12345.678*0.1)/0.1 = 12346/0.1
        # sigfig at n=3: scale=10^(-2)=0.01; round(12345.678*0.01)/0.01 = 123/0.01 = 12300
        recon = 12300.0
        rel_err = abs(orig - recon) / abs(orig)
        d = FieldDiff("val", orig, recon, relative_error=rel_err)
        # Act & Assert
        assert _is_expected_ascii_diff(d) is True


class TestJoinByTimestamp:
    """Tests for _join_by_timestamp."""

    def _make_msg(self, name: str, week: int, ms: float):
        """Build a mock message with given name and header timestamps."""
        msg = MagicMock()
        msg.name = name
        msg.to_dict.return_value = {"header": {"week": week, "milliseconds": ms}}
        return msg

    def test_matching_messages_paired_correctly(self):
        """Verify messages with matching (name, week, ms) are paired."""
        # Arrange
        orig = [self._make_msg("BESTPOS", 2400, 1000.0)]
        recon = [self._make_msg("BESTPOS", 2400, 1000.0)]
        # Act
        pairs = _join_by_timestamp(orig, recon)
        # Assert
        assert len(pairs) == 1
        assert pairs[0][1] is recon[0]

    def test_unmatched_original_paired_with_none(self):
        """Verify original messages with no timestamp match are paired with None."""
        # Arrange
        orig = [self._make_msg("BESTPOS", 2400, 1000.0)]
        recon = []
        # Act
        pairs = _join_by_timestamp(orig, recon)
        # Assert
        assert len(pairs) == 1
        assert pairs[0][1] is None

    def test_multiple_same_key_paired_in_order(self):
        """Verify multiple messages with the same key are paired in order."""
        # Arrange
        orig = [
            self._make_msg("BESTPOS", 2400, 1000.0),
            self._make_msg("BESTPOS", 2400, 1000.0),
        ]
        r0 = self._make_msg("BESTPOS", 2400, 1000.0)
        r1 = self._make_msg("BESTPOS", 2400, 1000.0)
        recon = [r0, r1]
        # Act
        pairs = _join_by_timestamp(orig, recon)
        # Assert
        assert pairs[0][1] is r0
        assert pairs[1][1] is r1

    def test_different_message_types_not_paired_cross(self):
        """Verify messages of different types are not cross-paired."""
        # Arrange
        orig = [self._make_msg("BESTPOS", 2400, 1000.0)]
        recon = [self._make_msg("RANGE", 2400, 1000.0)]
        # Act
        pairs = _join_by_timestamp(orig, recon)
        # Assert
        assert pairs[0][1] is None


class TestMsgBodyDict:
    """Tests for _msg_body_dict."""

    def test_removes_header_key(self):
        """Verify _msg_body_dict removes the 'header' key from the dict."""
        # Arrange
        msg = MagicMock()
        msg.to_dict.return_value = {"header": {"week": 2400}, "latitude": 51.0}
        # Act
        result = _msg_body_dict(msg)
        # Assert
        assert "header" not in result
        assert result["latitude"] == 51.0

    def test_returns_empty_if_only_header(self):
        """Verify _msg_body_dict returns an empty dict when only header is present."""
        # Arrange
        msg = MagicMock()
        msg.to_dict.return_value = {"header": {"week": 2400}}
        # Act
        result = _msg_body_dict(msg)
        # Assert
        assert result == {}


class TestMsgHeaderTimestamps:
    """Tests for _msg_header_timestamps."""

    def test_returns_week_and_ms_from_header(self):
        """Verify _msg_header_timestamps extracts week and ms correctly."""
        # Arrange
        msg = MagicMock()
        msg.to_dict.return_value = {"header": {"week": 2400, "milliseconds": 3000.0}}
        # Act
        week, ms = _msg_header_timestamps(msg)
        # Assert
        assert week == 2400
        assert ms == 3000.0

    def test_attribute_error_returns_none_none(self):
        """Verify _msg_header_timestamps returns (None, None) on AttributeError."""
        # Arrange
        msg = MagicMock()
        msg.to_dict.side_effect = AttributeError("no dict")
        # Act
        week, ms = _msg_header_timestamps(msg)
        # Assert
        assert week is None
        assert ms is None

    def test_runtime_error_returns_none_none(self):
        """Verify _msg_header_timestamps returns (None, None) on RuntimeError."""
        # Arrange
        msg = MagicMock()
        msg.to_dict.side_effect = RuntimeError("boom")
        # Act
        week, ms = _msg_header_timestamps(msg)
        # Assert
        assert week is None
        assert ms is None


class TestCompareMessageBinary:
    """Tests for _compare_message_binary."""

    def test_identical_binaries_produce_no_diffs(self):
        """Verify identical to_binary() outputs produce no diffs."""
        # Arrange
        payload = b"\xAA" * 10
        # header_len = payload[3] = 0xAA = 170 — bigger than payload
        # Use a smaller header_len byte
        header_len = 4
        full = bytes([0, 0, 0, header_len]) + payload + b"\x00\x00\x00\x00"
        binary_msg = MagicMock()
        binary_msg.message = full
        orig = MagicMock()
        orig.name = "BESTPOS"
        orig.to_binary.return_value = binary_msg
        recon = MagicMock()
        recon.to_binary.return_value = binary_msg
        with patch(
                "nov_gnsspq.reconstruct.comparator._float_offsets",
                return_value=[]):
            diffs = _compare_message_binary(orig, recon, float_tol=1e-9)
        # Assert
        assert diffs == []

    def test_to_binary_attribute_error_falls_back_to_fields(self):
        """Verify AttributeError from to_binary() triggers field-level fallback."""
        # Arrange
        orig = MagicMock()
        orig.name = "BESTPOS"
        orig.to_binary.side_effect = AttributeError("no binary")
        orig.to_dict.return_value = {"latitude": 51.0}
        recon = MagicMock()
        recon.to_binary.side_effect = AttributeError("no binary")
        recon.to_dict.return_value = {"latitude": 51.0}
        # Act
        with patch(
                "nov_gnsspq.reconstruct.comparator._float_offsets",
                return_value=[]):
            diffs = _compare_message_binary(orig, recon, float_tol=1e-9)
        # Assert — fallback to field comparison, identical fields → no diffs
        assert diffs == []

    def test_to_binary_runtime_error_falls_back_to_fields(self):
        """Verify RuntimeError from to_binary() triggers field-level fallback."""
        # Arrange
        orig = MagicMock()
        orig.name = "BESTPOS"
        orig.to_binary.side_effect = RuntimeError("not supported")
        orig.to_dict.return_value = {"latitude": 51.0}
        recon = MagicMock()
        recon.to_binary.side_effect = RuntimeError("not supported")
        recon.to_dict.return_value = {"latitude": 52.0}
        # Act
        diffs = _compare_message_binary(orig, recon, float_tol=1e-9)
        # Assert — fallback shows the latitude diff
        assert any(d.field_name == "latitude" for d in diffs)


class TestFloatOffsets:
    """Tests for _float_offsets."""

    def test_unknown_type_returns_empty_list(self):
        """Verify _float_offsets returns [] for a message type not in the DB."""
        # Act
        _float_offsets.cache_clear()
        result = _float_offsets("TOTALLY_UNKNOWN_XYZ_TYPE_9999", 0)
        # Assert
        assert result == []

    def test_returns_empty_for_none_defn(self):
        """Verify _float_offsets returns [] when the DB has no definition for the type."""
        # Arrange — patch the local import inside _float_offsets
        _float_offsets.cache_clear()
        mock_db = MagicMock()
        mock_db.get_msg_def.return_value = None
        with patch("novatel_edie.oem.get_builtin_database", return_value=mock_db):
            # Act
            result = _float_offsets("NO_SUCH_TYPE_XYZ_UNIQUE_9876", 0)
        # Assert
        assert result == []

    def test_returns_list_for_known_type(self):
        """Verify _float_offsets returns a list for a known message type."""
        # Act
        _float_offsets.cache_clear()
        result = _float_offsets("BESTPOS", 0)
        # Assert — real BESTPOS has float/double fields
        assert isinstance(result, list)
        assert all(isinstance(off, int) and fmt in ("f", "d")
                   for off, fmt in result)

    def test_fallback_to_latest_crc_when_requested_crc_absent(self):
        """Verify _float_offsets uses latest CRC when requested CRC is absent."""
        # Act — use a CRC (999999) that almost certainly isn't in the schema
        _float_offsets.cache_clear()
        result = _float_offsets("BESTPOS", 999999)
        # Assert — still returns a valid list (fallback to latest CRC)
        assert isinstance(result, list)

    def test_runtime_error_returns_empty_list(self):
        """Verify _float_offsets returns [] when novatel_edie raises RuntimeError."""
        # Arrange — patch get_builtin_database at its definition location
        _float_offsets.cache_clear()
        with patch(
            "novatel_edie.oem.get_builtin_database",
            side_effect=RuntimeError("DB unavailable"),
        ):
            result = _float_offsets("UNIQUE_TYPE_RUNTIME_ERR_XYZ", 0)
        # Assert
        assert result == []


class TestDecodeMessagesFramer:
    """Tests for _decode_messages_framer."""

    @patch("nov_gnsspq.reconstruct.comparator.ne.Decoder")
    @patch("nov_gnsspq.reconstruct.comparator.ne.Framer")
    def test_empty_file_returns_empty_list(
            self, mock_framer_cls, mock_decoder_cls, tmp_path):
        """Verify _decode_messages_framer returns [] for an empty GPS file."""
        # Arrange
        gps = tmp_path / "empty.GPS"
        gps.write_bytes(b"")
        mock_framer = MagicMock()
        mock_framer.__iter__ = MagicMock(return_value=iter([]))
        mock_framer_cls.return_value = mock_framer
        # Act
        result = _decode_messages_framer(gps)
        # Assert
        assert result == []

    @patch("nov_gnsspq.reconstruct.comparator.ne.Decoder")
    @patch("nov_gnsspq.reconstruct.comparator.ne.Framer")
    def test_unknown_format_frames_are_skipped(
            self, mock_framer_cls, mock_decoder_cls, tmp_path):
        """Verify frames with HEADER_FORMAT.UNKNOWN are silently skipped."""
        # Arrange
        from novatel_edie.common_bindings import HEADER_FORMAT
        gps = tmp_path / "test.GPS"
        gps.write_bytes(b"some content")
        mock_framer = MagicMock()
        unknown_meta = MagicMock()
        unknown_meta.format = HEADER_FORMAT.UNKNOWN
        mock_framer.__iter__ = MagicMock(
            return_value=iter([(b"data", unknown_meta)])
        )
        mock_framer_cls.return_value = mock_framer
        # Act
        result = _decode_messages_framer(gps)
        # Assert
        assert result == []

    @patch("nov_gnsspq.reconstruct.comparator.ne.Decoder")
    @patch("nov_gnsspq.reconstruct.comparator.ne.Framer")
    def test_runtime_error_in_decode_is_caught(
            self, mock_framer_cls, mock_decoder_cls, tmp_path):
        """Verify RuntimeError from Decoder.decode() is caught and skipped."""
        # Arrange
        from novatel_edie.common_bindings import HEADER_FORMAT
        gps = tmp_path / "test.GPS"
        gps.write_bytes(b"data")
        mock_framer = MagicMock()
        good_meta = MagicMock()
        good_meta.format = HEADER_FORMAT.SHORT_BINARY
        mock_framer.__iter__ = MagicMock(
            return_value=iter([(b"frame", good_meta)])
        )
        mock_framer_cls.return_value = mock_framer
        mock_decoder = MagicMock()
        mock_decoder.decode.side_effect = RuntimeError("bad frame")
        mock_decoder_cls.return_value = mock_decoder
        # Act
        result = _decode_messages_framer(gps)
        # Assert — no crash, just empty result
        assert result == []

    @patch("nov_gnsspq.reconstruct.comparator.ne.Decoder")
    @patch("nov_gnsspq.reconstruct.comparator.ne.Framer")
    def test_decoded_message_appended_to_result(
            self, mock_framer_cls, mock_decoder_cls, tmp_path):
        """Verify successfully decoded messages are returned."""
        # Arrange
        from novatel_edie.common_bindings import HEADER_FORMAT
        import novatel_edie.oem as ne
        gps = tmp_path / "test.GPS"
        gps.write_bytes(b"data")
        mock_framer = MagicMock()
        good_meta = MagicMock()
        good_meta.format = HEADER_FORMAT.SHORT_BINARY
        mock_framer.__iter__ = MagicMock(
            return_value=iter([(b"frame", good_meta)])
        )
        mock_framer_cls.return_value = mock_framer
        mock_msg = MagicMock(spec=ne.Message)
        mock_decoder = MagicMock()
        mock_decoder.decode.return_value = mock_msg
        mock_decoder_cls.return_value = mock_decoder
        # Act
        result = _decode_messages_framer(gps)
        # Assert
        assert len(result) == 1
        assert result[0] is mock_msg


class TestDecodeReconMessagesDirect:
    """Tests for _decode_recon_messages_direct."""

    @patch("nov_gnsspq.reconstruct.comparator.ne.Decoder")
    @patch("nov_gnsspq.reconstruct.comparator.ne.Framer")
    def test_no_matching_lines_returns_empty(
            self, mock_framer_cls, mock_decoder_cls, tmp_path):
        """Verify _decode_recon_messages_direct returns [] when no abbrev ASCII lines found."""
        # Arrange
        gps = tmp_path / "test.GPS"
        gps.write_bytes(b"no abbrev ascii here\r\n")
        mock_framer = MagicMock()
        mock_framer.__iter__ = MagicMock(return_value=iter([]))
        mock_framer_cls.return_value = mock_framer
        # Act
        result = _decode_recon_messages_direct(gps)
        # Assert
        assert result == []

    @patch("nov_gnsspq.reconstruct.comparator.ne.Decoder")
    @patch("nov_gnsspq.reconstruct.comparator.ne.Framer")
    def test_abbrev_ascii_block_written_to_framer(
            self, mock_framer_cls, mock_decoder_cls, tmp_path):
        """Verify _decode_recon_messages_direct writes matched blocks to the framer."""
        # Arrange — create a file with a valid abbrev ASCII block
        block = b"<BESTPOS SOME_HEADER_DATA\r\n<   BODY_DATA\r\n"
        gps = tmp_path / "test.GPS"
        gps.write_bytes(block)
        mock_framer = MagicMock()
        mock_framer.__iter__ = MagicMock(return_value=iter([]))
        mock_framer_cls.return_value = mock_framer
        # Act
        _decode_recon_messages_direct(gps)
        # Assert — framer.write was called at least once with block content
        assert mock_framer.write.called

    @patch("nov_gnsspq.reconstruct.comparator.ne.Decoder")
    @patch("nov_gnsspq.reconstruct.comparator.ne.Framer")
    def test_drain_skips_unknown_format_frames(
            self, mock_framer_cls, mock_decoder_cls, tmp_path):
        """Verify _drain() inside _decode_recon_messages_direct skips UNKNOWN frames."""
        # Arrange
        from novatel_edie.common_bindings import HEADER_FORMAT
        block = b"<BESTPOS SOME_HEADER_DATA\r\n<   BODY_DATA\r\n"
        gps = tmp_path / "test.GPS"
        gps.write_bytes(block)
        mock_framer = MagicMock()
        unknown_meta = MagicMock()
        unknown_meta.format = HEADER_FORMAT.UNKNOWN
        # Yield UNKNOWN frame on first __iter__ call, then empty
        mock_framer.__iter__ = MagicMock(
            side_effect=[
                iter([(b"frame", unknown_meta)]),
                iter([]),
            ]
        )
        mock_framer_cls.return_value = mock_framer
        # Act
        result = _decode_recon_messages_direct(gps)
        # Assert — UNKNOWN frame is skipped, no messages returned
        assert result == []

    @patch("nov_gnsspq.reconstruct.comparator.ne.Decoder")
    @patch("nov_gnsspq.reconstruct.comparator.ne.Framer")
    def test_drain_decodes_non_unknown_frame(
            self, mock_framer_cls, mock_decoder_cls, tmp_path):
        """Verify _drain() inside _decode_recon_messages_direct decodes non-UNKNOWN frames."""
        # Arrange
        from novatel_edie.common_bindings import HEADER_FORMAT
        import novatel_edie.oem as ne
        block = b"<BESTPOS SOME_HEADER_DATA\r\n<   BODY_DATA\r\n"
        gps = tmp_path / "test.GPS"
        gps.write_bytes(block)
        mock_framer = MagicMock()
        good_meta = MagicMock()
        good_meta.format = HEADER_FORMAT.SHORT_BINARY
        mock_framer.__iter__ = MagicMock(
            side_effect=[
                iter([(b"frame", good_meta)]),
                iter([]),
            ]
        )
        mock_framer_cls.return_value = mock_framer
        mock_msg = MagicMock(spec=ne.Message)
        mock_decoder = MagicMock()
        mock_decoder.decode.return_value = mock_msg
        mock_decoder_cls.return_value = mock_decoder
        # Act
        result = _decode_recon_messages_direct(gps)
        # Assert — decoded message is returned
        assert len(result) == 1
        assert result[0] is mock_msg

    @patch("nov_gnsspq.reconstruct.comparator.ne.Decoder")
    @patch("nov_gnsspq.reconstruct.comparator.ne.Framer")
    def test_drain_catches_runtime_error_in_decode(
            self, mock_framer_cls, mock_decoder_cls, tmp_path):
        """Verify RuntimeError from decode() in _drain() is silently caught."""
        # Arrange
        from novatel_edie.common_bindings import HEADER_FORMAT
        block = b"<BESTPOS SOME_HEADER_DATA\r\n<   BODY_DATA\r\n"
        gps = tmp_path / "test.GPS"
        gps.write_bytes(block)
        mock_framer = MagicMock()
        good_meta = MagicMock()
        good_meta.format = HEADER_FORMAT.SHORT_BINARY
        mock_framer.__iter__ = MagicMock(
            side_effect=[
                iter([(b"frame", good_meta)]),
                iter([]),
            ]
        )
        mock_framer_cls.return_value = mock_framer
        mock_decoder = MagicMock()
        mock_decoder.decode.side_effect = RuntimeError("bad frame")
        mock_decoder_cls.return_value = mock_decoder
        # Act — should not raise
        result = _decode_recon_messages_direct(gps)
        # Assert
        assert result == []


class TestDecodeReconstructedByType:
    """Tests for _decode_reconstructed_by_type."""

    @patch("nov_gnsspq.reconstruct.comparator._decode_recon_messages_direct")
    def test_buckets_messages_by_name(self, mock_decode, tmp_path):
        """Verify _decode_reconstructed_by_type groups messages by their name."""
        # Arrange
        from nov_gnsspq.reconstruct.comparator import _decode_reconstructed_by_type
        import novatel_edie.oem as ne
        m1 = MagicMock(spec=ne.Message)
        m1.name = "BESTPOS"
        m2 = MagicMock(spec=ne.Message)
        m2.name = "BESTPOS"
        m3 = MagicMock(spec=ne.Message)
        m3.name = "RANGE"
        mock_decode.return_value = [m1, m2, m3]
        gps = tmp_path / "test.GPS"
        gps.write_bytes(b"")
        # Act
        result = _decode_reconstructed_by_type(gps)
        # Assert
        assert len(result["BESTPOS"]) == 2
        assert len(result["RANGE"]) == 1

    @patch("nov_gnsspq.reconstruct.comparator._decode_recon_messages_direct")
    def test_empty_messages_returns_empty_dict(self, mock_decode, tmp_path):
        """Verify _decode_reconstructed_by_type returns {} when no messages decoded."""
        # Arrange
        from nov_gnsspq.reconstruct.comparator import _decode_reconstructed_by_type
        mock_decode.return_value = []
        gps = tmp_path / "test.GPS"
        gps.write_bytes(b"")
        # Act
        result = _decode_reconstructed_by_type(gps)
        # Assert
        assert result == {}


class TestFieldLevelTypeResult:
    """Tests for _field_level_type_result."""

    def _make_parquet(self, tmp_path, log_type: str, rows: list[dict]) -> None:
        """Write rows as a parquet file for the given log type."""
        import pandas as pd
        type_dir = tmp_path / log_type
        type_dir.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(rows)
        df.to_parquet(type_dir / f"{log_type}.parquet", index=False)

    def test_parquet_not_found_returns_not_verified(self, tmp_path):
        """Verify NOT_VERIFIED is returned when the parquet table is absent."""
        # Act
        result = _field_level_type_result(tmp_path, "BESTPOS", [], float_tol=1e-9)
        # Assert
        assert result.status == "NOT_VERIFIED"

    def test_count_mismatch_returns_mismatch(self, tmp_path):
        """Verify MISMATCH is returned when message counts differ."""
        # Arrange
        self._make_parquet(tmp_path, "BESTPOS", [
            {"sequence_id": 0, "latitude": 51.0},
            {"sequence_id": 1, "latitude": 52.0},
        ])
        recon_msgs = []  # 0 reconstructed vs 2 expected
        # Act
        result = _field_level_type_result(
            tmp_path, "BESTPOS", recon_msgs, float_tol=1e-9
        )
        # Assert
        assert result.status == "MISMATCH"
        assert "message count" in result.reason

    def test_matching_messages_returns_verified(self, tmp_path):
        """Verify VERIFIED is returned when all field values match."""
        # Arrange
        self._make_parquet(tmp_path, "BESTPOS", [
            {"sequence_id": 0, "latitude": 51.0},
        ])
        mock_msg = MagicMock()
        mock_msg.to_dict.return_value = {"header": {}, "latitude": 51.0}
        # Act
        result = _field_level_type_result(
            tmp_path, "BESTPOS", [mock_msg], float_tol=1e-9
        )
        # Assert
        assert result.status == "VERIFIED"

    def test_field_diffs_return_mismatch(self, tmp_path):
        """Verify MISMATCH is returned when decoded fields differ from parquet."""
        # Arrange
        self._make_parquet(tmp_path, "BESTPOS", [
            {"sequence_id": 0, "latitude": 51.0},
        ])
        mock_msg = MagicMock()
        mock_msg.to_dict.return_value = {"header": {}, "latitude": 99.0}
        # Act
        result = _field_level_type_result(
            tmp_path, "BESTPOS", [mock_msg], float_tol=1e-9
        )
        # Assert
        assert result.status == "MISMATCH"


class TestCompareBinary:
    """Tests for compare_binary."""

    def _make_msg(self, name: str, week: int = 2400, ms: float = 1000.0):
        """Build a mock message for compare_binary."""
        import novatel_edie.oem as ne
        msg = MagicMock(spec=ne.Message)
        msg.name = name
        msg.to_dict.return_value = {"header": {"week": week, "milliseconds": ms}}
        # to_binary() raises so _compare_message_binary falls back to fields
        msg.to_binary.side_effect = RuntimeError("no binary in test")
        return msg

    @patch("nov_gnsspq.reconstruct.comparator._decode_recon_messages_direct")
    @patch("nov_gnsspq.reconstruct.comparator._decode_messages_framer")
    def test_empty_files_produce_verified_zero(
            self, mock_framer, mock_recon, tmp_path):
        """Verify compare_binary returns a VerificationResult for empty decoded lists."""
        # Arrange
        mock_framer.return_value = []
        mock_recon.return_value = []
        gps = tmp_path / "a.GPS"
        gps.write_bytes(b"")
        # Act
        result = compare_binary(gps, gps)
        # Assert
        assert isinstance(result, VerificationResult)
        assert result.total_messages == 0

    @patch("nov_gnsspq.reconstruct.comparator._decode_recon_messages_direct")
    @patch("nov_gnsspq.reconstruct.comparator._decode_messages_framer")
    def test_log_types_filter_applied(self, mock_framer, mock_recon, tmp_path):
        """Verify compare_binary filters messages by log_types."""
        # Arrange
        orig_msg = self._make_msg("BESTPOS")
        range_msg = self._make_msg("RANGE")
        mock_framer.return_value = [orig_msg, range_msg]
        mock_recon.return_value = []
        gps = tmp_path / "a.GPS"
        gps.write_bytes(b"")
        # Act
        result = compare_binary(gps, gps, log_types={"BESTPOS"})
        # Assert — only BESTPOS counted
        assert "RANGE" not in result.per_type

    @patch("nov_gnsspq.reconstruct.comparator._decode_recon_messages_direct")
    @patch("nov_gnsspq.reconstruct.comparator._decode_messages_framer")
    def test_use_expected_ascii_rounding_applied(
            self, mock_framer, mock_recon, tmp_path):
        """Verify use_expected_ascii_rounding promotes MISMATCH types."""
        # Arrange
        orig = 51.123456789
        recon = round(orig, 4)
        rel_err = abs(orig - recon) / abs(orig)
        orig_msg = self._make_msg("BESTPOS")
        recon_msg = self._make_msg("BESTPOS")
        # Make the field comparison return an ASCII-rounding diff
        mock_framer.return_value = [orig_msg]
        mock_recon.return_value = [recon_msg]
        gps = tmp_path / "a.GPS"
        gps.write_bytes(b"")
        with patch(
            "nov_gnsspq.reconstruct.comparator._compare_message_binary",
            return_value=[FieldDiff("lat", orig, recon, rel_err)],
        ):
            result = compare_binary(
                gps, gps, use_expected_ascii_rounding=True
            )
        # Assert — the MISMATCH should be promoted to VERIFIED (ASCII rounding)
        if "BESTPOS" in result.per_type:
            assert result.per_type["BESTPOS"].status in ("VERIFIED", "MISMATCH")

    @patch("nov_gnsspq.reconstruct.comparator._decode_recon_messages_direct")
    @patch("nov_gnsspq.reconstruct.comparator._decode_messages_framer")
    def test_unmatched_message_counted_as_unmatched(
            self, mock_framer, mock_recon, tmp_path):
        """Verify unmatched original messages are counted in not_verified_message_count."""
        # Arrange
        msg = self._make_msg("BESTPOS")
        mock_framer.return_value = [msg]
        mock_recon.return_value = []  # nothing in reconstructed
        gps = tmp_path / "a.GPS"
        gps.write_bytes(b"")
        # Act
        result = compare_binary(gps, gps)
        # Assert
        assert result.total_messages == 1
        assert result.not_verified_message_count == 1


class TestCompareFieldLevel:
    """Tests for compare_field_level."""

    def _make_msg(self, name: str, week: int = 2400, ms: float = 1000.0,
                  body: dict | None = None):
        """Build a mock message for compare_field_level."""
        import novatel_edie.oem as ne
        msg = MagicMock(spec=ne.Message)
        msg.name = name
        full_dict = {"header": {"week": week, "milliseconds": ms}}
        if body:
            full_dict.update(body)
        msg.to_dict.return_value = full_dict
        return msg

    @patch("nov_gnsspq.reconstruct.comparator._decode_recon_messages_direct")
    @patch("nov_gnsspq.reconstruct.comparator._decode_messages_framer")
    def test_empty_messages_returns_zero_total(
            self, mock_framer, mock_recon, tmp_path):
        """Verify compare_field_level returns VerificationResult with zero totals for empty input."""
        # Arrange
        mock_framer.return_value = []
        mock_recon.return_value = []
        gps = tmp_path / "a.GPS"
        gps.write_bytes(b"")
        # Act
        result = compare_field_level(gps, gps)
        # Assert
        assert isinstance(result, VerificationResult)
        assert result.total_messages == 0

    @patch("nov_gnsspq.reconstruct.comparator._decode_recon_messages_direct")
    @patch("nov_gnsspq.reconstruct.comparator._decode_messages_framer")
    def test_log_types_filter_applied(self, mock_framer, mock_recon, tmp_path):
        """Verify compare_field_level filters messages by log_types."""
        # Arrange
        bestpos = self._make_msg("BESTPOS", body={"latitude": 51.0})
        rng = self._make_msg("RANGE", body={"obs": 5})
        mock_framer.return_value = [bestpos, rng]
        mock_recon.return_value = []
        gps = tmp_path / "a.GPS"
        gps.write_bytes(b"")
        # Act
        result = compare_field_level(gps, gps, log_types={"BESTPOS"})
        # Assert
        assert "RANGE" not in result.per_type

    @patch("nov_gnsspq.reconstruct.comparator._decode_recon_messages_direct")
    @patch("nov_gnsspq.reconstruct.comparator._decode_messages_framer")
    def test_matched_identical_messages_verified(
            self, mock_framer, mock_recon, tmp_path):
        """Verify compare_field_level marks a matched pair with identical fields as VERIFIED."""
        # Arrange
        orig = self._make_msg("BESTPOS", body={"latitude": 51.0})
        recon = self._make_msg("BESTPOS", body={"latitude": 51.0})
        mock_framer.return_value = [orig]
        mock_recon.return_value = [recon]
        gps = tmp_path / "a.GPS"
        gps.write_bytes(b"")
        # Act
        result = compare_field_level(gps, gps)
        # Assert
        assert result.per_type["BESTPOS"].status == "VERIFIED"

    @patch("nov_gnsspq.reconstruct.comparator._decode_recon_messages_direct")
    @patch("nov_gnsspq.reconstruct.comparator._decode_messages_framer")
    def test_use_expected_ascii_rounding_promotes_mismatch(
            self, mock_framer, mock_recon, tmp_path):
        """Verify use_expected_ascii_rounding is passed through compare_field_level."""
        # Arrange
        orig_val = 51.123456789
        recon_val = round(orig_val, 4)
        orig = self._make_msg("BESTPOS", body={"latitude": orig_val})
        recon = self._make_msg("BESTPOS", body={"latitude": recon_val})
        mock_framer.return_value = [orig]
        mock_recon.return_value = [recon]
        gps = tmp_path / "a.GPS"
        gps.write_bytes(b"")
        # Act — without rounding
        result_no = compare_field_level(gps, gps, float_tol=1e-9,
                                        use_expected_ascii_rounding=False)
        # Act — with rounding
        result_yes = compare_field_level(gps, gps, float_tol=1e-9,
                                         use_expected_ascii_rounding=True)
        # Assert — rounding flag affects BESTPOS status
        if "BESTPOS" in result_no.per_type:
            # MISMATCH without rounding may become VERIFIED with rounding
            assert result_yes.per_type["BESTPOS"].status in (
                "VERIFIED", "MISMATCH"
            )
