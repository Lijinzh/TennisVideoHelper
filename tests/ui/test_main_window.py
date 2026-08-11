import os
from pathlib import Path
import time

import pytest
from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QSizePolicy

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tennis_video_helper.ui.main_window import (
    AnalysisFormValues,
    HitTimeline,
    ParameterTile,
    MainWindow,
    MixedProcessOutputDecoder,
    VIDEO_FILE_FILTER,
    build_analyze_arguments,
    build_optimize_arguments,
    build_stop_command,
    decode_utf8_chunks,
    empty_candidate_guidance,
    format_analysis_scope,
    format_clock,
    incompatible_analysis_scope_message,
    parse_output_path,
    parse_paths,
    parse_acceleration_line,
    parse_optimization_line,
    parse_progress_line,
    parse_review_line,
    process_invocation,
    process_ids_match,
)
import tennis_video_helper.ui.main_window as gui_module
from tennis_video_helper.core.models import MediaInfo, RallySegment
from tennis_video_helper.review.session import (
    ReviewClipCandidate,
    ReviewHit,
    ReviewSession,
    ReviewVideoCandidate,
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

    assert arguments[:3] == ["-m", "tennis_video_helper.app.cli", "analyze"]
    assert str(values.input_path) in arguments
    assert str(values.output_path) in arguments
    assert arguments[arguments.index("--min-rally-duration") + 1] == "15"
    assert arguments[arguments.index("--min-confirmed-hits") + 1] == "3"
    assert arguments[arguments.index("--analysis-fps") + 1] == "10"
    assert arguments[arguments.index("--backend") + 1] == "auto"
    assert arguments[arguments.index("--precision") + 1] == "fp16"
    assert arguments[arguments.index("--batch-size") + 1] == "16"
    assert "--progress-json" in arguments
    assert "--prepare-review" in arguments
    assert "--allow-cpu" in arguments
    assert "--1080p-output" in arguments
    assert "--overwrite-existing" in arguments
    assert arguments[arguments.index("--limit-duration") + 1] == "300"


def test_windows_app_user_model_id_is_registered(monkeypatch) -> None:
    registered: list[str] = []

    class FakeShell32:
        def SetCurrentProcessExplicitAppUserModelID(self, value: str) -> None:
            registered.append(value)

    class FakeWindll:
        shell32 = FakeShell32()

    monkeypatch.setattr(gui_module.os, "name", "nt")
    monkeypatch.setattr(gui_module.ctypes, "windll", FakeWindll())

    gui_module._set_windows_app_user_model_id()

    assert registered == [gui_module.WINDOWS_APP_USER_MODEL_ID]


def test_source_run_prefers_windows_ico(monkeypatch) -> None:
    monkeypatch.setattr(gui_module.os, "name", "nt")

    assert gui_module._app_icon_path() is not None
    assert gui_module._app_icon_path().suffix == ".ico"


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


def test_build_analyze_arguments_can_request_original_quality() -> None:
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
        export_original_quality=True,
    )

    arguments = build_analyze_arguments(values)

    assert "--original-quality" in arguments
    assert "--1080p-output" not in arguments


def test_build_optimize_arguments_uses_real_video_and_progress_protocol() -> None:
    arguments = build_optimize_arguments(Path("D:/videos/match.mov"), 45)

    assert arguments[:3] == ["-m", "tennis_video_helper.app.cli", "optimize"]
    assert arguments[3] == "D:\\videos\\match.mov" or arguments[3] == "D:/videos/match.mov"
    assert arguments[arguments.index("--benchmark-seconds") + 1] == "45"
    assert "--progress-json" in arguments


def test_frozen_process_invocation_reuses_packaged_executable(monkeypatch) -> None:
    monkeypatch.setattr("tennis_video_helper.ui.main_window.sys.frozen", True, raising=False)
    monkeypatch.setattr("tennis_video_helper.ui.main_window.sys.executable", "TennisVideoHelper.exe")

    program, arguments = process_invocation(
        ["-m", "tennis_video_helper.app.cli", "optimize", "sample.mov"]
    )

    assert program == "TennisVideoHelperWorker.exe"
    assert arguments == ["optimize", "sample.mov"]


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
        window.min_confirmed_hits,
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


def test_review_workspace_fits_primary_controls_without_scrolling() -> None:
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

    candidate_position = window.candidate_list.mapTo(
        central, window.candidate_list.rect().topLeft()
    )
    assert window.preview.width() > window.preview.height()
    assert candidate_position.x() < preview_position.x()
    assert start_position.x() > preview_position.x() + window.preview.width()
    assert input_position.y() < preview_position.y()
    assert window.page_scroll.verticalScrollBar().maximum() == 0

    window.close()
    app.processEvents()


