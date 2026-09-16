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

Programmatic runner and CLI entry point for the nov_gnsspq convert command.
"""

import argparse
import importlib.metadata
import logging
import sys
from pathlib import Path
from typing import TextIO

from nov_gnsspq.compat.telemetry import start_as_auto_span, telemetry

import nov_gnsspq
from nov_gnsspq import PqConverter, setup_logging
from nov_gnsspq.exceptions import DatabaseExistsError
from nov_gnsspq.cli.banner import ConvertBannerInfo, print_convert_banner
from nov_gnsspq.writer.generator import zip_database
from nov_gnsspq.writer.parallel.engine import PARALLEL_MIN_BYTES, _auto_tune

log = logging.getLogger("nov_gnsspq.cli.convert")
tracer = telemetry.get_tracer(__name__)


@start_as_auto_span(tracer=tracer)
def run_convert(
        input_path: str | Path,
        output_path: str | Path,
        *,
        parallel: bool | None = None,
        overwrite: bool = False,
        no_banner: bool = False,
        banner_stream: TextIO | None = None,
        archive: bool = False):
    """Converts a GPS log file to a nov_gnsspq Parquet database.

    Args:
        input_path: Path to the source GPS log file.
        output_path: Directory to write the database into.
        parallel: ``True`` force parallel, ``False`` force standard,
            ``None`` auto-select by file size (>= threshold -> Parallel).
        overwrite: If ``True``, allow writing into a directory that already
            contains a database. Default ``False``.
        no_banner: Suppress the startup banner (useful in CI / scripted
            runs).
        banner_stream: Stream to write the banner to. Defaults to
            ``sys.stdout``.
        archive: If ``True``, compress the output database directory into a
            ``.gnsspq`` archive at ``{output_path}.gnsspq`` after a
            successful conversion. The original directory is preserved.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    stream = banner_stream or sys.stdout

    # On Windows the default stdout encoding is cp1252 which can't encode
    # box-drawing characters or emit ANSI true-color sequences. Reconfigure
    # to UTF-8 so the banner renders correctly without PYTHONUTF8=1.
    if banner_stream is None and hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except OSError:
            pass

    if not no_banner:
        file_size = input_path.stat().st_size
        tune = _auto_tune(str(input_path))
        writer_name = (
            "Parallel"
            if (
                parallel is True
                or (parallel is None and file_size >= PARALLEL_MIN_BYTES)
            )
            else "Standard"
        )
        writer_selection = "auto" if parallel is None else "user specified"
        try:
            edie_ver = importlib.metadata.version("novatel_edie")
        except importlib.metadata.PackageNotFoundError:
            edie_ver = "?"

        info = ConvertBannerInfo(
            input_path=input_path,
            output_path=output_path,
            file_size_mb=file_size / 1_000_000,
            writer=writer_name,
            writer_selection=writer_selection,
            workers=tune["workers"],
            threshold_mb=int(PARALLEL_MIN_BYTES / 1_000_000),
            edie_version=edie_ver,
            nov_gnsspq_version=nov_gnsspq.__version__,
        )
        print_convert_banner(info, stream)

    with PqConverter(
        output_path, overwrite=overwrite, parallel=parallel
    ) as db:
        db.consume(str(input_path))

    # TODO: add zip_only / zip_keep variants
    if archive:
        zip_database(output_path)


@start_as_auto_span(tracer=tracer)
def main(argv=None):
    """CLI entry point for ``nov_gnsspq convert``.

    Args:
        argv: Argument list to parse. Defaults to ``sys.argv[1:]``.
    """
    setup_logging()
    parser = argparse.ArgumentParser(
        prog="gnsspq convert",
        description=(
            "Convert a GPS log file to a nov_gnsspq Parquet database."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  gnsspq convert log.GPS -o ./db\n"
            "  gnsspq convert log.GPS -o ./db --parallel\n"
        ),
    )
    parser.add_argument(
        "input",
        metavar="INPUT",
        help="source GPS log file",
    )
    parser.add_argument(
        "--out", "-o",
        metavar="DIR",
        required=True,
        dest="output",
        help="output directory for the Parquet database",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--parallel",
        action="store_true",
        default=False,
        help="force parallel writer (default: auto-select by file size)",
    )
    mode_group.add_argument(
        "--no-parallel",
        action="store_true",
        default=False,
        dest="no_parallel",
        help="force standard single-threaded writer",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="overwrite an existing database in the output directory",
    )
    parser.add_argument(
        "--archive", "--zip",
        action="store_true",
        default=False,
        dest="archive",
        help=(
            "compress the output database directory into a .gnsspq archive "
            "after conversion (output_dir.gnsspq). The original directory "
            "is preserved. (--zip is an alias.)"
        ),
    )
    # TODO: --no-banner  suppress the startup banner
    # TODO: --no-color   strip ANSI escape codes regardless of TTY

    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        parser.error(f"input file not found: {args.input}")

    parallel: bool | None = None
    if args.parallel:
        parallel = True
    elif args.no_parallel:
        parallel = False

    try:
        run_convert(
            input_path=input_path,
            output_path=args.output,
            parallel=parallel,
            overwrite=args.overwrite,
            archive=args.archive,
        )
    except DatabaseExistsError as exc:
        parser.error(f"{exc}  Pass --overwrite to replace it.")
