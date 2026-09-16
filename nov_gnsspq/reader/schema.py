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

Schema constants and version metadata for the GNSS PQ reader.
"""

from __future__ import annotations

SCHEMA_VERSION: str = "1"
WRITER_VERSION: str = "1.0.0"

# ---- column names -----------------------------------------------------------
HEADER_PREFIX: str = "header_"
SEQUENCE_ID_COL: str = "sequence_id"
PARENT_ID_COL: str = "parent_id"
TIME_COLUMNS: list[str] = ["header_week", "header_milliseconds"]

# ---- metadata file ----------------------------------------------------------
METADATA_FILENAME: str = "_metadata.json"