def test_reference_layout_uses_space_for_large_preview_without_log_panel() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1100, 760)
    window.show()
    QTest.qWait(80)
    app.processEvents()

    status_panel = window.start_button.parentWidget()
    workbench = status_panel.parentWidget()
    compact_workbench_height = workbench.height()
    compact_preview_size = window.preview.size()
    assert compact_workbench_height >= 500
    assert not hasattr(window, "log")
    assert window.preview.width() >= 420
    assert window.preview.height() >= 300
    assert window.candidate_list.height() >= 300

    window.resize(1440, 920)
    QTest.qWait(80)
    app.processEvents()

    assert window.workbench_card.height() > compact_workbench_height
    assert window.preview.width() >= compact_preview_size.width()
    assert window.preview.height() > compact_preview_size.height()
    assert window.page_scroll.verticalScrollBar().maximum() == 0

    window.close()
    app.processEvents()


def test_parameter_tiles_and_large_buttons_do_not_overlap() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1100, 760)
    window.show()
    window.parameters_action.trigger()
    app.processEvents()

    tiles = window.findChildren(ParameterTile)
    assert tiles
    for tile in tiles:
        assert tile.control.geometry().bottom() < tile.note.geometry().top()

    assert window.min_rally._up_button.width() >= 28
    assert window.min_rally._up_button.height() >= 18
    assert window.min_rally._down_button.width() >= 28
    assert isinstance(
        window.playback_rate_control,
        gui_module.LargeArrowDoubleSpinBox,
    )
    assert window.playback_rate_control._up_button.width() >= 28
    assert window.playback_rate_control._down_button.height() >= 18
    assert window.min_rally._down_button.height() >= 18
    original_value = window.min_rally.value()
    QTest.mouseClick(window.min_rally._up_button, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert window.min_rally.value() == pytest.approx(original_value + 0.5)

    window.close()
    app.processEvents()


def test_standard_menu_contains_input_output_and_parameter_actions() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.processEvents()

    menu_titles = [action.text() for action in window.menuBar().actions()]
    assert any("文件" in title for title in menu_titles)
    assert any("编辑" in title for title in menu_titles)
    assert any("视图" in title for title in menu_titles)
    assert any("帮助" in title for title in menu_titles)
    assert "分析与复核" not in window.findChild(QLabel, "heroTitle").text()
    assert window.start_button.text() == "开始分析"
    assert window.settings_button.text() == "参数调节"
    assert window.parameters_action.text() == "参数调节"
    assert window.parameters_action.isCheckable() is False
    assert window.settings_button.isCheckable() is False
    assert window.parameter_card.isHidden() is True

    QTest.mouseClick(window.settings_button, Qt.MouseButton.LeftButton)
    assert window.parameter_card.isVisible() is True
    assert window.settings_button.isHidden() is True
    assert window.workbench_card.isHidden() is True
    assert window.back_to_review_button.text() == "← 返回候选片段"

    QTest.mouseClick(window.back_to_review_button, Qt.MouseButton.LeftButton)
    assert window.parameter_card.isHidden() is True
    assert window.workbench_card.isVisible() is True
    assert window.settings_button.isVisible() is True

    window.close()
    app.processEvents()


def test_analysis_scope_is_visible_and_warns_when_limited() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.analysis_scope_label.text() == "分析范围：完整视频"
    assert window.analysis_scope_label.property("mode") == "complete"

    window.limit_minutes.setValue(0.1)
    window.limit_check.setChecked(True)

    assert "仅前 0.1 分钟" in window.analysis_scope_label.text()
    assert "其余内容不会检查" in window.analysis_scope_label.text()
    assert window.analysis_scope_label.property("mode") == "limited"

    window.close()
    app.processEvents()


def test_empty_candidate_guidance_explains_limited_range() -> None:
    assert format_analysis_scope(None) == "分析范围：完整视频"
    assert "完整视频" in empty_candidate_guidance(None)
    assert "前 0.1 分钟" in empty_candidate_guidance(6.0)
    assert "关闭“仅分析前”" in empty_candidate_guidance(6.0)


def test_analysis_scope_shorter_than_minimum_rally_is_rejected() -> None:
    message = incompatible_analysis_scope_message(6.0, 10.0)

    assert message is not None
    assert "前 6 秒" in message
    assert "最短回合设置为 10 秒" in message
    assert incompatible_analysis_scope_message(10.0, 10.0) is None
    assert incompatible_analysis_scope_message(None, 10.0) is None


def test_primary_analysis_button_is_not_clipped_in_compact_window() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1100, 760)
    window.show()
    app.processEvents()

    text_width = window.start_button.fontMetrics().horizontalAdvance(
        window.start_button.text()
    )
    assert window.start_button.width() >= text_width + 32

    window.close()
    app.processEvents()


