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

EDIE-specific parallel processing components: boundary detection, chunk
decoding, worker-process functions, and TableNode accumulation infrastructure.
"""

from __future__ import annotations

import enum
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, TypedDict

import novatel_edie as ne
import novatel_edie.oem as ne_oem
import pyarrow as pa
import pyarrow.parquet as pq

from nov_gnsspq.reader.schema import (HEADER_PREFIX, PARENT_ID_COL,
                                      SEQUENCE_ID_COL)
from nov_gnsspq.writer.progress import (WorkerProgressReporter,
                                        _message_byte_len)

_log = logging.getLogger(__name__)

_FLUSH_CHECK_INTERVAL = 500


class WorkerResult(TypedDict):
    """Return value of EdieChunkProcessor.process.

    Tier 1 users who supply a custom ResultMerger alongside the default
    EdieChunkProcessor must accept a list[WorkerResult] in their merge()
    method.
    """

    worker_id: int
    total_messages: int
    worker_output_dir: str
    table_tree: dict
    log_table_path: str
    unknown_path: str


SAT_ID_TYPE = ne.SatelliteId

_FAST_TYPES = frozenset({int, float, str, bool, type(None)})

_ENUMERATION_META = type(type(ne.SatelliteId))
_PYCSTRUCT_META = type(type(ne.SatelliteId))

try:
    _ENUMERATION_META_NAME = _ENUMERATION_META.__name__
    _PYCSTRUCT_META_NAME = _PYCSTRUCT_META.__name__
except AttributeError:
    _ENUMERATION_META_NAME = "EnumerationType"
    _PYCSTRUCT_META_NAME = "PyCStructType"

_BINARY_SYNC_B0 = 0xAA
_BINARY_SYNC_B1 = 0x44
_BINARY_SYNC_B2 = 0x12
_ASCII_SYNC = frozenset({ord("#"), ord("%")})

_SENTINEL = object()


def _col_append(
        cols: dict[str, list],
        field: str,
        row_count: int,
        value: Any):
    """Initialize a column buffer if absent, then append value."""
    if field not in cols:
        cols[field] = [None] * row_count
    cols[field].append(value)


def _count_messages(input_file: str) -> int:
    """Count all messages in a GPS file for proper chunk sizing.

    Counts all message types (Message, UnknownMessage, and others) to match
    the indexing used in worker processing.

    Args:
        input_file: Path to the GPS input file.

    Returns:
        Total number of messages found in the file.
    """
    file_parser = ne_oem.FileParser(input_file)
    file_parser.convert(ne.ENCODE_FORMAT.FLATTENED_BINARY)

    count = 0
    for _ in file_parser:
        count += 1

    return count


def _find_message_boundary(
        filepath: str,
        approx_offset: int,
        search_window: int = 65536) -> int:
    """Return the byte offset of the next valid NovAtel message boundary.

    Searches at or after ``approx_offset`` using the novatel_edie Framer to
    properly validate message boundaries. Unknown/garbage bytes are counted
    as skipped until the first valid frame is found. Falls back to
    ``approx_offset`` if no valid message is found within ``search_window``.

    Args:
        filepath: Path to the GPS binary file.
        approx_offset: Starting byte offset for the search.
        search_window: Maximum number of bytes to scan forward.

    Returns:
        Byte offset of the next valid message start, or ``approx_offset``
        if none is found within the search window.
    """
    file_size = os.path.getsize(filepath)
    if approx_offset >= file_size:
        return file_size
    read_end = min(file_size, approx_offset + search_window)
    with open(filepath, "rb") as f:
        f.seek(approx_offset)
        chunk = f.read(read_end - approx_offset)
    framer = ne_oem.Framer()
    framer.report_unknown_bytes = True
    framer.write(chunk)
    skipped = 0
    for frame_data, metadata in framer:
        if metadata.format == ne.HEADER_FORMAT.UNKNOWN:
            skipped += len(frame_data)
        else:
            return approx_offset + skipped
    return approx_offset


class EdieFramerSplitter:
    """Default BoundarySplitter: snaps to NovAtel message boundaries.

    Wraps ``_find_message_boundary``. Picklable - no instance state.
    """

    def snap_boundary(
            self,
            file_path: Path | str,
            candidate_offset: int) -> int:
        """Return the nearest valid NovAtel message boundary.

        Args:
            file_path: Path to the GPS binary file.
            candidate_offset: Approximate byte position to start searching.

        Returns:
            Byte offset of the next valid message start, or EOF offset if
            no valid frame is found within the search window.
        """
        return _find_message_boundary(str(file_path), candidate_offset)


class EdieChunkProcessor:
    """Default ChunkProcessor: decodes a GPS byte-range slice using EDIE.

    Accumulates results as per-worker Parquet files. Wraps
    ``_worker_process``. All constructor args are picklable primitives.

    Attributes:
        - chunk_size: Row flush threshold per worker.
        - compression: Parquet compression codec.

    Public API:
        - process()
    """

    def __init__(
            self,
            chunk_size: int | None = None,
            compression: str = "zstd"):
        """Initialize EdieChunkProcessor with processing configuration.

        Args:
            chunk_size: Row flush threshold per worker. ``None`` = auto-tuned
                from file size on first call.
            compression: Parquet compression codec (default ``'zstd'``).
        """
        self._chunk_size = chunk_size
        self._compression = compression

    def process(
            self,
            file_path: Path | str,
            start_byte: int,
            end_byte: int,
            worker_id: int,
            temp_dir: Path | str,
            progress: WorkerProgressReporter | None = None) -> WorkerResult:
        """Parse ``[start_byte, end_byte)`` of ``file_path`` and write output.

        Args:
            file_path: Path to the source GPS file.
            start_byte: Inclusive start byte.
            end_byte: Exclusive end byte.
            worker_id: Worker index used for output file naming.
            temp_dir: Engine-managed directory for this worker's output.
            progress: Optional reporter for live per-worker byte progress.
                Supplied by ``ParallelFileEngine`` when a progress callback or
                progress bar is active; ``None`` disables reporting.

        Returns:
            A ``WorkerResult`` dict with table_tree, log_table_path, etc.
        """
        chunk_size = self._chunk_size
        if chunk_size is None:
            from nov_gnsspq.writer.parallel.engine import _auto_tune
            chunk_size = _auto_tune(str(file_path))["chunk_size"]

        args = {
            "worker_id": worker_id,
            "input_file": str(file_path),
            "start_byte": start_byte,
            "end_byte": end_byte,
            "worker_output_dir": str(temp_dir),
            "compression": self._compression,
            "chunk_size": chunk_size,
            "progress": progress,
        }
        return _worker_process(args)


def _flush_worker(flush_queue: Any, compression: str):
    """Dequeue (cols_snap, node) tuples and write row groups in background.

    Args:
        flush_queue: A queue that yields ``(cols_snap, node)`` tuples or the
            ``_SENTINEL`` value to signal shutdown.
        compression: Parquet compression codec name (e.g. ``"zstd"``).
    """
    while True:
        item = flush_queue.get()
        if item is _SENTINEL:
            flush_queue.task_done()
            break
        try:
            cols_snap, node = item
            _write_row_group(cols_snap, node, compression)
        finally:
            flush_queue.task_done()


def _w_add_entry(
        message: dict[str, Any],
        table: dict[str, Any],
        log_type: str,
        parent_id: int | None,
        parent_output_dir: str,
        output_folder: str):
    """Accumulate one decoded message dict into the table-node tree.

    Module-level function required for multiprocessing picklability.

    Args:
        message: Decoded message fields dict.
        table: Current-level dict mapping log_type names to TableNode objects.
        log_type: Name of the log type being inserted.
        parent_id: Sequence id of the parent row, or ``None`` for root nodes.
        parent_output_dir: Output directory of the parent node.
        output_folder: Root output folder for the worker.
    """
    node = table.get(log_type)
    if node is None:
        node_output_dir = os.path.join(parent_output_dir, log_type)
        rel = os.path.relpath(node_output_dir, output_folder)
        safe_path = rel.replace(os.sep, "__").replace("/", "__")
        node = TableNode(safe_path, node_output_dir, log_type)
        table[log_type] = node

    seq_id = _w_get_seq_id(node, parent_id)
    cols = node.cols
    row_count = node.row_count

    if SEQUENCE_ID_COL not in cols:
        cols[SEQUENCE_ID_COL] = [None] * row_count
    cols[SEQUENCE_ID_COL].append(seq_id)

    if parent_id is not None:
        if PARENT_ID_COL not in cols:
            cols[PARENT_ID_COL] = [None] * row_count
        cols[PARENT_ID_COL].append(parent_id)

    for field, value in message.items():
        if not isinstance(value, (dict, list)):
            _w_process_value(value, field, cols, row_count)
        elif isinstance(value, dict):
            _w_add_entry(
                value,
                node.subtables,
                field,
                seq_id,
                parent_output_dir=node.output_dir,
                output_folder=output_folder,
            )
        else:
            _w_dispatch_list_field(
                field, value, node, seq_id, output_folder
            )

    expected = row_count + 1
    for col_list in cols.values():
        if len(col_list) < expected:
            col_list.append(None)

    node.last_seq_id = seq_id
    node.last_parent_id = parent_id
    node.row_count += 1


def _w_dispatch_list_field(
        field: str,
        value: list,
        node: "TableNode",
        seq_id: int,
        output_folder: str):
    """Recurse a list-valued field into the node's subtables.

    Handles two cases: a list of dicts (one subtable row each) and a list
    of scalars (converted to a ``key_0``, ``key_1``, ... keyed dict).
    Module-level function required for multiprocessing picklability.

    Args:
        field: The field name (used as the subtable key).
        value: The list value to dispatch.
        node: The parent TableNode whose subtables receive the rows.
        seq_id: Sequence id of the parent row.
        output_folder: Root output folder for the worker.
    """
    if not value:
        return
    if all(isinstance(item, dict) for item in value):
        for item in value:
            _w_add_entry(
                item,
                node.subtables,
                field,
                seq_id,
                parent_output_dir=node.output_dir,
                output_folder=output_folder,
            )
    else:
        list_dict = {f"key_{i}": item for i, item in enumerate(value)}
        _w_add_entry(
            list_dict,
            node.subtables,
            field,
            seq_id,
            parent_output_dir=node.output_dir,
            output_folder=output_folder,
        )


def _w_build_table_tree(tables: dict[str, Any]) -> dict[str, Any]:
    """Build a serializable summary tree from the live table-node dict.

    Args:
        tables: Dict mapping log_type names to TableNode objects.

    Returns:
        Dict of ``{log_type: {row_count, parquet_path, subtables}}``.
    """
    tree: dict[str, Any] = {}
    for log_type, node in tables.items():
        parquet_path = os.path.join(
            node.output_dir, f"{node.log_type}.parquet"
        )
        if not os.path.exists(parquet_path):
            parquet_path = None
            row_count = 0
        else:
            try:
                row_count = pq.read_metadata(parquet_path).num_rows
            except (OSError, pa.lib.ArrowInvalid):
                row_count = 0
        tree[log_type] = {
            "row_count": row_count,
            "parquet_path": parquet_path,
            "subtables": _w_build_table_tree(node.subtables),
        }
    return tree


def _w_close_all_writers(tables: dict[str, Any]):
    """Close all open ParquetWriter handles in a table-node tree.

    Module-level function required for multiprocessing picklability.

    Args:
        tables: Dict mapping log_type names to TableNode objects.
    """
    for node in tables.values():
        if node.parquet_writer is not None:
            node.parquet_writer.close()
            node.parquet_writer = None
        _w_close_all_writers(node.subtables)


def _w_flush_all(tables: dict[str, Any], compression: str):
    """Flush all nodes with buffered rows in a table-node tree.

    Module-level function required for multiprocessing picklability.

    Args:
        tables: Dict mapping log_type names to TableNode objects.
        compression: Parquet compression codec name.
    """
    for node in tables.values():
        if node.row_count > 0:
            _w_flush_node(node, compression)
        _w_flush_all(node.subtables, compression)


def _w_flush_node(node: "TableNode", compression: str):
    """Snapshot and flush a single TableNode's buffered rows to Parquet.

    Module-level function required for multiprocessing picklability.

    Args:
        node: The TableNode whose column buffers should be flushed.
        compression: Parquet compression codec name.
    """
    cols_snap = {k: list(v) for k, v in node.cols.items()}
    for lst in node.cols.values():
        lst.clear()
    node.row_count = 0
    _write_row_group(cols_snap, node, compression)


def _w_get_seq_id(node: "TableNode", parent_id: int | None) -> int:
    """Return the next sequence id for a table node.

    Module-level function required for multiprocessing picklability.

    Args:
        node: The TableNode being inserted into.
        parent_id: Sequence id of the parent row, or ``None`` for root nodes.

    Returns:
        The next sequence id to assign.
    """
    if node.last_seq_id is None:
        return 0
    if not node.subtables and node.last_parent_id != parent_id:
        return 0
    return node.last_seq_id + 1


def _w_maybe_flush_subtree(
        node: "TableNode",
        chunk_size: int,
        compression: str):
    """Flush a node (and all its descendants) if the chunk threshold is met.

    Module-level function required for multiprocessing picklability.

    Args:
        node: Root of the subtree to check.
        chunk_size: Row count threshold that triggers a flush.
        compression: Parquet compression codec name.
    """
    if node.row_count >= chunk_size:
        _w_flush_node(node, compression)
    for subnode in node.subtables.values():
        _w_maybe_flush_subtree(subnode, chunk_size, compression)


def _w_process_value(
        value: Any,
        field: str,
        cols: dict[str, list],
        row_count: int):
    """Append a decoded field value into the appropriate column buffer.

    Handles Python primitives, NovAtel enumeration types, PyCStruct types,
    Python enums, and arbitrary objects with a ``.value`` attribute.
    Module-level function required for multiprocessing picklability.

    Args:
        value: The field value to store.
        field: Column name under which the value is stored.
        cols: Column-buffer dict for the current table node.
        row_count: Current row count of the node (used to back-fill nulls).
    """
    t = type(value)
    if t in _FAST_TYPES:
        _col_append(cols, field, row_count, value)
        return

    t_meta_name = type(t).__name__

    if t_meta_name == _ENUMERATION_META_NAME:
        if isinstance(value, SAT_ID_TYPE):
            for key, sub_value in value.to_dict().items():
                _w_process_value(
                    sub_value, f"{field}_{key}", cols, row_count
                )
            return
        if hasattr(value, "value") and isinstance(value.value, bytes):
            _col_append(cols, field, row_count, value.value)
            return
        _col_append(cols, field, row_count, str(value))
        raw_field = f"{field}_raw"
        try:
            _col_append(cols, raw_field, row_count, int(value))
        except (TypeError, ValueError):
            _col_append(cols, raw_field, row_count, None)
        return

    if isinstance(value, enum.Enum):
        _col_append(cols, field, row_count, str(value))
        raw_field = f"{field}_raw"
        _col_append(cols, raw_field, row_count, value.value)
        return

    if hasattr(value, "value"):
        _col_append(cols, field, row_count, str(value))
        return

    _col_append(cols, field, row_count, value)


def _worker_process(args: dict[str, Any]) -> dict[str, Any]:
    """Parse a byte-range slice of a GPS file and write per-type Parquet files.

    Top-level function required for multiprocessing picklability.

    Args:
        args: Dict with keys: ``worker_id``, ``input_file``,
            ``start_byte``, ``end_byte``, ``worker_output_dir``,
            ``compression``, ``chunk_size``.

    Returns:
        WorkerResult dict with keys: ``worker_id``, ``total_messages``,
        ``worker_output_dir``, ``table_tree``, ``log_table_path``,
        ``unknown_path``.
    """
    worker_id = args["worker_id"]
    input_file = args["input_file"]
    start_byte = args["start_byte"]
    end_byte = args["end_byte"]
    worker_output_dir = args["worker_output_dir"]
    compression = args["compression"]
    chunk_size = args["chunk_size"]
    reporter = args.get("progress") or WorkerProgressReporter()

    os.makedirs(worker_output_dir, exist_ok=True)

    slice_size = end_byte - start_byte
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=f"_w{worker_id}.GPS")
    try:
        with os.fdopen(tmp_fd, "wb") as tmp_f:
            with open(input_file, "rb") as src:
                src.seek(start_byte)
                remaining = slice_size
                buf_size = 1 << 20
                while remaining > 0:
                    chunk = src.read(min(buf_size, remaining))
                    if not chunk:
                        break
                    tmp_f.write(chunk)
                    remaining -= len(chunk)

        file_parser = ne_oem.FileParser(tmp_path)

        tables: dict[str, Any] = {}
        sequence_id = 0
        log_types: list[str] = []
        log_seqs: list[int] = []
        unknown_seqs: list[int] = []
        unknown_payloads: list[bytes | None] = []
        flush_ctr = 0
        consumed_bytes = 0

        for message in file_parser:
            seq_id = sequence_id
            consumed_bytes += _message_byte_len(message)

            if isinstance(message, ne_oem.Message):
                log_type = message.name
                try:
                    message_dict = message.to_dict()
                except RuntimeError:
                    try:
                        payload = bytes(message.payload)
                    except (TypeError, RuntimeError, AttributeError):
                        payload = None
                    unknown_seqs.append(seq_id)
                    unknown_payloads.append(payload)
                else:
                    header_dict = message_dict.pop("header", {})
                    message_dict.update(
                        {f"{HEADER_PREFIX}{k}": v
                         for k, v in header_dict.items()}
                    )
                    _w_add_entry(
                        message_dict,
                        tables,
                        log_type,
                        parent_id=None,
                        parent_output_dir=worker_output_dir,
                        output_folder=worker_output_dir,
                    )
            elif isinstance(message, ne_oem.UnknownMessage):
                log_type = "UnknownMessage"
                try:
                    payload = bytes(message.payload)
                except (TypeError, RuntimeError):
                    payload = None
                unknown_seqs.append(seq_id)
                unknown_payloads.append(payload)

            elif isinstance(message, ne_oem.Response):
                log_type = "Response"
                unknown_seqs.append(seq_id)
                unknown_payloads.append(None)

            else:
                log_type = type(message).__name__
                try:
                    payload = bytes(message.data)
                except (TypeError, RuntimeError):
                    payload = None
                unknown_seqs.append(seq_id)
                unknown_payloads.append(payload)

            log_types.append(log_type)
            log_seqs.append(seq_id)
            sequence_id += 1

            flush_ctr += 1
            if flush_ctr >= _FLUSH_CHECK_INTERVAL:
                flush_ctr = 0
                reporter.update(consumed_bytes)
                if log_type in tables:
                    _w_maybe_flush_subtree(
                        tables[log_type], chunk_size, compression
                    )

        reporter.update(consumed_bytes, final=True)

        _w_flush_all(tables, compression)
        _w_close_all_writers(tables)

        log_table_path = os.path.join(
            worker_output_dir, f"log_table_w{worker_id}.parquet"
        )
        pq.write_table(
            pa.table({
                "log": pa.array(log_types, type=pa.string()),
                SEQUENCE_ID_COL: pa.array(log_seqs, type=pa.int64()),
            }),
            log_table_path,
            compression=compression,
        )

        unknown_path = os.path.join(
            worker_output_dir, f"unknown_w{worker_id}.parquet"
        )
        if unknown_seqs:
            pq.write_table(
                pa.table({
                    SEQUENCE_ID_COL: pa.array(
                        unknown_seqs, type=pa.int64()
                    ),
                    "payload": pa.array(
                        unknown_payloads, type=pa.binary()
                    ),
                }),
                unknown_path,
                compression=compression,
            )
        else:
            pq.write_table(
                pa.schema([
                    (SEQUENCE_ID_COL, pa.int64()),
                    ("payload", pa.binary()),
                ]).empty_table(),
                unknown_path,
                compression=compression,
            )

        table_tree = _w_build_table_tree(tables)

        return {
            "worker_id": worker_id,
            "total_messages": sequence_id,
            "worker_output_dir": worker_output_dir,
            "table_tree": table_tree,
            "log_table_path": log_table_path,
            "unknown_path": unknown_path,
        }

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _write_row_group(
        cols_snap: dict[str, list],
        node: "TableNode",
        compression: str):
    """Write one row group to the node's ParquetWriter, creating it if needed.

    Args:
        cols_snap: Snapshot of column buffers to write.
        node: The TableNode that owns the ParquetWriter.
        compression: Parquet compression codec name.
    """
    if node.schema_cached is not None:
        try:
            arrays = []
            n_rows = (
                len(next(iter(cols_snap.values()))) if cols_snap else 0
            )
            for field in node.schema_cached:
                raw = cols_snap.get(field.name)
                if raw is None:
                    raw = [None] * n_rows
                arrays.append(pa.array(raw, type=field.type))
            table = pa.Table.from_arrays(
                arrays, schema=node.schema_cached
            )
        except (
            pa.ArrowInvalid,
            pa.ArrowTypeError,
            pa.ArrowNotImplementedError,
        ):
            table = pa.table(cols_snap)
            node.schema_cached = table.schema
    else:
        table = pa.table(cols_snap)

    if node.parquet_writer is None:
        os.makedirs(node.output_dir, exist_ok=True)
        path = os.path.join(
            node.output_dir, f"{node.log_type}.parquet"
        )
        node.parquet_writer = pq.ParquetWriter(
            path, table.schema, compression=compression
        )
        node.schema_cached = table.schema

    node.parquet_writer.write_table(table)


class TableNode:
    """Per-table-node state for columnar accumulation and incremental flushing.

    Uses ``__slots__`` for approximately 20% faster attribute access compared
    to nested dicts.

    Attributes:
        - cols: Column-buffer dict mapping field names to value lists.
        - subtables: Child TableNode objects keyed by sub-log-type name.
        - last_seq_id: Sequence id of the last row inserted, or ``None``.
        - last_parent_id: Parent id of the last row inserted.
        - safe_path: Filesystem-safe relative path string for this node.
        - output_dir: Absolute directory path for this node's Parquet file.
        - log_type: Name of the log type this node represents.
        - row_count: Number of rows currently buffered in ``cols``.
        - parquet_writer: Open ParquetWriter, or ``None`` if not yet created.
        - schema_cached: Cached PyArrow schema, or ``None`` before first write.
    """

    __slots__ = (
        "cols",
        "last_parent_id",
        "last_seq_id",
        "log_type",
        "output_dir",
        "parquet_writer",
        "row_count",
        "safe_path",
        "schema_cached",
        "subtables",
    )

    def __init__(self, safe_path: str, output_dir: str, log_type: str):
        """Initialize a TableNode with its path metadata.

        Args:
            safe_path: Filesystem-safe relative path string for this node.
            output_dir: Absolute directory path for this node's Parquet file.
            log_type: Name of the log type this node represents.
        """
        self.cols: dict[str, list] = {}
        self.last_parent_id: int | None = None
        self.last_seq_id: int | None = None
        self.log_type = log_type
        self.output_dir = output_dir
        self.parquet_writer: pq.ParquetWriter | None = None
        self.row_count: int = 0
        self.safe_path = safe_path
        self.schema_cached: pa.Schema | None = None
        self.subtables: dict[str, TableNode] = {}
