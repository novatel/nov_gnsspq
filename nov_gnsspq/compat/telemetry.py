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

Tracing setup, resolved through the ``nov_gnsspq.plugins`` entry point group.

A provider may register ``telemetry`` and ``auto_span`` to supply real
tracing. With no provider installed the defaults below are inert: no tracer
is created, no span is opened, and no data is collected or transmitted.
"""

from nov_gnsspq.compat import load_plugin


class _NoOpTelemetry:
    """Inert default used when no telemetry provider is registered."""

    def initialize_telemetry(self, service_name: str) -> None:
        """Accepts the service name and does nothing."""

    def get_tracer(self, name: str) -> None:
        """Returns ``None``; no tracer is created."""
        return None


def _no_op_auto_span(tracer):
    """Inert default decorator factory.

    Args:
        tracer: Ignored.

    Returns:
        A decorator that returns the function it is given, unchanged.
    """
    def decorator(fn):
        return fn
    return decorator


telemetry = load_plugin("telemetry", _NoOpTelemetry())
start_as_auto_span = load_plugin("auto_span", _no_op_auto_span)
