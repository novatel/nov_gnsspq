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

Package initialization for nov_gnsspq.writer.
"""
from nov_gnsspq.writer.parallel import ParallelGPSWriter
from nov_gnsspq.writer.parallel.edie import WorkerResult
from nov_gnsspq.writer.parallel.engine import ParallelFileEngine
from nov_gnsspq.writer.parallel.protocols import (BoundarySplitter,
                                                  ChunkProcessor, ResultMerger)
from nov_gnsspq.writer.standard import GPSWriter

__all__ = [
    "BoundarySplitter",
    "ChunkProcessor",
    "GPSWriter",
    "ParallelFileEngine",
    "ParallelGPSWriter",
    "ResultMerger",
    "WorkerResult",
]
