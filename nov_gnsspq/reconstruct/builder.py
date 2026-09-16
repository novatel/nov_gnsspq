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

Reconstructs GPS files from a nov_gnsspq parquet database using EDIE.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from nov_gnsspq.exceptions import ReconstructionError
from nov_gnsspq.reader.schema import PARENT_ID_COL, SEQUENCE_ID_COL

log = logging.getLogger(__name__)

_SKIP_COLS = frozenset({SEQUENCE_ID_COL, PARENT_ID_COL})

_HEADER_FLOAT_FIELDS = frozenset({"milliseconds"})

# Fields accepted by the EDIE ``Header`` constructor. Parquet also stores
# header_message_id, header_length and header_message_definition_crc, but
# EDIE derives those on encode and exposes them as read-only properties, so
# passing them to the constructor raises TypeError. An allow-list is used
# rather than a skip-list so that header fields added by future EDIE
# releases are dropped instead of breaking construction outright.
_HEADER_CTOR_FIELDS = frozenset({
    "message_type",
    "port_address",
    "sequence",
    "idle_time",
    "time_status",
    "week",
    "milliseconds",
    "receiver_status",
    "receiver_sw_version",
})


def _build_message_payload(
        log_type: str,
        row: dict,
        output_format: str = "abbrev_ascii") -> bytes | None:
    """Constructs an EDIE message from a parquet row and returns encoded bytes.

    For binary output a two-stage encode is used:
    construct -> abbrev_ascii -> Framer/Decoder -> to_binary().
    This lets EDIE recompute format-specific header fields (message_type,
    length) correctly, since directly calling to_binary() on a manually
    constructed message produces a corrupt binary header.

    Args:
        log_type: EDIE message type name (e.g. "BESTPOS").
        row: Dictionary of column name -> value from a parquet row.
        output_format: Either "abbrev_ascii" (default) or "binary".

    Returns:
        Encoded message bytes, or None if the type is unsupported or
        construction fails.
    """
    from novatel_edie.oem import Decoder, Framer, Header
    from novatel_edie.oem import messages as _ne_messages

    msg_class = getattr(_ne_messages, log_type, None)
    if msg_class is None:
        return None
    try:
        hdr_fields = _cast_header_fields({
            name: v
            for k, v in row.items()
            if k.startswith("header_")
            and (name := k.removeprefix("header_")) in _HEADER_CTOR_FIELDS
        })
        body = _filter_body_columns(row)
        header = Header(**hdr_fields)
        msg = msg_class(header=header, **body)
        abbrev = msg.to_abbrev_ascii().message
        if output_format == "binary":
            framer = Framer()
            framer.write(abbrev + b"\r\n")
            frame, _ = framer.get_frame()
            parsed = Decoder().decode(frame)
            return parsed.to_binary().message
        return abbrev
    except (TypeError, ValueError, AttributeError, RuntimeError) as exc:
        log.debug("Failed to construct %s: %s", log_type, exc)
        return None


def _cast_header_fields(hdr: dict) -> dict:
    """Casts header field values to the types the EDIE Header constructor needs.

    Pandas reads integer parquet columns as float64; Header rejects floats for
    every field except milliseconds.

    Args:
        hdr: Raw header field dictionary read from parquet.

    Returns:
        Dictionary with values cast to int or float as appropriate.
    """
    result = {}
    for k, v in hdr.items():
        if k in _HEADER_FLOAT_FIELDS:
            result[k] = float(v)
        else:
            try:
                result[k] = int(v)
            except (TypeError, ValueError):
                result[k] = v
    return result


def _filter_body_columns(row: dict) -> dict:
    """Strips parquet-internal columns before passing to the EDIE constructor.

    Enum fields are stored as strings in parquet alongside a {field}_raw
    integer. EDIE constructors require the integer value, so _raw values
    are substituted when present.

    Args:
        row: Full parquet row dictionary including header and internal cols.

    Returns:
        Filtered dictionary containing only body fields with correct types.
    """
    raw_fields = {k[:-4] for k in row if k.endswith("_raw")}
    result = {}
    for k, v in row.items():
        if (k in _SKIP_COLS
                or k.startswith("header_")
                or k.endswith("_raw")):
            continue
        if k in raw_fields:
            result[k] = row[f"{k}_raw"]
        else:
            result[k] = v
    return result


