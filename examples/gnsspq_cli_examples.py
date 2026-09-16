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

Example usage of nov_gnsspq.
"""
"""
Examples for invoking the gnsspq convert CLI.

These examples call the CLI entry point directly from Python, which is useful
for testing or embedding nov_gnsspq conversions inside larger scripts.  For normal
use from a terminal, see the shell commands in the comments below each example.

Shell quick-reference
---------------------
    # Basic conversion (auto writer selection)
    gnsspq convert recording.GPS -o ./db

    # Force parallel writer
    gnsspq convert recording.GPS -o ./db --parallel

    # Force standard (single-threaded) writer
    gnsspq convert recording.GPS -o ./db --no-parallel

    # Show help
    gnsspq convert --help
"""

import logging
import sys

from nov_gnsspq import setup_logging
from nov_gnsspq.cli.convert import main as convert_main
from nov_gnsspq.cli.convert import run_convert

# Point this at a recording of your own, or pass one on the command line.
INPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "recording.GPS"

# ---------------------------------------------------------------------------
# Example 1 — programmatic call via run_convert()
# Shell equivalent: gnsspq convert <input> -o ./example_1_db
# ---------------------------------------------------------------------------

def example_basic():
    """Convert a test file using auto writer selection."""
    setup_logging(logging.INFO)
    run_convert(INPUT_FILE, "./example_1_db")


# ---------------------------------------------------------------------------
# Example 2 — force parallel writer via run_convert()
# Shell equivalent: gnsspq convert <input> -o ./example_2_db --parallel
# ---------------------------------------------------------------------------

def example_parallel():
    """Force the parallel writer regardless of file size."""
    setup_logging(logging.INFO)
    run_convert(INPUT_FILE, "./example_2_db", parallel=True)


# ---------------------------------------------------------------------------
# Example 3 — invoke the CLI entry point directly (mirrors the shell command)
# Shell equivalent: gnsspq convert <input> -o ./example_3_db --no-parallel
# ---------------------------------------------------------------------------

def example_via_cli_entrypoint():
    """Call the CLI main() the same way the installed nov_gnsspq command does."""
    convert_main([INPUT_FILE, "-o", "./example_3_db", "--no-parallel"])


if __name__ == "__main__":
    example_via_cli_entrypoint()
