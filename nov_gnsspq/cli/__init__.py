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

Top-level CLI entry point for the nov_gnsspq package.
"""
from __future__ import annotations

import sys

_USAGE = """\
usage: gnsspq <command> [options]

commands:
  convert          convert a GPS log file to a Parquet database
  plot             generate plots from a nov_gnsspq Parquet database
  reconstruct      verify that a nov_gnsspq database is lossless
  validate-source  compare two GPS files or databases by fingerprint

Run 'gnsspq <command> --help' for subcommand help.\
"""


def main(argv=None):
    """Dispatches to the appropriate nov_gnsspq subcommand.

    Args:
        argv: Argument list to parse; defaults to sys.argv[1:].
    """
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in {"-h", "--help"}:
        print(_USAGE)
        sys.exit(0)

    cmd, *rest = argv
    if cmd == "convert":
        from nov_gnsspq.cli.convert import main as convert_main
        convert_main(rest)
    elif cmd == "plot":
        from nov_gnsspq.cli.plot import main as plot_main
        plot_main(rest)
    elif cmd == "reconstruct":
        from nov_gnsspq.cli.reconstruct import main as reconstruct_main
        reconstruct_main(rest)
    elif cmd in {"validate-source", "validate_source"}:
        from nov_gnsspq.cli.validate_source import main as validate_source_main
        validate_source_main(rest)
    else:
        print(
            f"gnsspq: unknown command '{cmd}'\n\n{_USAGE}",
            file=sys.stderr)
        sys.exit(1)
