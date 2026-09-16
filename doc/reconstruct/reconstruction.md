# nov_gnsspq Reconstruction & Verification

The `gnsspq reconstruct` command reads a nov_gnsspq Parquet database, rebuilds a complete GPS log file from it, and compares the rebuilt file against the original recording to prove that the conversion introduced no data loss.

---

## Why this matters

The nov_gnsspq writer converts NovAtel GPS logs into Parquet databases. Every conversion is a claim: "this database contains everything the original recording contained." Reconstruction and verification close the loop on that claim.

The verification pipeline is:

```
original GPS  ──────────────────────────────────────────┐
                                                         │ compare
original GPS  →  parquet  →  reconstructed GPS  ─────────┘
```

The original GPS file is always one of the two endpoints. This means a bug that affects both the parquet writer and the reconstructor identically cannot be hidden, since the original file is independent of both.

---

## What confidence looks like

`gnsspq reconstruct` runs two complementary checks:

### Field-level comparison (`--mode field`)

Decodes both the original GPS and the reconstructed GPS with EDIE's parser. Compares every decoded field value pair-by-pair:

| Field type | Pass condition |
|---|---|
| `float` / `double` | within `float_tol` (relative) |
| `int`, enum | exact integer equality |
| `str`, `bytes` | exact equality |

If this passes: every value the parquet stored came back out of the reconstructed GPS unchanged. The parquet is a faithful decoded representation of the original recording.

### Binary-level comparison (`--mode binary`)

