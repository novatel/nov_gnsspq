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

Comparison functions for verifying reconstructed GPS files against originals.
"""
from __future__ import annotations

import logging
import math
import re
import struct
from functools import lru_cache
from pathlib import Path

from tqdm import tqdm

_log = logging.getLogger(__name__)

import novatel_edie.oem as ne
import pandas as pd
# pylint: disable-next=no-name-in-module  # pybind11 binding
from novatel_edie.common_bindings import HEADER_FORMAT

from nov_gnsspq.reconstruct.types import (FieldDiff, TypeResult,
                                          VerificationResult)

_ABBREV_ASCII_LINE_RE = re.compile(
    rb'<[A-Z][A-Z0-9]+ [^\r\n]+\r\n<[ ]+[^\r\n]+\r\n'
)


def _apply_ascii_rounding_promotion(
        per_type: dict[str, TypeResult]) -> dict[str, TypeResult]:
    """Promote MISMATCH to VERIFIED for types with only ASCII rounding diffs.

    Diffs are preserved in the TypeResult for report display; only the status
    and mismatch counter change. Types with non-ASCII diffs (non-float, large
    errors) remain MISMATCH.

    Args:
        per_type: Mapping of log type name to TypeResult.

    Returns:
        per_type: Updated mapping with eligible types promoted to VERIFIED.
    """
    result = {}
    for log_type, tr in per_type.items():
        if tr.status == "MISMATCH" and tr.field_diffs and all(
            _is_expected_ascii_diff(d) for d in tr.field_diffs
        ):
            result[log_type] = TypeResult(
                status="VERIFIED",
                message_count=tr.message_count,
                reason=(
                    f"all {len(tr.field_diffs)} diff(s) are expected "
                    f"ASCII-format rounding"
                    + (f"; {tr.reason}" if tr.reason else "")
                ),
                field_diffs=tr.field_diffs,
            )
        else:
            result[log_type] = tr
    return result


def _compare_field_dicts(
        original: dict,
        reconstructed: dict,
        float_tol: float) -> list[FieldDiff]:
    """Return FieldDiff entries for any field that does not match.

    Args:
        original: Ground-truth field dict from the original GPS file.
        reconstructed: Field dict from the reconstructed GPS file.
        float_tol: Relative tolerance for floating-point comparisons.

    Returns:
        diffs: List of FieldDiff objects for mismatched fields.
    """
    diffs = []
    for field, orig_val in original.items():
        recon_val = reconstructed.get(field)
        if recon_val is None and orig_val is not None:
            diffs.append(FieldDiff(field, orig_val, None, None))
            continue

        # Enum: compare as integers
        if hasattr(orig_val, "__int__") and not isinstance(
                orig_val, (int, float)):
            if int(orig_val) != int(recon_val):
                diffs.append(FieldDiff(field, orig_val, recon_val, None))
            continue
        if hasattr(recon_val, "__int__") and not isinstance(
                recon_val, (int, float)):
            orig_int = orig_val if isinstance(orig_val, int) else None
            if orig_int is None or orig_int != int(recon_val):
                diffs.append(FieldDiff(field, orig_val, recon_val, None))
            continue

        if isinstance(orig_val, float):
            if not math.isclose(orig_val, recon_val, rel_tol=float_tol):
                rel_err = (
                    abs(orig_val - recon_val) / max(abs(orig_val), 1e-300)
                )
                diffs.append(
                    FieldDiff(field, orig_val, recon_val, rel_err)
                )
        elif orig_val != recon_val:
            diffs.append(FieldDiff(field, orig_val, recon_val, None))
    return diffs


def _decode_messages_framer(gps_path: str | Path) -> list[ne.Message]:
    """Decode GPS messages using EDIE Framer and Decoder.

    Framer-based decoding is more robust than FileParser for files that mix
    ASCII and binary frames or contain unrecognised bytes between valid
    messages. Framer explicitly scans for NovAtel frame-start sequences
    (<, #, 0xAA44...) rather than relying on sequential line parsing, so it
    recovers reliably after encountering garbage bytes.

    Args:
        gps_path: Path to the GPS file to decode.

    Returns:
        messages: List of decoded EDIE Message objects.
    """
    framer = ne.Framer()
    framer.report_unknown_bytes = True
    decoder = ne.Decoder()
    messages: list[ne.Message] = []

    def _drain(framer: ne.Framer):
        for frame_data, metadata in framer:
            if metadata.format == HEADER_FORMAT.UNKNOWN:
                continue
            try:
                msg = decoder.decode(frame_data)
                if isinstance(msg, ne.Message):
                    messages.append(msg)
            except (RuntimeError, ValueError) as exc:
                _log.debug("Skipped undecoded frame in framer path: %s", exc)

    with open(gps_path, "rb") as f:
        chunk = f.read(1 << 16)
        while chunk:
            framer.write(chunk)
            _drain(framer)
            chunk = f.read(1 << 16)

    # Sentinel flushes any trailing incomplete frame — Framer needs to see
    # the start of the next message before it finalises the current one.
    framer.write(b"<DUMMY\r\n")
    _drain(framer)

    return messages


def _decode_reconstructed_by_type(
        reconstructed_gps: Path) -> dict[str, list]:
    """Parse reconstructed GPS and bucket decoded messages by log type name.

    Args:
        reconstructed_gps: Path to the reconstructed GPS file.

    Returns:
        buckets: Mapping of log type name to list of decoded messages.
    """
    buckets: dict[str, list] = {}
    for msg in _decode_recon_messages_direct(reconstructed_gps):
        buckets.setdefault(msg.name, []).append(msg)
    return buckets


def _decode_recon_messages_direct(
        gps_path: str | Path) -> list[ne.Message]:
    """Decode a reconstructed GPS file by scanning for abbrev ASCII lines.

    The EDIE Framer can be confused by unknown byte sequences that start with
    '#' or '%' (NovAtel frame-start characters), consuming subsequent valid
    '<MESSAGE' lines as part of an UNKNOWN chunk. In a reconstructed file all
    supported messages are written as 2-line abbrev ASCII blocks (header +
    body), so we extract them with a regex and feed them to the Framer without
    the interstitial unknown bytes. The Framer is drained after each write to
    avoid buffer overflow.

    Args:
        gps_path: Path to the reconstructed GPS file.

    Returns:
        messages: List of decoded EDIE Message objects.
    """
    data = Path(gps_path).read_bytes()
    framer = ne.Framer()
    decoder = ne.Decoder()
    messages: list[ne.Message] = []

    def _drain():
        for frame_data, metadata in framer:
            if metadata.format == HEADER_FORMAT.UNKNOWN:
                continue
            try:
                msg = decoder.decode(frame_data)
                if isinstance(msg, ne.Message):
                    messages.append(msg)
            except (RuntimeError, ValueError) as exc:
                _log.debug("Skipped undecoded frame in direct path: %s", exc)

    for match in _ABBREV_ASCII_LINE_RE.finditer(data):
        framer.write(b"\r\n" + match.group())
        _drain()

    framer.write(b"<DUMMY\r\n")
    _drain()

    return messages


def _field_level_type_result(
        db_path: Path,
        log_type: str,
        recon_msgs_for_type: list,
        float_tol: float) -> TypeResult:
    """Return a TypeResult for one log type using parquet vs decoded fields.

    Args:
        db_path: Path to the nov_gnsspq database directory.
        log_type: Name of the log type to verify.
        recon_msgs_for_type: Decoded messages from the reconstructed GPS for
            this log type.
        float_tol: Relative tolerance for floating-point comparisons.

    Returns:
        result: TypeResult describing the verification outcome.
    """
    p = db_path / log_type / f"{log_type}.parquet"
    if not p.exists():
        return TypeResult(
            status="NOT_VERIFIED",
            message_count=0,
            reason="parquet table not found",
            field_diffs=[],
        )

    truth_rows = (
        pd.read_parquet(p).sort_values("sequence_id").to_dict("records")
    )
    count = len(truth_rows)

    if len(truth_rows) != len(recon_msgs_for_type):
        return TypeResult(
            status="MISMATCH",
            message_count=count,
            reason=(
                f"message count: expected {len(truth_rows)}, "
                f"got {len(recon_msgs_for_type)}"
            ),
            field_diffs=[],
        )

    all_diffs: list[FieldDiff] = []
    for truth, recon_msg in zip(truth_rows, recon_msgs_for_type):
        recon_dict = recon_msg.to_dict()
        hdr = recon_dict.pop("header", {})
        recon_flat = {f"header_{k}": v for k, v in hdr.items()}
        recon_flat.update(recon_dict)
        truth_body = {}
        for tk, tv in truth.items():
            if (
                tk.endswith("_raw")
                or tk in ("sequence_id", "parent_id")
                or tk.startswith("header_")
            ):
                continue
            raw_key = f"{tk}_raw"
            truth_body[tk] = truth[raw_key] if raw_key in truth else tv
        recon_body = {
            k: v
            for k, v in recon_flat.items()
            if not k.startswith("header_")
        }
        all_diffs.extend(
            _compare_field_dicts(truth_body, recon_body, float_tol)
        )

    if all_diffs:
        return TypeResult(
            status="MISMATCH",
            message_count=count,
            reason=f"{len(all_diffs)} field diff(s)",
            field_diffs=all_diffs,
        )
    return TypeResult(
        status="VERIFIED",
        message_count=count,
        reason=None,
        field_diffs=[],
    )


@lru_cache(maxsize=256)
def _float_offsets(
        msg_name: str,
        msg_crc: int = 0) -> list[tuple[int, str]]:
    """Return byte offsets for every float/double field in a message payload.

    Returns a list of (byte_offset, fmt) pairs where fmt is 'f' (4-byte
    IEEE 754 float) or 'd' (8-byte double). Offsets are relative to the
    start of the message payload (after the binary header). Used by
    compare_binary to apply float tolerance at the correct byte positions
    instead of requiring exact byte equality.

    Falls back to the latest available CRC definition if msg_crc is not in
    the schema. Returns [] if the message type is unknown or the schema
    lookup fails.

    Args:
        msg_name: NovAtel log type name (e.g. 'BESTPOS').
        msg_crc: Message definition CRC for version selection; defaults to 0
            which causes fallback to the latest available definition.

    Returns:
        offsets: List of (byte_offset, fmt) tuples.
    """
    try:
        from novatel_edie.oem import get_builtin_database
        db = get_builtin_database()
        defn = db.get_msg_def(msg_name)
        if defn is None or not defn.fields:
            return []
        fields_dict = defn.fields
        if msg_crc in fields_dict:
            field_list = fields_dict[msg_crc]
        else:
            latest_crc = max(fields_dict.keys())
            field_list = fields_dict[latest_crc]
        offsets: list[tuple[int, str]] = []
        byte_offset = 0
        for field in field_list:
            # data_type.name is a non-string object — str() converts it to
            # "FLOAT", "DOUBLE", etc.
            type_name = str(field.data_type.name)
            # Array fields: total size = array_length * element_size.
            if hasattr(field, "array_length"):
                type_len = field.array_length * field.data_type.length
            else:
                type_len = field.data_type.length
            if type_name == "FLOAT":
                offsets.append((byte_offset, "f"))
            elif type_name == "DOUBLE":
                offsets.append((byte_offset, "d"))
            byte_offset += type_len
        return offsets
    except (ImportError, AttributeError, TypeError, RuntimeError):
        return []


def _is_expected_ascii_diff(d: FieldDiff) -> bool:
    """Return True if this diff is fully explained by EDIE's ASCII encoding.

    Covers three cases:
    - Negligible: relative error < 0.1 ppm (1e-7).
    - ASCII decimal truncation: EDIE writes fixed decimal places; NovAtel
      binary stores many fields as float32, so value is float32(round(orig,
      N)).
    - ASCII significant-figure truncation: EDIE encodes in scientific
      notation with limited sig figs; any diff with rel error < 1e-5
      qualifies.

    Non-float diffs (relative_error is None) always return False.

    Args:
        d: FieldDiff to evaluate.

    Returns:
        is_expected: True if the diff is attributable to ASCII encoding.
    """
    if d.relative_error is None:
        return False
    if d.relative_error < 1e-7:
        return True
    try:
        orig = float(d.original_value)
        recon = float(d.reconstructed_value)
    except (TypeError, ValueError):
        return False
    # ASCII decimal truncation (float32 or double)
    for n in range(2, 8):
        rounded = round(orig, n)
        try:
            f32 = struct.unpack("f", struct.pack("f", rounded))[0]
        except (struct.error, OverflowError):
            f32 = None
        tol = 1e-12 * max(abs(recon), 1e-10)
        if abs(rounded - recon) < tol or (
            f32 is not None and abs(f32 - recon) < tol
        ):
            return True
    if d.relative_error < 1e-5:
        return True
    # Significant-figure truncation
    if orig != 0 and recon != 0:
        mag = math.floor(math.log10(abs(orig)))
        for n in range(2, 8):
            scale = 10 ** (n - 1 - mag)
            rounded = round(orig * scale) / scale
            try:
                f32 = struct.unpack("f", struct.pack("f", rounded))[0]
            except (struct.error, OverflowError):
                f32 = None
            tol = 1e-12 * max(abs(recon), 1e-100)
            if abs(rounded - recon) < tol or (
                f32 is not None and abs(f32 - recon) < tol
            ):
                return True
    return False


def _join_by_timestamp(
        orig_msgs: list,
        recon_msgs: list) -> list[tuple]:
    """Join original and reconstructed messages on (name, week, milliseconds).

    Returns a list of (orig_msg, recon_msg | None) pairs. For each original
    message the reconstructed lookup is searched for a message with the same
    name and header timestamps. When multiple messages share a key they are
    paired in the order they appear. An original message with no matching
    reconstructed message yields (orig_msg, None).

    This replaces the old positional zip approach so that messages dropped
    from the reconstructed file (because EDIE cannot reconstruct that type)
    do not cause every subsequent message to be compared against the wrong
    partner.

    Args:
        orig_msgs: Decoded messages from the original GPS file.
        recon_msgs: Decoded messages from the reconstructed GPS file.

    Returns:
        pairs: List of (orig_msg, recon_msg | None) tuples.
    """
    recon_by_key: dict[tuple, list] = {}
    for msg in recon_msgs:
        week, ms = _msg_header_timestamps(msg)
        recon_by_key.setdefault((msg.name, week, ms), []).append(msg)

    recon_used: dict[tuple, int] = {}
    pairs: list[tuple] = []
    for orig_msg in orig_msgs:
        week, ms = _msg_header_timestamps(orig_msg)
        key = (orig_msg.name, week, ms)
        idx = recon_used.get(key, 0)
        candidates = recon_by_key.get(key, [])
        if idx < len(candidates):
            pairs.append((orig_msg, candidates[idx]))
            recon_used[key] = idx + 1
        else:
            pairs.append((orig_msg, None))
    return pairs


def _msg_body_dict(msg) -> dict:
    """Extract the body fields from a decoded EDIE Message as a plain dict.

    Args:
        msg: Decoded EDIE Message object.

    Returns:
        body: Dict of body fields with the header entry removed.
    """
    d = msg.to_dict()
    d.pop("header", None)
    return d


def _msg_header_timestamps(msg) -> tuple[object, object]:
    """Return (week, milliseconds) from the message header dict.

    Args:
        msg: Decoded EDIE Message object.

    Returns:
        timestamps: Tuple of (week, milliseconds), or (None, None) on error.
    """
    try:
        hdr = msg.to_dict().get("header", {})
        return hdr.get("week"), hdr.get("milliseconds")
    except (AttributeError, RuntimeError):
        return None, None


def _build_type_result(
        count: int,
        unmatched: int,
        diffs: list[FieldDiff],
        diff_label: str) -> TypeResult:
    """Build a TypeResult from per-type comparison stats.

    Args:
        count: Total message count for this log type.
        unmatched: Messages with no timestamp match in the reconstructed file.
        diffs: Accumulated field or byte diffs for this log type.
        diff_label: Human-readable label for the diff kind (e.g. "field diff(s)").

    Returns:
        TypeResult with status MISMATCH, NOT_VERIFIED, or VERIFIED.
    """
    matched = count - unmatched
    unmatched_note = (
        f"{unmatched}/{count} message(s) had no timestamp match "
        f"in reconstructed GPS" if unmatched else None
    )
    if diffs:
        reason = f"{len(diffs)} {diff_label}"
        if unmatched_note:
            reason = f"{reason}; {unmatched_note}"
        return TypeResult(
            status="MISMATCH",
            message_count=count,
            reason=reason,
            field_diffs=diffs,
        )
    if matched == 0:
        return TypeResult(
            status="NOT_VERIFIED",
            message_count=count,
            reason=unmatched_note,
            field_diffs=[],
        )
    return TypeResult(
        status="VERIFIED",
        message_count=count,
        reason=unmatched_note,
        field_diffs=[],
    )


def _build_per_type_results(
        type_counts: dict[str, int],
        type_unmatched: dict[str, int],
        all_diffs: dict[str, list[FieldDiff]],
        diff_label: str) -> dict[str, TypeResult]:
    """Build the per-type TypeResult mapping from accumulated comparison stats.

    Args:
        type_counts: Total message count per log type.
        type_unmatched: Unmatched message count per log type.
        all_diffs: Accumulated diffs per log type.
        diff_label: Human-readable label for the diff kind.

    Returns:
        Mapping of log type name to TypeResult.
    """
    return {
        log_type: _build_type_result(
            count,
            type_unmatched.get(log_type, 0),
            all_diffs.get(log_type, []),
            diff_label,
        )
        for log_type, count in type_counts.items()
    }


def _summarize_per_type(
        per_type: dict[str, TypeResult]) -> tuple[int, int, int]:
    """Return (verified_count, not_verified_message_count, mismatch_count) from per_type.

    Args:
        per_type: Mapping of log type name to TypeResult.

    Returns:
        Tuple of (verified_count, not_verified_message_count, mismatch_count).
    """
    verified = sum(1 for t in per_type.values() if t.status == "VERIFIED")
    not_verified = sum(
        t.message_count
        for t in per_type.values()
        if t.status == "NOT_VERIFIED"
    )
    mismatched = sum(
        1 for t in per_type.values() if t.status == "MISMATCH"
    )
    return verified, not_verified, mismatched


def _compare_payload_bytes(
        orig_payload: bytes,
        recon_payload: bytes,
        msg_name: str,
        float_tol: float) -> list[FieldDiff]:
    """Compare two binary payloads byte-by-byte with float tolerance at schema offsets.

    Args:
        orig_payload: Binary payload extracted from the original message.
        recon_payload: Binary payload extracted from the reconstructed message.
        msg_name: NovAtel log type name used to look up float field offsets.
        float_tol: Relative tolerance for floating-point comparisons.

    Returns:
        diffs: List of FieldDiff objects for any mismatched bytes or floats.
    """
    if len(orig_payload) != len(recon_payload):
        return [
            FieldDiff(
                "_payload_length",
                len(orig_payload),
                len(recon_payload),
                None,
            )
        ]

    offsets = _float_offsets(msg_name)
    float_field_at: dict[int, tuple[int, str]] = {}
    for start, fmt in offsets:
        size = 4 if fmt == "f" else 8
        for i in range(start, start + size):
            float_field_at[i] = (start, fmt)

    diffs: list[FieldDiff] = []
    compared_float_starts: set[int] = set()
    for i, (ob, rb) in enumerate(zip(orig_payload, recon_payload)):
        if ob == rb:
            continue
        if i in float_field_at:
            start, fmt = float_field_at[i]
            if start in compared_float_starts:
                continue
            compared_float_starts.add(start)
            size = 4 if fmt == "f" else 8
            orig_val = struct.unpack(
                fmt, orig_payload[start:start + size]
            )[0]
            recon_val = struct.unpack(
                fmt, recon_payload[start:start + size]
            )[0]
            rel_err = (
                abs(orig_val - recon_val) / max(abs(orig_val), 1e-300)
            )
            if rel_err > float_tol:
                diffs.append(
                    FieldDiff(
                        f"_float_offset_{start}",
                        orig_val,
                        recon_val,
                        rel_err,
                    )
                )
        else:
            diffs.append(FieldDiff(f"_byte_{i}", ob, rb, None))
    return diffs


def _compare_message_binary(
        orig_msg,
        recon_msg,
        float_tol: float) -> list[FieldDiff]:
    """Compare a matched message pair at binary level.

    Falls back to field-level comparison when ``to_binary()`` fails on either
    message. On success, extracts payloads via the binary header length byte
    and delegates byte-level comparison to ``_compare_payload_bytes``.

    Args:
        orig_msg: Decoded EDIE Message from the original file.
        recon_msg: Decoded EDIE Message from the reconstructed file.
        float_tol: Relative tolerance for float fields.

    Returns:
        diffs: List of FieldDiff objects for any mismatches.
    """
    try:
        orig_bytes = orig_msg.to_binary().message
        recon_bytes = recon_msg.to_binary().message
    except (AttributeError, RuntimeError):
        return _compare_field_dicts(
            _msg_body_dict(orig_msg),
            _msg_body_dict(recon_msg),
            float_tol,
        )
    header_len = orig_bytes[3]
    return _compare_payload_bytes(
        orig_bytes[header_len:-4],
        recon_bytes[header_len:-4],
        orig_msg.name,
        float_tol,
    )


def compare_binary(
        original_gps: str | Path,
        reconstructed_gps: str | Path,
        float_tol: float = 1e-9,
        log_types: set[str] | None = None,
        use_expected_ascii_rounding: bool = False) -> VerificationResult:
    """Compare original GPS against reconstructed GPS at the binary level.

    The original file is decoded with _decode_messages_framer. The
    reconstructed file is decoded with _decode_recon_messages_direct (regex
    scan for abbrev ASCII lines), which is robust to unknown byte sequences
    that start with NovAtel frame-start characters that would confuse the
    streaming Framer. For each matched message pair, both messages are
    re-encoded to binary via to_binary(). The binary payloads are then
    compared byte-by-byte. At byte offsets corresponding to float/double
    fields (from EDIE's runtime schema via _float_offsets), float tolerance
    is applied. At all other offsets, exact byte equality is required.

    Encoding both messages through to_binary() normalises them to the same
    wire format, so source-format differences (ASCII vs binary) do not
    produce false mismatches.

    Args:
        original_gps: Path to the original GPS file.
        reconstructed_gps: Path to the reconstructed GPS file.
        float_tol: Relative tolerance for float/double field comparisons.
        log_types: If provided, only messages in this set are compared.
        use_expected_ascii_rounding: If True, types whose only diffs are due
            to EDIE's ASCII encoding are promoted from MISMATCH to VERIFIED.

    Returns:
        result: VerificationResult summarising the comparison outcome.
    """
    orig_msgs = _decode_messages_framer(original_gps)
    recon_msgs = _decode_recon_messages_direct(reconstructed_gps)

    if log_types is not None:
        orig_msgs = [m for m in orig_msgs if m.name in log_types]
        recon_msgs = [m for m in recon_msgs if m.name in log_types]

    all_diffs: dict[str, list[FieldDiff]] = {}
    type_counts: dict[str, int] = {}
    type_unmatched: dict[str, int] = {}

    pairs = _join_by_timestamp(orig_msgs, recon_msgs)
    for orig_msg, recon_msg in tqdm(
            pairs, total=len(pairs), desc="Comparing (binary)", unit="msg",
            ncols=100):
        log_type = orig_msg.name
        type_counts[log_type] = type_counts.get(log_type, 0) + 1
        if recon_msg is None:
            type_unmatched[log_type] = type_unmatched.get(log_type, 0) + 1
            continue
        diffs = _compare_message_binary(orig_msg, recon_msg, float_tol)
        if diffs:
            all_diffs.setdefault(log_type, []).extend(diffs)

    per_type = _build_per_type_results(
        type_counts, type_unmatched, all_diffs, "byte/float diff(s)"
    )
    if use_expected_ascii_rounding:
        per_type = _apply_ascii_rounding_promotion(per_type)
    verified, not_verified, mismatched = _summarize_per_type(per_type)
    return VerificationResult(
        total_messages=len(orig_msgs),
        verified_count=verified,
        not_verified_message_count=not_verified,
        mismatch_count=mismatched,
        per_type=per_type,
        recon_decoded_count=len(recon_msgs),
    )


def compare_field_level(
        original_gps: str | Path,
        reconstructed_gps: str | Path,
        float_tol: float = 1e-9,
        log_types: set[str] | None = None,
        use_expected_ascii_rounding: bool = False) -> VerificationResult:
    """Compare original GPS against reconstructed GPS field-by-field.

    Both files are decoded with _decode_messages_framer (EDIE Framer +
    Decoder). Messages are matched by (name, week, milliseconds) rather than
    positionally, so message types that EDIE cannot reconstruct do not cause
    false mismatches for the types it can.

    A message present in the original with no timestamp match in the
    reconstructed file is recorded as NOT_VERIFIED for that type.

    Args:
        original_gps: Path to the original GPS file.
        reconstructed_gps: Path to the reconstructed GPS file.
        float_tol: Relative tolerance for floating-point field comparisons.
        log_types: If provided, only messages in this set are compared.
        use_expected_ascii_rounding: If True, types whose only diffs are due
            to EDIE's ASCII encoding are promoted from MISMATCH to VERIFIED.

    Returns:
        result: VerificationResult summarising the comparison outcome.
    """
    orig_msgs = _decode_messages_framer(original_gps)
    recon_msgs = _decode_recon_messages_direct(reconstructed_gps)

    if log_types is not None:
        orig_msgs = [m for m in orig_msgs if m.name in log_types]
        recon_msgs = [m for m in recon_msgs if m.name in log_types]

    all_diffs: dict[str, list[FieldDiff]] = {}
    type_counts: dict[str, int] = {}
    type_unmatched: dict[str, int] = {}

    pairs = _join_by_timestamp(orig_msgs, recon_msgs)
    for orig_msg, recon_msg in tqdm(
            pairs, total=len(pairs), desc="Comparing (field)", unit="msg",
            ncols=100):
        log_type = orig_msg.name
        type_counts[log_type] = type_counts.get(log_type, 0) + 1
        if recon_msg is None:
            type_unmatched[log_type] = type_unmatched.get(log_type, 0) + 1
            continue
        diffs = _compare_field_dicts(
            _msg_body_dict(orig_msg),
            _msg_body_dict(recon_msg),
            float_tol,
        )
        if diffs:
            all_diffs.setdefault(log_type, []).extend(diffs)

    per_type = _build_per_type_results(
        type_counts, type_unmatched, all_diffs, "field diff(s)"
    )
    if use_expected_ascii_rounding:
        per_type = _apply_ascii_rounding_promotion(per_type)
    verified, not_verified, mismatched = _summarize_per_type(per_type)
    return VerificationResult(
        total_messages=len(orig_msgs),
        verified_count=verified,
        not_verified_message_count=not_verified,
        mismatch_count=mismatched,
        per_type=per_type,
        recon_decoded_count=len(recon_msgs),
    )
