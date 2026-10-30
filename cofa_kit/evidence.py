"""Bounded, opt-in content snapshots; not a signature or continuous file monitor."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

from .core import KitError, _unique_object, workspace_root

MAX_FILES = 32
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_RESULT_BYTES = 2 * 1024 * 1024
ERRORS = {"missing", "not_regular", "unsafe_path", "unreadable", "unstable", "size_limit"}
LIMITS = ("Compares SHA256 only for explicitly watched files at recorded before/after and current reads. "
          "It cannot detect changes restored between reads, untracked dependencies, or forged metadata. "
          "This is not a security signature or evidence of functional correctness. A fresh result can describe a failed command.")


class WatchReadError(KitError):
    def __init__(self, code: str, read_bytes: int = 0):
        self.code = code
        self.read_bytes = read_bytes
        super().__init__(code)


def _relative(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1024 or "\x00" in value:
        raise KitError("Watched/result paths must be nonempty relative strings of at most 1024 characters")
    value = value.replace("\\", "/")
    parts = PurePosixPath(value).parts
    if value.startswith("/") or ":" in value or ".." in parts or not parts:
        raise KitError("Watched/result paths must stay inside the workspace without parent traversal")
    if any(part.endswith((".", " ")) for part in parts):
        raise KitError("Watched/result path components cannot end in a dot or space")
    return PurePosixPath(value).as_posix()


def _regular_path(root: Path, relative: str):
    path = root
    for part in PurePosixPath(relative).parts:
        path = path / part
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
            raise WatchReadError("unsafe_path")
    if not stat.S_ISREG(info.st_mode):
        raise WatchReadError("not_regular")
    return path, info


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read(root: Path, relative: str, remaining: int, *, keep_bytes=False):
    """Reject observed instability around a bounded regular-file read."""
    total = 0
    try:
        path, before = _regular_path(root, relative)
        if before.st_size > remaining:
            raise WatchReadError("size_limit")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        digest, chunks = hashlib.sha256(), []
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or _identity(opened) != _identity(before):
                raise WatchReadError("unstable")
            while True:
                block = stream.read(min(65536, remaining - total + 1))
                if not block:
                    break
                total += len(block)
                if total > remaining:
                    raise WatchReadError("size_limit")
                digest.update(block)
                if keep_bytes:
                    chunks.append(block)
            if _identity(os.fstat(stream.fileno())) != _identity(opened) or total != opened.st_size:
                raise WatchReadError("unstable")
        _, after = _regular_path(root, relative)
        if _identity(before) != _identity(after):
            raise WatchReadError("unstable")
        return {"path": relative, "sha256": digest.hexdigest(), "size_bytes": total}, b"".join(chunks)
    except FileNotFoundError as error:
        raise WatchReadError("missing", total) from error
    except (OSError, ValueError) as error:
        if isinstance(error, WatchReadError):
            error.read_bytes = total
            raise
        raise WatchReadError("unreadable", total) from error


def _capture(root: Path, paths: list[str], *, strict: bool) -> list[dict[str, Any]]:
    records, remaining = [], MAX_TOTAL_BYTES
    for relative in paths:
        try:
            record, _ = _read(root, relative, remaining)
            remaining -= record["size_bytes"]
        except WatchReadError as error:
            if strict:
                raise KitError(f"Cannot watch {relative}: {error.code}") from error
            record = {"path": relative, "error": error.code}
            # Count bytes consumed by failed/unstable reads too, without making
            # an unrelated unchanged file look oversized after a missing file.
            remaining = max(0, remaining - error.read_bytes)
        records.append(record)
    return records


def prepare_watch(workspace: str | Path, paths: list[str]) -> list[dict[str, Any]]:
    if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_FILES:
        raise KitError(f"--watch requires 1 to {MAX_FILES} explicit files")
    normalized = [_relative(path) for path in paths]
    if len({os.path.normcase(path) for path in normalized}) != len(normalized):
        raise KitError("Duplicate watched paths are not allowed")
    return _capture(workspace_root(workspace), normalized, strict=True)


def finish_watch(workspace: str | Path, before: list[dict[str, Any]]) -> dict[str, Any]:
    after = _capture(workspace_root(workspace), [item["path"] for item in before], strict=False)
    return {"version": 1, "before": before, "after": after,
            "changed_during_run": before != after}


def _validate_snapshot(snapshot) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(snapshot, dict) or set(snapshot) != {"version", "before", "after", "changed_during_run"}:
        raise KitError("Missing or malformed watched_files snapshot; run again with --watch")
    if type(snapshot["version"]) is not int or snapshot["version"] != 1 or type(snapshot["changed_during_run"]) is not bool:
        raise KitError("Unsupported or malformed watched_files snapshot version/flag")
    for phase in ("before", "after"):
        records = snapshot[phase]
        if not isinstance(records, list) or not 1 <= len(records) <= MAX_FILES:
            raise KitError("Invalid watched file count")
        paths, total = [], 0
        for item in records:
            if not isinstance(item, dict) or "path" not in item:
                raise KitError("Malformed watched file record")
            normalized = _relative(item["path"])
            if normalized != item["path"]:
                raise KitError("Stored watched paths must be normalized")
            paths.append(os.path.normcase(normalized))
            if phase == "after" and set(item) == {"path", "error"}:
                if not isinstance(item["error"], str) or item["error"] not in ERRORS:
                    raise KitError("Invalid snapshot read error")
                continue
            if set(item) != {"path", "sha256", "size_bytes"} or not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
                raise KitError("Malformed watched SHA256 record")
            if type(item["size_bytes"]) is not int or not 0 <= item["size_bytes"] <= MAX_TOTAL_BYTES:
                raise KitError("Invalid watched file size")
            total += item["size_bytes"]
        if len(set(paths)) != len(paths) or total > MAX_TOTAL_BYTES:
            raise KitError("Duplicate watched paths or snapshot exceeds content limit")
    before, after = snapshot["before"], snapshot["after"]
    if [item["path"] for item in before] != [item["path"] for item in after]:
        raise KitError("Before/after watched paths must match in order")
    if snapshot["changed_during_run"] != (before != after):
        raise KitError("Inconsistent changed_during_run flag")
    return before, after


def check_evidence(workspace: str | Path, result_path: str) -> dict[str, Any]:
    root = workspace_root(workspace)
    relative = _relative(result_path)
    try:
        _, raw = _read(root, relative, MAX_RESULT_BYTES, keep_bytes=True)
        record = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                            parse_constant=lambda value: (_ for _ in ()).throw(KitError("Invalid JSON number")))
    except (WatchReadError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise KitError(f"Cannot read a stable valid result.json: {error}") from error
    if not isinstance(record, dict) or record.get("launched") is not True or type(record.get("ok")) is not bool:
        raise KitError("Result must describe a launched command with a boolean ok field")
    _, after = _validate_snapshot(record.get("watched_files"))
    current = _capture(root, [item["path"] for item in after], strict=False)
    changed = record["watched_files"]["changed_during_run"]
    issues = [{"type": "changed_during_run", "message": "A watched file changed or could not be read stably after execution"}] if changed else []
    for expected, observed in zip(after, current):
        if "error" in observed:
            issues.append({"path": observed["path"], "type": observed["error"]})
        elif "error" in expected:
            issues.append({"path": observed["path"], "type": "post_run_snapshot_unavailable"})
        elif expected != observed:
            issues.append({"path": observed["path"], "type": "content_changed"})
    return {"fresh": not issues, "execution_ok": record["ok"], "tracked_count": len(after),
            "changed_during_run": changed, "issues": issues,
            "bounds": {"max_files": MAX_FILES, "max_total_bytes_per_read_pass": MAX_TOTAL_BYTES}, "limits": LIMITS}
