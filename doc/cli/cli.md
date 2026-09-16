# nov_gnsspq CLI Reference

The `nov_gnsspq` command converts NovAtel GPS binary recordings into a queryable Parquet database. All subsequent analysis reads directly from the Parquet files, with no re-decoding required.

---

## Installation

```bash
pip install nov_gnsspq
```

After installation the `nov_gnsspq` command is available on your `PATH`.

---

## Usage

```
gnsspq <command> [options]
```

Run `gnsspq --help` to list available commands. Run `gnsspq <command> --help` for command-specific help.

---

## Commands

### `convert`

Convert a GPS log file to a nov_gnsspq Parquet database.

```
gnsspq convert INPUT -o DIR [options]
```

#### Positional arguments

| Argument | Description |
|---|---|
| `INPUT` | Path to the source GPS log file. |

#### Options

| Flag | Description |
|---|---|
| `-o DIR`, `--out DIR` | **Required.** Output directory for the Parquet database. Created if it does not exist. |
| `--parallel` | Force the parallel writer. Mutually exclusive with `--no-parallel`. |
| `--no-parallel` | Force the standard single-threaded writer. Mutually exclusive with `--parallel`. |
| `--zip` | Compress the output database directory into a zip archive (`DIR.zip`) after conversion. The original directory is preserved alongside the archive. |
| `--overwrite` | Overwrite an existing database at `DIR` if one already exists. Without this flag, converting to an existing output directory exits with an error. |
| `-h`, `--help` | Show help and exit. |

#### Writer auto-selection

When neither `--parallel` nor `--no-parallel` is given, the writer is chosen automatically based on the input file size:

| File size | Writer selected |
|---|---|
| < 50 MB | Standard (single-threaded) |
| ≥ 50 MB | Parallel (multi-process) |

The startup banner always reports which writer was selected and why (`auto` or `user specified`).

---

### `plot`

Generate plots from a nov_gnsspq Parquet database. Requires the `nov_gnsspq[plot]` optional dependency (`matplotlib`, `contextily`).

```
gnsspq plot DB_DIR [--plot NAME ...] [--out DIR]
```

#### Positional arguments

| Argument | Description |
|---|---|
| `DB_DIR` | Path to the nov_gnsspq Parquet database directory produced by `gnsspq convert`. |

#### Options

| Flag | Description |
|---|---|
| `--plot NAME [NAME ...]` | One or more plot names to generate. When omitted, all nine available plots are attempted. |
| `--out DIR` | Directory to save PNG files into (one file per plot, named `{plot}.png`). When omitted, each figure is shown interactively via `plt.show()`. The directory is created if it does not exist. |
| `--osm` | Overlay OpenStreetMap tiles on the `position` scatter map. Requires `contextily` (`pip install contextily`). Silently ignored for all other plot types. |
| `-h`, `--help` | Show help and exit. |

#### Available plot names

| Name | Required log(s) |
|---|---|
| `accuracy` | `BESTPOS` |
| `attitude_accuracy` | `INSSTDEV` |
| `imu` | `RAWIMUSX` / `RAWIMUX` / `RAWIMUS` / `RAWIMU` |
| `position` | `BESTPOS` |
| `position_accuracy` | `INSSTDEV` |
| `satellite_stats` | `RANGE` (+ optional `SATVIS2`) |
| `signal` | `RANGE` |
| `skyview` | `SATVIS2` |
| `tracking` | `RANGE` |

#### Behaviour

When no `--plot` arguments are given, all nine plots are attempted. Plots whose required log is absent in the database are skipped and reported to stderr; this is expected behaviour when a recording does not contain every log type. The command exits with code `0` as long as at least one plot succeeds.

When specific plots are requested via `--plot` and all of them fail, the command exits with code `1`.

---

## Examples

### Basic conversion

```bash
gnsspq convert recording.GPS -o ./db
```

Converts `recording.GPS` and writes the database to `./db/`. Writer mode is chosen automatically from file size.

### Force parallel mode

```bash
gnsspq convert recording.GPS -o ./db --parallel
```

Useful for large files on multi-core machines, or when you want consistent parallel behaviour regardless of file size.

### Force standard mode

```bash
gnsspq convert recording.GPS -o ./db --no-parallel
```

Useful in memory-constrained environments or when consistent single-threaded behaviour is required.

### Create a shareable zip archive

```bash
gnsspq convert recording.GPS -o ./db --zip
```

After conversion completes, the output directory is compressed into `./db.zip`. The `./db/` directory is preserved unchanged alongside the archive; the zip unpacks to a `db/` directory with the same internal structure as the original.

Flags compose normally:

```bash
gnsspq convert recording.GPS -o ./db --parallel --zip
```

---

## Output structure

```
db/
├── log_table.parquet          # one row per message, in arrival order
├── _metadata.json             # SHA-256, message count, schema version
├── unknown_data.parquet       # unrecognised message payloads (if any)
├── BESTPOS/
│   └── BESTPOS.parquet
├── RANGE/
│   ├── RANGE.parquet
│   └── obs/
│       └── obs.parquet        # child table — linked via parent_id
└── ...
```

Each NovAtel message type gets its own Parquet file. Nested sub-messages (satellite observations, almanac entries, etc.) are stored as child tables and linked to their parent row via `parent_id → sequence_id`.

---

### `reconstruct`

Verify that a nov_gnsspq Parquet database is a lossless representation of the original GPS recording. Rebuilds a GPS file from the database and compares it against the original.

```
gnsspq reconstruct DB_PATH ORIGINAL_GPS [options]
```

#### Positional arguments

| Argument | Description |
|---|---|
| `DB_PATH` | Path to the nov_gnsspq Parquet database directory. |
| `ORIGINAL_GPS` | Path to the original GPS log file. |

