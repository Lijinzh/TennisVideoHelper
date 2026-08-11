# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path(SPEC).resolve().parent.parent
runtime_dir = project_root / "runtime"
runtime_files = (
    [(str(path), "runtime") for path in runtime_dir.iterdir() if path.is_file()]
    if runtime_dir.is_dir()
    else []
)
model_files = [
    (str(project_root / "assets" / "models" / "yolo11n-pose.onnx"), "assets/models"),
    (str(project_root / "assets" / "models" / "yolo11n.onnx"), "assets/models"),
]
icon_files = [
    (str(project_root / "assets" / "icons" / icon_name), "assets/icons")
    for icon_name in ("app_icon.png", "app_icon.ico")
]

excluded_modules = [
    "torch",
    "torchvision",
    "ultralytics",
    "tensorrt",
    "tensorrt_bindings",
    "tensorrt_libs",
    "onnx",
    "onnxslim",
    "modelopt",
    "nvidia_modelopt",
    "cupy",
    "cupy_backends",
    "PyNvVideoCodec",
    "polars",
    "matplotlib",
    "sklearn",
    "scipy",
    "librosa",
    "numba",
    "llvmlite",
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

common = dict(
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[*runtime_files, *model_files, *icon_files],
    hiddenimports=["onnxruntime.capi._pybind_state"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=1,
)

gui_a = Analysis(
    [str(project_root / "src" / "tennis_video_helper" / "ui" / "main_window.py")],
    **common,
)
worker_a = Analysis(
    [str(project_root / "src" / "tennis_video_helper" / "app" / "cli.py")],
    **common,
)
gui_pyz = PYZ(gui_a.pure)
worker_pyz = PYZ(worker_a.pure)

gui_exe = EXE(
    gui_pyz,
    gui_a.scripts,
    [],
    exclude_binaries=True,
    name="TennisVideoHelper",
    icon=str(project_root / "assets" / "icons" / "app_icon.ico"),
    console=False,
    optimize=1,
)
worker_exe = EXE(
    worker_pyz,
    worker_a.scripts,
    [],
    exclude_binaries=True,
    name="TennisVideoHelperWorker",
    icon=str(project_root / "assets" / "icons" / "app_icon.ico"),
    console=False,
    optimize=1,
)

COLLECT(
    gui_exe,
    worker_exe,
    gui_a.binaries,
    gui_a.datas,
    worker_a.binaries,
    worker_a.datas,
    strip=False,
    upx=True,
    upx_exclude=["*.dll"],
    name="TennisVideoHelper-Light",
)
