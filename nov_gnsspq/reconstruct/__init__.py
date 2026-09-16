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

Package initialization for nov_gnsspq.reconstruct.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal, overload

log = logging.getLogger(__name__)

from nov_gnsspq.reconstruct.builder import reconstruct
from nov_gnsspq.reconstruct.comparator import (compare_binary,
                                               compare_field_level)
from nov_gnsspq.reconstruct.report import (print_console_summary,
                                           write_html_report)
from nov_gnsspq.reconstruct.types import (BothResults, FieldDiff, TypeResult,
                                          VerificationResult)


@overload
def verify(
        db_path: str | Path,
        original_gps: str | Path,
        *,
        mode: Literal["field"],
        output_gps: str | Path | None = ...,
        report: str | Path | None = ...,
        float_tol: float = ...,
        no_report: bool = ...,
        use_expected_ascii_rounding: bool = ...) -> VerificationResult: ...


@overload
def verify(
        db_path: str | Path,
        original_gps: str | Path,
        *,
        mode: Literal["binary"],
        output_gps: str | Path | None = ...,
        report: str | Path | None = ...,
        float_tol: float = ...,
        no_report: bool = ...,
        use_expected_ascii_rounding: bool = ...) -> VerificationResult: ...


@overload
def verify(
        db_path: str | Path,
        original_gps: str | Path,
        *,
        mode: Literal["both"] = ...,
        output_gps: str | Path | None = ...,
        report: str | Path | None = ...,
        float_tol: float = ...,
        no_report: bool = ...,
        use_expected_ascii_rounding: bool = ...) -> BothResults: ...


def verify(
        db_path: str | Path,
        original_gps: str | Path,
        *,
        mode: str = "both",
        output_gps: str | Path | None = None,
        report: str | Path | None = None,
        float_tol: float = 1e-9,
        no_report: bool = False,
        log_types: set[str] | None = None,
        use_expected_ascii_rounding: bool = False
        ) -> VerificationResult | BothResults:
    """Reconstruct a GPS file from a database and verify it against the original.

    Args:
        db_path: Path to the nov_gnsspq database directory.
        original_gps: Path to the original GPS file to compare against.
        mode: Comparison mode -- ``"field"`` compares decoded field values,
            ``"binary"`` compares byte-by-byte with float tolerance,
            ``"both"`` (default) runs both and returns a BothResults.
        output_gps: Path for the reconstructed GPS output file. Defaults
            to ``reconstructed.GPS`` in the current working directory.
        report: Path for the HTML report output. Defaults to
            ``reconstruction_report.html`` in the current working directory.
        float_tol: Floating-point tolerance for numeric comparisons.
        no_report: If True, suppresses HTML report generation.
        log_types: If provided, only messages of those types are compared.
        use_expected_ascii_rounding: If True, types whose only diffs are
            expected ASCII-format rounding are treated as VERIFIED. Diffs
            are still shown in the HTML report.

    Returns:
        result: A VerificationResult for ``"field"`` or ``"binary"`` mode,
            or a BothResults for ``"both"`` mode.
    """
    db_path = Path(db_path)
    original_gps = Path(original_gps)

    if output_gps is None:
        output_gps = Path.cwd() / "reconstructed.GPS"
    output_gps = Path(output_gps)

    if report is None:
        report = Path.cwd() / "reconstruction_report.html"
    report = Path(report)

    log.info("Reconstructing GPS file from database...")
    reconstruct(db_path, output_gps)

    if mode == "field":
        log.info("Comparing messages (field level)...")
        result = compare_field_level(
            original_gps, output_gps, float_tol,
            log_types=log_types,
            use_expected_ascii_rounding=use_expected_ascii_rounding,
        )
        print_console_summary(result, db_path)
        if not no_report:
            log.info("Writing HTML report...")
            write_html_report(
                result, report, mode="field", float_tol=float_tol,
            )
            log.info("HTML report: %s", report)
        return result

    if mode == "binary":
        log.info("Comparing messages (binary)...")
        result = compare_binary(
            original_gps, output_gps, float_tol,
            log_types=log_types,
            use_expected_ascii_rounding=use_expected_ascii_rounding,
        )
        print_console_summary(result, db_path)
        if not no_report:
            log.info("Writing HTML report...")
            write_html_report(
                result, report, mode="binary", float_tol=float_tol,
            )
            log.info("HTML report: %s", report)
        return result

    # mode == "both"
    log.info("Comparing messages (field level)...")
    field_result = compare_field_level(
        original_gps, output_gps, float_tol,
        log_types=log_types,
        use_expected_ascii_rounding=use_expected_ascii_rounding,
    )
    log.info("Comparing messages (binary)...")
    binary_result = compare_binary(
        original_gps, output_gps, float_tol,
        log_types=log_types,
        use_expected_ascii_rounding=use_expected_ascii_rounding,
    )

    for _, res in (("field", field_result), ("binary", binary_result)):
        print_console_summary(res, db_path)

    if not no_report:
        field_report = (
            report.parent / (report.stem + "_field" + report.suffix)
        )
        binary_report = (
            report.parent / (report.stem + "_binary" + report.suffix)
        )
        log.info("Writing HTML reports...")
        write_html_report(
            field_result, field_report, mode="field", float_tol=float_tol,
        )
        write_html_report(
            binary_result, binary_report,
            mode="binary", float_tol=float_tol,
        )
        log.info("HTML reports: %s, %s", field_report, binary_report)

    return BothResults(field=field_result, binary=binary_result)


__all__ = [
    "reconstruct",
    "verify",
    "VerificationResult",
    "TypeResult",
    "FieldDiff",
    "BothResults",
    "compare_field_level",
    "compare_binary",
]
