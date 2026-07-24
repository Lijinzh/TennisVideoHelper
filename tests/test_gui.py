import os
from pathlib import Path

import pytest
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tennis_video_helper.gui import (
    AnalysisFormValues,
    MainWindow,
    VIDEO_FILE_FILTER,
    build_analyze_arguments,
    build_stop_command,
    parse_output_path,
    parse_paths,
    process_ids_match,
)


def test_build_analyze_arguments_includes_paths_and_parameters() -> None:
    values = AnalysisFormValues(
        input_path=Path("D:/videos"),
        output_path=Path("D:/selected"),
        min_rally_duration=15.0,
        pre_roll=2.5,
        post_roll=3.5,
        end_silence=4.0,
        analysis_fps=10,
        audio_sensitivity=1.1,
        visual_sensitivity=0.9,
        limit_duration=300.0,
    )

    arguments = build_analyze_arguments(values)

    assert arguments[:3] == ["-m", "tennis_video_helper.cli", "analyze"]
    assert str(values.input_path) in arguments
    assert str(values.output_path) in arguments
    assert arguments[arguments.index("--min-rally-duration") + 1] == "15"
    assert arguments[arguments.index("--analysis-fps") + 1] == "10"
    assert arguments[arguments.index("--limit-duration") + 1] == "300"


def test_build_analyze_arguments_omits_unlimited_duration() -> None:
    values = AnalysisFormValues(
        input_path=Path("D:/videos"),
        output_path=Path("D:/selected"),
        min_rally_duration=10.0,
        pre_roll=2.0,
        post_roll=3.0,
        end_silence=3.5,
        analysis_fps=12,
        audio_sensitivity=1.0,
        visual_sensitivity=1.0,
        limit_duration=None,
    )

    assert "--limit-duration" not in build_analyze_arguments(values)


def test_parse_paths_rejects_empty_output() -> None:
    with pytest.raises(ValueError, match="输出文件夹"):
        parse_paths("D:/videos", "   ")


def test_parse_output_path_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="输出文件夹"):
        parse_output_path("  ")


def test_video_file_filter_only_advertises_supported_formats() -> None:
    assert "*.avi" not in VIDEO_FILE_FILTER.lower()
    for extension in ("mp4", "mov", "mkv", "m4v"):
        assert f"*.{extension}" in VIDEO_FILE_FILTER.lower()


def test_build_stop_command_terminates_windows_process_tree() -> None:
    assert build_stop_command(4321, platform="nt") == [
        "taskkill",
        "/PID",
        "4321",
        "/T",
        "/F",
    ]


def test_process_ids_match_only_for_same_running_task() -> None:
    assert process_ids_match(4321, 4321) is True
    assert process_ids_match(4321, 9876) is False
    assert process_ids_match(0, 0) is False


def test_failed_process_start_restores_idle_ui() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._set_running(True)
    window.elapsed_timer.start()

    window._process_error(QProcess.ProcessError.FailedToStart)

    assert window.start_button.isEnabled() is True
    assert window.stop_button.isEnabled() is False
    assert window.elapsed_timer.isActive() is False
    assert "启动失败" in window.status_badge.text()
    window.close()
    app.processEvents()
