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

Shared data types for nov_gnsspq reconstruction verification results.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Literal, NamedTuple


@dataclasses.dataclass
class FieldDiff:
    """Represents a difference between an original and reconstructed field.

    Attributes:
        - field_name: Name of the differing field.
        - original_value: Value from the original message.
        - reconstructed_value: Value from the reconstructed message.
        - relative_error: Relative error between the two values, or None
            if not applicable.
    """

    field_name: str
    original_value: Any
    reconstructed_value: Any
    relative_error: float | None


@dataclasses.dataclass
class TypeResult:
    """Verification result for a single message type.

    Attributes:
        - status: Overall verification status for this message type.
        - message_count: Number of messages of this type processed.
        - reason: Human-readable explanation of the status, or None.
        - field_diffs: List of per-field differences found during
            verification.
    """

    status: Literal["VERIFIED", "NOT_VERIFIED", "MISMATCH"]
    message_count: int
    reason: str | None
    field_diffs: list[FieldDiff]


@dataclasses.dataclass
class VerificationResult:
    """Aggregated verification result across all message types.

    Attributes:
        - total_messages: Number of messages decoded from the original
            GPS file.
        - verified_count: Number of message types that verified
            successfully.
        - not_verified_message_count: Total message count for NOT_VERIFIED types.
        - mismatch_count: Number of message types with MISMATCH status.
        - per_type: Per-message-type verification results keyed by type
            name.
        - recon_decoded_count: Number of messages decoded from the
            reconstructed GPS file. A value lower than total_messages
            indicates that some messages were silently dropped during
            reconstruction.
    """

    total_messages: int
    verified_count: int
    not_verified_message_count: int
    mismatch_count: int
    per_type: dict[str, TypeResult]
    recon_decoded_count: int = 0


class BothResults(NamedTuple):
    """Paired field-level and binary-level verification results.

    Attributes:
        - field: Verification result from field-level comparison.
        - binary: Verification result from binary-level comparison.
    """

    field: VerificationResult
    binary: VerificationResult
