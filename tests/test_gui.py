import os
from pathlib import Path
import time

import pytest
from PySide6.QtCore import QProcess, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tennis_video_helper.gui import (
    AnalysisFormValues,
    ParameterTile,
    MainWindow,
    VIDEO_FILE_FILTER,
    build_analyze_arguments,
    build_stop_command,
    format_clock,
    parse_output_path,
    parse_paths,
    parse_acceleration_line,
    parse_progress_line,
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
    assert arguments[arguments.index("--backend") + 1] == "auto"
    assert arguments[arguments.index("--precision") + 1] == "fp16"
    assert arguments[arguments.index("--batch-size") + 1] == "16"
    assert "--progress-json" in arguments
    assert "--allow-cpu" in arguments
    assert "--overwrite-existing" in arguments
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


def test_parameter_spin_boxes_keep_text_area_visible() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.processEvents()

    for control in (
        window.min_rally,
        window.pre_roll,
        window.post_roll,
        window.end_silence,
        window.analysis_fps,
        window.audio_sensitivity,
        window.visual_sensitivity,
        window.inference_batch_size,
    ):
        assert control.text()
        assert control.lineEdit().height() >= control.fontMetrics().height()

    window.close()
    app.processEvents()


def test_initial_view_focuses_primary_action_and_stays_at_top() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1100, 760)
    window.show()
    app.processEvents()

    window.page_scroll.verticalScrollBar().setValue(
        window.page_scroll.verticalScrollBar().maximum()
    )
    window._show_initial_view()

    assert window.start_button.hasFocus()
    assert window.page_scroll.verticalScrollBar().value() == 0

    window.close()
    app.processEvents()


def test_portrait_workspace_fits_primary_controls_without_scrolling() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1100, 760)
    window.show()
    app.processEvents()

    central = window.centralWidget()
    preview_position = window.preview.mapTo(central, window.preview.rect().topLeft())
    start_position = window.start_button.mapTo(
        central, window.start_button.rect().topLeft()
    )
    input_position = window.input_edit.mapTo(
        central, window.input_edit.rect().topLeft()
    )

    assert window.preview.width() < window.preview.height()
    assert start_position.x() > preview_position.x() + window.preview.width()
    assert input_position.x() > start_position.x()
    assert window.page_scroll.verticalScrollBar().maximum() == 0

    window.close()
    app.processEvents()


def test_reference_layout_balances_status_and_fills_log_card() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1100, 760)
    window.show()
    QTest.qWait(80)
    app.processEvents()

    status_panel = window.start_button.parentWidget()
    workbench = status_panel.parentWidget()
    log_card = window.log.parentWidget()
    main_gaps = [
        window.percent_label.geometry().top()
        - window.acceleration_label.geometry().bottom()
        - 1,
        window.progress.geometry().top() - window.phase_label.geometry().bottom() - 1,
        window.task_summary_label.geometry().top()
        - max(
            window.elapsed_label.geometry().bottom(),
            window.eta_label.geometry().bottom(),
        )
        - 1,
    ]

    compact_workbench_height = workbench.height()
    compact_log_height = window.log.height()
    assert compact_workbench_height >= 352
    assert workbench.geometry().top() <= 100
    assert max(main_gaps) - min(main_gaps) <= 2
    assert window.log.height() >= 115
    assert window.log.geometry().top() <= 45
    assert log_card.height() - window.log.geometry().bottom() - 1 <= 20

    window.resize(1440, 920)
    QTest.qWait(80)
    app.processEvents()

    assert window.workbench_card.height() > compact_workbench_height
    assert window.log.height() > compact_log_height
    assert window.page_scroll.verticalScrollBar().maximum() == 0

    window.close()
    app.processEvents()


def test_parameter_tiles_and_large_buttons_do_not_overlap() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1100, 760)
    window.show()
    app.processEvents()

    tiles = window.findChildren(ParameterTile)
    assert tiles
    for tile in tiles:
        assert tile.control.geometry().bottom() < tile.note.geometry().top()

    assert window.min_rally._up_button.width() >= 28
    assert window.min_rally._up_button.height() >= 18
    assert window.min_rally._down_button.width() >= 28
    assert window.min_rally._down_button.height() >= 18
    original_value = window.min_rally.value()
    QTest.mouseClick(window.min_rally._up_button, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert window.min_rally.value() == pytest.approx(original_value + 0.5)

    window.close()
    app.processEvents()


def test_progress_payload_updates_visible_status() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._started_at = time.monotonic() - 20

    window._apply_progress(
        {
            "percent": 42.5,
            "phase": "GPU 分析画面",
            "current_video": None,
            "video_index": 2,
            "video_total": 4,
        }
    )

    assert window.progress.value() == 425
    assert window.progress.format() == "42.5%"
    assert window.percent_label.text() == "42%"
    assert window.phase_label.text() == "GPU 分析画面"
    assert window.video_count_label.text() == "第 2/4 个视频"
    assert window.eta_label.text() != "正在估算"

    window.close()
    app.processEvents()


def test_acceleration_payload_shows_actual_gpu_backend() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    payload = parse_acceleration_line(
        'TVH_ACCELERATION {"cuda_available":true,"nvenc_available":true,'
        '"device_name":"RTX 4060","inference_backend":"TensorRT",'
        '"precision":"FP16","decoder":"NVDEC","encoder":"NVENC"}'
    )
    assert payload is not None
    window._apply_acceleration_status(payload)

    assert "GPU 加速：已启用" in window.acceleration_label.text()
    assert "TensorRT FP16" in window.acceleration_label.text()
    assert "NVDEC" in window.acceleration_label.text()
    assert window.acceleration_label.property("mode") == "enabled"

    window._apply_acceleration_status(
        {
            "cuda_available": False,
            "nvenc_available": False,
            "inference_backend": "CPU",
            "decoder": "OpenCV",
            "encoder": "libx265",
        }
    )
    assert "已回退 CPU" in window.acceleration_label.text()
    assert window.acceleration_label.property("mode") == "cpu"

    window.close()
    app.processEvents()


def test_progress_line_and_clock_formatting() -> None:
    payload = parse_progress_line(
        'TVH_PROGRESS {"percent":12.5,"phase":"读取视频信息","video_total":2}'
    )

    assert payload is not None
    assert payload["percent"] == 12.5
    assert parse_progress_line("普通日志") is None
    assert parse_progress_line("TVH_PROGRESS invalid") is None
    assert format_clock(3661) == "01:01:01"