def test_parameter_page_content_stays_aligned_to_top() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1440, 920)
    window.show()
    window.parameters_action.trigger()
    app.processEvents()

    section_title = window.parameter_card.findChild(QLabel, "sectionTitle")
    first_tile = window.findChildren(ParameterTile)[0]
    assert section_title is not None
    assert section_title.height() == 32
    assert first_tile.geometry().top() - section_title.geometry().bottom() < 24

    window.close()
    app.processEvents()


def test_hit_timeline_emits_seek_position_and_tracks_hits() -> None:
    app = QApplication.instance() or QApplication([])
    timeline = HitTimeline()
    timeline.resize(500, 54)
    timeline.set_hits(10_000, [2_000, 5_000, 8_000])
    timeline.set_position(5_000)
    positions: list[int] = []
    timeline.seekRequested.connect(positions.append)
    timeline.show()
    app.processEvents()

    QTest.mouseClick(
        timeline,
        Qt.MouseButton.LeftButton,
        pos=timeline.rect().center(),
    )

    assert timeline._hit_positions_ms == (2_000, 5_000, 8_000)
    assert positions and positions[-1] == pytest.approx(5_000, abs=100)
    timeline.close()


def test_review_protocol_line_is_parsed() -> None:
    payload = parse_review_line(
        'TVH_REVIEW {"manifest":"D:/output/.review/review-session.json",'
        '"candidate_count":3}'
    )

    assert payload is not None
    assert payload["candidate_count"] == 3
    assert parse_review_line("普通日志") is None


def test_review_session_populates_selectable_candidates_and_hit_timeline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "source.mp4"
    clip_path = tmp_path / "review" / "clips" / "rally_001.mp4"
    clip_path.parent.mkdir(parents=True)
    clip_path.write_bytes(b"preview")
    media = MediaInfo(
        path=source,
        duration=30.0,
        width=1920,
        height=1080,
        fps=30.0,
        video_codec="h264",
        pixel_format="yuv420p",
        audio_codec="aac",
        audio_sample_rate=48_000,
        audio_channels=2,
        rotation=0,
        color_transfer=None,
        is_hdr10=False,
        is_dolby_vision=False,
    )
    segment = RallySegment(2, 12, 0, 15, 10, 0.9, 3)
    clip = ReviewClipCandidate(
        id="1:1",
        index=1,
        path=clip_path,
        segment=segment,
        hits=(
            ReviewHit(2.0, 2.0, 0.9, "击球一"),
            ReviewHit(8.0, 8.0, 0.8, "击球二"),
        ),
    )
    video = ReviewVideoCandidate(
        source=source,
        output_dir=tmp_path / "output" / "source",
        staging_dir=clip_path.parents[1],
        media=media,
        clips=(clip,),
        audio_events=(),
        visual_events=(),
        fused_events=(),
    )
    cover = QPixmap(32, 18)
    cover.fill(Qt.GlobalColor.green)
    monkeypatch.setattr(gui_module, "_video_thumbnail", lambda _path: cover)
    window = MainWindow()
    window._set_review_session(
        ReviewSession(tmp_path / "review", True, (video,))
    )
    app.processEvents()

    assert window.candidate_list.count() == 1
    assert window.candidate_list.item(0).checkState() == Qt.CheckState.Checked
    assert (
        window.candidate_list.item(0).data(gui_module.CANDIDATE_VIEWED_ROLE)
        is True
    )
    assert window.candidate_list.item(0).text().startswith("已看 · ")
    assert window.selected_count_label.text() == "已选 1/1 段"
    assert window.hit_timeline._hit_positions_ms == (2_000, 8_000)
    assert window.publish_button.isEnabled() is True
    assert window.preview_stack.currentWidget() is window.preview
    assert window.preview._source_pixmap.isNull() is False

    window._preview_state_changed(
        gui_module.QMediaPlayer.PlaybackState.PlayingState
    )
    assert window.preview_stack.currentWidget() is window.video_widget
    window.preview_stack.setCurrentWidget(window.preview)

    window.candidate_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    second_clip_path = clip_path.with_name("rally_002.mp4")
    second_clip_path.write_bytes(b"preview-2")
    second_clip = ReviewClipCandidate(
        id="1:2",
        index=2,
        path=second_clip_path,
        segment=RallySegment(14, 24, 13, 26, 10, 0.9, 4),
        hits=(ReviewHit(3.0, 17.0, 0.9, "击球三"),),
    )
    expanded_video = ReviewVideoCandidate(
        source=video.source,
        output_dir=video.output_dir,
        staging_dir=video.staging_dir,
        media=video.media,
        clips=(clip, second_clip),
        audio_events=video.audio_events,
        visual_events=video.visual_events,
        fused_events=video.fused_events,
    )
    window._set_review_session(
        ReviewSession(tmp_path / "review", True, (expanded_video,))
    )
    app.processEvents()

    assert window.candidate_list.count() == 2
    assert window.candidate_list.item(0).checkState() == Qt.CheckState.Unchecked
    assert window.candidate_list.item(1).checkState() == Qt.CheckState.Checked
    assert (
        window.candidate_list.item(1).data(gui_module.CANDIDATE_VIEWED_ROLE)
        is False
    )
    assert window.candidate_list.currentRow() == 0
    assert window._current_candidate_id == "1:1"
    assert window.selected_count_label.text() == "已选 1/2 段"

    window.candidate_list.setCurrentRow(1)
    app.processEvents()
    assert (
        window.candidate_list.item(1).data(gui_module.CANDIDATE_VIEWED_ROLE)
        is True
    )
    assert window.candidate_list.item(1).text().startswith("已看 · ")

    window._review_session = None
    window.close()
    app.processEvents()


