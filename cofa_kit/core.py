"""Small, dependency-free helpers. No network or model calls are made here."""
from __future__ import annotations

import csv
import json
import math
import platform
import shutil
import subprocess
import sys
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_JSON_BYTES = 20 * 1024 * 1024
MAX_LOG_BYTES = 20 * 1024 * 1024
MAX_ROWS = 100_000
PRIORITIES = {"must", "should", "could"}
STATUSES = {"todo", "in_progress", "verified", "blocked"}
KINDS = {"decision", "test", "assumption"}


class KitError(ValueError):
    """A readable validation error, safe to show without a stack trace."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def workspace_root(workspace: str | Path) -> Path:
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise KitError(f"Workspace directory does not exist: {root}")
    return root


def contained_path(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    """Resolve a workspace-relative path, including every existing symlink."""
    if not isinstance(relative, str) or not relative.strip():
        raise KitError("File paths must be non-empty relative strings")
    rel = Path(relative)
    if rel.is_absolute() or rel.drive or ".." in rel.parts:
        raise KitError(f"Path must stay inside the workspace: {relative}")
    # Backslashes are separators on Windows but ordinary characters on Unix.
    # Reject portable traversal/drive patterns as well.
    normalized = relative.replace("\\", "/")
    if normalized.startswith("/") or ".." in normalized.split("/") or ":" in normalized:
        raise KitError(f"Path must be a portable workspace-relative path: {relative}")
    candidate = (root / rel).resolve()
    if not candidate.is_relative_to(root):
        raise KitError(f"Path resolves outside the workspace: {relative}")
    if must_exist and not candidate.is_file():
        raise KitError(f"File not found: {relative}")
    return candidate


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise KitError(f"Duplicate JSON object key: {key}")
        result[key] = value
    return result


def read_json(path: Path, *, encoding: str = "utf-8-sig") -> Any:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise KitError(f"JSON exceeds {MAX_JSON_BYTES // 1024 // 1024} MiB; use a smaller file or CSV")
    with path.open("r", encoding=encoding) as stream:
        return json.load(stream, object_pairs_hook=_unique_object,
                         parse_constant=lambda x: (_ for _ in ()).throw(KitError(f"Invalid JSON number: {x}")))


def init_workspace(workspace: str | Path) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    contents = {
        "requirements.json": json.dumps({
            "required_files": [],
            "criteria": [{"id": "R1", "requirement": "Replace with an actual requirement from the task brief",
                          "priority": "must", "status": "todo", "evidence": []}],
        }, ensure_ascii=False, indent=2) + "\n",
        "decision-log.jsonl": "",
    }
    for name in contents:
        candidate = root / name
        if candidate.exists() or candidate.is_symlink():
            raise KitError(f"Refusing to overwrite existing file: {name}")
    created: list[str] = []
    for name, text in contents.items():
        with (root / name).open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        created.append(name)
    return {"workspace": str(root), "created": created,
            "next": "Replace the sample criterion, add required file paths, then record actual decisions and tests."}


def doctor() -> dict[str, Any]:
    versions: dict[str, str | None] = {"python": platform.python_version()}
    for executable in ("git", "node", "codex"):
        resolved = shutil.which(executable)
        if resolved is None:
            versions[executable] = None
            continue
        try:
            output = subprocess.run([resolved, "--version"], capture_output=True, text=True,
                                    timeout=8, shell=False, errors="replace")
            versions[executable] = (output.stdout or output.stderr).strip()[:200] or f"exit {output.returncode}"
        except (OSError, subprocess.TimeoutExpired) as error:
            versions[executable] = f"version check unavailable ({type(error).__name__})"
    return {"python_supported": sys.version_info >= (3, 10), "platform": platform.system(),
            "versions": versions, "network_checked": False, "credentials_read": False,
            "note": "Checks local executable presence/version only. It does not verify platform permissions, MCP, or network access."}


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or isinstance(value, (list, dict)) or _missing(value):
        return None
    try:
        parsed = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def profile_file(file: str | Path, *, format: str = "auto", encoding: str = "utf-8-sig",
                 max_rows: int = 10_000) -> dict[str, Any]:
    """Summarize only the first max_rows records. Never send contents anywhere."""
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or not 1 <= max_rows <= MAX_ROWS:
        raise KitError(f"max_rows must be between 1 and {MAX_ROWS}")
    if encoding not in {"utf-8-sig", "cp949"}:
        raise KitError("Supported encodings: utf-8-sig, cp949")
    path = Path(file).expanduser().resolve()
    if not path.is_file():
        raise KitError(f"Input file does not exist: {path}")
    if format == "auto":
        format = path.suffix.lower().lstrip(".")
    if format not in {"csv", "json"}:
        raise KitError("Choose CSV or JSON (or use --format csv|json)")
    rows: list[dict[str, Any]] = []
    columns: list[str] = []
    truncated = False
    total_rows: int | None = None
    if format == "csv":
        with path.open("r", encoding=encoding, newline="") as stream:
            reader = csv.reader(stream, strict=True)
            try:
                columns = next(reader)
            except StopIteration:
                raise KitError("CSV is empty; a header row is required") from None
            if not columns or any(not c.strip() for c in columns):
                raise KitError("CSV headers must be non-empty")
            if len(columns) != len(set(columns)):
                raise KitError("CSV contains duplicate column names")
            if len(columns) > 1000:
                raise KitError("CSV exceeds 1000 columns")
            for line_number, values in enumerate(reader, start=2):
                if not values:
                    continue
                if len(rows) == max_rows:
                    truncated = True
                    break
                if len(values) != len(columns):
                    raise KitError(f"CSV record {line_number}: expected {len(columns)} fields, found {len(values)}")
                rows.append(dict(zip(columns, values)))
            if not truncated:
                total_rows = len(rows)
    else:
        data = read_json(path, encoding=encoding)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise KitError("JSON must be an object or an array of objects")
        total_rows = len(data)
        truncated = total_rows > max_rows
        for row in data[:max_rows]:
            if not isinstance(row, dict):
                raise KitError("Each sampled JSON record must be an object")
            rows.append(row)
            for key in row:
                if key not in columns:
                    columns.append(key)
        if len(columns) > 1000:
            raise KitError("JSON sample exceeds 1000 columns")
    summary = []
    for name in columns:
        values = [row.get(name) for row in rows]
        present = [value for value in values if not _missing(value)]
        numeric = [number for value in present if (number := _numeric(value)) is not None]
        numeric_summary = None
        if numeric:
            # Dividing before summing avoids overflow for repeated large finite values.
            numeric_summary = {"count": len(numeric), "min": min(numeric), "max": max(numeric),
                               "mean": math.fsum(n / len(numeric) for n in numeric)}
        summary.append({"name": name, "missing": len(values) - len(present),
                        "distinct_non_missing": len({json.dumps(value, sort_keys=True, ensure_ascii=False) for value in present}),
                        "numeric": numeric_summary,
                        "non_numeric_non_missing": len(present) - len(numeric)})
    signatures = [json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows]
    return {"file": path.name, "format": format, "encoding": encoding, "rows_sampled": len(rows),
            "total_rows": total_rows, "truncated": truncated, "max_rows": max_rows,
            "duplicate_rows_in_sample": len(signatures) - len(set(signatures)), "columns": summary,
            "scope": "Statistics cover sampled rows only; no rows after the sample are validated.",
            "warnings": (["Sample limit reached. Full-file conclusions require additional checks."] if truncated else [])}


def load_manifest(root: Path, manifest: str = "requirements.json") -> dict[str, Any]:
    path = contained_path(root, manifest, must_exist=True)
    data = read_json(path)
    if not isinstance(data, dict):
        raise KitError("Manifest must be a JSON object")
    if set(data) - {"required_files", "criteria"}:
        raise KitError("Manifest has unsupported fields; use required_files and criteria")
    if not isinstance(data.get("required_files"), list) or not isinstance(data.get("criteria"), list):
        raise KitError("Manifest must contain required_files and criteria arrays")
    for file in data["required_files"]:
        contained_path(root, file)
    ids: set[str] = set()
    for item in data["criteria"]:
        if not isinstance(item, dict):
            raise KitError("Every criterion must be an object")
        if set(item) != {"id", "requirement", "priority", "status", "evidence"}:
            raise KitError("Each criterion needs exactly id, requirement, priority, status, evidence")
        for key in ("id", "requirement"):
            if not isinstance(item[key], str) or not item[key].strip():
                raise KitError(f"Criterion {key} must be a non-empty string")
        if item["id"] in ids:
            raise KitError(f"Duplicate criterion id: {item['id']}")
        ids.add(item["id"])
        if not isinstance(item["priority"], str) or item["priority"] not in PRIORITIES:
            raise KitError(f"Invalid priority for {item['id']}")
        if not isinstance(item["status"], str) or item["status"] not in STATUSES:
            raise KitError(f"Invalid status for {item['id']}")
        if not isinstance(item["evidence"], list):
            raise KitError(f"Evidence must be an array for {item['id']}")
        for file in item["evidence"]:
            contained_path(root, file)
    return data


def _file_problem(root: Path, relative: str) -> str | None:
    path = contained_path(root, relative)
    if not path.is_file():
        return "missing or not a regular file"
    if path.stat().st_size == 0:
        return "empty file"
    return None


def check_workspace(workspace: str | Path, manifest: str = "requirements.json") -> dict[str, Any]:
    root = workspace_root(workspace)
    data = load_manifest(root, manifest)
    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not data["criteria"]:
        issues.append({"type": "criteria", "message": "No requirements have been defined"})
    for file in data["required_files"]:
        if problem := _file_problem(root, file):
            issues.append({"type": "required_file", "file": file, "message": problem})
    for item in data["criteria"]:
        target = issues if item["priority"] == "must" else warnings
        if item["status"] != "verified":
            target.append({"type": "criterion", "id": item["id"], "message": f"Status is {item['status']}, not verified"})
        if item["status"] == "verified" and not item["evidence"]:
            target.append({"type": "evidence", "id": item["id"], "message": "Verified criterion has no evidence files"})
        for file in item["evidence"]:
            if problem := _file_problem(root, file):
                target.append({"type": "evidence", "id": item["id"], "file": file, "message": problem})
    return {"ok": not issues, "criteria_count": len(data["criteria"]), "issues": issues, "warnings": warnings,
            "limits": "Checks paths, file presence, and declared statuses only. It does not prove correctness, validate evidence contents, or submit anything."}


def append_log(workspace: str | Path, kind: str, summary: str, evidence: list[str] | None = None) -> dict[str, Any]:
    root = workspace_root(workspace)
    if kind not in KINDS:
        raise KitError("Log kind must be decision, test, or assumption")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 20_000:
        raise KitError("Log summary must contain 1 to 20000 characters")
    evidence = evidence or []
    if not isinstance(evidence, list):
        raise KitError("Evidence must be an array")
    for file in evidence:
        contained_path(root, file, must_exist=True)
    path = contained_path(root, "decision-log.jsonl")
    if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
        raise KitError("Decision log exceeds 20 MiB")
    record = {"timestamp": utc_now(), "kind": kind, "summary": summary.strip(), "evidence": evidence}
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_log(root: Path) -> list[dict[str, Any]]:
    path = contained_path(root, "decision-log.jsonl", must_exist=True)
    if path.stat().st_size > MAX_LOG_BYTES:
        raise KitError("Decision log exceeds 20 MiB")
    result = []
    with path.open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            record = json.loads(line, object_pairs_hook=_unique_object)
            if not isinstance(record, dict) or set(record) != {"timestamp", "kind", "summary", "evidence"}:
                raise KitError(f"Invalid decision log record at line {line_number}")
            if not isinstance(record["kind"], str) or record["kind"] not in KINDS or not isinstance(record["summary"], str) or not isinstance(record["timestamp"], str):
                raise KitError(f"Invalid decision log values at line {line_number}")
            if not isinstance(record["evidence"], list):
                raise KitError(f"Invalid evidence at log line {line_number}")
            for file in record["evidence"]:
                contained_path(root, file)
            result.append(record)
    return result


def _cell(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;").replace("\r", " ").replace("\n", "<br>")


def _test_summary(text: str) -> dict[str, Any]:
    """Recognize common unittest/pytest summaries, without claiming test quality."""
    ran = re.search(r"Ran\s+(\d+)\s+tests?\b", text)
    if ran:
        count = int(ran.group(1))
        skipped_match = re.search(r"\bskipped=(\d+)\b", text)
        skipped = int(skipped_match.group(1)) if skipped_match else 0
        return {"recognized": "unittest", "collected": count, "skipped": skipped,
                "no_tests": count == 0, "all_skipped": count > 0 and skipped == count,
                "reported_failure": bool(re.search(r"^FAILED\b", text, re.MULTILINE))}
    if re.search(r"\bno tests ran\b|\bcollected 0 items\b", text):
        return {"recognized": "pytest", "no_tests": True, "all_skipped": False}
    # Use pytest's final duration line, not counts embedded in individual test logs.
    summary_lines = [line for line in text.splitlines() if re.search(r"\bin\s+\d+(?:\.\d+)?s\b", line)]
    for line in reversed(summary_lines):
        counts = {key: int(number) for number, key in re.findall(r"(\d+)\s+(passed|failed|skipped|error|errors|xfailed|xpassed)\b", line)}
        if counts:
            executed = sum(counts.get(key, 0) for key in ("passed", "failed", "error", "errors", "xfailed", "xpassed"))
            return {"recognized": "pytest", "counts": counts, "no_tests": False,
                    "all_skipped": executed == 0 and counts.get("skipped", 0) > 0,
                    "reported_failure": any(counts.get(key, 0) > 0 for key in ("failed", "error", "errors"))}
    return {"recognized": None, "no_tests": False, "all_skipped": False,
            "note": "No supported test summary recognized. Exit code alone does not establish test coverage."}


def run_check(workspace: str | Path, criterion_id: str, command: list[str], *, timeout: float = 30,
              max_output_bytes: int = 65_536) -> dict[str, Any]:
    """Run an explicit one-shot command locally and record bounded observed output.

    This is not a sandbox: use only commands permitted by the task. No shell is
    inserted. A timeout stops the direct child; descendants are not managed.
    """
    root = workspace_root(workspace)
    manifest = load_manifest(root)
    if criterion_id not in {item["id"] for item in manifest["criteria"]}:
        raise KitError("--id must identify a criterion in requirements.json")
    if not isinstance(command, list) or not command or any(not isinstance(arg, str) or "\x00" in arg for arg in command):
        raise KitError("Provide a non-empty command argument list after --")
    if not command[0].strip():
        raise KitError("Command executable must not be empty")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 1800:
        raise KitError("Timeout must be greater than zero and at most 1800 seconds")
    if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) or not 1024 <= max_output_bytes <= 1_048_576:
        raise KitError("max_output_bytes must be between 1024 and 1048576 per stream")
    evidence_root = contained_path(root, "evidence")
    evidence_root.mkdir(exist_ok=True)
    run_name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    destination = contained_path(root, "evidence/" + run_name)
    destination.mkdir()
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    totals = {"stdout": 0, "stderr": 0}
    tail_buffers = {"stdout": bytearray(), "stderr": bytearray()}
    stop = threading.Event()

    def consume(stream, name):
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                if stop.is_set():
                    break
                totals[name] += len(chunk)
                remaining = max_output_bytes - len(buffers[name])
                if remaining > 0:
                    buffers[name].extend(chunk[:remaining])
                tail_buffers[name].extend(chunk)
                if len(tail_buffers[name]) > 16_384:
                    del tail_buffers[name][:-16_384]
        finally:
            stream.close()

    started = utc_now()
    clock = time.monotonic()
    timed_out = False
    try:
        process = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, bufsize=0)
    except OSError as error:
        # Keep failed launches reviewable too; do not imply the command ran.
        record = {"criterion_id": criterion_id, "command": command, "started_at": started,
                  "duration_seconds": round(time.monotonic() - clock, 3), "exit_code": None,
                  "timed_out": False, "ok": False, "launched": False,
                  "error": str(error), "evidence_directory": f"evidence/{run_name}"}
        (destination / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        append_log(root, "test", f"{criterion_id}: command could not launch; no test result established", [f"evidence/{run_name}/result.json"])
        return record
    threads = [threading.Thread(target=consume, args=(getattr(process, name), name), daemon=True)
               for name in ("stdout", "stderr")]
    for thread in threads:
        thread.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=1)
    streams_closed = all(not thread.is_alive() for thread in threads)
    stop.set()
    # A descendant retaining a pipe does not block return. Only finite, one-shot
    # commands should be used; the tool deliberately never kills platform processes.
    evidence_paths = []
    for name in ("stdout", "stderr"):
        # Preserve bytes exactly, including non-UTF-8 programs, and keep the on-disk
        # byte bound identical to the memory bound.
        (destination / f"{name}.txt").write_bytes(bytes(buffers[name]))
        evidence_paths.append(f"evidence/{run_name}/{name}.txt")
    summary = _test_summary("\n".join(bytes(tail_buffers[name]).decode("utf-8", errors="replace") for name in ("stdout", "stderr")))
    ok = process.returncode == 0 and not timed_out and streams_closed and not summary["no_tests"] and not summary["all_skipped"] and not summary.get("reported_failure", False)
    record = {"criterion_id": criterion_id, "command": command, "started_at": started,
              "duration_seconds": round(time.monotonic() - clock, 3), "exit_code": process.returncode,
              "timed_out": timed_out, "launched": True, "ok": ok,
              "streams_closed": streams_closed, "captured_bytes": {name: len(buffers[name]) for name in buffers},
              "observed_bytes": totals, "output_truncated": {name: totals[name] > len(buffers[name]) for name in buffers},
              "test_summary": summary, "evidence_directory": f"evidence/{run_name}",
              "limits": "Command success is not functional correctness. Requirement statuses are unchanged. Timeout kills only the direct child; do not run servers or launch background processes."}
    (destination / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence_paths.insert(0, f"evidence/{run_name}/result.json")
    append_log(root, "test", f"{criterion_id}: observed command exit={process.returncode}, timeout={timed_out}, no_tests={summary['no_tests']}, all_skipped={summary['all_skipped']}; correctness requires review", evidence_paths)
    return record


def report_workspace(workspace: str | Path, manifest: str = "requirements.json") -> str:
    root = workspace_root(workspace)
    data = load_manifest(root, manifest)
    audit = check_workspace(root, manifest)
    logs = read_log(root)
    lines = ["# Work evidence report", "", f"Generated: {utc_now()}", "",
             "This report repeats recorded claims and local file checks. It does not independently certify correctness.", "",
             "## Requirements", "", "| ID | Requirement | Priority | Declared status | Evidence paths |",
             "| --- | --- | --- | --- | --- |"]
    for item in data["criteria"]:
        lines.append("| " + " | ".join(_cell(x) for x in [item["id"], item["requirement"], item["priority"], item["status"], ", ".join(item["evidence"]) or "None recorded"]) + " |")
    lines += ["", "## Structural checks", "", f"Required structural checks: {'PASS' if audit['ok'] else 'GAPS FOUND'}", ""]
    for issue in audit["issues"] + audit["warnings"]:
        lines.append(f"- {_cell(issue.get('id', issue.get('file', issue['type'])))}: {_cell(issue['message'])}")
    if not audit["issues"] and not audit["warnings"]:
        lines.append("- No structural gaps detected. Evidence contents and runtime behavior still require review.")
    lines += ["", "## Recorded decisions, tests, and assumptions", ""]
    if not logs:
        lines.append("No decisions or test outcomes have been recorded.")
    for record in logs:
        lines += [f"- {_cell(record['timestamp'])} [{_cell(record['kind'])}] {_cell(record['summary'])}"]
        if record["evidence"]:
            lines.append("  Evidence paths: " + _cell(", ".join(record["evidence"])))
    lines += ["", "## Interpretation limits", "", audit["limits"], "",
              "No generated answer to a follow-up assessment is included. During that phase, stop using AI and respond independently.", ""]
    return "\n".join(lines)
