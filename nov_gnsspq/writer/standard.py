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

Single-threaded GPS-to-Parquet writer (GPSWriter).
"""

import hashlib
import json
import logging
import os
import queue
import threading

import novatel_edie.oem as ne_oem
import pyarrow as pa
import pyarrow.parquet as pq
from tqdm import tqdm

from nov_gnsspq.reader.schema import (HEADER_PREFIX, METADATA_FILENAME,
                                      SCHEMA_VERSION,
                                      SEQUENCE_ID_COL, WRITER_VERSION)
from nov_gnsspq.writer.parallel.edie import (_SENTINEL, TableNode,
                                             _flush_worker, _w_add_entry,
                                             _w_close_all_writers,
                                             _w_dispatch_list_field,
                                             _w_get_seq_id, _w_process_value)
from nov_gnsspq.writer.parallel.engine import _auto_tune
from nov_gnsspq.writer.progress import (BarObserver, ConversionPhase,
                                        ProgressTracker, _message_byte_len)

_log = logging.getLogger(__name__)

_FLUSH_CHECK_INTERVAL = 500


class GPSWriter:
    """Single-threaded GPS-to-Parquet writer.

    Parses a NovAtel GPS binary file and writes each message type
    into its own Parquet table under a structured output directory.

    Key design points:
        - One background flush thread handles all disk I/O while
          the main thread parses.
        - One pq.ParquetWriter per table node; no chunk files or
          consolidation step.
        - PyArrow pa.table() for table construction (2-5x faster
          than pandas).
        - Zstd level-3 compression by default (3-5x faster than
          Brotli).

    Attributes:
        - input_file: Absolute path to the .GPS input file.
        - output_folder: Root directory for the Parquet output tree.
        - compression: Parquet compression codec in use.
        - log_prefix: Logger prefix string used in debug output.

    Public API:
        - write_to_db()
    """

    def __init__(
            self,
            input_file: str,
            output_folder: str,
            _workers: int | None = None,
            chunk_size: int | None = None,
            compression: str = "zstd",
            tracker: ProgressTracker | None = None):
        """Initializes GPSWriter and starts the background flush thread.

        Args:
            input_file: Absolute path to the .GPS input file.
            output_folder: Directory that will receive the Parquet
                output tree.
            _workers: Unused; reserved for future parallelism.
            chunk_size: Row threshold per flush.  None means
                auto-tuned from file size.
            compression: Parquet compression codec (default
                ``'zstd'``).
            tracker: Pre-configured ProgressTracker that receives
                periodic ConversionProgress snapshots. Defaults to an
                inert tracker with no observers.
        """
        self.input_file = input_file
        self.output_folder = output_folder
        self.compression = compression
        self._tracker = tracker if tracker is not None else ProgressTracker()

        tune = _auto_tune(input_file)
        self._chunk_size = (
            chunk_size if chunk_size is not None
            else tune["chunk_size"]
        )
        self._est_messages = tune["est_messages"]
        self.log_prefix = "nov_gnsspq_convert-standard"

        _log.debug(
            "[%s] auto-tune: chunk_size=%s, est_messages=%s, "
            "compression=%s, with num workers: %s",
            self.log_prefix,
            f"{self._chunk_size:,}",
            f"{self._est_messages:,}",
            compression,
            tune["workers"],
        )

        # Main accumulation structures
        self._tables: dict[str, TableNode] = {}
        self._sequence_id: int = 0

        # log_table and unknown_table: accumulated in-memory,
        # written at end.
        self._log_table_cols: dict[str, list] = {
            "log": [],
            SEQUENCE_ID_COL: [],
        }
        self._unknown_cols: dict[str, list] = {
            SEQUENCE_ID_COL: [],
            "payload": [],
        }

        # Flush queue + background thread
        self._flush_queue: queue.Queue = queue.Queue(maxsize=32)
        self._flush_thread = threading.Thread(
            target=_flush_worker,
            args=(self._flush_queue, compression),
            daemon=True,
        )
        self._flush_thread.start()

        # Flush-check counter
        self._flush_ctr: int = 0

    # --- public ---

    def write_to_db(self):
        """Parses the GPS file and writes all tables to Parquet."""
        os.makedirs(self.output_folder, exist_ok=True)

        file_size = os.path.getsize(self.input_file)
        self._tracker.total_bytes = file_size
        self._tracker.force_emit(ConversionPhase.INITIALIZING, 0)
        sha256 = self._compute_sha256(self.input_file)

        file_parser = ne_oem.FileParser(self.input_file)

        bytes_done = 0

        with tqdm(
                total=file_size,
                desc="Decoding",
                unit="B",
                unit_scale=True,
                ncols=100) as pbar:
            bar = BarObserver(pbar)
            self._tracker.add_callback(bar)
            self._tracker.force_emit(ConversionPhase.DECODING, 0)
            for message in file_parser:
                seq_id = self._sequence_id
                bytes_done += _message_byte_len(message)

                if isinstance(message, ne_oem.Message):
                    log_type = message.name
                    try:
                        message_dict = message.to_dict()
                    except RuntimeError:
                        _log.warning(
                            "to_dict() failed for %s (seq %d), storing as unknown",
                            log_type, seq_id,
                        )
                        try:
                            payload = bytes(message.payload)
                        except (TypeError, RuntimeError, AttributeError):
                            payload = None
                        self._unknown_cols[SEQUENCE_ID_COL].append(seq_id)
                        self._unknown_cols["payload"].append(payload)
                    else:
                        header_dict = message_dict.pop("header", {})
                        prefixed_header = {
                            f"{HEADER_PREFIX}{k}": v
                            for k, v in header_dict.items()
                        }
                        message_dict.update(prefixed_header)

                        self._add_entry(
                            message_dict,
                            self._tables,
                            log_type,
                            parent_id=None,
                            _parent_output_dir=self.output_folder,
                        )

                elif isinstance(message, ne_oem.UnknownMessage):
                    log_type = "UnknownMessage"
                    try:
                        payload = bytes(message.payload)
                    except (TypeError, RuntimeError):
                        payload = None
                    self._unknown_cols[SEQUENCE_ID_COL].append(seq_id)
                    self._unknown_cols["payload"].append(payload)

                else:
                    log_type = type(message).__name__
                    try:
                        payload = bytes(message.data)
                    except (TypeError, RuntimeError, AttributeError):
                        payload = None
                    self._unknown_cols[SEQUENCE_ID_COL].append(seq_id)
                    self._unknown_cols["payload"].append(payload)

                self._log_table_cols["log"].append(log_type)
                self._log_table_cols[SEQUENCE_ID_COL].append(seq_id)
                self._sequence_id += 1

                self._flush_ctr += 1
                if self._flush_ctr >= _FLUSH_CHECK_INTERVAL:
                    self._flush_ctr = 0
                    if log_type in self._tables:
                        self._maybe_flush_subtree(
                            self._tables[log_type]
                        )

                self._tracker.emit(ConversionPhase.DECODING, bytes_done)

            self._tracker.force_emit(ConversionPhase.DECODING, file_size)
            bar.close()
            self._tracker.remove_callback(bar)

        self._flush_all_remaining()

        self._flush_queue.join()
        self._flush_queue.put(_SENTINEL)
        self._flush_queue.join()
        self._flush_thread.join()

        self._close_all_writers(self._tables)
        self._write_log_table()
        self._write_unknown_table()

        self._write_metadata(
            file_size=file_size,
            sha256=sha256,
            total_messages=self._sequence_id,
        )

        self._tracker.force_emit(ConversionPhase.DONE, file_size)

    # --- private ---

    # Columnar accumulation

    def _add_entry(
            self,
            message: dict,
            table: dict[str, TableNode],
            log_type: str,
            parent_id: int | None = None,
            _parent_output_dir: str = ""):
        """Delegates to _w_add_entry."""
        _w_add_entry(
            message, table, log_type, parent_id,
            _parent_output_dir, self.output_folder
        )

    def _dispatch_list_field(
            self,
            field: str,
            value: list,
            node: TableNode,
            seq_id: int):
        """Delegates to _w_dispatch_list_field."""
        _w_dispatch_list_field(field, value, node, seq_id, self.output_folder)

    # Writer lifecycle

    def _close_all_writers(self, tables: dict[str, TableNode]):
        """Delegates to _w_close_all_writers."""
        _w_close_all_writers(tables)

    # Flush helpers

    def _enqueue_flush(self, node: TableNode):
        """Snapshots a node's columns and enqueues them for writing.

        Clears the node's in-memory columns and resets its row count
        after snapshotting so the main thread can continue
        accumulating immediately.

        Args:
            node: The TableNode whose columns should be flushed.
        """
        cols_snap = {k: list(v) for k, v in node.cols.items()}
        for lst in node.cols.values():
            lst.clear()
        node.row_count = 0
        self._flush_queue.put((cols_snap, node))

    def _flush_all_remaining(self):
        """Enqueues every node with pending rows for writing."""
        self._flush_subtree_unconditional(self._tables)

    def _flush_subtree_unconditional(
            self, tables: dict[str, TableNode]):
        """Recursively enqueues all non-empty nodes in the tree.

        Args:
            tables: Mapping of log-type name to TableNode at the
                current level of the tree.
        """
        for node in tables.values():
            if node.row_count > 0:
                self._enqueue_flush(node)
            self._flush_subtree_unconditional(node.subtables)

    def _get_seq_id(self, node: TableNode, parent_id: int | None) -> int:
        """Delegates to _w_get_seq_id."""
        return _w_get_seq_id(node, parent_id)

    def _maybe_flush_subtree(self, node: TableNode):
        """Flushes a node and its descendants if over the chunk limit.

        Args:
            node: The root TableNode of the subtree to inspect.
        """
        if node.row_count >= self._chunk_size:
            self._enqueue_flush(node)
        for subnode in node.subtables.values():
            self._maybe_flush_subtree(subnode)

    def _process_value(
            self,
            value,
            field: str,
            cols: dict[str, list],
            row_count: int):
        """Delegates to _w_process_value."""
        _w_process_value(value, field, cols, row_count)

    # Final table writes

    def _write_log_table(self):
        """Writes the log-type index table to Parquet."""
        top_dir = self.output_folder
        os.makedirs(top_dir, exist_ok=True)
        table = pa.table(self._log_table_cols)
        pq.write_table(
            table,
            os.path.join(
                top_dir,
                f"{os.path.basename(self.output_folder)}.parquet",
            ),
            compression=self.compression,
        )

    # Metadata

    def _write_metadata(
            self,
            file_size: int,
            sha256: str,
            total_messages: int):
        """Serialises conversion metadata to a JSON sidecar file.

        Args:
            file_size: Byte length of the source GPS file.
            sha256: Hex-encoded SHA-256 digest of the source file.
            total_messages: Total number of messages parsed.
        """
        meta = {
            "source_filename": os.path.basename(self.input_file),
            "file_size": file_size,
            "sha256": sha256,
            "total_message_count": total_messages,
            "schema_version": SCHEMA_VERSION,
            "writer_version": WRITER_VERSION,
        }
        path = os.path.join(self.output_folder, METADATA_FILENAME)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    def _write_unknown_table(self):
        """Writes unrecognised message payloads to unknown_data.parquet."""
        top_dir = self.output_folder
        os.makedirs(top_dir, exist_ok=True)
        if not self._unknown_cols[SEQUENCE_ID_COL]:
            schema = pa.schema([
                (SEQUENCE_ID_COL, pa.int64()),
                ("payload", pa.binary()),
            ])
            table = schema.empty_table()
        else:
            table = pa.table({
                SEQUENCE_ID_COL: pa.array(
                    self._unknown_cols[SEQUENCE_ID_COL],
                    type=pa.int64(),
                ),
                "payload": pa.array(
                    self._unknown_cols["payload"],
                    type=pa.binary(),
                ),
            })
        pq.write_table(
            table,
            os.path.join(top_dir, "unknown_data.parquet"),
            compression=self.compression,
        )

    @staticmethod
    def _compute_sha256(path: str) -> str:
        """Computes the SHA-256 hex digest of a file.

        Args:
            path: Absolute or relative path to the file.

        Returns:
            hexdigest: Lowercase hex string of the SHA-256 digest.
        """
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
