![nov_gnsspq](doc/gnsspq-logo.png)

**Convert NovAtel GPS log files to Parquet databases for fast analytical
querying.**

## Overview

`nov_gnsspq` converts NovAtel `.GPS` recordings into structured Apache Parquet (
columnar) databases. The source format, NovAtel's log protocol, is parsed
using `novatel_edie`, NovAtel's binary decoding library.
The decoded messages are stored as Parquet files via PyArrow and pandas, which
makes downstream queries orders of magnitude faster than re-parsing the binary
on every access.

The database layout mirrors the log-type hierarchy of the recording. Each log
type (e.g., `BESTPOS`, `RANGE`) gets its own subdirectory and Parquet file.
Nested message fields, such as the channel-observation block inside a `RANGE`
message, are stored as separate subtable Parquet files linked by
a `sequence_id` / `parent_id` relationship.

For files above 50 MB, `PqConverter` automatically selects a parallel
multi-process writer that splits the file into chunks, processes them
concurrently, and merges the resulting Parquet fragments. Files below that
threshold use the standard single-threaded writer. You can request a
writer explicitly when performance or resource constraints require it; note
that the parallel writer still delegates to the standard one below 50 MB,
where the cost of splitting and merging outweighs the benefit.

## Quick Start

**1. Install**

```bash
# Core package
poetry add nov_gnsspq

# With plotting extras (matplotlib + plotly)
poetry add "nov_gnsspq[plot]"
```

Both are also installable with `pip install nov_gnsspq` and `pip install "nov_gnsspq[plot]"`.

**2. Convert a GPS file to a database**

```python
from nov_gnsspq import PqConverter

PqConverter("mydb/").write_to_db("recording.GPS")
```

`PqConverter` handles the conversion. The simplest usage is to instantiate it
with the output directory and call `write_to_db()` with the path to the GPS
file.

The `write_to_db()` call reads the entire file, selects the appropriate 
writer, and writes the Parquet database to `mydb/`. The
directory is created if it does not exist.

### Output Structure

A converted database directory looks like this:

```
mydb/
├── mydb.parquet            # root index: one row per message (log type + sequence_id)
├── _metadata.json          # schema version, writer version, total message count
├── unknown_data.parquet    # unrecognised / unparseable messages
├── BESTPOS/
│   └── BESTPOS.parquet
├── RANGE/
│   ├── RANGE.parquet
│   └── obs/
│       └── obs.parquet     # nested channel observations (one row per satellite per epoch)
├── RAWIMUS/
│   └── RAWIMUS.parquet
└── ...
```

Each log-type Parquet file contains the decoded header fields (
prefixed `header_`), all message body fields, and a `sequence_id` column linking
back to the root index. Nested subtable Parquet files additionally contain
a `parent_id` column referencing the `sequence_id` of their parent row.


**3. Read the database**

```python
from nov_gnsspq import PqReader

db = PqReader("mydb/")
bestpos = db.subtables.BESTPOS
```

`PqReader` loads the index table and exposes each log type as an attribute
of `db.subtables`. Accessing `bestpos` gives you a `LogTable` with the full
BESTPOS data and any nested subtables.

**4. Filter and query**

```python
from nov_gnsspq.compat.gpstime import GPSTime

start = GPSTime(seconds=345600.0, week=2310)
bestpos.filter_start_time(start)
print(bestpos.get_mean("lat"))
```

Filters accumulate in-place on the active view (`cur_table`).
Call `bestpos.reset_filters()` to restore the full dataset.

## CLI Usage

The **`gnsspq`** command exposes four subcommands:

```
gnsspq convert          convert a GPS log file to a Parquet database
gnsspq plot             generate plots from a nov_gnsspq Parquet database
gnsspq reconstruct      verify that a nov_gnsspq database is lossless
gnsspq validate-source  compare two GPS files or databases by fingerprint
```

### convert

