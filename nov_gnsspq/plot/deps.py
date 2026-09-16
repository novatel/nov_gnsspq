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

Shared dependency guards for the nov_gnsspq plot subpackage.
"""


def require_matplotlib():
    """Raise ImportError if matplotlib is not installed.

    Raises:
        ImportError: If ``matplotlib`` is not installed.
            Install with ``pip install nov_gnsspq[plot]``.
    """
    try:
        import matplotlib
    except ImportError as exc:
        raise ImportError(
            "nov_gnsspq plot support requires matplotlib. "
            "Install with: pip install nov_gnsspq[plot]"
        ) from exc


def require_plotly():
    """Raise ImportError if plotly is not installed.

    Raises:
        ImportError: If ``plotly`` is not installed.
            Install with ``pip install nov_gnsspq[plot]``.
    """
    try:
        import plotly
    except ImportError as exc:
        raise ImportError(
            "Interactive plots require plotly. "
            "Install with: pip install nov_gnsspq[plot]"
        ) from exc
