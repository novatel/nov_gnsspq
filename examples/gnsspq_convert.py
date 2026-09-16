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
import logging
import sys
from time import perf_counter

from nov_gnsspq import setup_logging
from nov_gnsspq.cli.convert import run_convert

if __name__ == "__main__":
    setup_logging(logging.DEBUG)

    # Usage: python gnsspq_convert.py [recording.GPS] [output_dir]
    input_file = sys.argv[1] if len(sys.argv) > 1 else "recording.GPS"
    output_folder = sys.argv[2] if len(sys.argv) > 2 else "./converted_db"

    start_time = perf_counter()
    run_convert(input_file, output_folder, parallel=True, zip_output=True)
    end_time = perf_counter()
    print(f"Time taken: {end_time - start_time:.4f} seconds")
