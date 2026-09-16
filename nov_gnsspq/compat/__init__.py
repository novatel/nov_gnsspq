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

Plugin resolution for the optional pieces of this package.

Providers register objects under the ``nov_gnsspq.plugins`` entry point
group. Each module in this subpackage asks for one by name and supplies a
working default, so the package installs and runs with no provider present.

Discovery is **opt-in**. Unless :func:`enable_plugins` has been called,
:func:`load_plugin` returns the caller's default without reading installed
distribution metadata, so importing ``nov_gnsspq`` never executes
third-party code. A host application that wants provider support calls
:func:`enable_plugins` before importing the rest of the package::

    from nov_gnsspq.compat import enable_plugins
    enable_plugins()

    import nov_gnsspq

Defaults are bound when each shim module is first imported, so an
:func:`enable_plugins` call made afterwards has no effect on names that are
already resolved.
"""

import functools
from importlib.metadata import entry_points
from typing import Any

#: Entry point group that providers register under.
PLUGIN_GROUP = "nov_gnsspq.plugins"


#: Set by :func:`enable_plugins`. While false, no metadata is read and no
#: provider code is imported.
_enabled = False


def enable_plugins(enabled: bool = True) -> None:
    """Opts in to (or out of) provider discovery.

    Call this before importing the rest of ``nov_gnsspq`` if a provider
    distribution should be allowed to supply implementations. Loading a
    provider imports third-party code, which is why it is never done
    implicitly.

    Args:
        enabled: True to allow discovery, False to disable it again.
    """
    global _enabled  # pylint: disable=global-statement
    _enabled = enabled
    _discover.cache_clear()


def plugins_enabled() -> bool:
    """Reports whether provider discovery is currently opted in.

    Returns:
        True if :func:`enable_plugins` has enabled discovery.
    """
    return _enabled


@functools.lru_cache(maxsize=None)
def _discover() -> dict:
    """Maps entry point name to entry point for the plugin group.

    Scanning installed distribution metadata is the expensive part of
    resolution, so it is done once per process and cached.

    Returns:
        Entry points in :data:`PLUGIN_GROUP`, keyed by name. Empty while
        discovery is not opted in.
    """
    if not _enabled:
        return {}
    return {ep.name: ep for ep in entry_points(group=PLUGIN_GROUP)}


def load_plugin(name: str, default: Any) -> Any:
    """Loads the object registered under ``name``, or returns ``default``.

    Returns ``default`` unmodified unless :func:`enable_plugins` has opted
    in to discovery.

    Args:
        name: Entry point name within :data:`PLUGIN_GROUP`.
        default: Object to use when no provider registered ``name``.

    Returns:
        The object loaded from the entry point, or ``default``.
    """
    entry_point = _discover().get(name)
    return default if entry_point is None else entry_point.load()
