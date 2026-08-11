from pathlib import Path
import subprocess

from tennis_video_helper.media import runtime as runtime_tools


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
        "project_directory",
        lambda _name: tmp_path / "missing-runtime",
    )

    assert runtime_tools.media_executable("ffmpeg") == "ffmpeg"


def test_subprocess_no_window_kwargs_hides_helpers_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(runtime_tools.os, "name", "nt")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    assert runtime_tools.subprocess_no_window_kwargs() == {
        "creationflags": 0x08000000
    }


def test_subprocess_no_window_kwargs_is_empty_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(runtime_tools.os, "name", "posix")

    assert runtime_tools.subprocess_no_window_kwargs() == {}
