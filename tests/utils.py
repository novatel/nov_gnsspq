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

Utility helpers for resolving paths to GPS test resource files.

Test-suite scaffolding. This is deliberately outside the installed
``nov_gnsspq`` package so that the published distribution carries no
dependency on the test recordings.
"""

import os

RESOURCE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "resources")
)


def resource(filename: str) -> str:
    """Returns the absolute filepath for a resource file by name.

    Args:
        filename: Name of the file within the GPS test resources directory.

    Returns:
        path: Absolute path to the requested resource file.
    """
    return os.path.join(RESOURCE_DIR, filename)
