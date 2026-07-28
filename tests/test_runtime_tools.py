from pathlib import Path

from tennis_video_helper import runtime_tools


def test_media_executable_prefers_override(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "ffmpeg.exe"
    executable.write_bytes(b"test")
    monkeypatch.setenv("TVH_FFMPEG_DIR", str(tmp_path))

    assert runtime_tools.media_executable("ffmpeg") == str(executable)
    assert runtime_tools.media_tool_available("ffmpeg") is True


def test_media_executable_falls_back_to_command_name(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TVH_FFMPEG_DIR", str(tmp_path))
    monkeypatch.setattr(runtime_tools.sys, "executable", str(tmp_path / "python.exe"))
    monkeypatch.setattr(
        runtime_tools,
        "__file__",
        str(tmp_path / "src" / "package" / "runtime_tools.py"),
    )

    assert runtime_tools.media_executable("ffmpeg") == "ffmpeg"
