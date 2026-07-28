# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

project_root = Path(SPEC).resolve().parent.parent
package_edition = os.environ.get("TVH_PACKAGE_EDITION", "full").casefold()
compact_package = package_edition == "compact"
package_directory_name = "TennisVideoHelper-Compact" if compact_package else "TennisVideoHelper"
runtime_dir = project_root / "runtime"
runtime_files = (
    [(str(path), "runtime") for path in runtime_dir.iterdir() if path.is_file()]
    if runtime_dir.is_dir()
    else []
)
model_files = [
    (str(path), "models")
    for path in (
        project_root / "yolo11n-pose.pt",
        project_root / "yolo11n.onnx",
    )
    if path.is_file()
]
icon_files = [(str(project_root / "assets" / "app_icon.png"), "assets")]
engine_cache = Path.home() / ".cache" / "tennis-video-helper" / "engines"
engine_files = (
    [(str(path), "engines") for path in engine_cache.glob("*.engine")]
    if engine_cache.is_dir()
    else []
)
pynv_datas, pynv_binaries, pynv_hiddenimports = collect_all("PyNvVideoCodec")
pynv_package = project_root / ".venv" / "Lib" / "site-packages" / "PyNvVideoCodec"
if pynv_package.is_dir():
    pynv_binaries.extend(
        (str(path), "PyNvVideoCodec") for path in pynv_package.glob("*.pyd")
    )
pynv_hiddenimports.extend(
    [
        "PyNvVideoCodec.VersionCheck",
        "PyNvVideoCodec.PyNvVideoCodec_121",
        "PyNvVideoCodec.PyNvVideoCodec_130",
        "PyNvVideoCodec.decoders.SimpleDecoder",
        "PyNvVideoCodec.decoders.ThreadedDecoder",
    ]
)

excluded_modules = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner",
    "pytest",
]
if compact_package:
    excluded_modules.extend(
        [
            "cupy",
            "cupy_backends",
            "modelopt",
            "nvidia_modelopt",
            "onnx",
            "onnxruntime",
            "onnxslim",
            "polygraphy",
            "polars",
            "tensorrt",
            "tensorrt_bindings",
            "tensorrt_libs",
        ]
    )

a = Analysis(
    [str(project_root / "src" / "tennis_video_helper" / "gui.py")],
    pathex=[str(project_root / "src")],
    binaries=pynv_binaries,
    datas=[*runtime_files, *model_files, *engine_files, *icon_files, *pynv_datas],
    hiddenimports=["tennis_video_helper.cli", *pynv_hiddenimports],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

worker_a = Analysis(
    [str(project_root / "src" / "tennis_video_helper" / "cli.py")],
    pathex=[str(project_root / "src")],
    binaries=pynv_binaries,
    datas=[*runtime_files, *model_files, *engine_files, *icon_files, *pynv_datas],
    hiddenimports=pynv_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=1,
)
worker_pyz = PYZ(worker_a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TennisVideoHelper",
    icon=str(project_root / "assets" / "app_icon.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

worker_exe = EXE(
    worker_pyz,
    worker_a.scripts,
    [],
    exclude_binaries=True,
    name="TennisVideoHelperWorker",
    icon=str(project_root / "assets" / "app_icon.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    worker_exe,
    a.binaries,
    a.datas,
    worker_a.binaries,
    worker_a.datas,
    strip=False,
    upx=True,
    upx_exclude=["*.dll"],
    name=package_directory_name,
)
