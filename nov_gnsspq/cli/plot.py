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

CLI subcommand for generating plots from a nov_gnsspq Parquet database.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
from collections.abc import Callable
from pathlib import Path

from nov_gnsspq.compat.telemetry import start_as_auto_span, telemetry

import nov_gnsspq
from nov_gnsspq import setup_logging
from nov_gnsspq.cli.banner import PlotBannerInfo, print_plot_banner
from nov_gnsspq.plot.deps import require_matplotlib, require_plotly
from nov_gnsspq.reader.frontend import PqReader

log = logging.getLogger("nov_gnsspq.cli.plot")
tracer = telemetry.get_tracer(__name__)

_PLOT_REGISTRY: dict[str, tuple[str, str]] = {
    "accuracy": (
        "nov_gnsspq.plot.accuracy",
        "accuracy",
    ),
    "attitude_accuracy": (
        "nov_gnsspq.plot.attitude_accuracy",
        "attitude_accuracy",
    ),
    "imu": (
        "nov_gnsspq.plot.imu",
        "imu",
    ),
    "position": (
        "nov_gnsspq.plot.position",
        "position",
    ),
    "position_accuracy": (
        "nov_gnsspq.plot.position_accuracy",
        "position_accuracy",
    ),
    "satellite_stats": (
        "nov_gnsspq.plot.satellite_stats",
        "satellite_stats",
    ),
    "signal": (
        "nov_gnsspq.plot.signal",
        "signal",
    ),
    "skyview": (
        "nov_gnsspq.plot.skyview",
        "skyview",
    ),
    "tracking": (
        "nov_gnsspq.plot.tracking",
        "tracking",
    ),
}

_INTERACTIVE_REGISTRY: dict[str, tuple[str, str]] = {
    "accuracy": (
        "nov_gnsspq.plot.accuracy",
        "accuracy_interactive",
    ),
    "attitude_accuracy": (
        "nov_gnsspq.plot.attitude_accuracy",
        "attitude_accuracy_interactive",
    ),
    "imu": (
        "nov_gnsspq.plot.imu",
        "imu_interactive",
    ),
    "position": (
        "nov_gnsspq.plot.position",
        "position_interactive",
    ),
    "position_accuracy": (
        "nov_gnsspq.plot.position_accuracy",
        "position_accuracy_interactive",
    ),
    "satellite_stats": (
        "nov_gnsspq.plot.satellite_stats",
        "satellite_stats_interactive",
    ),
    "signal": (
        "nov_gnsspq.plot.signal",
        "signal_interactive",
    ),
    "skyview": (
        "nov_gnsspq.plot.skyview",
        "skyview_interactive",
    ),
    "tracking": (
        "nov_gnsspq.plot.tracking",
        "tracking_interactive",
    ),
}

_ALL_PLOTS: list[str] = [
    "position",
    "accuracy",
    "signal",
    "tracking",
    "satellite_stats",
    "skyview",
    "position_accuracy",
    "attitude_accuracy",
    "imu",
]


def _load_plot_fn(name: str) -> Callable:
    """Lazily import and return the named matplotlib plot function.

    Args:
        name: A key from _PLOT_REGISTRY.

    Returns:
        The callable plot function.
    """
    module_name, fn_name = _PLOT_REGISTRY[name]
    module = importlib.import_module(module_name)
    return getattr(module, fn_name)


def _load_interactive_fn(name: str) -> Callable:
    """Lazily import and return the named interactive plot function.

    Args:
        name: A key from _INTERACTIVE_REGISTRY.

    Returns:
        The callable interactive plot function.
    """
    module_name, fn_name = _INTERACTIVE_REGISTRY[name]
    module = importlib.import_module(module_name)
    return getattr(module, fn_name)


@start_as_auto_span(tracer=tracer)
def run_plot(
        db_path: str | Path,
        plots: list[str] | None = None,
        out_dir: str | Path | None = None,
        html: bool = False,
        osm: bool = False) -> dict[str, Exception]:
    """Generate plots from a nov_gnsspq Parquet database.

    When *html* is True, all plots are rendered as interactive Plotly
    figures and combined into a single tabbed HTML dashboard.  When
    *out_dir* is set the dashboard is written to
    ``<out_dir>/dashboard.html``; otherwise it is opened in the default
    browser via a temporary file.  Plots that return ``None`` (e.g.
    because their required log is absent) are silently skipped from the
    dashboard.

    When *html* is False, each plot is saved as a PNG in *out_dir*, or
    shown via ``plt.show()`` when *out_dir* is None.

    Args:
        db_path: Path to the nov_gnsspq Parquet database directory.
        plots: Plot names to generate.  When None, all registered plots
            are attempted.
        out_dir: Directory to save output files into.  When None,
            figures are shown or opened interactively.
        html: When True, render interactive Plotly figures and produce
            a single tabbed HTML dashboard.
        osm: When True, overlay OpenStreetMap tiles on the position
            scatter (matplotlib path only; ignored when html=True).
            Requires ``contextily`` to be installed.

    Returns:
        failures: A dict mapping plot name to the exception raised for
            every plot that failed.  An empty dict means all plots
            succeeded.

    Raises:
        ImportError: If required plot dependencies are not installed.
    """
    requested = plots if plots is not None else _ALL_PLOTS
    db = PqReader(str(db_path))

    save_dir: Path | None = None
    if out_dir is not None:
        save_dir = Path(out_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

    failures: dict[str, Exception] = {}

    if html:
        require_plotly()
        from nov_gnsspq.plot.dashboard import build_tabbed_html

        figs = {}
        for name in requested:
            try:
                kwargs = {"osm": osm} if name == "position" else {}
                fig = _load_interactive_fn(name)(db, **kwargs)
                if fig is not None:
                    figs[name] = fig
            except Exception as exc:  # pylint: disable=broad-exception-caught
                failures[name] = exc

        if figs:
            html_content = build_tabbed_html(figs)
            if save_dir is not None:
                (save_dir / "dashboard.html").write_text(
                    html_content, encoding="utf-8"
                )
            else:
                import tempfile
                import webbrowser
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".html",
                    delete=False,
                    encoding="utf-8",
                ) as tmp:
                    tmp.write(html_content)
                    webbrowser.open(f"file://{tmp.name}")

        return failures

    # Matplotlib path
    require_matplotlib()
    import matplotlib.pyplot as plt

    for name in requested:
        try:
            kwargs = {"osm": osm} if name == "position" else {}
            fig = _load_plot_fn(name)(db, plot=False, **kwargs)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            failures[name] = exc
            continue

        if fig is None:
            continue

        if save_dir is not None:
            fig.savefig(
                save_dir / f"{name}.png",
                dpi=150,
                bbox_inches="tight",
            )
            plt.close(fig)
        else:
            plt.show()
            plt.close(fig)

    return failures


