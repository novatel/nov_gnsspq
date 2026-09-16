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

Unit tests for the reconstruct data types module.
"""
import pytest

from nov_gnsspq.reconstruct.types import (
    BothResults,
    FieldDiff,
    TypeResult,
    VerificationResult,
)

# pylint: disable=protected-access


class TestFieldDiff:
    """Tests for FieldDiff."""

    def test_fields(self):
        """Tests FieldDiff stores all fields correctly."""
        # Act
        fd = FieldDiff("lat", 1.0, 1.0000001, 1e-7)
        # Assert
        assert fd.field_name == "lat"
        assert fd.original_value == 1.0
        assert fd.reconstructed_value == 1.0000001
        assert fd.relative_error == pytest.approx(1e-7)

    def test_relative_error_none_for_non_float(self):
        """Tests FieldDiff accepts None relative_error for non-float fields."""
        # Act
        fd = FieldDiff("status", 1, 2, None)
        # Assert
        assert fd.relative_error is None


class TestTypeResult:
    """Tests for TypeResult."""

    def test_defaults(self):
        """Tests TypeResult initializes with empty field_diffs list."""
        # Act
        tr = TypeResult(
            status="VERIFIED",
            message_count=10,
            reason=None,
            field_diffs=[],
        )
        # Assert
        assert tr.field_diffs == []

    def test_not_verified_has_reason(self):
        """Tests TypeResult stores the reason for NOT_VERIFIED status."""
        # Act
        tr = TypeResult(
            status="NOT_VERIFIED",
            message_count=5,
            reason="nested obs",
            field_diffs=[],
        )
        # Assert
        assert tr.reason == "nested obs"


class TestVerificationResult:
    """Tests for VerificationResult."""

    def test_totals(self):
        """Tests VerificationResult stores total_messages correctly."""
        # Act
        vr = VerificationResult(
            total_messages=100,
            verified_count=80,
            not_verified_message_count=20,
            mismatch_count=0,
            per_type={},
        )
        # Assert
        assert vr.total_messages == 100

    def test_recon_decoded_count_defaults_to_zero(self):
        """Tests recon_decoded_count defaults to zero when not provided."""
        # Act
        vr = VerificationResult(
            total_messages=100,
            verified_count=80,
            not_verified_message_count=20,
            mismatch_count=0,
            per_type={},
        )
        # Assert
        assert vr.recon_decoded_count == 0

    def test_recon_decoded_count_can_be_set(self):
        """Tests recon_decoded_count can be explicitly provided."""
        # Act
        vr = VerificationResult(
            total_messages=100,
            verified_count=80,
            not_verified_message_count=20,
            mismatch_count=0,
            per_type={},
            recon_decoded_count=98,
        )
        # Assert
        assert vr.recon_decoded_count == 98


class TestBothResults:
    """Tests for BothResults."""

    def _make_vr(self):
        """Provides a minimal VerificationResult for use in tests."""
        return VerificationResult(
            total_messages=10,
            verified_count=8,
            not_verified_message_count=2,
            mismatch_count=0,
            per_type={},
        )

    def test_both_results_is_namedtuple(self):
        """Tests BothResults stores field and binary results as attributes."""
        # Arrange
        field = self._make_vr()
        binary = self._make_vr()
        # Act
        r = BothResults(field=field, binary=binary)
        # Assert
        assert r.field is field
        assert r.binary is binary

    def test_both_results_unpacks(self):
        """Tests BothResults supports tuple unpacking."""
        # Arrange
        field = self._make_vr()
        binary = self._make_vr()
        # Act
        f, b = BothResults(field=field, binary=binary)
        # Assert
        assert f is field
        assert b is binary
