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

Examples for the gnsspq reconstruct command and Python API.

The reconstruct module reads a nov_gnsspq Parquet database, rebuilds a GPS log
file from the stored field values using novatel-edie, and compares the result
against the original recording to prove no data was lost in the conversion.

Shell quick-reference
---------------------
    # Both modes (default: field-level + binary comparison)
    gnsspq reconstruct my_db/ recording.GPS

    # Field-level only
    gnsspq reconstruct my_db/ recording.GPS --mode field

    # Binary encoding level only
    gnsspq reconstruct my_db/ recording.GPS --mode binary

    # nconvert binary normalisation (mutually exclusive with --mode)
    gnsspq reconstruct my_db/ recording.GPS --nconvert nconvert-m6.exe

    # Treat ASCII-format truncation diffs as VERIFIED
    gnsspq reconstruct my_db/ recording.GPS --use-expected-ascii-rounding

    # Write reconstructed file to a specific location
    gnsspq reconstruct my_db/ recording.GPS --output-gps /tmp/check.GPS

    # Adjust float tolerance (default 1e-9)
    gnsspq reconstruct my_db/ recording.GPS --float-tol 1e-6

    # Console summary only — skip the HTML report
    gnsspq reconstruct my_db/ recording.GPS --no-report

    # Show help
    gnsspq reconstruct --help

Interpretation of results
--------------------------
    VERIFIED     — all field values round-trip faithfully through the parquet
    NOT VERIFIED — message type unsupported by novatel-edie (e.g. RANGE
                   nested obs); raw bytes are preserved for future support
    MISMATCH     — field values differ; the HTML report shows exact diffs with
                   colour-coded categories (negligible / ASCII truncation /
                   non-float / large error)

A run with mismatch_count == 0 and recon_decoded_count == total_messages
gives the strongest confidence guarantee: all messages were reconstructed and
all decoded field values round-trip cleanly through the parquet.
"""
import sys

from nov_gnsspq import setup_logging
from nov_gnsspq.cli.convert import run_convert
from nov_gnsspq.reconstruct import BothResults, VerificationResult, reconstruct, verify

# Point this at a recording of your own, or pass one on the command line.
INPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "recording.GPS"


# ---------------------------------------------------------------------------
# Example 1 — both modes (default)
# Shell: gnsspq reconstruct my_db/ recording.GPS
# ---------------------------------------------------------------------------

def example_verify_both(db_path: str, original_gps: str) -> BothResults:
    """Run field-level and binary verification and print a count check."""
    result: BothResults = verify(
        db_path=db_path,
        original_gps=original_gps,
    )

    for label, r in (("field", result.field), ("binary", result.binary)):
        delta = r.recon_decoded_count - r.total_messages
        count_status = (
            "OK" if delta == 0
            else f"WARN: {abs(delta)} msg(s) missing in reconstructed"
        )
        print(
            f"[{label}] verified={r.verified_count}"
            f"  mismatches={r.mismatch_count}"
            f"  count={count_status}"
        )
    return result


# ---------------------------------------------------------------------------
# Example 2 — field-level only with ASCII-rounding promotion
# Shell: gnsspq reconstruct my_db/ recording.GPS --mode field
#        --use-expected-ascii-rounding
# ---------------------------------------------------------------------------

def example_verify_field_ascii(
        db_path: str,
        original_gps: str) -> VerificationResult:
    """Field-level verify, promoting ASCII truncation diffs to VERIFIED."""
    result = verify(
        db_path=db_path,
        original_gps=original_gps,
        mode="field",
        use_expected_ascii_rounding=True,
    )
    print(
        f"verified={result.verified_count}  "
        f"mismatches={result.mismatch_count}  "
        f"original={result.total_messages}  "
        f"reconstructed={result.recon_decoded_count}"
    )
    return result


# ---------------------------------------------------------------------------
# Example 3 — nconvert binary normalisation
# Shell: gnsspq reconstruct my_db/ recording.GPS --nconvert nconvert-m6.exe
# ---------------------------------------------------------------------------

def example_verify_nconvert(
        db_path: str,
        original_gps: str,
        nconvert_exe: str) -> VerificationResult:
    """Verify using nconvert binary normalisation."""
    result = verify(
        db_path=db_path,
        original_gps=original_gps,
        nconvert_exe=nconvert_exe,
    )
    for log_type, tr in sorted(result.per_type.items()):
        print(f"  {log_type:<20} {tr.status}")
    return result


# ---------------------------------------------------------------------------
# Example 4 — rebuild only (no comparison)
# ---------------------------------------------------------------------------

def example_reconstruct_only(db_path: str, output_gps: str):
    """Write a reconstructed GPS file from a parquet database."""
    reconstruct(db_path=db_path, output_gps=output_gps)
    print(f"Reconstructed GPS written to {output_gps}")


# ---------------------------------------------------------------------------
# Example 5 — full pipeline: convert then verify with count check
# ---------------------------------------------------------------------------

def example_convert_then_verify():
    """Convert a test file and immediately verify the output database."""
    setup_logging()

    input_file = INPUT_FILE
    db_path = "./span_db"

    run_convert(input_file, db_path)

    result: BothResults = verify(
        db_path=db_path,
        original_gps=input_file,
        no_report=False,
    )

    field = result.field
    count_ok = field.recon_decoded_count == field.total_messages

    if not count_ok:
        delta = field.total_messages - field.recon_decoded_count
        print(
            f"WARNING: {delta} message(s) missing from reconstructed GPS "
            f"({field.recon_decoded_count} decoded vs "
            f"{field.total_messages} in original)."
        )
    elif field.mismatch_count > 0:
        print(
            f"WARNING: {field.mismatch_count} message type(s) have "
            f"field mismatches."
        )
        for log_type, tr in field.per_type.items():
            if tr.status == "MISMATCH":
                print(f"  {log_type}: {tr.reason}")
    else:
        print(
            "Verification passed — parquet is a faithful representation "
            "of the recording."
        )

    return result


# ---------------------------------------------------------------------------
# Example 6 — inspect per-type results programmatically
# ---------------------------------------------------------------------------

def example_inspect_results(db_path: str, original_gps: str):
    """Show how to iterate over per-type results after verification."""
    result = verify(
        db_path=db_path,
        original_gps=original_gps,
        mode="field",
        no_report=True,
    )

    verified = [
        t for t, r in result.per_type.items() if r.status == "VERIFIED"
    ]
    not_verified = [
        t for t, r in result.per_type.items()
        if r.status == "NOT_VERIFIED"
    ]
    mismatched = [
        t for t, r in result.per_type.items() if r.status == "MISMATCH"
    ]

    print(f"Verified types:      {verified}")
    print(f"Not verified types:  {not_verified}")
    print(f"Mismatched types:    {mismatched}")
    print(
        f"Message count:  original={result.total_messages}"
        f"  reconstructed={result.recon_decoded_count}"
    )

    for log_type in mismatched:
        tr = result.per_type[log_type]
        print(f"\n{log_type} field diffs:")
        for diff in tr.field_diffs:
            err = (
                f"  rel_err={diff.relative_error:.2e}"
                if diff.relative_error else ""
            )
            print(
                f"  {diff.field_name}: "
                f"{diff.original_value!r} → "
                f"{diff.reconstructed_value!r}{err}"
            )


if __name__ == "__main__":
    example_convert_then_verify()