def _find_log_index(db_path: Path) -> Path:
    """Returns the path to the log-index parquet table within the database.

    Args:
        db_path: Root directory of the nov_gnsspq parquet database.

    Returns:
        Path to the log-index parquet file.

    Raises:
        FileNotFoundError: If neither the primary nor fallback index exists.
    """
    db_path = Path(db_path)
    primary = db_path / f"{db_path.name}.parquet"
    if primary.exists():
        return primary
    fallback = db_path / "log_table.parquet"
    if fallback.exists():
        return fallback
    raise FileNotFoundError(
        f"No log-index table found in {db_path}. "
        f"Expected {primary.name} or log_table.parquet."
    )


def reconstruct(
        db_path: str | Path,
        output_gps: str | Path,
        output_format: str = "abbrev_ascii"):
    """Writes a GPS file reconstructed from a nov_gnsspq parquet database.

    Supported message types are reconstructed from their parquet tables via
    EDIE. Unsupported or unknown types are copied verbatim from
    unknown_data.parquet using sequence_id as the join key.

    Args:
        db_path: Root directory of the nov_gnsspq parquet database.
        output_gps: Destination path for the reconstructed GPS file.
        output_format: Either "abbrev_ascii" (default) or "binary".

    Raises:
        ReconstructionError: If a sequence_id for an unknown type is absent
            from unknown_data.parquet.
    """
    db_path = Path(db_path)
    output_gps = Path(output_gps)

    log_index_path = _find_log_index(db_path)
    log_index = (
        pd.read_parquet(log_index_path)
        .sort_values("sequence_id")
        .reset_index(drop=True)
    )
    all_types = log_index["log"].unique().tolist()

    # Load raw payloads for unknown/unsupported messages keyed by sequence_id.
    unknown_payloads: dict[int, bytes] = {}
    unknown_parquet = db_path / "unknown_data.parquet"
    if unknown_parquet.exists():
        unk_df = pd.read_parquet(unknown_parquet)
        for _, row in unk_df.iterrows():
            seq = int(row["sequence_id"])
            if row["payload"] is None:
                log.warning(
                    "sequence_id=%d has no raw bytes in unknown_data.parquet "
                    "(payload was unrecoverable at write time); "
                    "message will be omitted from output",
                    seq,
                )
                unknown_payloads[seq] = b""
            else:
                unknown_payloads[seq] = bytes(row["payload"])

    # Load parquet tables only for types with a subdirectory + parquet file.
    type_tables: dict[str, pd.DataFrame] = {}
    type_counters: dict[str, int] = {}
    for log_type in all_types:
        parquet_path = db_path / log_type / f"{log_type}.parquet"
        if parquet_path.exists():
            df = (
                pd.read_parquet(parquet_path)
                .sort_values("sequence_id")
                .reset_index(drop=True)
            )
            type_tables[log_type] = df
            type_counters[log_type] = 0

    total_messages = len(log_index)
    log.info(
        "Rebuilding %d messages (%d types) from database...",
        total_messages, len(all_types),
    )
    output_gps.parent.mkdir(parents=True, exist_ok=True)
    _had_construction_failure = False
    with open(output_gps, "wb") as f:
        for _, index_row in tqdm(
                log_index.iterrows(),
                total=total_messages,
                desc="Reconstructing",
                unit="msg",
                ncols=100):
            log_type = index_row["log"]
            seq_id = int(index_row["sequence_id"])

            if log_type in type_tables:
                row_idx = type_counters[log_type]
                df = type_tables[log_type]
                if row_idx < len(df):
                    row = df.iloc[row_idx].to_dict()
                    type_counters[log_type] += 1
                    payload = _build_message_payload(
                        log_type, row, output_format
                    )
                    if payload is not None:
                        f.write(payload)
                        continue
                    _had_construction_failure = True
                    # Construction failed -- fall back to raw bytes if available.
                    if seq_id in unknown_payloads:
                        f.write(unknown_payloads[seq_id])
                        continue
                    log.debug(
                        "Construction failed for %s seq=%d; "
                        "no raw bytes, skipping",
                        log_type,
                        seq_id,
                    )
                    continue
            else:
                # Unknown/unsupported type -- copy raw bytes verbatim.
                if seq_id not in unknown_payloads:
                    raise ReconstructionError(
                        f"sequence_id={seq_id} (type={log_type}) is not in "
                        f"unknown_data.parquet. This indicates a writer bug "
                        f"-- every unsupported message should be stored there."
                    )
                f.write(unknown_payloads[seq_id])

    if _had_construction_failure:
        log.warning(
            "Some messages failed to reconstruct; "
            "re-run with DEBUG logging to see per-message details"
        )