class _BannerHelpAction(argparse.Action):
    """Custom --help action that prints the plot banner first."""

    def __init__(
            self,
            option_strings: list[str],
            dest: str = argparse.SUPPRESS,
            default: str = argparse.SUPPRESS,
            help: str | None = None):
        """Initializes _BannerHelpAction.

        Args:
            option_strings: List of option strings (e.g. ['-h', '--help']).
            dest: Destination attribute name on the namespace.
            default: Default value for the action.
            help: Help string for the action.
        """
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            default=default,
            nargs=0,
            help=help,
        )

    def __call__(
            self,
            parser: argparse.ArgumentParser,
            namespace: argparse.Namespace,
            values: list | str,
            option_string: str | None = None):
        """Prints the plot banner then the standard help text and exits.

        Args:
            parser: The ArgumentParser instance.
            namespace: The namespace object being populated.
            values: Argument values (empty for nargs=0).
            option_string: The option string that triggered this action.
        """
        print_plot_banner(PlotBannerInfo(
            plots=_ALL_PLOTS,
            out_dir=None,
            html=False,
            nov_gnsspq_version=nov_gnsspq.__version__,
        ))
        parser.print_help()
        parser.exit()


@start_as_auto_span(tracer=tracer)
def main(argv: list[str] | None = None):
    """CLI entry point for ``nov_gnsspq plot``."""
    parser = argparse.ArgumentParser(
        prog="gnsspq plot",
        description=(
            "Generate plots from a nov_gnsspq Parquet database.\n\n"
            "By default every available plot is attempted; use --plot "
            "to restrict to specific ones.  Pass --html to render "
            "interactive Plotly figures in a single tabbed dashboard "
            "instead of static PNG files."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
        epilog=(
            "available plots:\n"
            + "\n".join(f"  {p}" for p in _ALL_PLOTS)
            + "\n\nexamples:\n"
            "  gnsspq plot ./my_db\n"
            "  gnsspq plot ./my_db --plot position accuracy\n"
            "  gnsspq plot ./my_db --html\n"
            "  gnsspq plot ./my_db --html --out ./figures\n"
            "  gnsspq plot ./my_db --plot signal skyview --out ./figures\n"
        ),
    )
    parser.add_argument(
        "-h", "--help",
        action=_BannerHelpAction,
        help="show this help message and exit",
    )
    parser.add_argument(
        "db",
        metavar="DB_DIR",
        help="nov_gnsspq Parquet database directory",
    )
    parser.add_argument(
        "--plot",
        metavar="NAME",
        nargs="+",
        choices=_ALL_PLOTS,
        dest="plots",
        help=(
            "one or more plot names to generate "
            "(default: all available)"
        ),
    )
    parser.add_argument(
        "--out",
        metavar="DIR",
        dest="out_dir",
        help=(
            "directory to save output files into; "
            "omit to show plots interactively"
        ),
    )
    parser.add_argument(
        "--html",
        action="store_true",
        default=False,
        help=(
            "render interactive Plotly figures; "
            "produces a single dashboard.html when --out is set"
        ),
    )
    parser.add_argument(
        "--osm",
        action="store_true",
        default=False,
        help=(
            "overlay OpenStreetMap tiles on the position scatter "
            "(matplotlib only; requires contextily)"
        ),
    )

    setup_logging()
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.is_dir():
        parser.error(f"database directory not found: {args.db}")

    requested_plots = args.plots or _ALL_PLOTS
    print_plot_banner(PlotBannerInfo(
        plots=requested_plots,
        out_dir=Path(args.out_dir) if args.out_dir else None,
        html=args.html,
        nov_gnsspq_version=nov_gnsspq.__version__,
    ))

    try:
        failures = run_plot(
            db_path=db_path,
            plots=args.plots,
            out_dir=args.out_dir,
            html=args.html,
            osm=args.osm,
        )
    except ImportError as exc:
        print(f"gnsspq plot: {exc}", file=sys.stderr)
        sys.exit(1)

    if failures:
        for name, exc in failures.items():
            log.warning("'%s' skipped — %s: %s", name, type(exc).__name__, exc)

    if args.out_dir:
        saved = [p for p in requested_plots if p not in failures]
        out_path = Path(args.out_dir)
        if args.html and saved:
            print(
                f"  saved {out_path / 'dashboard.html'} "
                f"({', '.join(saved)})"
            )
        elif not args.html:
            for name in saved:
                print(f"  saved {out_path / f'{name}.png'}")

    if args.plots and len(failures) == len(requested_plots):
        sys.exit(1)
