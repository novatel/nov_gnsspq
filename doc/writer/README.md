# nov_gnsspq Writer: Getting Started

Convert NovAtel GPS binary recordings into a queryable Parquet database in one
call.
After conversion, all analysis reads directly from Parquet, with no re-decoding
required.

---

## Installation

```bash
pip install nov_gnsspq
```

**Requirements:** Python 3.10+, `novatel_edie`, `pyarrow` (installed
automatically as dependencies).

---

## Quick Start

### Command Line

```bash
gnsspq convert recording.GPS output_db/
```

The converter auto-selects **Standard** mode for files under 50 MB and *
*Parallel** mode for larger files. Progress is shown in the terminal.

```bash
# Force parallel mode (useful for multi-core machines with any file size)
gnsspq convert recording.GPS output_db/ --parallel

# Force standard (single-threaded) mode
gnsspq convert recording.GPS output_db/ --no-parallel

# Overwrite an existing database
gnsspq convert recording.GPS output_db/ --overwrite

# Compress the output directory into output_db.zip for sharing (directory is preserved)
gnsspq convert recording.GPS output_db/ --zip
```

### Python API

```python
from nov_gnsspq import PqConverter

PqConverter("my_db").write_to_db("recording.GPS")
```

That's it. All tables are written and `_metadata.json` is finalized.

---

## Output Structure

The output directory contains one Parquet file per NovAtel message type, plus
sidecar files:

```
output_db/
├── output_db.parquet          # log_table: one row per message, in arrival order
├── _metadata.json             # SHA-256 digest, message count, schema version
├── unknown_data.parquet       # unrecognised message payloads
├── BESTPOS/
│   └── BESTPOS.parquet        # all BESTPOS messages, one row per fix
├── RANGE/
│   ├── RANGE.parquet          # RANGE header rows
│   └── obs/
│       └── obs.parquet        # per-satellite observations (child table)
├── GPSEPHEM/
│   └── GPSEPHEM.parquet
└── ...
```

**Nested sub-messages** (satellite observations, almanac entries, etc.) are
stored as child tables. They link back to their parent row via a `parent_id`
column that references the parent's `sequence_id`. Use a standard DataFrame join
to reconstruct the hierarchy.

---

## Python API Reference

### `PqConverter`

```python
from nov_gnsspq import PqConverter

with PqConverter(
        output_dir="output_db/",
        overwrite=False,  # True → allow replacing an existing database
        parallel=None,
        # None = auto, True = force parallel, False = force standard
) as db:
    db.consume("recording.GPS")
```

#### Constructor parameters

| Parameter    | Type           | Default  | Description                                                                                                                                              |
|--------------|----------------|----------|----------------------------------------------------------------------------------------------------------------------------------------------------------|
| `output_dir` | `str \| Path`  | required | Destination directory. Created if it does not exist.                                                                                                     |
| `overwrite`  | `bool`         | `False`  | Allow writing into a directory that already contains a database. Raises `DatabaseExistsError` if `False` and the directory already has `_metadata.json`. |
| `parallel`   | `bool \| None` | `None`   | `None` = auto-select based on file size (50 MB threshold). `True` = always use parallel. `False` = always use standard.                                  |

#### Methods

| Method                | Description                                                                                                  |
|-----------------------|--------------------------------------------------------------------------------------------------------------|
| `consume(source)`     | Convert a file path, `FileParser`, or any iterable of records. Selects file or streaming mode automatically. |
| `write(record)`       | Add a single `ne.Message` / `ne.UnknownMessage` in streaming mode.                                           |
| `write_to_db(source)` | File-mode-only convenience; identical to `consume` for paths and `FileParser` inputs.                        |

All methods raise `RuntimeError` if called outside a `with` block.

---

## Writer Modes

### Standard (single-threaded)

Used automatically for files **under 50 MB**, or when `parallel=False`.

- Single `ne.FileParser` pass on the main thread.
- Background daemon thread handles all disk I/O, so parsing and writing overlap.
- Low memory footprint; suitable for constrained environments.

### Parallel (multi-process)

Used automatically for files **50 MB and above**, or when `parallel=True`.

- File is split into N byte-range slices aligned to NovAtel message boundaries.
- One worker process per slice via `ProcessPoolExecutor`.
- Results are merged with globally consistent `sequence_id` / `parent_id`
  values.
- Worker count and row-group size are auto-tuned from file size and CPU count.
- Typical speedup: ~80% over standard on multi-core machines.

Worker count and chunk size are derived automatically:

```
workers    = clamp(cpu_count - 1,  min=2, max=8)
chunk_size = clamp(est_messages / (workers * 8),  min=20_000, max=200_000)
```

---

## Streaming Mode (real-time ingestion)

When `consume()` receives anything other than a file path (a
live `ne.FileParser`, a generator, or any iterable of records), it operates in *
*streaming mode**. Records accumulate in memory and are written incrementally;
the database is finalized when the `with` block exits.

```python
import novatel_edie as ne
from nov_gnsspq import PqConverter

parser = ne.Parser()

with PqConverter("live_db/") as db:
    while receiver.is_active():
        data = receiver.read()
        parser.write(data)
        db.consume(parser)  # drains whatever is available right now
```

Streaming mode uses the same output structure as file mode. The `_metadata.json`
sidecar omits `sha256`, `file_size`, and `source_filename` because there is no
single source file.

---

## Data Integrity

Every file-based conversion writes a SHA-256 digest of the source `.GPS` file
into `_metadata.json`:

```json
{
  "source_filename": "recording.GPS",
  "file_size": 157286400,
  "sha256": "3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b",
  "total_message_count": 450000,
  "schema_version": "1",
  "writer_version": "1.0.0"
}
```

To verify a database was generated from a specific file:

```python
import hashlib, json, pathlib

meta = json.loads(pathlib.Path("output_db/_metadata.json").read_text())
sha = hashlib.sha256(pathlib.Path("recording.GPS").read_bytes()).hexdigest()
assert sha == meta["sha256"], "Source file has changed or been substituted"
```

---

## Error Handling

| Exception                        | When                                                               |
|----------------------------------|--------------------------------------------------------------------|
| `nov_gnsspq.DatabaseExistsError` | Output directory already contains a database and `overwrite=False` |
| `nov_gnsspq.WriteError`          | OS-level filesystem error during write (wraps `OSError`)           |
| `RuntimeError`                   | `consume()` or `write()` called outside a `with` block             |

---

## Column Conventions

All header fields are prefixed with `header_` to avoid collisions with message
body fields (
e.g., `header_gps_week`, `header_milliseconds`, `header_receiver_status`).

Enumeration fields appear twice:

| Column        | Type     | Content                                        |
|---------------|----------|------------------------------------------------|
| `{field}`     | `string` | Human-readable name (`"WAAS"`, `"NARROW_INT"`) |
| `{field}_raw` | `int64`  | Raw integer value for efficient filtering      |

The `sequence_id` column in every table is the global arrival-order index.
The `parent_id` column in child tables is a foreign key into the parent
table's `sequence_id`.

---

## Further Reading

- [CLI reference](../cli/cli.md): all `nov_gnsspq` commands, flags, and exit
  codes
- [Reconstruction & verification](../reconstruct/reconstruction.md): verify a
  database is a lossless representation of the original recording
- [Plots reference](../plot/plots.md): available plot functions, required logs,
  and Python API
- [Conceptual design](writer-conceptual.md): what the writer does and why
- [High-level design](writer-high-level-design.md): component architecture and
  data flow
- [Detailed design](writer-detailed-design.md): class reference, algorithms,
  and configuration constants
