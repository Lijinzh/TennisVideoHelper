"""Atomically publish generated media directories on Windows and POSIX."""

from __future__ import annotations

from pathlib import Path
import shutil
import time
import uuid


def replace_path_with_retry(
    source: Path,
    target: Path,
    *,
    attempts: int = 12,
    delay_seconds: float = 0.5,
) -> None:
    """Rename a path while tolerating short-lived Windows filesystem locks."""

    last_error: PermissionError | None = None
    for attempt in range(attempts):
        try:
            source.replace(target)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(delay_seconds)
    assert last_error is not None
    raise last_error


def replace_output_directory(working_dir: Path, output_dir: Path) -> None:
    """Publish a completed directory and restore the old result on failure."""

    backup_dir: Path | None = None
    if output_dir.exists():
        backup_dir = output_dir.with_name(
            f".{output_dir.name}.backup-{uuid.uuid4().hex}"
        )
        replace_path_with_retry(output_dir, backup_dir)
    try:
        replace_path_with_retry(working_dir, output_dir)
    except Exception:
        if backup_dir is not None and backup_dir.exists() and not output_dir.exists():
            replace_path_with_retry(backup_dir, output_dir)
        raise
    if backup_dir is not None:
        shutil.rmtree(backup_dir, ignore_errors=True)
