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

CLI entry point for nov_gnsspq reconstruct.
"""
from __future__ import annotations

import argparse
import importlib.metadata
from pathlib import Path

from nov_gnsspq.compat.telemetry import start_as_auto_span, telemetry

import nov_gnsspq
from nov_gnsspq import setup_logging
from nov_gnsspq.cli.banner import (ReconstructBannerInfo,
                                   print_reconstruct_banner)
from nov_gnsspq.reconstruct import verify

tracer = telemetry.get_tracer(__name__)


@start_as_auto_span(tracer=tracer)
def main(argv: list[str] | None = None):
    """CLI entry point for ``nov_gnsspq reconstruct``.

    Parses command-line arguments and invokes the reconstruct/verify
    pipeline against a nov_gnsspq Parquet database and an original GPS file.

    Args:
        argv: Argument list to parse. Defaults to ``sys.argv[1:]`` when
            ``None``.
    """
    setup_logging()
    parser = argparse.ArgumentParser(
        prog="nov_gnsspq reconstruct",
        description=(
            "Reconstruct a GPS file from a nov_gnsspq database and verify "
            "data integrity. EXPERIMENTAL: flags and output may change "
            "between releases."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  nov_gnsspq reconstruct my_db/ recording.GPS\n"
            "  nov_gnsspq reconstruct my_db/ recording.GPS --mode field\n"
            "  nov_gnsspq reconstruct my_db/ recording.GPS --mode binary\n"
            "  nov_gnsspq reconstruct my_db/ recording.GPS --no-report\n"
            "  nov_gnsspq reconstruct my_db/ recording.GPS --log-types BESTPOS BESTVEL\n"
        ),
    )
    parser.add_argument(
        "db_path",
        metavar="DB_PATH",
        help="nov_gnsspq Parquet database directory")
    parser.add_argument(
        "original_gps",
        metavar="ORIGINAL_GPS",
        help="original GPS log file")
    parser.add_argument(
        "--output-gps",
        metavar="PATH",
        dest="output_gps",
        default=None,
        help=(
            "write reconstructed GPS file here "
            "(default: ./reconstructed.GPS)"
        ))
    parser.add_argument(
        "--report",
        metavar="PATH",
        default=None,
        help=(
            "write HTML report here "
            "(default: ./reconstruction_report.html)"
        ))
    parser.add_argument(
        "--float-tol",
        metavar="FLOAT",
        dest="float_tol",
        type=float,
        default=1e-9,
        help="float comparison tolerance (default: 1e-9)")
    parser.add_argument(
        "--no-report",
        action="store_true",
        dest="no_report",
        help="console summary only; skip HTML report")
    parser.add_argument(
        "--use-expected-ascii-rounding",
        action="store_true",
        dest="use_expected_ascii_rounding",
        help=(
            "treat diffs caused by EDIE ASCII encoding (fixed decimal "
            "places, float32 round-trip) as VERIFIED instead of MISMATCH"
        ),
    )

    parser.add_argument(
        "--mode",
        choices=["field", "binary", "both"],
        default="both",
        help="comparison mode: field, binary, or both (default: both)",
    )

    parser.add_argument(
        "--log-types",
        metavar="TYPE",
        dest="log_types",
        nargs="+",
        default=None,
        help=(
            "restrict comparison to these message types "
            "(e.g. BESTPOS BESTVEL); default: all types"
        ),
    )

    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    original_gps = Path(args.original_gps)

    if not db_path.exists():
        parser.error(f"db_path not found: {args.db_path}")
    if not original_gps.exists():
        parser.error(f"original_gps not found: {args.original_gps}")

    try:
        edie_ver = importlib.metadata.version("novatel_edie")
    except importlib.metadata.PackageNotFoundError:
        edie_ver = "unknown"

    print_reconstruct_banner(ReconstructBannerInfo(
        db_path=db_path,
        original_gps=original_gps,
        mode=args.mode,
        nov_gnsspq_version=nov_gnsspq.__version__,
        edie_version=edie_ver,
    ))

    log_types = set(args.log_types) if args.log_types else None

    verify(
        db_path=db_path,
        original_gps=original_gps,
        mode=args.mode,
        output_gps=args.output_gps,
        report=args.report,
        float_tol=args.float_tol,
        no_report=args.no_report,
        use_expected_ascii_rounding=args.use_expected_ascii_rounding,
        log_types=log_types,
    )
