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

Tests that the nov_gnsspq plugin seam ships inert and opt-in.
"""

from unittest import mock

import pytest

from nov_gnsspq import compat
from nov_gnsspq.compat import gpstime as compat_gpstime
from nov_gnsspq.compat import telemetry as compat_telemetry


@pytest.fixture(autouse=True)
def _restore_optin():
    """Leaves discovery opted out however a test finishes."""
    yield
    compat.enable_plugins(False)


class TestDiscoveryIsOptOutByDefault:
    """Tests that a default install resolves no providers."""

    def test_plugins_disabled_by_default(self):
        """Tests discovery is off unless a caller opts in."""
        assert compat.plugins_enabled() is False

    def test_load_plugin_returns_default(self):
        """Tests load_plugin hands back the caller's default verbatim."""
        sentinel = object()
        assert compat.load_plugin("telemetry", sentinel) is sentinel

    def test_no_metadata_read_while_opted_out(self):
        """Tests no installed-distribution metadata is scanned when opted out.

        This is the supply-chain guarantee: a third party registering the
        entry point gets no code execution during ``import nov_gnsspq``.
        """
        compat.enable_plugins(False)
        with mock.patch.object(compat, "entry_points") as fake:
            assert compat.load_plugin("telemetry", "default") == "default"
        fake.assert_not_called()


class TestTelemetrySeamIsInert:
    """Tests the shipped telemetry defaults collect and transmit nothing."""

    def test_telemetry_is_the_in_repo_noop(self):
        """Tests the telemetry object is this package's own no-op."""
        assert isinstance(compat_telemetry.telemetry,
                          compat_telemetry._NoOpTelemetry)

    def test_get_tracer_returns_none(self):
        """Tests no tracer is created."""
        assert compat_telemetry.telemetry.get_tracer(__name__) is None

    def test_initialize_telemetry_does_nothing(self):
        """Tests initialization is a no-op and returns None."""
        assert compat_telemetry.telemetry.initialize_telemetry("svc") is None

    def test_auto_span_returns_function_unchanged(self):
        """Tests the decorator adds no wrapper, so calls are untouched."""
        def fn():
            return "value"

        decorated = compat_telemetry.start_as_auto_span(tracer=None)(fn)
        assert decorated is fn
        assert not hasattr(decorated, "__wrapped__")
        assert decorated() == "value"

    def test_package_import_does_not_initialize_telemetry(self):
        """Tests importing the package does not initialize a provider."""
        import nov_gnsspq

        assert not hasattr(nov_gnsspq, "telemetry")


class TestGpsTimeSeamIsInert:
    """Tests the gpstime shim falls back to the in-repo implementation."""

    def test_gpstime_is_the_in_repo_default(self):
        """Tests GPSTime resolves to this package's own class."""
        assert compat_gpstime.GPSTime is compat_gpstime._DefaultGPSTime


class TestOptInStillResolvesProviders:
    """Tests the seam remains functional for a caller that opts in."""

    def test_enable_plugins_allows_resolution(self):
        """Tests an opted-in caller resolves a registered provider."""
        provider = object()
        fake_ep = mock.Mock()
        fake_ep.name = "telemetry"
        fake_ep.load.return_value = provider

        compat.enable_plugins(True)
        with mock.patch.object(compat, "entry_points", return_value=[fake_ep]):
            assert compat.load_plugin("telemetry", "default") is provider

    def test_enable_plugins_can_be_reversed(self):
        """Tests opting back out stops resolution again."""
        compat.enable_plugins(True)
        compat.enable_plugins(False)
        assert compat.plugins_enabled() is False
        assert compat.load_plugin("telemetry", "default") == "default"
