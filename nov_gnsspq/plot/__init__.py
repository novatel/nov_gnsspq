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

Plot functions for nov_gnsspq - requires the nov_gnsspq[plot] optional
dependency.
"""

from nov_gnsspq.plot.accuracy import accuracy, accuracy_interactive
from nov_gnsspq.plot.attitude_accuracy import (attitude_accuracy,
                                               attitude_accuracy_interactive)
from nov_gnsspq.plot.imu import imu, imu_interactive
from nov_gnsspq.plot.position import position, position_interactive
from nov_gnsspq.plot.position_accuracy import (position_accuracy,
                                               position_accuracy_interactive)
from nov_gnsspq.plot.satellite_stats import (satellite_stats,
                                             satellite_stats_interactive)
from nov_gnsspq.plot.signal import signal, signal_interactive
from nov_gnsspq.plot.skyview import skyview, skyview_interactive
from nov_gnsspq.plot.tracking import tracking, tracking_interactive

__all__ = [
    "accuracy",
    "accuracy_interactive",
    "attitude_accuracy",
    "attitude_accuracy_interactive",
    "imu",
    "imu_interactive",
    "position",
    "position_interactive",
    "position_accuracy",
    "position_accuracy_interactive",
    "satellite_stats",
    "satellite_stats_interactive",
    "signal",
    "signal_interactive",
    "skyview",
    "skyview_interactive",
    "tracking",
    "tracking_interactive",
]