#### Options

| Flag | Default | Description |
|---|---|---|
| `--output-gps PATH` | `<DB_PATH>/reconstructed.GPS` | Write reconstructed GPS file here. |
| `--report PATH` | `<DB_PATH>/reconstruction_report.html` | Write HTML report here. |
| `--nconvert PATH` | — | Path to `nconvert-m6.exe`. Enables binary comparison mode. |
| `--float-tol FLOAT` | `1e-9` | Float comparison tolerance (external mode only). |
| `--no-report` | — | Print console summary only; skip the HTML report. |
| `--log-types TYPE [TYPE ...]` | — | Restrict verification to these NovAtel log type names (e.g. `BESTPOS BESTVEL`). When omitted, all log types in the database are verified. |
| `-h`, `--help` | — | Show help and exit. |

See [reconstruction.md](../reconstruct/reconstruction.md) for the full reference including comparison modes, result status codes, and the Python API.

---

### `validate-source`

Compare two GPS files or databases by fingerprint (file size + SHA-256). Each argument may be a GPS log file, a nov_gnsspq Parquet database directory, or a `.zip` / `.gnsspq` archive. Arguments may be supplied in either order. Also accepts `validate_source` as an alias.

```
gnsspq validate-source PATH_A PATH_B
```

#### Positional arguments

| Argument | Description |
|---|---|
| `PATH_A` | First path — a GPS log file or nov_gnsspq database (directory, `.zip`, or `.gnsspq`). |
| `PATH_B` | Second path — a GPS log file or nov_gnsspq database (directory, `.zip`, or `.gnsspq`). |

#### Output

The command prints a single result line to stdout and exits:

| Output | Exit code | Meaning |
|---|---|---|
| `VALID   inputs match.` | `0` | File size and SHA-256 both match. |
| `INVALID metadata_missing [first argument] — …` | `1` | First argument database has no `_metadata.json`. |
| `INVALID metadata_missing [second argument] — …` | `1` | Second argument database has no `_metadata.json`. |
| `INVALID metadata_incomplete [first argument] — …` | `1` | First argument database metadata lacks `file_size` or `sha256`. |
| `INVALID metadata_incomplete [second argument] — …` | `1` | Second argument database metadata lacks `file_size` or `sha256`. |
| `INVALID file_size_mismatch — …` | `1` | Byte sizes differ. |
| `INVALID sha256_mismatch — …` | `1` | SHA-256 digests differ. |

#### Examples

```bash
gnsspq validate-source recording.GPS ./mydb
gnsspq validate-source ./mydb recording.GPS
gnsspq validate-source ./mydb_a ./mydb_b
gnsspq validate-source recording_a.GPS recording_b.GPS
```

#### Python API

```python
from nov_gnsspq import compare, ValidationResult

result = compare("recording.GPS", "./mydb")
if result.valid:
    print("match")
else:
    print(f"mismatch: {result.reason}")
```

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Command completed successfully (conversion finished, or inputs match). |
| `1` | Argument error or validation mismatch (missing flag, file not found, inputs do not match). |
| `2` | Runtime error (filesystem error, decode failure). |

---

## Python API

The CLI is a thin wrapper over the `run_convert()` function. Use it directly when embedding conversions in scripts:

```python
from nov_gnsspq.cli.convert import run_convert

run_convert(
    input_path="recording.GPS",
    output_path="./db",
    parallel=None,          # None = auto, True = force parallel, False = force standard
    zip_output=False,       # True → also write ./db.zip alongside ./db/
    overwrite=False,        # True → overwrite existing database at output_path
)
```

To control the zip step directly, for example to capture the archive path or zip an existing database without re-converting, call `zip_database()` after the generator:

```python
from nov_gnsspq.writer.generator import PqConverter, zip_database
from pathlib import Path

output = Path("./db")
with PqConverter(output) as db:
    db.consume("recording.GPS")

zip_path = zip_database(output)   # returns Path("./db.zip")
```

See `nov_gnsspq/examples/nov_gnsspq_cli_examples.py` for runnable examples, and [README](../writer/README.md) for the full Python API reference including `PqConverter`.

---

## Plotting Examples

### Show all plots interactively

```bash
gnsspq plot ./db
```

Attempts all nine plots. Plots whose required log is absent in the database are skipped and reported to stderr. Each figure is shown interactively in sequence.

### Show specific plots

```bash
gnsspq plot ./db --plot position skyview tracking
```

### Save plots to a directory

```bash
gnsspq plot ./db --out ./figures
```

Writes `accuracy.png`, `position.png`, etc. to `./figures/`. The directory is created if it does not exist. Filenames are fixed to `{plot_name}.png`.

### Save a single plot

```bash
gnsspq plot ./db --plot satellite_stats --out ./figures
```

### Python API

`run_plot()` is the programmatic equivalent of the CLI command:

```python
from nov_gnsspq.cli.plot import run_plot

failures = run_plot(
    db_path="./db",
    plots=None,         # None = all plots; list of names to restrict
    out_dir="./figures",# None = plt.show()
    osm=False,          # True → overlay OSM tiles on the position scatter map
)

for name, exc in failures.items():
    print(f"  {name} skipped — {exc}")
```

To call plot functions directly, for example to customise the figure before saving, use `nov_gnsspq.plot`:

```python
from nov_gnsspq.reader.frontend import PqReader
import nov_gnsspq.plot as plot
import matplotlib.pyplot as plt

db = PqReader("./db")
fig = plot.satellite_stats(db, prns=[1, 3, 7, 15])
fig.savefig("selected_prns.png", dpi=150, bbox_inches="tight")
plt.close(fig)
```

See [plots.md](../plot/plots.md) for the full per-plot reference including required logs and parameter descriptions.