Encodes both the original and reconstructed decoded messages to NovAtel binary format via EDIE, then compares the binary payloads byte-by-byte. At byte offsets corresponding to float or double fields (looked up from EDIE's runtime message schema), a float tolerance is applied instead of requiring exact byte equality. At all other byte positions, exact equality is required.

For unknown/unsupported messages (those copied verbatim from `unknown_data.parquet`), the raw frame bytes are compared exactly.

If this passes: the reconstructed GPS is a byte-faithful reproduction of the original, not just a value-equivalent one. This catches encoding-layer differences, such as field ordering, header values, and enum encoding, that a field-level comparison would miss.

### Both modes together (`--mode both`, default)

Running both gives the strongest guarantee. A recording that passes both checks is confirmed lossless at the value level and at the binary encoding level.

---

## Reconstruction: how it works

The reconstructed GPS file contains **every message** from the original recording, in arrival order. Nothing is omitted.

```
log index (sequence_id order)
    │
    ├─ supported type (BESTPOS, BESTVEL, …)
    │       → decoded fields from parquet
    │       → reconstructed via EDIE message constructors
    │       → written as NovAtel binary
    │
    └─ unsupported / unknown (UnknownMessage, UnknownBytes, RANGE, …)
            → raw payload bytes copied verbatim from unknown_data.parquet
```

Supported messages are reconstructed using the EDIE constructor API (`Header(...)`, `BESTPOS(...)`, etc.) and encoded to abbreviated ASCII by default. When binary output is requested, a two-stage process is used: construct → abbreviated ASCII → Framer/Decoder → `to_binary()`. This two-stage path is necessary because calling `to_binary()` directly on a manually constructed message produces a corrupt binary header; routing through the Framer/Decoder pipeline causes EDIE to recompute the format-specific header fields (message length, format flags) correctly.

Unsupported and unknown messages are not reconstructed; they are copied byte-for-byte from the `unknown_data.parquet` table that the nov_gnsspq writer produced during the original conversion. This means RANGE observations, proprietary messages, and any bytes the writer could not decode are all preserved exactly.

---

## Requirements

- **novatel-edie** with an active constructor API (`Header(...)`, `BESTPOS(...)`, etc.). The constraint in `pyproject.toml` is `^2.0.4`, but the constructor API availability depends on the specific build; if reconstruction fails with `no constructor defined`, the installed novatel-edie version does not expose the required constructors.

---

## Usage

```
gnsspq reconstruct DB_PATH ORIGINAL_GPS [options]
```

### Positional arguments

| Argument | Description |
|---|---|
| `DB_PATH` | Path to the nov_gnsspq Parquet database directory. |
| `ORIGINAL_GPS` | Path to the original GPS log file used to create the database. |

### Options

| Flag | Default | Description |
|---|---|---|
| `--mode MODE` | `both` | Comparison mode: `field`, `binary`, or `both`. |
| `--output-gps PATH` | `./reconstructed.GPS` | Where to write the reconstructed GPS file. |
| `--report PATH` | `./reconstruction_report.html` | Where to write the HTML report. In `both` mode, two reports are written: `<stem>_field.html` and `<stem>_binary.html`. |
| `--float-tol FLOAT` | `1e-9` | Relative tolerance for floating-point comparisons. |
| `--no-report` | — | Print console summary only; skip the HTML report. |
| `--use-expected-ascii-rounding` | — | Promote MISMATCH→VERIFIED for types whose only diffs are explained by EDIE's ASCII encoding (see below). |
| `-h`, `--help` | — | Show help and exit. |

---

## ASCII encoding limitations and `--use-expected-ascii-rounding`

EDIE's ASCII encoder introduces two kinds of numeric differences that are inherent to the format, not indicators of data loss:

1. **Fixed decimal places**: `to_ascii()` writes floats with a fixed number of decimal places (e.g. `51.1235` from `51.12345678`). The original binary value is preserved in the parquet; the reconstructed GPS has the truncated ASCII representation.

2. **float32 round-trip**: NovAtel binary fields are often 4-byte IEEE 754 floats. After ASCII encode/decode, the value is `float32(round(orig, N))` rather than the full-precision double.

Running `--mode field` without any flag will report these as MISMATCH. The `--use-expected-ascii-rounding` flag tells the verifier to classify such diffs as VERIFIED, because the parquet faithfully stores the original value, and the mismatch is in the ASCII-format reconstruction, not in the database. The diffs are still visible in the HTML report under the type's detail section.

Use this flag when you want a clean "all green" result for a database known to contain only ASCII-format truncation diffs.

---

## Comparison modes

### `--mode field` (field-level)

Iterates both files with EDIE's `Framer`, decoding each message with `Decoder`. Compares every decoded field pair with the rules above. Unknown frames are marked `NOT_VERIFIED`.

### `--mode binary` (binary-level)

Iterates both files with EDIE's `Framer`. For each known message, encodes both the original and reconstructed decoded messages to binary via `to_binary()`, then compares byte-by-byte. Float/double field byte offsets are resolved at runtime from EDIE's message schema (`get_builtin_database().get_msg_def(name)`), cached per message type. For unknown frames, compares raw frame bytes exactly.

### `--mode both` (default)

Runs both comparisons and returns separate results for each. Two HTML reports are written when reporting is enabled: the report path stem receives `_field` and `_binary` suffixes (e.g. `reconstruction_report_field.html` and `reconstruction_report_binary.html`). The console summary is printed twice, once for each mode.

---

## Result status codes

| Status | Meaning |
|---|---|
| `VERIFIED` | All comparisons passed for this message type. |
| `NOT_VERIFIED` | Message type has no decoded fields to compare (unknown/unsupported). Raw bytes are intact and verified by binary mode. |
| `MISMATCH` | One or more comparisons failed. The HTML report shows exact diffs. |

A run with `mismatch_count == 0` and at least one verified type confirms the parquet is a faithful, lossless representation of all supported message types in the recording.

---

## Console output

In `--mode both`, the console summary is printed twice — once for field comparison, once for binary. Each block looks like the following example (shown here for a single mode):

```
Reconstruction report -- my_db/
--------------------------------------------------
  BESTPOS              842 msgs   VERIFIED
  RANGE                637 msgs   NOT_VERIFIED  (raw bytes preserved)
--------------------------------------------------
  Verified:         842 / 1479  (56.9%)
  Not verified:     637 / 1479  (43.1%)
  Mismatches:         0
```

---

## HTML report

The HTML report contains:

- **Stat boxes**: total messages, verified count, not-verified count, mismatch count.
- **Per-type main table**: one row per VERIFIED or MISMATCH type. MISMATCH rows include an expandable diff table showing original value, reconstructed value, relative error, and a coloured category badge.
- **Diff categories**: each diff in the expandable table is classified:
  | Category | Colour | Meaning |
  |---|---|---|
  | Negligible | Green | Relative error < 0.1 ppm |
  | ASCII truncation | Amber | Diff explained by EDIE fixed decimal places or float32 round-trip |
  | Non-float mismatch | Pink | Integer/enum/string mismatch, requires investigation |
  | Large relative error | Red | Float error ≥ 1e-5 and not explained by ASCII encoding, requires investigation |
- **Legend**: explains all four categories inline.
- **Undecodable / NOT_VERIFIED section**: a collapsible section at the bottom lists all NOT_VERIFIED types (unsupported message types whose raw bytes were copied verbatim) with their reason, separate from the main table.

---

## Examples

```bash
# Default: both comparison modes, two HTML reports written
gnsspq reconstruct my_db/ recording.GPS

# Field-level only
gnsspq reconstruct my_db/ recording.GPS --mode field

# Binary-level only
gnsspq reconstruct my_db/ recording.GPS --mode binary

# Custom output paths
gnsspq reconstruct my_db/ recording.GPS \
    --output-gps /tmp/rebuilt.GPS \
    --report /tmp/report.html

# Console summary only
gnsspq reconstruct my_db/ recording.GPS --no-report

# Looser float tolerance
gnsspq reconstruct my_db/ recording.GPS --float-tol 1e-6

# Treat ASCII-format truncation diffs as VERIFIED
gnsspq reconstruct my_db/ recording.GPS --use-expected-ascii-rounding
```

---

## Python API

```python
from nov_gnsspq.reconstruct import verify, reconstruct, VerificationResult, BothResults

# Full round-trip: rebuild GPS file + both comparison modes
result: BothResults = verify(
    db_path="my_db/",
    original_gps="recording.GPS",
    mode="both",                         # "field" | "binary" | "both"
    output_gps="reconstructed.GPS",      # optional
    report="report.html",                # optional
    float_tol=1e-9,
    no_report=False,
    use_expected_ascii_rounding=False,   # True to promote ASCII-truncation diffs to VERIFIED
)

print(f"field:  verified={result.field.verified_count}  mismatches={result.field.mismatch_count}")
print(f"binary: verified={result.binary.verified_count}  mismatches={result.binary.mismatch_count}")

# Single mode — returns VerificationResult directly
field_result: VerificationResult = verify(
    db_path="my_db/",
    original_gps="recording.GPS",
    mode="field",
)

# Rebuild only (no comparison)
reconstruct(db_path="my_db/", output_gps="rebuilt.GPS")
```

### `verify()` parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `db_path` | `str \| Path` | required | nov_gnsspq Parquet database directory. |
| `original_gps` | `str \| Path` | required | Original GPS log file. |
| `mode` | `str` | `"both"` | `"field"`, `"binary"`, or `"both"`. |
| `output_gps` | `str \| Path \| None` | `./reconstructed.GPS` | Destination for the rebuilt GPS file (current working directory). |
| `report` | `str \| Path \| None` | `./reconstruction_report.html` | Destination for the HTML report (current working directory). |
| `float_tol` | `float` | `1e-9` | Relative tolerance for float comparisons. |
| `no_report` | `bool` | `False` | Skip writing the HTML report. |
| `log_types` | `set[str] \| None` | `None` | If provided, only messages of those types are compared; all others are skipped. |
| `use_expected_ascii_rounding` | `bool` | `False` | Promote MISMATCH→VERIFIED for types whose only diffs are EDIE ASCII-format truncation. |

### Return types

| `mode` | Return type |
|---|---|
| `"field"` | `VerificationResult` |
| `"binary"` | `VerificationResult` |
| `"both"` | `BothResults(field=VerificationResult, binary=VerificationResult)` |

### `VerificationResult` fields

| Field | Type | Description |
|---|---|---|
| `total_messages` | `int` | Total rows in the log-index table (original file). |
| `verified_count` | `int` | Number of message types that VERIFIED. |
| `not_verified_message_count` | `int` | Total message count for NOT_VERIFIED types. |
| `mismatch_count` | `int` | Number of message types with MISMATCH. |
| `per_type` | `dict[str, TypeResult]` | Per-type results, keyed by log type name. |
| `recon_decoded_count` | `int` | Number of messages decoded from the reconstructed GPS file. A value lower than `total_messages` indicates that some messages were silently dropped during reconstruction. |

---

## Limitations

- **Nested message types** (e.g. RANGE satellite sub-records) cannot be reconstructed from parquet because the novatel-edie constructor API does not support them. Their raw bytes are preserved in `unknown_data.parquet` and copied verbatim into the reconstructed file. In binary mode they compare as VERIFIED (exact byte copy). In field-level mode they compare as NOT_VERIFIED (no decoded fields to compare).
- **Constructor API availability** depends on the installed novatel-edie build. If reconstruction silently skips messages or logs `Failed to construct <TYPE>`, the installed version does not expose the required constructors. Re-run with `DEBUG` logging to see per-message details.

---

## See also

- [CLI reference](../cli/cli.md): all `nov_gnsspq` commands
- [Getting started](../writer/README.md): conversion, output structure, and reading the database
- `nov_gnsspq/examples/nov_gnsspq_reconstruct.py`: runnable Python examples
