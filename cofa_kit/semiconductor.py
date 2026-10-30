"""Local count aggregation and educational frozen-baseline I-MR analysis.

Formula references: https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc322.htm
and https://www.itl.nist.gov/div898/handbook/semstat/semstat-doc.pdf (printed p.68).
The baseline-size warning is a kit convention, not a NIST acceptance rule.
"""
from __future__ import annotations

import csv
import math
import re
from datetime import datetime
from pathlib import Path

from .core import KitError

IDENTITY_COLUMNS = ("tool_id", "chamber_id", "product", "recipe", "metric", "unit")
ISO_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$")


def column_list(value: str) -> list[str]:
    columns = [column.strip() for column in value.split(",")]
    if not columns or any(not c for c in columns) or len(set(columns)) != len(columns):
        raise KitError("Column lists must contain unique, non-empty comma-separated names")
    return columns


def _columns(columns: list[str], label: str) -> None:
    if not isinstance(columns, list) or not columns or any(not isinstance(c, str) or not c.strip() for c in columns):
        raise KitError(f"{label} must be a non-empty list of column names")
    if len(columns) != len(set(columns)):
        raise KitError(f"{label} contains duplicate column names")


def _csv_rows(file, required, encoding, max_rows):
    if encoding not in {"utf-8-sig", "cp949"}:
        raise KitError("Supported encodings: utf-8-sig, cp949")
    if type(max_rows) is not int or not 1 <= max_rows <= 100_000:
        raise KitError("max_rows must be between 1 and 100000")
    with Path(file).expanduser().open(encoding=encoding, newline="") as stream:
        reader = csv.reader(stream, strict=True)
        header = next(reader, None)
        if not header or any(not c.strip() for c in header) or len(header) != len(set(header)) or len(header) > 1000:
            raise KitError("CSV needs unique, non-empty headers (at most 1000)")
        missing = sorted(set(required) - set(header))
        if missing:
            raise KitError("Missing columns: " + ", ".join(missing))
        for number, values in enumerate(reader, 1):
            if number > max_rows:
                raise KitError("CSV exceeds max_rows; no partial analysis is returned")
            if len(values) != len(header):
                raise KitError(f"Data row {number}: expected {len(header)} fields, found {len(values)}")
            yield number, dict(zip(header, values))


def _nonmissing(row, columns, number):
    values = tuple(row[c].strip() for c in columns)
    if any(not value for value in values):
        raise KitError(f"Data row {number}: missing identifier/group/value in {','.join(columns)}")
    return values


def _counts(tested, passed):
    return {"tested": tested, "passed": passed, "failed": tested - passed,
            "pass_rate": passed / tested if tested else None,
            "pass_rate_pct": 100 * passed / tested if tested else None}


def yield_summary(file, *, group_by: list[str], key: list[str], tested_col="tested",
                  passed_col="passed", encoding="utf-8-sig", max_rows=100_000):
    """Aggregate integer counts, rejecting ambiguous duplicate inspection keys."""
    _columns(group_by, "group_by")
    _columns(key, "key")
    _columns([tested_col, passed_col], "count columns")
    groups, seen = {}, set()
    total_tested = total_passed = row_count = 0
    for number, row in _csv_rows(file, group_by + key + [tested_col, passed_col], encoding, max_rows):
        identity = _nonmissing(row, key, number)
        if identity in seen:
            raise KitError(f"Data row {number}: duplicate composite key; define retest policy before aggregation")
        seen.add(identity)
        group = _nonmissing(row, group_by, number)
        values = _nonmissing(row, [tested_col, passed_col], number)
        if any(not re.fullmatch(r"[0-9]+", value) or len(value) > 18 for value in values):
            raise KitError(f"Data row {number}: counts must be nonnegative integers of at most 18 digits")
        tested, passed = map(int, values)
        if passed > tested:
            raise KitError(f"Data row {number}: passed exceeds tested")
        aggregate = groups.setdefault(group, [0, 0, 0])
        aggregate[0] += tested
        aggregate[1] += passed
        aggregate[2] += 1
        total_tested += tested
        total_passed += passed
        row_count += 1
    results = [{"group": dict(zip(group_by, group)), "rows": values[2], **_counts(values[0], values[1])}
               for group, values in sorted(groups.items())]
    warnings = []
    if not row_count:
        warnings.append("No records: pass rate is unknown, not zero.")
    if any(result["tested"] == 0 for result in results):
        warnings.append("A group has zero tested count; its pass rate is null.")
    return {"analysis": "weighted_test_pass_rate", "rows": row_count, "group_by": group_by, "key": key,
            "totals": _counts(total_tested, total_passed), "groups": results, "warnings": warnings,
            "metric_scope": "Test pass rate over the selected inspection population. It is not full wafer, manufacturing, or shipment yield unless coverage is independently established.",
            "limits": "Counts must describe tested/passed units, not defect events. No imputation, retest deduplication, quality acceptance, or causal conclusion is performed."}


