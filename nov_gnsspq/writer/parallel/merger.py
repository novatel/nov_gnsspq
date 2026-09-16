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

Parquet merge components: per-worker output assembly with sequence_id /
parent_id offset correction.
"""

import logging
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from nov_gnsspq.reader.schema import PARENT_ID_COL, SEQUENCE_ID_COL

_log = logging.getLogger(__name__)


def _apply_offsets(
        table: pa.Table,
        seq_offset: int,
        parent_offset: int,
        is_leaf: bool) -> pa.Table:
    """Apply sequence_id / parent_id offsets to a single worker's table.

    Args:
        table: PyArrow table from a single worker output.
        seq_offset: Integer offset to add to the sequence_id column.
        parent_offset: Integer offset to add to the parent_id column.
        is_leaf: Whether this table is a leaf node in the table tree.

    Returns:
        The table with adjusted sequence and parent id columns.
    """
    is_root = PARENT_ID_COL not in table.schema.names

    if (not is_leaf or is_root) and seq_offset != 0:
        if SEQUENCE_ID_COL in table.schema.names:
            idx = table.schema.get_field_index(SEQUENCE_ID_COL)
            table = table.set_column(
                idx,
                SEQUENCE_ID_COL,
                # pylint: disable-next=no-member  # C extension
                pc.add(table[SEQUENCE_ID_COL], seq_offset),
            )

    if not is_root and parent_offset != 0:
        if PARENT_ID_COL in table.schema.names:
            idx = table.schema.get_field_index(PARENT_ID_COL)
            table = table.set_column(
                idx,
                PARENT_ID_COL,
                # pylint: disable-next=no-member  # C extension
                pc.add(table[PARENT_ID_COL], parent_offset),
            )

    return table


def _merge_log_table(
        results: list[dict],
        output_folder: str,
        compression: str) -> int:
    """Concatenate per-worker log tables with global seq_id offsets.

    Args:
        results: List of WorkerResult dicts, each containing
            ``log_table_path`` and ``total_messages``.
        output_folder: Directory where the merged log table is written.
        compression: Parquet compression codec name.

    Returns:
        Total number of messages across all workers.
    """
    tables = []
    global_offset = 0
    for r in results:
        tbl = pq.read_table(r["log_table_path"])
        if global_offset != 0 and len(tbl) > 0:
            idx = tbl.schema.get_field_index(SEQUENCE_ID_COL)
            tbl = tbl.set_column(
                idx,
                SEQUENCE_ID_COL,
                # pylint: disable-next=no-member  # C extension
                pc.add(tbl[SEQUENCE_ID_COL], global_offset),
            )
        tables.append(tbl)
        global_offset += r["total_messages"]

    merged = (
        pa.concat_tables(tables)
        if tables
        else pa.table({
            "log": pa.array([], type=pa.string()),
            SEQUENCE_ID_COL: pa.array([], type=pa.int64()),
        })
    )
    db_name = os.path.basename(output_folder)
    pq.write_table(
        merged,
        os.path.join(output_folder, f"{db_name}.parquet"),
        compression=compression,
    )
    return global_offset


def _merge_tree(
        trees_per_worker: list[dict],
        output_folder: str,
        compression: str,
        parent_seq_offsets: list[int],
        path_parts: list[str]):
    """Recursively merge per-worker Parquet files for each log_type.

    Args:
        trees_per_worker: List of table-tree dicts, one per worker.
        output_folder: Root output directory for merged files.
        compression: Parquet compression codec name.
        parent_seq_offsets: Per-worker parent sequence id offsets at this
            level of the tree.
        path_parts: Path components accumulated from parent recursive calls.
    """
    all_log_types: set[str] = set()
    for tree in trees_per_worker:
        all_log_types.update(tree.keys())

    for log_type in all_log_types:
        worker_paths = []
        worker_row_counts = []
        for tree in trees_per_worker:
            info = tree.get(log_type)
            if info and info.get("parquet_path"):
                worker_paths.append(info["parquet_path"])
                worker_row_counts.append(info["row_count"])
            else:
                worker_paths.append(None)
                worker_row_counts.append(0)

        seq_offsets = [0] * len(worker_paths)
        for k in range(1, len(worker_paths)):
            seq_offsets[k] = seq_offsets[k - 1] + worker_row_counts[k - 1]

        is_leaf = not any(
            bool(trees_per_worker[k].get(log_type, {}).get("subtables"))
            for k in range(len(trees_per_worker))
        )

        out_dir = os.path.join(output_folder, *path_parts, log_type)
        os.makedirs(out_dir, exist_ok=True)
        final_path = os.path.join(out_dir, f"{log_type}.parquet")

        tables_to_concat = []
        for path, seq_off, par_off in zip(
            worker_paths, seq_offsets, parent_seq_offsets
        ):
            if path is None or not os.path.exists(path):
                continue
            tbl = pq.read_table(path)
            tbl = _apply_offsets(tbl, seq_off, par_off, is_leaf)
            tables_to_concat.append(tbl)

        if tables_to_concat:
            merged = pa.concat_tables(
                tables_to_concat, promote_options="default"
            )
            pq.write_table(merged, final_path, compression=compression)

        subtrees = [
            trees_per_worker[k].get(log_type, {}).get("subtables", {})
            for k in range(len(trees_per_worker))
        ]
        _merge_tree(
            subtrees,
            output_folder,
            compression,
            parent_seq_offsets=seq_offsets,
            path_parts=path_parts + [log_type],
        )


def _merge_unknown_table(
        results: list[dict],
        output_folder: str,
        compression: str):
    """Concatenate per-worker unknown tables with global seq_id offsets.

    Args:
        results: List of WorkerResult dicts, each containing ``unknown_path``
            and ``total_messages``.
        output_folder: Directory where the merged unknown table is written.
        compression: Parquet compression codec name.
    """
    tables = []
    global_offset = 0
    for r in results:
        tbl = pq.read_table(r["unknown_path"])
        if global_offset != 0 and len(tbl) > 0:
            idx = tbl.schema.get_field_index(SEQUENCE_ID_COL)
            tbl = tbl.set_column(
                idx,
                SEQUENCE_ID_COL,
                # pylint: disable-next=no-member  # C extension
                pc.add(tbl[SEQUENCE_ID_COL], global_offset),
            )
        tables.append(tbl)
        global_offset += r["total_messages"]

    merged = (
        pa.concat_tables(tables)
        if tables
        else pa.schema([
            (SEQUENCE_ID_COL, pa.int64()),
            ("payload", pa.binary()),
        ]).empty_table()
    )
    pq.write_table(
        merged,
        os.path.join(output_folder, "unknown_data.parquet"),
        compression=compression,
    )


class ParquetMerger:
    """Merges per-worker Parquet outputs into a final database.

    Wraps the existing ``_merge_tree``, ``_merge_log_table``, and
    ``_merge_unknown_table`` functions.

    Public API:
        - merge()
    """

    def __init__(self, compression: str = "zstd"):
        """Initializes ParquetMerger with a Parquet compression codec.

        Args:
            compression: Parquet compression codec for the merged output.
        """
        self._compression = compression

    def merge(self, worker_results: list, output_dir: Path | str):
        """Merge per-worker Parquet files into the final database directory.

        Args:
            worker_results: List of ``WorkerResult`` dicts, sorted by
                ``worker_id``.
            output_dir: Destination for the final merged Parquet tree.
        """
        output_dir = str(output_dir)
        compression = self._compression
        actual_workers = len(worker_results)

        trees = [r["table_tree"] for r in worker_results]
        _merge_tree(
            trees,
            output_dir,
            compression,
            parent_seq_offsets=[0] * actual_workers,
            path_parts=[],
        )
        _merge_log_table(worker_results, output_dir, compression)
        _merge_unknown_table(worker_results, output_dir, compression)