```bash
# Basic conversion — output directory is created automatically
gnsspq convert recording.GPS -o ./mydb

# Force parallel writer regardless of file size
gnsspq convert recording.GPS -o ./mydb --parallel

# Compress the output directory into mydb.zip after conversion
gnsspq convert recording.GPS -o ./mydb --zip
```

By default the writer is selected automatically: files >= 50 MB use the parallel
writer; smaller files use the standard writer. A startup banner reports the
selected writer, worker count, file size, and library versions.

### plot

```bash
# Generates all available plots, showing them interactively
gnsspq plot mydb/  


# Interactive Plotly figures; writes a single dashboard.html with --out
gnsspq plot mydb/ --html

# Overlay the position track on an OpenStreetMap basemap (needs contextily)
gnsspq plot mydb/ --osm
```

### reconstruct

```bash
# Reconstruct and compare — runs both field and binary checks by default
gnsspq reconstruct mydb/ recording.GPS
```
---
## Advanced Usage

### Reading the Database

**`PqReader`** is the primary read interface. It loads the database from the
directory written by `PqConverter` and exposes a navigable hierarchy.

#### Filtering by time

Time values may be `GPSTime` instances or `datetime.datetime` objects.

```python
bestpos.filter_start_time(start_time)  # keep entries at or after start_time
bestpos.filter_end_time(end_time)  # keep entries at or before end_time
bestpos.filter_time_range(start, end)  # combined range filter
```

#### Filtering by field value

```python
# Keep only entries where pos_type equals 50
bestpos.filter_entries("pos_type", "==", 50)

# Filter on a subtable field
range_table.filter_entries("cn0", ">=", 35, subtable="obs")
```

Supported comparators: `==`, `!=`, `<`, `<=`, `>`, `>=`.

#### Statistics

```python
# Method-based
mean_lat = bestpos.get_mean("lat")
max_hdop = bestpos.get_max("hdop")
std_lat = bestpos.get_std("lat")

# Property shorthand via FieldValue — equivalent to the method calls above
mean_lat = bestpos.lat.mean
max_hdop = bestpos.hdop.max
std_lat = bestpos.lat.std
```

`FieldValue` exposes `.mean`, `.median`, `.min`, `.max`, `.sum`, `.std`, and
grouped variants (`.grouped_mean`, etc.) as properties on each column of
a `LogTable` or `LogSubtable`.

#### Resetting filters

```python
bestpos.reset_filters()  # restores the full dataset on this table and its subtables
db.reset_filters()  # resets all tables in the database
```

#### Iterating over entries

```python
for log_name, entry in db:
    print(log_name, entry.header_week, entry.lat)
```

Each iteration step yields the log type name and a dynamically constructed
dataclass instance populated with the row's fields.

### Streaming / real-time mode

Instead of calling `db.consume(path)` for a complete file, you can feed
individual records from a live parser. This is useful when processing a data
stream before a file is fully available.

```python
import novatel_edie as ne
from nov_gnsspq import PqConverter

parser = ne.Parser()
with PqConverter("mydb/") as db:
    while collecting:
        parser.write(stream.read())
        db.consume(parser)
```

In streaming mode `db.consume()` drains whatever messages are currently
available in `parser`. Buffers are flushed periodically (every 50,000 messages
per log type) to bound memory usage. The final flush and metadata write happen
automatically when the `with` block exits.

You can also write a single record at a time:

```python
with PqConverter("mydb/") as db:
    for record in my_record_source:
        db.write(record)
```

### Force parallel or standard writer

```python
# Always use parallel writer
with PqConverter("mydb/", parallel=True) as db:
    db.consume("recording.GPS")

# Always use standard writer
with PqConverter("mydb/", parallel=False) as db:
    db.consume("recording.GPS")
```


## Plotting

Plotting requires the `[plot]` extra (`matplotlib` and `plotly`).

```bash
# List all available plots and options
gnsspq plot --help

# Interactive Plotly figures; writes a single dashboard.html with --out
gnsspq plot mydb/ --html

# Overlay the position track on an OpenStreetMap basemap (needs contextily)
gnsspq plot mydb/ --osm
```

