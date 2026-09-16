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

Functionality to use GPS time weeks and seconds.

``GPSTime`` is resolved through the ``nov_gnsspq.plugins`` entry point group:
a provider may register ``gpstime`` to supply its own implementation, and the
implementation below is used when none is registered. Always import
``GPSTime`` from this module rather than from a provider, so that the class
used in ``isinstance`` checks is the one this package resolved.
"""

import datetime

from nov_gnsspq.compat import load_plugin

_GPS_EPOCH = datetime.datetime(1980, 1, 6, tzinfo=datetime.timezone.utc)
_SECONDS_PER_WEEK = 604800

# GPS time does not observe leap seconds, so it has run a fixed number of
# seconds ahead of UTC since each leap second insertion below. Source:
# IERS Bulletin C. No leap second has been inserted since 2017-01-01, so
# the offset has been a constant 18 seconds since then.
_LEAP_SECOND_OFFSETS = [
    (datetime.datetime(1981, 7, 1, tzinfo=datetime.timezone.utc), 1),
    (datetime.datetime(1982, 7, 1, tzinfo=datetime.timezone.utc), 2),
    (datetime.datetime(1983, 7, 1, tzinfo=datetime.timezone.utc), 3),
    (datetime.datetime(1985, 7, 1, tzinfo=datetime.timezone.utc), 4),
    (datetime.datetime(1988, 1, 1, tzinfo=datetime.timezone.utc), 5),
    (datetime.datetime(1990, 1, 1, tzinfo=datetime.timezone.utc), 6),
    (datetime.datetime(1991, 1, 1, tzinfo=datetime.timezone.utc), 7),
    (datetime.datetime(1992, 7, 1, tzinfo=datetime.timezone.utc), 8),
    (datetime.datetime(1993, 7, 1, tzinfo=datetime.timezone.utc), 9),
    (datetime.datetime(1994, 7, 1, tzinfo=datetime.timezone.utc), 10),
    (datetime.datetime(1996, 1, 1, tzinfo=datetime.timezone.utc), 11),
    (datetime.datetime(1997, 7, 1, tzinfo=datetime.timezone.utc), 12),
    (datetime.datetime(1999, 1, 1, tzinfo=datetime.timezone.utc), 13),
    (datetime.datetime(2006, 1, 1, tzinfo=datetime.timezone.utc), 14),
    (datetime.datetime(2009, 1, 1, tzinfo=datetime.timezone.utc), 15),
    (datetime.datetime(2012, 7, 1, tzinfo=datetime.timezone.utc), 16),
    (datetime.datetime(2015, 7, 1, tzinfo=datetime.timezone.utc), 17),
    (datetime.datetime(2017, 1, 1, tzinfo=datetime.timezone.utc), 18),
]


def _gps_utc_offset(dt: datetime.datetime) -> int:
    offset = 0
    for leap_dt, leap_offset in _LEAP_SECOND_OFFSETS:
        if dt >= leap_dt:
            offset = leap_offset
    return offset


class _DefaultGPSTime:
    """Default GPS time implementation.

    Supports GPSTime(seconds, week) and GPSTime(datetime); exposes
    .week and .seconds, matching the surface nov_gnsspq relies on.
    """

    def __init__(self, seconds, week=None):
        if week is None:
            dt = seconds
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            elapsed = (
                dt - _GPS_EPOCH
                + datetime.timedelta(seconds=_gps_utc_offset(dt))
            ).total_seconds()
            self.week, self.seconds = divmod(elapsed, _SECONDS_PER_WEEK)
            self.week = int(self.week)
        else:
            self.week = week
            self.seconds = seconds

    def __repr__(self):
        return f"GPSTime(seconds={self.seconds!r}, week={self.week!r})"


GPSTime = load_plugin("gpstime", _DefaultGPSTime)
