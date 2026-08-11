from pathlib import Path

from tennis_video_helper import resources


def test_source_assets_resolve_from_grouped_directories() -> None:
    icon = resources.asset_path("icons", "app_icon.png")
    pose_model = resources.asset_path("models", "yolo11n-pose.onnx")

    assert icon == (resources.PROJECT_ROOT / "assets/icons/app_icon.png").resolve()
    assert pose_model == (
        resources.PROJECT_ROOT / "assets/models/yolo11n-pose.onnx"
    ).resolve()


def test_asset_override_takes_priority(monkeypatch, tmp_path: Path) -> None:
    overridden = tmp_path / "app_icon.png"
    overridden.write_bytes(b"override")
    monkeypatch.setenv("TVH_ICON_DIR", str(tmp_path))

    assert resources.asset_path("icons", "app_icon.png") == overridden.resolve()