The Python API mirrors the CLI:

```python
from nov_gnsspq import PqReader
from nov_gnsspq import plot as gpq_plot

db = PqReader("mydb/")

# Static matplotlib plots
gpq_plot.position(db)
gpq_plot.accuracy(db)
gpq_plot.signal(db)
gpq_plot.satellite_stats(db)
gpq_plot.imu(db)
gpq_plot.skyview(db)

# Interactive Plotly variants
gpq_plot.position_interactive(db)
gpq_plot.tracking_interactive(db)
```

Each plot function accepts the `PqReader` instance and renders the figure.
Interactive variants return Plotly `Figure` objects you can further customise or
export.

## Reconstruction and Verification (experimental)

`gnsspq reconstruct` proves that the Parquet database is a lossless
representation of the original recording by reconstructing a GPS file from the
database and comparing it against the source.

### CLI

```bash
# Reconstruct and compare — runs both field and binary checks by default
gnsspq reconstruct mydb/ recording.GPS

# Field-level comparison only
gnsspq reconstruct mydb/ recording.GPS --mode field

# Binary comparison only
gnsspq reconstruct mydb/ recording.GPS --mode binary
```

After comparison, an HTML report is written to the working
directory (`reconstruction_report.html`).

### Python API

```python
from nov_gnsspq.reconstruct import verify

result = verify("mydb/", "recording.GPS", mode="both")

# Inspect individual mode results
print(result.field.passed)  # True / False
print(result.binary.passed)
```

`verify` accepts `mode="field"`, `mode="binary"`, or `mode="both"`. `"both"`
returns a `BothResults` with `.field` and `.binary` attributes, each
a `VerificationResult`. `VerificationResult` contains per-log-type `TypeResult`
entries with any `FieldDiff` records describing mismatches.

## Documentation

Reference and design documentation lives under [`doc/`](doc/):

| Document | Contents |
|---|---|
| [`doc/cli/cli.md`](doc/cli/cli.md) | Full CLI reference for every subcommand |
| [`doc/plot/plots.md`](doc/plot/plots.md) | Every plot, its inputs and options |
| [`doc/reader/reader-design.md`](doc/reader/reader-design.md) | `PqReader` design and the subtable model |
| [`doc/reconstruct/reconstruction.md`](doc/reconstruct/reconstruction.md) | How lossless verification works |
| [`doc/writer/`](doc/writer/) | Writer design: auto-selection, the standard and parallel writers, and the table-node model |

## Optional plugin providers

`nov_gnsspq` contains a small plugin seam. Two pieces of the package -- GPS
time handling (`nov_gnsspq.compat.gpstime`) and tracing
(`nov_gnsspq.compat.telemetry`) -- can resolve their implementation from the
`nov_gnsspq.plugins` entry point group, falling back to implementations
included in this repository.

**As published, nothing is registered and nothing is active.** The shipped
defaults create no tracer, open no span, read no environment variables, and
send no data anywhere; `start_as_auto_span` returns the function it decorates
unchanged. Discovery is opt-in: importing `nov_gnsspq` reads no installed
distribution metadata and cannot execute third-party provider code. A host
application that wants provider support asks for it explicitly, before
importing the rest of the package:

```python
from nov_gnsspq.compat import enable_plugins

enable_plugins()

import nov_gnsspq
```

[`tests/compat/test_plugins.py`](tests/compat/test_plugins.py) asserts this
behaviour, including that no metadata is read while discovery is opted out.

## License

This project is licensed under the MIT License. 
A copy of the license is available in the LICENSE file included with this 
repository - [LICENSE](LICENSE).

This software may incorporate or depend upon third-party software components
that are subject to separate license terms. Users are responsible for complying
with any applicable third-party licenses.

NovAtel® and other product names, logos, and trademarks referenced in this
project are the property of their respective owners. No rights or licenses to
NovAtel trademarks are granted under the MIT License.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, AS MORE FULLY SET FORTH IN THE LICENSE FILE.
