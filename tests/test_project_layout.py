import ast
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "tennis_video_helper"


def test_source_tree_is_grouped_by_responsibility() -> None:
    expected_packages = {
        "app",
        "core",
        "detection",
        "media",
        "review",
        "ui",
    }

    assert expected_packages <= {
        path.name for path in PACKAGE.iterdir() if path.is_dir()
    }


def test_legacy_flat_modules_and_root_models_are_gone() -> None:
    legacy_modules = {
        "audio.py",
        "cli.py",
        "config.py",
        "exporter.py",
        "fusion.py",
        "gui.py",
        "media.py",
        "models.py",
        "nvdec.py",
        "optimizer.py",
        "pipeline.py",
        "report.py",
        "review.py",
        "runtime_tools.py",
        "vision.py",
    }

    assert not legacy_modules & {
        path.name for path in PACKAGE.iterdir() if path.is_file()
    }
    assert not (ROOT / "yolo11n-pose.onnx").exists()
    assert not (ROOT / "yolo11n.onnx").exists()
    assert not (ROOT / "main.py").exists()


def test_console_entry_points_follow_the_new_layers() -> None:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]

    assert project["scripts"] == {
        "tennis-video-helper": "tennis_video_helper.app.cli:app",
        "tennis-video-helper-gui": "tennis_video_helper.ui.main_window:main",
    }
    assert project["version"] == "0.1.2"


def test_lower_layers_do_not_depend_on_application_or_ui() -> None:
    forbidden = {
        "core": {"app", "detection", "media", "review", "ui"},
        "media": {"app", "detection", "review", "ui"},
        "detection": {"app", "review", "ui"},
        "review": {"app", "detection", "ui"},
    }

    for layer, forbidden_layers in forbidden.items():
        for source in (PACKAGE / layer).rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            imported_layers = {
                node.module.split(".")[1]
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("tennis_video_helper.")
                and len(node.module.split(".")) > 1
            }
            assert not imported_layers & forbidden_layers, source
