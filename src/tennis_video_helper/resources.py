"""Resolve source-tree and bundled application resources from one place."""

from __future__ import annotations

import os
from pathlib import Path
import sys


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[1]
_ASSET_ENVIRONMENT = {
    "icons": "TVH_ICON_DIR",
    "models": "TVH_MODEL_DIR",
}


def asset_path(category: str, path: str | Path) -> Path | None:
    """Return an explicit, overridden, bundled, or source-tree asset path."""

    requested = Path(path).expanduser()
    if requested.is_file():
        return requested.resolve()

    candidates: list[Path] = []
    override = os.environ.get(_ASSET_ENVIRONMENT.get(category, ""))
    if override:
        candidates.append(Path(override).expanduser() / requested.name)

    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "assets" / category / requested.name)

    candidates.extend(
        (
            Path(sys.executable).resolve().parent
            / "assets"
            / category
            / requested.name,
            PROJECT_ROOT / "assets" / category / requested.name,
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def project_directory(name: str) -> Path:
    """Return a repository-level runtime directory for source installations."""

    return PROJECT_ROOT / name
