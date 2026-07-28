"""Resolve media tools from a bundled runtime or the host PATH."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _configure_bundled_library_path() -> None:
    """Expose PyInstaller's shared DLL directory to bundled FFmpeg subprocesses."""

    bundle_root = getattr(sys, "_MEIPASS", None)
    if not bundle_root or os.name != "nt":
        return
    root = str(Path(bundle_root).resolve())
    entries = os.environ.get("PATH", "").split(os.pathsep)
    if root.casefold() not in {entry.casefold() for entry in entries if entry}:
        os.environ["PATH"] = root + os.pathsep + os.environ.get("PATH", "")


_configure_bundled_library_path()


def media_executable(name: str) -> str:
    """Return a bundled FFmpeg executable when present, otherwise its PATH name."""

    executable_name = f"{name}.exe" if os.name == "nt" else name
    for directory in _runtime_directories():
        candidate = directory / executable_name
        if candidate.is_file():
            return str(candidate)
    return name


def media_tool_available(name: str) -> bool:
    """Check whether a bundled or system media executable can be launched."""

    executable = media_executable(name)
    return Path(executable).is_file() or shutil.which(executable) is not None


def subprocess_no_window_kwargs() -> dict[str, int]:
    """Return flags that keep helper executables hidden on Windows."""

    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def _runtime_directories() -> tuple[Path, ...]:
    directories: list[Path] = []
    override = os.environ.get("TVH_FFMPEG_DIR")
    if override:
        directories.append(Path(override).expanduser())

    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        directories.append(Path(bundle_root) / "runtime")

    directories.extend(
        (
            Path(sys.executable).resolve().parent / "runtime",
            Path(__file__).resolve().parents[2] / "runtime",
        )
    )
    return tuple(dict.fromkeys(directory.resolve() for directory in directories))
