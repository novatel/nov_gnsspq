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

Source validation helpers for nov_gnsspq.
"""
from __future__ import annotations

import hashlib
import json
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

from nov_gnsspq.reader.schema import METADATA_FILENAME


@dataclass
class ValidationResult:
    """Result of a compare() call.

    Attributes:
        valid: True if both inputs have matching fingerprints.
        reason: Failure reason string when valid is False, None otherwise.
        detail: "first argument" or "second argument" when a metadata error
            is attributable to one side; None otherwise.
    """

    valid: bool
    reason: str | None = None
    detail: str | None = None


def _hash_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_fingerprint(path: Path, label: str) -> tuple[int, str] | ValidationResult:
    suffix = path.suffix.lower()
    if suffix in {".zip", ".gnsspq"}:
        member = f"{path.stem}/{METADATA_FILENAME}"
        with zipfile.ZipFile(path) as zf:
            if member not in zf.namelist():
                return ValidationResult(valid=False, reason="metadata_missing", detail=label)
            metadata = json.loads(zf.read(member))
    elif path.is_dir():
        meta_path = path / METADATA_FILENAME
        if not meta_path.exists():
            return ValidationResult(valid=False, reason="metadata_missing", detail=label)
        with open(meta_path, encoding="utf-8") as f:
            metadata = json.load(f)
    else:
        return (os.path.getsize(path), _hash_file(path))

    if "file_size" not in metadata or "sha256" not in metadata:
        return ValidationResult(valid=False, reason="metadata_incomplete", detail=label)
    return (metadata["file_size"], metadata["sha256"])


def compare(a: Path | str, b: Path | str) -> ValidationResult:
    """Compare two paths by fingerprint (file size + SHA-256).

    Auto-detects each path as a GPS file or database:
    - ``.zip`` / ``.gnsspq`` suffix or directory → database (reads ``_metadata.json``)
    - anything else → GPS file (hashes the file directly)

    Args:
        a: First path — a GPS log file or nov_gnsspq database.
        b: Second path — a GPS log file or nov_gnsspq database.

    Returns:
        A :class:`ValidationResult` with ``valid=True`` when fingerprints match.

        On mismatch or metadata error, ``valid=False`` and ``reason`` is one of:
        ``"metadata_missing"``, ``"metadata_incomplete"``,
        ``"file_size_mismatch"``, or ``"sha256_mismatch"``.

        When a metadata error is attributable to one side, ``detail`` is
        ``"first argument"`` or ``"second argument"``.

    Raises:
        FileNotFoundError: Either path does not exist.
        OSError: Either path is not readable.
    """
    fp_a = _extract_fingerprint(Path(a), "first argument")
    if isinstance(fp_a, ValidationResult):
        return fp_a

    fp_b = _extract_fingerprint(Path(b), "second argument")
    if isinstance(fp_b, ValidationResult):
        return fp_b

    size_a, sha256_a = fp_a
    size_b, sha256_b = fp_b

    if size_a != size_b:
        return ValidationResult(valid=False, reason="file_size_mismatch")
    if sha256_a.lower() != sha256_b.lower():
        return ValidationResult(valid=False, reason="sha256_mismatch")
    return ValidationResult(valid=True)