def spc_summary(file, *, value_col: str, time_col: str, baseline_count: int,
                series_cols: list[str] | None = None, encoding="utf-8-sig", max_rows=100_000):
    """Use a fixed initial baseline to evaluate later observations in one series."""
    _columns([value_col, time_col], "value/time columns")
    if type(baseline_count) is not int or baseline_count < 3:
        raise KitError("baseline_count must be an integer of at least 3")
    if series_cols is not None:
        _columns(series_cols, "series_cols")
        if value_col in series_cols or time_col in series_cols:
            raise KitError("Series identity columns cannot include the value or timestamp")
    points, series = [], None
    checked = series_cols
    previous_time = None
    offset = None
    intervals = []
    for number, row in _csv_rows(file, [value_col, time_col] + (series_cols or []), encoding, max_rows):
        if checked is None:
            checked = [name for name in IDENTITY_COLUMNS if name in row and name not in {value_col, time_col}]
        identity = _nonmissing(row, checked, number) if checked else ()
        if series is None:
            series = identity
        elif identity != series:
            raise KitError(f"Data row {number}: mixed series identity; analyze one homogeneous stream")
        raw_value, raw_time = _nonmissing(row, [value_col, time_col], number)
        try:
            value = float(raw_value)
            if not math.isfinite(value) or not ISO_TIMESTAMP.fullmatch(raw_time):
                raise ValueError()
            timestamp = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        except ValueError:
            raise KitError(f"Data row {number}: require a finite number and ISO timestamp YYYY-MM-DDTHH:MM:SS[±HH:MM or Z]") from None
        current_offset = timestamp.utcoffset()
        if previous_time is not None:
            if current_offset != offset:
                raise KitError(f"Data row {number}: mixed timezone offsets or naive/aware timestamps")
            if timestamp <= previous_time:
                raise KitError(f"Data row {number}: timestamps must be strictly increasing; ties are rejected")
            intervals.append((timestamp - previous_time).total_seconds())
        offset, previous_time = current_offset, timestamp
        points.append({"row_number": number, "timestamp": raw_time, "value": value})
    if len(points) < baseline_count:
        raise KitError("Fewer data points than baseline_count")
    baseline = [point["value"] for point in points[:baseline_count]]
    ranges = [abs(baseline[i] - baseline[i - 1]) for i in range(1, baseline_count)]
    if any(not math.isfinite(value) for value in ranges):
        raise KitError("Numerical range overflow; rescale measurements before analysis")
    try:
        mean = math.fsum(value / baseline_count for value in baseline)
        mr_bar = math.fsum(value / len(ranges) for value in ranges)
        sigma = mr_bar / 1.128
        i_lcl, i_ucl, mr_ucl = mean - 3 * sigma, mean + 3 * sigma, 3.267 * mr_bar
        if any(not math.isfinite(v) for v in (mean, mr_bar, sigma, i_lcl, i_ucl, mr_ucl)):
            raise OverflowError()
    except (ValueError, OverflowError):
        raise KitError("Numerical range overflow; rescale measurements before analysis") from None
    indeterminate = mr_bar == 0
    warnings = []
    if baseline_count < 20:
        warnings.append("Fewer than 20 baseline observations: exploratory only. This threshold is a kit convention, not proof of process stability.")
    if not checked:
        warnings.append("No identity columns checked. Confirm a single tool/product/recipe/measurement/unit stream yourself.")
    if not points[baseline_count:]:
        warnings.append("No future observations; monitoring was not evaluated.")
    if intervals and min(intervals) != max(intervals):
        warnings.append("Observation intervals vary; gaps are not imputed or automatically segmented. Review the time sampling plan.")
    if indeterminate:
        warnings.append("Baseline moving range is zero. Limits cannot establish normality; all monitoring flags are null.")
    evaluation = []
    for i in range(baseline_count, len(points)):
        mr = abs(points[i]["value"] - points[i - 1]["value"])
        if not math.isfinite(mr):
            raise KitError("Numerical range overflow in monitoring points")
        evaluation.append({**points[i], "moving_range": mr,
                           "i_signal": None if indeterminate else points[i]["value"] < i_lcl or points[i]["value"] > i_ucl,
                           "mr_signal": None if indeterminate else mr > mr_ucl})
    return {"analysis": "frozen_baseline_individuals_moving_range", "status": "indeterminate" if indeterminate else "exploratory",
            "rows": len(points), "series_columns": checked or [], "series": dict(zip(checked or [], series or ())),
            "baseline": {"count": baseline_count, "start": points[0]["timestamp"], "end": points[baseline_count - 1]["timestamp"],
                         "mean": mean, "mr_bar": mr_bar, "sigma_estimate": None if indeterminate else sigma,
                         "i_lcl": None if indeterminate else i_lcl, "i_ucl": None if indeterminate else i_ucl,
                         "mr_lcl": None if indeterminate else 0.0, "mr_ucl": None if indeterminate else mr_ucl},
            "evaluation": evaluation, "warnings": warnings,
            "limits": "Baseline statistics are frozen; the first future moving range uses the last baseline point. Signals are investigation prompts, not defect classifications, causal proof, specification limits, capability estimates, or automatic control instructions."}
