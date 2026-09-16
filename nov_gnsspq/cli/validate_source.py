#!/usr/bin/env python3
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

CLI entry point for the nov_gnsspq validate-source command.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nov_gnsspq.compat.telemetry import start_as_auto_span, telemetry

from nov_gnsspq import compare, setup_logging

tracer = telemetry.get_tracer(__name__)

_REASON_DETAIL = {
    "metadata_missing": (
        "database has no _metadata.json — was it built with gnsspq convert?"
    ),
    "metadata_incomplete": (
        "database metadata is missing file_size or sha256 — "
        "may have been written in streaming mode"
    ),
    "file_size_mismatch": (
        "byte sizes differ — the two inputs do not correspond"
    ),
    "sha256_mismatch": (
        "SHA-256 digests differ — the two inputs do not match"
    ),
}


def run_validate_source(path_a: Path, path_b: Path) -> bool:
    """Compare two paths by fingerprint and print the result.

    Auto-detects each argument as a GPS file or database. Prints a single
    result line to stdout.

    Args:
        path_a: First path to compare.
        path_b: Second path to compare.

    Returns:
        ``True`` if the inputs match, ``False`` otherwise.
    """
    result = compare(path_a, path_b)
    if result.valid:
        print("VALID   inputs match.")
    else:
        msg = _REASON_DETAIL.get(result.reason, result.reason)
        side = f" [{result.detail}]" if result.detail else ""
        print(f"INVALID {result.reason}{side} — {msg}")
    return result.valid


@start_as_auto_span(tracer=tracer)
def main(argv=None):
    """CLI entry point for ``gnsspq validate-source``.

    Args:
        argv: Argument list to parse. Defaults to ``sys.argv[1:]``.
    """
    setup_logging()
    parser = argparse.ArgumentParser(
        prog="gnsspq validate-source",
        description=(
            "Compare two GPS files or databases by fingerprint (file size + SHA-256).\n"
            "Each argument may be a GPS log file, a Parquet database directory,\n"
            "or a .zip / .gnsspq archive. Arguments may be supplied in either order.\n"
            "Exits 0 if the inputs match, 1 if they do not."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  gnsspq validate-source recording.GPS ./mydb\n"
            "  gnsspq validate-source ./mydb recording.GPS\n"
            "  gnsspq validate-source ./mydb_a ./mydb_b\n"
            "  gnsspq validate-source recording_a.GPS recording_b.GPS\n"
        ),
    )
    parser.add_argument(
        "path_a",
        metavar="PATH_A",
        help="first path (GPS file or database)",
    )
    parser.add_argument(
        "path_b",
        metavar="PATH_B",
        help="second path (GPS file or database)",
    )

    args = parser.parse_args(argv)

    path_a, path_b = Path(args.path_a), Path(args.path_b)
    for label, p in [("first", path_a), ("second", path_b)]:
        if not p.exists():
            parser.error(f"{label} path not found: {p}")

    matched = run_validate_source(path_a, path_b)
    sys.exit(0 if matched else 1)