def test_video_playback_widget_cannot_expand_preview_layout() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1100, 760)
    window.show()
    app.processEvents()

    window_size = window.size()
    preview_size = window.preview_stack.size()
    scrollbar_maximum = window.page_scroll.verticalScrollBar().maximum()

    window._preview_state_changed(
        gui_module.QMediaPlayer.PlaybackState.PlayingState
    )
    app.processEvents()

    assert window.video_widget.sizeHint() == gui_module.QSize(0, 0)
    assert window.video_widget.minimumSizeHint() == gui_module.QSize(0, 0)
    assert window.video_widget.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
    assert window.video_widget.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Ignored
    assert window.size() == window_size
    assert window.preview_stack.size() == preview_size
    assert window.page_scroll.verticalScrollBar().maximum() == scrollbar_maximum

    window.close()
    app.processEvents()


def test_playback_rate_and_input_path_are_restored_on_next_launch(
    monkeypatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    stored: dict[str, object] = {}

    class FakeSettings:
        def value(self, key: str, default=None):
            return stored.get(key, default)

        def setValue(self, key: str, value) -> None:  # noqa: N802 - Qt API
            stored[key] = value

        def sync(self) -> None:
            pass

    monkeypatch.setattr(gui_module, "_application_settings", FakeSettings)
    window = MainWindow()

    class FakePlayer:
        def __init__(self) -> None:
            self.rates: list[float] = []

        def setPlaybackRate(self, rate: float) -> None:  # noqa: N802 - Qt API
            self.rates.append(rate)

    fake_player = FakePlayer()
    original_player = window.media_player
    window.media_player = fake_player

    assert window.playback_rate_control.minimum() == 0.25
    assert window.playback_rate_control.maximum() == 4.0
    window.playback_rate_control.setValue(2.75)
    assert fake_player.rates == [2.75]
    window.input_edit.setText("D:/tennis-videos")
    window._input_editing_finished()
    assert stored["preview/playback_rate"] == 2.75
    assert stored["paths/input"] == "D:/tennis-videos"

    window.media_player = original_player
    window.close()
    app.processEvents()

    restored = MainWindow()
    restored.show()
    app.processEvents()
    assert restored.playback_rate_control.value() == 2.75
    assert restored.media_player.playbackRate() == 2.75
    assert restored.input_edit.text() == "D:/tennis-videos"
    assert (
        restored.playback_rate_control.geometry().x()
        > restored.preview_time_label.geometry().x()
    )

    restored.close()
    app.processEvents()


def test_window_theme_can_switch_between_system_light_and_dark_styles() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    window._apply_theme(False)
    assert window._dark_theme is False
    assert window.styleSheet() == gui_module.LIGHT_STYLE_SHEET
    assert "background: #f3f5f7" in window.styleSheet()

    window._apply_theme(True)
    assert window._dark_theme is True
    assert window.styleSheet() == gui_module.DARK_STYLE_SHEET
    assert "background: #0a0b0d" in window.styleSheet()

    window.close()
    app.processEvents()


def test_pixel_theme_uses_segmented_progress_and_readable_chinese_font() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert isinstance(window.progress, gui_module.PixelProgressBar)
    assert isinstance(window.analysis_progress, gui_module.PixelProgressBar)
    assert "border-radius: 0px" in window.styleSheet()
    assert 'font-family: "Microsoft YaHei UI"' in window.styleSheet()
    labels = [label.text() for label in window.findChildren(gui_module.QLabel)]
    assert "■ AI TENNIS WORKFLOW / PIXEL MODE" in labels
    assert window.status_badge.text().startswith("■")
    assert isinstance(window.motion_rail, gui_module.PixelMotionRail)
    assert "border-bottom-width: 6px" in window.styleSheet()
    assert "border-top-color: #8191a1" in window.styleSheet()

    window.close()
    app.processEvents()


def test_pixel_motion_can_be_disabled_and_is_persisted() -> None:
    app = QApplication.instance() or QApplication([])
    settings = gui_module._application_settings()
    previous = settings.value("appearance/motion_enabled", None)
    window = MainWindow()

    original_phase = window.motion_rail._phase
    window.motion_rail.advance_frame()
    assert window.motion_rail._phase != original_phase

    window.motion_action.setChecked(False)
    assert window.motion_rail.animation_enabled is False
    assert window.motion_rail._timer.isActive() is False
    assert settings.value("appearance/motion_enabled", type=bool) is False

    window.motion_action.setChecked(True)
    assert window.motion_rail.animation_enabled is True
    assert settings.value("appearance/motion_enabled", type=bool) is True

    window.close()
    if previous is None:
        settings.remove("appearance/motion_enabled")
    else:
        settings.setValue("appearance/motion_enabled", previous)
    app.processEvents()


def test_loaded_candidate_media_does_not_reenter_player_controls() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    class FakePlayer:
        def __init__(self) -> None:
            self.positions: list[int] = []

        def setPosition(self, position: int) -> None:  # noqa: N802 - Qt API
            self.positions.append(position)

    fake_player = FakePlayer()
    original_player = window.media_player
    window.media_player = fake_player

    window._preview_media_status_changed(
        gui_module.QMediaPlayer.MediaStatus.LoadedMedia
    )

    assert fake_player.positions == []
    window.media_player = original_player
    window.close()
    app.processEvents()


def test_progress_payload_updates_visible_status() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._started_at = time.monotonic() - 20
    window._process_mode = "analysis"
    window._set_running(True)

    window._apply_progress(
        {
            "percent": 42.5,
            "phase": "GPU 分析画面",
            "current_video": None,
            "video_index": 2,
            "video_total": 4,
            "candidate_count": 12,
        }
    )

    assert window.progress.value() == 425
    assert window.progress.format() == "42.5%"
    assert window.percent_label.text() == "42%"
    assert window.phase_label.text() == "GPU 分析画面"
    assert window.video_count_label.text() == "第 2/4 个视频"
    assert "正在载入已生成的 12 个候选" in window.selected_count_label.text()
    assert window.eta_label.text() != "正在估算"
    assert window.analysis_feedback.isHidden() is False
    assert window.analysis_progress.value() == 425
    assert window.analysis_feedback_phase.text() == "GPU 分析画面"

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


def test_utf8_decoder_preserves_chinese_split_between_process_chunks() -> None:
    payload = "GPU 分析画面 · Threaded NVDEC · 中文日志".encode("utf-8")
    chunks = [payload[:5], payload[5:8], payload[8:17], payload[17:]]

    decoded = decode_utf8_chunks(chunks)

    assert decoded == "GPU 分析画面 · Threaded NVDEC · 中文日志"
    assert "�" not in decoded


def test_process_decoder_handles_mixed_utf8_and_windows_utf16_logs() -> None:
    decoder = MixedProcessOutputDecoder()
    utf8_line = "GPU 分析画面\n".encode("utf-8")
    utf16_line = "CUDA 运行库缺失\n".encode("utf-16-le")
    payload = utf8_line + utf16_line

    decoded = "".join(
        decoder.decode(chunk)
        for chunk in (payload[:7], payload[7:19], payload[19:31], payload[31:])
    )
    decoded += decoder.decode(b"", final=True)

    assert decoded == "GPU 分析画面\nCUDA 运行库缺失\n"
    assert "\x00" not in decoded
    assert "�" not in decoded


def test_optimization_result_line_is_parsed() -> None:
    payload = parse_optimization_line(
        'TVH_OPTIMIZATION {"inference_backend":"tensorrt","inference_batch_size":32}'
    )

    assert payload == {"inference_backend": "tensorrt", "inference_batch_size": 32}
    assert parse_optimization_line("普通日志") is None
