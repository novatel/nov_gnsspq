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

Renders console and HTML reports from a VerificationResult.
"""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path
from typing import TextIO

from nov_gnsspq.reconstruct.types import FieldDiff, VerificationResult

_SEP = "-" * 50

_CATEGORIES = {
    "negligible": {
        "label": "Negligible",
        "short": "Negligible",
        "bg": "#e8f5e9",
        "fg": "#1b5e20",
        "border": "#a5d6a7",
        "description": (
            "Relative error &lt;&nbsp;0.1&nbsp;ppm. Rounds off in any "
            "practical use. Caused by floating-point arithmetic in the "
            "ASCII encode/decode path."
        ),
    },
    "ascii_truncation": {
        "label": "ASCII truncation",
        "short": "ASCII truncation",
        "bg": "#fff8e1",
        "fg": "#e65100",
        "border": "#ffe082",
        "description": (
            "EDIE&apos;s <code>to_ascii()</code> writes floats with a "
            "fixed number of decimal places or significant figures. "
            "NovAtel binary fields are often stored as 4-byte "
            "IEEE&nbsp;754 floats, so after ASCII round-trip the stored "
            "value is <code>float32(round(orig,&nbsp;N))</code>. "
            "This is an inherent ASCII-format limitation -- "
            "<strong>not data loss</strong> in the parquet."
        ),
    },
    "non_float": {
        "label": "Non-float mismatch",
        "short": "Non-float",
        "bg": "#fce4ec",
        "fg": "#880e4f",
        "border": "#f48fb1",
        "description": (
            "An integer, enum, or string field has a different value "
            "between the original and reconstructed GPS. "
            "<strong>Requires investigation</strong> -- this may indicate "
            "a parquet write or reconstruction bug."
        ),
    },
    "large_error": {
        "label": "Large relative error",
        "short": "Large error",
        "bg": "#fce4ec",
        "fg": "#b71c1c",
        "border": "#ef9a9a",
        "description": (
            "Float relative error &ge;&nbsp;1&times;10<sup>&minus;5</sup>"
            " and not explained by EDIE&apos;s ASCII encoding rules. "
            "<strong>Requires investigation</strong> -- this may indicate "
            "precision loss or an encoding bug."
        ),
    },
}


def _analyze_diff(d: FieldDiff) -> str:
    """Returns a plain-English explanation for a float field difference.

    Args:
        d: The FieldDiff to analyze.

    Returns:
        A human-readable string describing the likely cause of the diff.
    """
    if d.relative_error is None:
        return "Exact value mismatch (non-float field)."

    try:
        orig = float(d.original_value)
        recon = float(d.reconstructed_value)
    except (TypeError, ValueError):
        return "Could not analyse (non-numeric value)."

    is_trunc, n_places = _is_ascii_truncation(orig, recon)

    if is_trunc or d.relative_error < 1e-7:
        rounded_str = f"{round(orig, n_places):.{n_places}f}".lstrip("-")
        digits = rounded_str.replace(".", "").lstrip("0")
        sig_figs = len(digits.rstrip("0")) if digits else 1

        if d.relative_error < 1e-7:
            detail = "difference is &lt;&nbsp;0.1&nbsp;ppm, negligible"
        else:
            detail = (
                f"~{sig_figs}&nbsp;significant figure(s) at this magnitude"
            )

        cause = (
            "Float32 field &plus; ASCII rounding"
            if is_trunc and d.relative_error >= 1e-7
            else "ASCII decimal truncation"
        )
        return (
            f"{cause} ({n_places}&nbsp;d.p., {detail}). "
            "EDIE&apos;s to_ascii() writes a fixed number of decimal "
            "places. NovAtel binary stores this field as a 4-byte "
            "IEEE&nbsp;754 float, so the reconstructed value is "
            "float32(ascii_rounded). "
            "Inherent ASCII format limit, not data loss."
        )

    is_sf, sf_n = _is_sigfig_truncation(orig, recon)
    if is_sf or d.relative_error < 1e-5:
        detail = (
            f"EDIE encodes with ~{sf_n}&nbsp;significant figures in "
            f"ASCII (rel.&nbsp;err.&nbsp;{d.relative_error:.2e})"
            if is_sf
            else (
                f"rel.&nbsp;err.&nbsp;{d.relative_error:.2e}, "
                "likely limited decimal places"
            )
        )
        return (
            f"ASCII significant-figure truncation. {detail}. "
            "Inherent ASCII format limit, not data loss."
        )

    return (
        f"Relative error {d.relative_error:.2e}. "
        "Exceeds expected ASCII format limits -- "
        "may require investigation."
    )


def _build_diffs_html(field_diffs: list[FieldDiff]) -> str:
    """Builds the collapsible HTML table of field diffs for one log type.

    Args:
        field_diffs: List of FieldDiff objects for a single log type.

    Returns:
        An HTML string, or an empty string if there are no diffs.
    """
    if not field_diffs:
        return ""

    sorted_diffs = sorted(field_diffs, key=_sort_key)

    counts: dict[str, int] = {}
    for d in sorted_diffs:
        cat = _diff_category(d)
        counts[cat] = counts.get(cat, 0) + 1

    badge_parts = []
    for cat in (
        "large_error", "non_float", "ascii_truncation", "negligible"
    ):
        if cat in counts:
            c = _CATEGORIES[cat]
            badge_parts.append(
                f"<span style='background:{c['bg']};color:{c['fg']};"
                f"border:1px solid {c['border']};border-radius:3px;"
                f"padding:2px 8px;margin-right:6px;font-size:0.9em'>"
                f"{counts[cat]}&nbsp;{c['short']}</span>"
            )
    badges_html = "".join(badge_parts)

    diff_rows = []
    for d in sorted_diffs:
        cat = _diff_category(d)
        c = _CATEGORIES[cat]
        rel_err_str = (
            "N/A" if d.relative_error is None
            else f"{d.relative_error:.2e}"
        )
        diff_rows.append(
            f"<tr style='background:{c['bg']}'>"
            f"<td>{_cat_badge(cat)}</td>"
            f"<td><code>{d.field_name}</code></td>"
            f"<td>{d.original_value}</td>"
            f"<td>{d.reconstructed_value}</td>"
            f"<td style='text-align:right'>{rel_err_str}</td>"
            f"<td style='color:#444;font-size:0.88em'>"
            f"{_analyze_diff(d)}</td>"
            f"</tr>"
        )

    return (
        f"<details><summary>Field diffs ({len(sorted_diffs)})"
        f"&nbsp;&nbsp;{badges_html}</summary>"
        f"<table border='1' style='margin-top:6px;width:100%'>"
        f"<tr><th>Category</th><th>Field</th><th>Original</th>"
        f"<th>Reconstructed</th><th>Rel error</th><th>Analysis</th>"
        f"</tr>"
        f"{''.join(diff_rows)}</table></details>"
    )


def _cat_badge(cat: str) -> str:
    """Renders an inline HTML badge for a diff category.

    Args:
        cat: A key from _CATEGORIES.

    Returns:
        An HTML span string styled with the category colours.
    """
    c = _CATEGORIES[cat]
    return (
        f"<span style='background:{c['bg']};color:{c['fg']};"
        f"border:1px solid {c['border']};border-radius:3px;"
        f"padding:1px 6px;font-size:0.85em;white-space:nowrap'>"
        f"{c['short']}</span>"
    )


def _diff_category(d: FieldDiff) -> str:
    """Classifies a FieldDiff into one of the keys in _CATEGORIES.

    Args:
        d: The FieldDiff to classify.

    Returns:
        A string key present in _CATEGORIES.
    """
    if d.relative_error is None:
        return "non_float"
    try:
        orig = float(d.original_value)
        recon = float(d.reconstructed_value)
    except (TypeError, ValueError):
        return "non_float"

    if d.relative_error < 1e-7:
        return "negligible"

    is_trunc, _ = _is_ascii_truncation(orig, recon)
    if is_trunc:
        return "ascii_truncation"

    is_sf, _ = _is_sigfig_truncation(orig, recon)
    if is_sf:
        return "ascii_truncation"

    if d.relative_error < 1e-5:
        return "ascii_truncation"

    return "large_error"


def _is_ascii_truncation(
        orig: float,
        recon: float) -> tuple[bool, int]:
    """Returns (is_ascii_truncation, decimal_places).

    Tests whether recon equals float32(round(orig, N)) for N in 2..7.
    EDIE's to_ascii() writes floats with a fixed number of decimal
    places. Many NovAtel binary fields are stored as float32, so after
    ASCII round-trip the value is float32(round(orig, N)).

    Args:
        orig: The original float value.
        recon: The reconstructed float value.

    Returns:
        A tuple of (matched, decimal_places). decimal_places is 0 when
        matched is False.
    """
    for n in range(2, 8):
        rounded = round(orig, n)
        try:
            f32 = struct.unpack("f", struct.pack("f", rounded))[0]
        except (struct.error, OverflowError):
            continue
        tol = 1e-12 * max(abs(recon), 1e-10)
        if abs(f32 - recon) < tol:
            return True, n
        if abs(rounded - recon) < tol:
            return True, n
    return False, 0


def _is_sigfig_truncation(
        orig: float,
        recon: float) -> tuple[bool, int]:
    """Returns (is_truncation, sig_figs).

    Tests whether recon matches orig rounded to N significant figures
    for N in 2..7. EDIE writes some fields in scientific notation with
    a small fixed number of significant figures.

    Args:
        orig: The original float value.
        recon: The reconstructed float value.

    Returns:
        A tuple of (matched, sig_figs). sig_figs is 0 when matched is
        False.
    """
    if orig == 0 or recon == 0:
        return False, 0
    mag = math.floor(math.log10(abs(orig)))
    for n in range(2, 8):
        scale = 10 ** (n - 1 - mag)
        rounded = round(orig * scale) / scale
        try:
            f32 = struct.unpack("f", struct.pack("f", rounded))[0]
        except (struct.error, OverflowError):
            f32 = None
        tol = 1e-12 * max(abs(recon), 1e-100)
        if abs(rounded - recon) < tol or (
            f32 is not None and abs(f32 - recon) < tol
        ):
            return True, n
    return False, 0


def _sort_key(d: FieldDiff) -> float:
    """Returns a sort key for FieldDiff ordering.

    Sorts largest relative error first; non-float diffs sort last.

    Args:
        d: The FieldDiff to produce a key for.

    Returns:
        A float sort key.
    """
    if d.relative_error is None:
        return float("inf")
    return -d.relative_error


def _undecodable_section(rows: list[str]) -> str:
    """Renders the collapsible NOT_VERIFIED table at the bottom of the report.

    Args:
        rows: Pre-rendered HTML row strings for undecodable log types.

    Returns:
        An HTML string, or an empty string if rows is empty.
    """
    if not rows:
        return ""
    return (
        f"<details style='margin-top:24px'>"
        f"<summary style='cursor:pointer;font-size:1em;color:#555'>"
        f"<b>Undecodable / Not Verified</b> ({len(rows)} type(s)) -- "
        f"message types EDIE cannot reconstruct; raw bytes stored "
        f"verbatim</summary>"
        f"<p style='color:#666;font-size:0.9em;margin:6px 0 8px'>"
        f"These types were present in the original GPS file but "
        f"the installed novatel-edie build cannot construct them. Their "
        f"raw bytes are preserved in "
        f"<code>unknown_data.parquet</code> for future reconstruction "
        f"when support is added."
        f"</p>"
        f"<table border='1' style='width:100%'>"
        f"<tr><th>Type</th><th>Status</th>"
        f"<th style='text-align:right'>Messages</th>"
        f"<th>Details</th></tr>"
        f"{''.join(rows)}"
        f"</table></details>"
    )


def print_console_summary(
        result: VerificationResult,
        db_path: str | Path,
        stream: TextIO | None = None):
    """Prints a plain-text reconstruction summary to a stream.

    Args:
        result: The VerificationResult to summarise.
        db_path: Path to the database, used in the report heading.
        stream: Output stream; defaults to sys.stdout.
    """
    stream = stream or sys.stdout
    print(f"\nReconstruction report -- {db_path}", file=stream)
    print(_SEP, file=stream)
    for log_type, tr in sorted(result.per_type.items()):
        status_str = tr.status.replace("_", " ")
        reason = f"  ({tr.reason})" if tr.reason else ""
        print(
            f"  {log_type:<20} {tr.message_count:>6} msgs"
            f"   {status_str}{reason}",
            file=stream,
        )
    print(_SEP, file=stream)
    total = result.total_messages

    def pct(n: int) -> str:
        """Returns a percentage string or 'N/A' when total is zero."""
        return f"{100 * n / total:.1f}%" if total else "N/A"

    print(
        f"  Verified:      {result.verified_count:>6} / {total}"
        f"  ({pct(result.verified_count)})",
        file=stream,
    )
    print(
        f"  Not verified:  {result.not_verified_message_count:>6} / {total}"
        f"  ({pct(result.not_verified_message_count)})",
        file=stream,
    )
    print(f"  Mismatches:    {result.mismatch_count:>6}", file=stream)
    if result.recon_decoded_count:
        delta = result.recon_decoded_count - total
        delta_str = (
            f"  ({'+'if delta >= 0 else ''}{delta} vs original)"
            if delta != 0
            else "  (matches original)"
        )
        warning = (
            "  *** COUNT MISMATCH -- possible dropped messages ***"
            if delta < 0 else ""
        )
        print(
            f"  Reconstructed: {result.recon_decoded_count:>6}"
            f" decoded{delta_str}{warning}",
            file=stream,
        )


def write_html_report(
        result: VerificationResult,
        path: str | Path,
        mode: str,
        float_tol: float):
    """Writes a self-contained HTML reconstruction report to disk.

    Args:
        result: The VerificationResult to render.
        path: Destination file path.
        mode: Reconstruction mode string shown in the report header.
        float_tol: Float tolerance used during verification, shown in
            the report header.
    """
    path = Path(path)

    main_rows = []
    undecodable_rows = []
    for log_type, tr in sorted(result.per_type.items()):
        colour = {
            "VERIFIED": "#2e7d32",
            "NOT_VERIFIED": "#757575",
            "MISMATCH": "#b71c1c",
        }.get(tr.status, "#757575")
        status_label = tr.status.replace("_", " ")
        reason_html = (
            f"<br><small style='color:#555'>{tr.reason}</small>"
            if tr.reason else ""
        )
        diffs_html = _build_diffs_html(tr.field_diffs)
        row = (
            f"<tr><td><b>{log_type}</b></td>"
            f"<td style='color:{colour}'>"
            f"<b>{status_label}</b>{reason_html}</td>"
            f"<td style='text-align:right'>{tr.message_count}</td>"
            f"<td>{diffs_html}</td></tr>"
        )
        if tr.status == "NOT_VERIFIED":
            undecodable_rows.append(row)
        else:
            main_rows.append(row)

    all_diffs = [
        d for tr in result.per_type.values() for d in tr.field_diffs
    ]
    global_counts: dict[str, int] = {}
    for d in all_diffs:
        cat = _diff_category(d)
        global_counts[cat] = global_counts.get(cat, 0) + 1

    global_badges = []
    for cat in (
        "large_error", "non_float", "ascii_truncation", "negligible"
    ):
        if cat in global_counts:
            c = _CATEGORIES[cat]
            global_badges.append(
                f"<span style='background:{c['bg']};color:{c['fg']};"
                f"border:1px solid {c['border']};border-radius:4px;"
                f"padding:3px 10px;margin-right:8px'>"
                f"<b>{global_counts[cat]}</b> {c['short']}</span>"
            )

    legend_items = []
    for cat, meta in _CATEGORIES.items():
        legend_items.append(
            f"<div style='margin-bottom:10px'>"
            f"<span style='background:{meta['bg']};color:{meta['fg']};"
            f"border:1px solid {meta['border']};border-radius:3px;"
            f"padding:2px 8px;font-weight:bold'>{meta['label']}</span>"
            f"&nbsp; {meta['description']}"
            f"</div>"
        )

    total = result.total_messages
    recon = result.recon_decoded_count
    count_delta = recon - total if recon else None
    count_ok = count_delta == 0
    count_colour = "#2e7d32" if count_ok else "#b71c1c"
    count_label = (
        "Reconstructed msgs"
        if count_ok
        else "Reconstructed msgs (!)"
    )
    count_note = (
        ""
        if not recon
        else (
            f"<p style='color:{count_colour};margin:4px 0 12px;"
            f"font-weight:bold'>"
            + (
                "&#10003; Reconstructed message count matches original."
                if count_ok
                else f"&#9888; Reconstructed file has {abs(count_delta)}"
                f" fewer messages than the original "
                f"({recon} vs {total}). Some messages may have been "
                f"silently dropped during reconstruction."
            )
            + "</p>"
        )
    )

    def _pct(n: int) -> str:
        """Returns a percentage string or 'N/A' when total is zero."""
        return f"{100 * n / total:.1f}%" if total else "N/A"

    no_main = (
        "<tr><td colspan='4' style='color:#888;text-align:center'>"
        "No verified or mismatched types</td></tr>"
    )
    global_badges_html = (
        f"<p style='margin-bottom:6px'>"
        f"<b>Field diffs by category:</b>&nbsp;&nbsp;"
        f"{''.join(global_badges)}</p>"
        if global_badges else ""
    )
    recon_stat_box = (
        f"  <div class='stat-box'>"
        f"<div class='val' style='color:{count_colour}'>{recon}</div>"
        f"<div class='lbl'>{count_label}</div></div>"
        if recon else ""
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'><title>Reconstruction Report</title>
<style>
  body{{font-family:system-ui,sans-serif;margin:2em;font-size:14px;\
color:#222;max-width:1400px}}
  h1{{margin-bottom:4px}}
  table{{border-collapse:collapse;width:100%}}
  td,th{{padding:6px 12px;vertical-align:top}}
  details>table td{{padding:4px 8px}}
  th{{background:#f5f5f5;text-align:left}}
  .legend{{background:#fafafa;border:1px solid #ddd;border-radius:6px;\
padding:16px;margin-bottom:20px}}
  .stats{{display:flex;gap:20px;margin:12px 0}}
  .stat-box{{background:#f5f5f5;border-radius:6px;padding:10px 18px;\
min-width:120px;text-align:center}}
  .stat-box .val{{font-size:1.6em;font-weight:bold}}
  .stat-box .lbl{{font-size:0.85em;color:#555}}
  summary{{cursor:pointer;padding:4px 0}}
  code{{font-family:monospace;font-size:0.95em}}
</style>
</head><body>
<h1>Reconstruction Report</h1>
<p style='color:#555;margin:2px 0'>\
<b>Mode:</b> {mode}&nbsp;&nbsp; \
<b>Float tolerance:</b> {float_tol}</p>

<div class='stats'>
  <div class='stat-box'>
    <div class='val' style='color:#2e7d32'>{result.verified_count}</div>
    <div class='lbl'>Verified types</div>
  </div>
  <div class='stat-box'>
    <div class='val' style='color:#757575'>\
{result.not_verified_message_count}</div>
    <div class='lbl'>Not-verified msgs</div>
  </div>
  <div class='stat-box'>
    <div class='val' style='color:#b71c1c'>{result.mismatch_count}</div>
    <div class='lbl'>Mismatch types</div>
  </div>
  <div class='stat-box'>
    <div class='val'>{total}</div>
    <div class='lbl'>Original msgs</div>
  </div>
{recon_stat_box}
</div>

{count_note}

{global_badges_html}

<div class='legend'>
<b>Field diff categories</b>
<p style='margin:8px 0 12px;color:#555;font-size:0.92em'>
  Float diffs appear when the original GPS file uses binary format and \
the reconstructed file uses
  EDIE&apos;s abbreviated ASCII format. EDIE&apos;s ASCII encoder writes \
a fixed number of decimal
  places or significant figures, which rounds float32 fields. These are \
<em>format limitations</em>,
  not parquet data loss -- the full-precision value is stored in the \
parquet database.
</p>
{''.join(legend_items)}
</div>

<table border='1'>
<tr><th>Type</th><th>Status</th>\
<th style='text-align:right'>Messages</th><th>Details</th></tr>
{"".join(main_rows) if main_rows else no_main}
</table>

{_undecodable_section(undecodable_rows)}
</body></html>"""
    path.write_text(html, encoding="utf-8")
