from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_repository_has_a_chinese_contribution_guide() -> None:
    guide = ROOT / "CONTRIBUTING.md"
    redirect = ROOT / "docs" / "contributing.html"

    assert guide.is_file()
    assert redirect.is_file()
    assert "blob/main/CONTRIBUTING.md" in redirect.read_text(encoding="utf-8")

    text = guide.read_text(encoding="utf-8")
    assert "uv sync --extra dev" in text
    assert "uv run pytest -q" in text
    assert "src/tennis_video_helper/detection/audio.py" in text
    assert "src/tennis_video_helper/detection/vision/" in text
    assert "src/tennis_video_helper/detection/fusion.py" in text
    assert "tests/app/test_pipeline.py" in text
    assert "不要提交私人训练视频" in text
