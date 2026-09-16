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

Examples of custom ParallelFileEngine components at Tier 1, 2, and 3.

Each tier is self-contained and runnable — set INPUT_FILE to a .GPS file on
disk, then run the tier function directly.

  Tier 1: keep EDIE decoding, write merged output as CSV instead of Parquet.
  Tier 2: keep EDIE boundary detection, write per-chunk JSON, merge to one file.
  Tier 3: fully custom splitter/processor/merger for a hypothetical line-based
           text format (e.g. NMEA-style one-record-per-line).
"""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from nov_gnsspq.writer.parallel.engine import ParallelFileEngine
from nov_gnsspq.writer.parallel.protocols import (
    BoundarySplitter,
    ChunkProcessor,
    ResultMerger,
)

# ---------------------------------------------------------------------------
# Change this to a real GPS file to run the examples.
# ---------------------------------------------------------------------------
INPUT_FILE = "recording.GPS"
OUTPUT_DIR = "custom_output"


# ===========================================================================
# Tier 1 — Custom storage, keep EDIE decoding
#
# Replace only ResultMerger.  The engine still uses EdieFramerSplitter and
# EdieChunkProcessor, so worker_results are list[WorkerResult] — use
# WorkerResult from nov_gnsspq.writer to get the typed schema.
# ===========================================================================

class CsvMerger:
    """Merge EDIE-decoded per-worker Parquet files into per-type CSV files.

    One CSV is written per NovAtel message type.  Column order matches the
    first worker that produced that type; subsequent workers must have the
    same schema (guaranteed by EDIE's deterministic field ordering).

    Constructor args are picklable primitives.
    """

    def __init__(self, output_subdir: str = "csv"):
        self._output_subdir = output_subdir

    def merge(self, worker_results: list, output_dir: Path) -> None:
        from nov_gnsspq.writer.parallel.edie import WorkerResult  # local to avoid circular

        csv_dir = output_dir / self._output_subdir
        csv_dir.mkdir(parents=True, exist_ok=True)

        # Collect all log types across workers.
        all_types: set[str] = set()
        for result in worker_results:
            all_types.update(result["table_tree"].keys())

        for log_type in sorted(all_types):
            out_path = csv_dir / f"{log_type}.csv"
            writer = None
            for result in worker_results:
                info = result["table_tree"].get(log_type, {})
                parquet_path = info.get("parquet_path")
                if not parquet_path or not os.path.exists(parquet_path):
                    continue
                table = pq.read_table(parquet_path)
                rows = table.to_pydict()
                columns = list(rows.keys())
                n_rows = len(next(iter(rows.values()))) if rows else 0
                if writer is None:
                    f = open(out_path, "w", newline="", encoding="utf-8")
                    writer = csv.DictWriter(f, fieldnames=columns)
                    writer.writeheader()
                for i in range(n_rows):
                    writer.writerow({col: rows[col][i] for col in columns})
            if writer is not None:
                f.close()


def run_tier1(input_file: str, output_dir: str) -> None:
    """Tier 1: default EDIE decoding, CSV output instead of Parquet."""
    engine = ParallelFileEngine(merger=CsvMerger())
    engine.run(input_file, output_dir)
    print(f"Tier 1 complete — CSV files written to {output_dir}/csv/")


# ===========================================================================
# Tier 2 — Custom decoder and storage, keep EDIE boundary detection
#
# Replace both ChunkProcessor and ResultMerger.  The engine still uses
# EdieFramerSplitter to align byte boundaries to valid NovAtel frames.
# Each worker decodes its slice with EDIE and writes a JSON file;
# the merger concatenates all records into one JSON output file.
# ===========================================================================

class JsonChunkProcessor:
    """Decode a GPS byte-range slice and write matching records as JSON.

    Args:
        message_types: Whitelist of NovAtel log-type names to include.
            All other types are discarded.  Pass an empty list to keep all.
    """

    def __init__(self, message_types: list[str]):
        self._message_types = list(message_types)  # must be picklable

    def process(
            self,
            file_path: Path,
            start_byte: int,
            end_byte: int,
            worker_id: int,
            temp_dir: Path,
            progress=None) -> Path:
        import tempfile
        import novatel_edie as ne

        slice_size = end_byte - start_byte
        temp_dir.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=f"_w{worker_id}.GPS")
        try:
            with os.fdopen(tmp_fd, "wb") as tmp_f, open(file_path, "rb") as src:
                src.seek(start_byte)
                remaining = slice_size
                while remaining > 0:
                    chunk = src.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    tmp_f.write(chunk)
                    remaining -= len(chunk)

            records = []
            for msg in ne.FileParser(tmp_path):
                if not isinstance(msg, ne.Message):
                    continue
                if self._message_types and msg.name not in self._message_types:
                    continue
                d = msg.to_dict()
                d["_log_type"] = msg.name
                d["_worker_id"] = worker_id
                records.append(d)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        out = temp_dir / f"w{worker_id}.json"
        out.write_text(json.dumps(records, default=str), encoding="utf-8")
        return out


class JsonMerger:
    """Concatenate per-worker JSON files into a single output file."""

    def merge(self, worker_results: list[Path], output_dir: Path) -> None:
        all_records: list[dict] = []
        for path in worker_results:
            if path.exists():
                all_records.extend(json.loads(path.read_text(encoding="utf-8")))

        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / "records.json"
        out.write_text(
            json.dumps(all_records, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"  Merged {len(all_records)} records → {out}")


def run_tier2(input_file: str, output_dir: str) -> None:
    """Tier 2: EDIE boundaries, JSON decode and output."""
    engine = ParallelFileEngine(
        processor=JsonChunkProcessor(message_types=["BESTPOS", "BESTVEL", "RANGE"]),
        merger=JsonMerger(),
    )
    engine.run(input_file, output_dir)
    print(f"Tier 2 complete — JSON written to {output_dir}/records.json")


# ===========================================================================
# Tier 3 — Fully custom (different binary / text format)
#
# All three components are replaced.  This example targets a hypothetical
# newline-delimited text format where each record is one line.  The splitter
# aligns boundaries to the start of the next line; the processor decodes
# its line range and writes CSV; the merger concatenates all CSVs.
# ===========================================================================

NEWLINE = ord("\n")


class LineSplitter:
    """Snap a byte offset to the start of the next line.

    Suitable for any newline-delimited text format (CSV, NMEA, custom logs).
    """

    def snap_boundary(self, file_path: Path, candidate_offset: int) -> int:
        file_size = os.path.getsize(file_path)
        if candidate_offset >= file_size:
            return file_size
        with open(file_path, "rb") as f:
            f.seek(candidate_offset)
            # Scan up to 4 KB for the next newline.
            window = f.read(4096)
        pos = window.find(NEWLINE)
        if pos == -1:
            return file_size
        return candidate_offset + pos + 1


class CsvChunkProcessor:
    """Parse one line-range of a comma-separated text file.

    Expected format: first line of the file is a header row; all subsequent
    lines are data rows.  The processor writes its matching rows to a CSV
    under temp_dir.

    Args:
        delimiter: Field delimiter character (default ``','``).
    """

    def __init__(self, delimiter: str = ","):
        self._delimiter = delimiter

    def process(
            self,
            file_path: Path,
            start_byte: int,
            end_byte: int,
            worker_id: int,
            temp_dir: Path,
            progress=None) -> Path:
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Read the header from the start of the file.
        with open(file_path, "r", encoding="utf-8") as f:
            header_line = f.readline().rstrip("\n")
        columns = header_line.split(self._delimiter)

        # Read only our assigned byte range.
        with open(file_path, "rb") as f:
            f.seek(start_byte)
            raw = f.read(end_byte - start_byte)
        lines = raw.decode("utf-8", errors="replace").splitlines()

        out = temp_dir / f"w{worker_id}.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=self._delimiter)
            writer.writerow(columns)
            for line in lines:
                if not line.strip():
                    continue
                row = line.split(self._delimiter)
                writer.writerow(row)
        return out


class CsvMergerT3:
    """Concatenate per-worker CSV files, deduplicating the header row."""

    def __init__(self, output_filename: str = "merged.csv"):
        self._output_filename = output_filename

    def merge(self, worker_results: list[Path], output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / self._output_filename
        header_written = False
        with open(out, "w", newline="", encoding="utf-8") as outf:
            for path in worker_results:
                if not path.exists():
                    continue
                with open(path, "r", newline="", encoding="utf-8") as inf:
                    reader = csv.reader(inf)
                    for i, row in enumerate(reader):
                        if i == 0:
                            if not header_written:
                                outf.write(",".join(row) + "\n")
                                header_written = True
                        else:
                            outf.write(",".join(row) + "\n")
        print(f"  Merged CSV written to {out}")


def run_tier3(input_file: str, output_dir: str) -> None:
    """Tier 3: fully custom components for a line-delimited text format."""
    engine = ParallelFileEngine(
        splitter=LineSplitter(),
        processor=CsvChunkProcessor(delimiter=","),
        merger=CsvMergerT3(output_filename="merged.csv"),
        num_workers=4,
    )
    engine.run(input_file, output_dir)
    print(f"Tier 3 complete — merged CSV written to {output_dir}/merged.csv")


# ---------------------------------------------------------------------------
# Pickling self-test — run before submitting to workers
# ---------------------------------------------------------------------------

def verify_picklable() -> None:
    """Confirm all custom components can be pickled (required for ProcessPoolExecutor)."""
    import pickle

    components = [
        ("CsvMerger", CsvMerger()),
        ("JsonChunkProcessor", JsonChunkProcessor(["BESTPOS"])),
        ("JsonMerger", JsonMerger()),
        ("LineSplitter", LineSplitter()),
        ("CsvChunkProcessor", CsvChunkProcessor()),
        ("CsvMergerT3", CsvMergerT3()),
    ]
    for name, obj in components:
        try:
            pickle.dumps(obj)
            print(f"  {name}: OK")
        except Exception as e:
            print(f"  {name}: FAILED — {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    # Usage: python parallel_engine_custom.py [pickle|1|2|3] [recording.GPS]
    tier = sys.argv[1] if len(sys.argv) > 1 else "pickle"
    if len(sys.argv) > 2:
        INPUT_FILE = sys.argv[2]

    if tier == "pickle":
        print("Pickling self-test:")
        verify_picklable()
    elif tier == "1":
        run_tier1(INPUT_FILE, OUTPUT_DIR + "_t1")
    elif tier == "2":
        run_tier2(INPUT_FILE, OUTPUT_DIR + "_t2")
    elif tier == "3":
        run_tier3(INPUT_FILE, OUTPUT_DIR + "_t3")
    else:
        print("Usage: python parallel_engine_custom.py "
              "[pickle|1|2|3] [recording.GPS]")
