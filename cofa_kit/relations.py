"""Inspect local CSV key cardinality without joining or changing source files."""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from .core import KitError

RELATIONSHIPS = ("one_to_one", "many_to_one", "one_to_many", "many_to_many")


def _validate_keys(columns: list[str], side: str) -> None:
    if not isinstance(columns, list) or not 1 <= len(columns) <= 16:
        raise KitError(f"{side}_key must contain 1 to 16 column names")
    if any(not isinstance(name, str) or not name.strip() or len(name) > 256 for name in columns):
        raise KitError(f"{side}_key column names must be nonblank strings of at most 256 characters")
    if len(columns) != len(set(columns)):
        raise KitError(f"{side}_key column names must be unique")


def _key_counts(file: str | Path, columns: list[str], side: str,
                encoding: str, max_rows: int) -> Counter:
    counts = Counter()
    with Path(file).expanduser().open("r", encoding=encoding, newline="") as stream:
        reader = csv.reader(stream, strict=True)
        header = next(reader, None)
        if not header or any(not name.strip() for name in header) or len(header) > 1000:
            raise KitError(f"{side}: CSV needs nonblank headers, at most 1000 columns")
        if len(header) != len(set(header)):
            raise KitError(f"{side}: CSV has duplicate header names")
        if not set(columns).issubset(header):
            raise KitError(f"{side}: CSV is missing required key columns")
        indices = [header.index(name) for name in columns]
        for number, row in enumerate(reader, start=1):
            if number > max_rows:
                raise KitError(f"{side}: CSV exceeds max_rows; no partial audit is returned")
            if len(row) != len(header):
                raise KitError(f"{side}: data row {number} has the wrong field count")
            key = tuple(row[index] for index in indices)
            if any(not value.strip() for value in key):
                raise KitError(f"{side}: data row {number} contains a blank key component")
            # Values are deliberately not stripped, case-folded or cast to numbers.
            counts[key] += 1
    return counts


def join_audit(left: str | Path, right: str | Path, *, left_key: list[str],
               right_key: list[str], relationship: str, encoding: str = "utf-8-sig",
               max_rows: int = 100_000) -> dict:
    """Predict equijoin row counts from complete, bounded key-frequency scans.

    Uniqueness contracts apply to the entire nonblank key column set on each
    side, including keys that have no counterpart. No actual join is executed.
    """
    _validate_keys(left_key, "left")
    _validate_keys(right_key, "right")
    if len(left_key) != len(right_key):
        raise KitError("left_key and right_key must have the same number of columns")
    if not isinstance(relationship, str) or relationship not in RELATIONSHIPS:
        raise KitError("Choose one_to_one, many_to_one, one_to_many, or many_to_many")
    if encoding not in {"utf-8-sig", "cp949"}:
        raise KitError("Supported encodings: utf-8-sig, cp949")
    if type(max_rows) is not int or not 1 <= max_rows <= 100_000:
        raise KitError("max_rows must be between 1 and 100000 per input file")
    left_counts = _key_counts(left, left_key, "left", encoding, max_rows)
    right_counts = _key_counts(right, right_key, "right", encoding, max_rows)
    shared = left_counts.keys() & right_counts.keys()

    def summary(counts):
        rows = sum(counts.values())
        matched = sum(counts[key] for key in shared)
        return {"rows": rows, "distinct_keys": len(counts),
                "duplicate_keys": sum(value > 1 for value in counts.values()),
                "matched_rows": matched, "unmatched_rows": rows - matched}

    left_summary, right_summary = summary(left_counts), summary(right_counts)
    inner = sum(left_counts[key] * right_counts[key] for key in shared)
    predicted_left = inner + left_summary["unmatched_rows"]
    predicted_right = inner + right_summary["unmatched_rows"]
    issues, warnings = [], []
    if relationship in ("one_to_one", "one_to_many") and left_summary["duplicate_keys"]:
        issues.append({"side": "left", "message": "Expected globally unique keys, but repeated keys exist"})
    if relationship in ("one_to_one", "many_to_one") and right_summary["duplicate_keys"]:
        issues.append({"side": "right", "message": "Expected globally unique keys, but repeated keys exist"})
    if predicted_left > left_summary["rows"]:
        warnings.append("A left join would increase the number of rows; repeated left-side quantities could be counted more than once.")
    if relationship == "many_to_many":
        warnings.append("many_to_many permits repeated keys on both sides and enforces no uniqueness. This does not establish a correct business relationship.")
    if left_summary["unmatched_rows"] or right_summary["unmatched_rows"]:
        warnings.append("Unmatched rows exist; review whether excluding or retaining them fits the task.")
    return {
        "analysis": "csv_join_cardinality", "ok": not issues, "relationship": relationship,
        "left": left_summary, "right": right_summary, "shared_keys": len(shared),
        "predicted_rows": {"inner": inner, "left": predicted_left, "right": predicted_right,
                           "full": inner + left_summary["unmatched_rows"] + right_summary["unmatched_rows"]},
        "left_join_expansion_factor": predicted_left / left_summary["rows"] if left_summary["rows"] else None,
        "issues": issues, "warnings": warnings,
        "semantics": {
            "matching": "Exact string equality by ordered key components. Leading zeros, case and surrounding whitespace are preserved. Blank components are rejected.",
            "uniqueness_scope": "All keys on the constrained side, including unmatched keys. duplicate_keys counts distinct keys occurring more than once, not duplicate rows."},
        "limits": "Complete bounded input scan; predicted row counts only. No actual join, deduplication, aggregate-sum conservation check or semantic-correctness proof is performed. No source keys or row contents are returned."
    }
