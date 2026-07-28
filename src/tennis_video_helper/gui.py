"""TennisVideoHelper 的 PySide6 桌面界面。"""

from __future__ import annotations

import codecs
import ctypes
from dataclasses import dataclass, replace
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2

from PySide6.QtCore import (
    QProcess,
    QProcessEnvironment,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tennis_video_helper.cli import ACCELERATION_PREFIX, PROGRESS_PREFIX, REVIEW_PREFIX
from tennis_video_helper.media import SUPPORTED_VIDEO_EXTENSIONS, scan_videos
from tennis_video_helper.optimizer import (
    OPTIMIZATION_PREFIX,
    OptimizationProfile,
    load_profile,
)
from tennis_video_helper.review import (
    ReviewClipCandidate,
    ReviewSession,
    ReviewVideoCandidate,
    discard_review_session,
    load_review_session,
    publish_review_session,
)


VIDEO_FILE_FILTER = (
    "视频文件 ("
    + " ".join(f"*{extension}" for extension in sorted(SUPPORTED_VIDEO_EXTENSIONS))
    + ");;所有文件 (*)"
)
WINDOWS_APP_USER_MODEL_ID = "TennisVideoHelper.Desktop.0.1"


@dataclass(frozen=True, slots=True)
class AnalysisFormValues:
    """界面提交给命令行分析器的值。"""

    input_path: Path
    output_path: Path
    min_rally_duration: float
    pre_roll: float
    post_roll: float
    end_silence: float
    analysis_fps: int
    audio_sensitivity: float
    visual_sensitivity: float
    limit_duration: float | None
    inference_backend: str = "auto"
    inference_precision: str = "fp16"
    inference_batch_size: int = 16
    require_gpu: bool = False
    export_original_quality: bool = False
    overwrite_existing_output: bool = True


def build_analyze_arguments(values: AnalysisFormValues) -> list[str]:
    """构造由 GUI 后台进程执行的 CLI 参数。"""

    arguments = [
        "-m",
        "tennis_video_helper.cli",
        "analyze",
        str(values.input_path),
        "--output",
        str(values.output_path),
        "--min-rally-duration",
        _number(values.min_rally_duration),
        "--pre-roll",
        _number(values.pre_roll),
        "--post-roll",
        _number(values.post_roll),
        "--end-silence",
        _number(values.end_silence),
        "--analysis-fps",
        str(values.analysis_fps),
        "--audio-sensitivity",
        _number(values.audio_sensitivity),
        "--visual-sensitivity",
        _number(values.visual_sensitivity),
        "--backend",
        values.inference_backend,
        "--precision",
        values.inference_precision,
        "--batch-size",
        str(values.inference_batch_size),
        "--progress-json",
        "--prepare-review",
    ]
    arguments.append("--require-gpu" if values.require_gpu else "--allow-cpu")
    arguments.append(
        "--original-quality"
        if values.export_original_quality
        else "--1080p-output"
    )
    arguments.append(
        "--overwrite-existing"
        if values.overwrite_existing_output
        else "--keep-existing"
    )
    if values.limit_duration is not None:
        arguments.extend(["--limit-duration", _number(values.limit_duration)])
    return arguments


def build_optimize_arguments(input_path: Path, benchmark_seconds: float = 60.0) -> list[str]:
    """构造本机硬件自动优化命令。"""

    return [
        "-m",
        "tennis_video_helper.cli",
        "optimize",
        str(input_path),
        "--benchmark-seconds",
        _number(benchmark_seconds),
        "--progress-json",
    ]


def process_invocation(arguments: list[str]) -> tuple[str, list[str]]:
    """Use the packaged worker executable when running from a frozen GUI."""

    if getattr(sys, "frozen", False):
        worker = Path(sys.executable).with_name("TennisVideoHelperWorker.exe")
        return str(worker), arguments[2:]
    return sys.executable, arguments


def _number(value: float) -> str:
    return f"{value:g}"


def decode_utf8_chunks(chunks: list[bytes]) -> str:
    """Decode arbitrarily split UTF-8 chunks without corrupting multibyte text."""

    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    text = "".join(decoder.decode(chunk, final=False) for chunk in chunks)
    return text + decoder.decode(b"", final=True)


class MixedProcessOutputDecoder:
    """解码后台进程混合输出的 UTF-8 和 Windows UTF-16LE 日志。"""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def decode(self, data: bytes, *, final: bool = False) -> str:
        self._buffer.extend(data)
        decoded: list[str] = []
        while self._buffer:
            is_utf16 = self._looks_like_utf16le(self._buffer)
            delimiter = b"\n\x00" if is_utf16 else b"\n"
            line_end = self._buffer.find(delimiter)
            if line_end < 0 and not final:
                break
            take = len(self._buffer) if line_end < 0 else line_end + len(delimiter)
            payload = bytes(self._buffer[:take])
            del self._buffer[:take]
            if is_utf16:
                if len(payload) % 2:
                    payload += b"\x00"
                decoded.append(payload.decode("utf-16-le", errors="replace"))
            else:
                decoded.append(payload.decode("utf-8", errors="replace"))
        return "".join(decoded)

    @staticmethod
    def _looks_like_utf16le(data: bytes | bytearray) -> bool:
        probe = bytes(data[:160])
        if len(probe) < 4:
            return False
        odd_bytes = probe[1::2]
        even_bytes = probe[0::2]
        odd_nulls = odd_bytes.count(0)
        even_nulls = even_bytes.count(0)
        return odd_nulls >= 2 and odd_nulls > even_nulls * 2


def _cuda_available() -> bool:
    try:
        import torch
    except ImportError:
        try:
            import onnxruntime as ort

            return bool(
                set(ort.get_available_providers())
                & {
                    "TensorrtExecutionProvider",
                    "CUDAExecutionProvider",
                    "DmlExecutionProvider",
                }
            )
        except (ImportError, OSError):
            return False
    return bool(torch.cuda.is_available())


def _cuda_device_name() -> str | None:
    try:
        import torch
    except ImportError:
        return "ONNX GPU" if _cuda_available() else None
    return torch.cuda.get_device_name(0) if torch.cuda.is_available() else None


def parse_paths(input_text: str, output_text: str) -> tuple[Path, Path]:
    """校验并转换界面中的输入、输出路径。"""

    if not input_text.strip():
        raise ValueError("请选择源视频或文件夹。")
    return Path(input_text.strip()), parse_output_path(output_text)


def parse_output_path(output_text: str) -> Path:
    """校验并转换输出路径。"""

    if not output_text.strip():
        raise ValueError("请选择输出文件夹。")
    return Path(output_text.strip())


def build_stop_command(process_id: int, *, platform: str = os.name) -> list[str] | None:
    """在 Windows 上构造终止整个后台进程树的命令。"""

    if platform != "nt" or process_id <= 0:
        return None
    return ["taskkill", "/PID", str(process_id), "/T", "/F"]


def process_ids_match(expected_process_id: int, current_process_id: int) -> bool:
    """判断延迟强制停止面对的是否仍是原任务。"""

    return expected_process_id > 0 and expected_process_id == current_process_id


def parse_progress_line(line: str) -> dict[str, object] | None:
    """解析 CLI 发给桌面端的单行结构化进度。"""

    if not line.startswith(PROGRESS_PREFIX):
        return None
    try:
        payload = json.loads(line[len(PROGRESS_PREFIX) :])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def parse_acceleration_line(line: str) -> dict[str, object] | None:
    """解析后台上报的真实 GPU/CPU 加速状态。"""

    if not line.startswith(ACCELERATION_PREFIX):
        return None
    try:
        payload = json.loads(line[len(ACCELERATION_PREFIX) :])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def parse_optimization_line(line: str) -> dict[str, object] | None:
    if not line.startswith(OPTIMIZATION_PREFIX):
        return None
    try:
        payload = json.loads(line[len(OPTIMIZATION_PREFIX) :])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def parse_review_line(line: str) -> dict[str, object] | None:
    """解析后台生成的候选复核清单位置。"""

    if not line.startswith(REVIEW_PREFIX):
        return None
    try:
        payload = json.loads(line[len(REVIEW_PREFIX) :])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def format_clock(seconds: float) -> str:
    """将秒数格式化为便于等待时阅读的时间。"""

    total_seconds = max(0, round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class PreviewLabel(QLabel):
    """保持宽高比并随窗口尺寸缩放的视频预览。"""

    def __init__(self) -> None:
        super().__init__("选择视频后将在这里显示预览")
        self._source_pixmap = QPixmap()
        self.setObjectName("videoPreview")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(420, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_source_pixmap(self, pixmap: QPixmap | None) -> None:
        self._source_pixmap = pixmap or QPixmap()
        if self._source_pixmap.isNull():
            self.setText("当前视频暂时无法生成预览")
        else:
            self.setText("")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        if self._source_pixmap.isNull():
            return
        target = self.contentsRect()
        scaled = self._source_pixmap.scaled(
            target.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter = QPainter(self)
        x = target.x() + (target.width() - scaled.width()) // 2
        y = target.y() + (target.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()


class HitTimeline(QWidget):
    """显示播放进度与模型识别击球点的可点击时间线。"""

    seekRequested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._duration_ms = 0
        self._position_ms = 0
        self._hit_positions_ms: tuple[int, ...] = ()
        self.setObjectName("hitTimeline")
        self.setMinimumHeight(54)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点击时间线可跳转；绿色点表示识别出的击球位置")

    def set_hits(self, duration_ms: int, hit_positions_ms: list[int]) -> None:
        self._duration_ms = max(0, duration_ms)
        self._position_ms = 0
        self._hit_positions_ms = tuple(
            sorted(max(0, position) for position in hit_positions_ms)
        )
        self.update()

    def set_duration(self, duration_ms: int) -> None:
        self._duration_ms = max(0, duration_ms)
        self.update()

    def set_position(self, position_ms: int) -> None:
        self._position_ms = max(0, position_ms)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(18, self.height() / 2 - 1.5, max(1, self.width() - 36), 3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#343940"))
        painter.drawRoundedRect(track, 1.5, 1.5)

        progress_fraction = self._fraction(self._position_ms)
        progress_track = QRectF(track.x(), track.y(), track.width() * progress_fraction, 3)
        painter.setBrush(QColor("#9add43"))
        painter.drawRoundedRect(progress_track, 1.5, 1.5)

        active_window_ms = 320
        for hit_ms in self._hit_positions_ms:
            x = track.x() + track.width() * self._fraction(hit_ms)
            active = abs(self._position_ms - hit_ms) <= active_window_ms
            passed = hit_ms < self._position_ms
            if active:
                painter.setBrush(QColor("#111316"))
                painter.setPen(QPen(QColor("#c8ff73"), 3))
                painter.drawEllipse(QRectF(x - 8, track.center().y() - 8, 16, 16))
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#9add43" if passed else "#d8f5a8"))
                radius = 4 if passed else 3.5
                painter.drawEllipse(
                    QRectF(x - radius, track.center().y() - radius, radius * 2, radius * 2)
                )

        playhead_x = track.x() + track.width() * progress_fraction
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawLine(
            int(playhead_x),
            int(track.center().y() - 13),
            int(playhead_x),
            int(track.center().y() + 13),
        )
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton and self._duration_ms > 0:
            fraction = min(1.0, max(0.0, (event.position().x() - 18) / max(1, self.width() - 36)))
            self.seekRequested.emit(round(fraction * self._duration_ms))
        super().mousePressEvent(event)

    def _fraction(self, position_ms: int) -> float:
        if self._duration_ms <= 0:
            return 0.0
        return min(1.0, max(0.0, position_ms / self._duration_ms))


class _LargeArrowButtons:
    """为数字框提供不依赖系统缩放的大尺寸上下按钮。"""

    def _install_arrow_buttons(self) -> None:
        self.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self._up_button = QToolButton(self)
        self._up_button.setObjectName("spinUpButton")
        self._up_button.setIcon(_make_arrow_icon(up=True))
        self._up_button.setIconSize(QSize(15, 9))
        self._up_button.setAutoRepeat(True)
        self._up_button.clicked.connect(self.stepUp)
        self._down_button = QToolButton(self)
        self._down_button.setObjectName("spinDownButton")
        self._down_button.setIcon(_make_arrow_icon(up=False))
        self._down_button.setIconSize(QSize(15, 9))
        self._down_button.setAutoRepeat(True)
        self._down_button.clicked.connect(self.stepDown)
        self._place_arrow_buttons()

    def _place_arrow_buttons(self) -> None:
        button_width = 30
        upper_height = self.height() // 2
        self._up_button.setGeometry(self.width() - button_width, 0, button_width, upper_height)
        self._down_button.setGeometry(
            self.width() - button_width,
            upper_height,
            button_width,
            self.height() - upper_height,
        )


class LargeArrowDoubleSpinBox(_LargeArrowButtons, QDoubleSpinBox):
    def __init__(self) -> None:
        super().__init__()
        self._install_arrow_buttons()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._place_arrow_buttons()


class LargeArrowSpinBox(_LargeArrowButtons, QSpinBox):
    def __init__(self) -> None:
        super().__init__()
        self._install_arrow_buttons()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._place_arrow_buttons()


class ParameterTile(QFrame):
    """带中文调参说明的单个参数卡片。"""

    def __init__(
        self,
        title: str,
        description: str,
        control: QWidget,
    ) -> None:
        super().__init__()
        self.setObjectName("parameterTile")
        self.setMinimumHeight(80)
        self.control = control
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        header = QHBoxLayout()
        label = QLabel(title)
        label.setObjectName("parameterTitle")
        header.addWidget(label)
        header.addStretch()
        header.addWidget(control)
        layout.addLayout(header)

        self.note = QLabel(description)
        self.note.setObjectName("parameterNote")
        self.note.setWordWrap(True)
        self.note.setMinimumHeight(22)
        self.note.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.note)


class MainWindow(QMainWindow):
    """磨砂黑风格的主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_process_output)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)
        self._started_at = 0.0
        self._stopping = False
        self._progress_percent = 0.0
        self._process_output_buffer = ""
        self._process_output_decoder = MixedProcessOutputDecoder()
        self._preview_path: Path | None = None
        self._acceleration_status: dict[str, object] = {}
        self._process_mode = "analysis"
        self._optimization_profile: OptimizationProfile | None = None
        self._review_manifest_path: Path | None = None
        self._review_session: ReviewSession | None = None
        self._review_candidates: dict[
            str, tuple[ReviewVideoCandidate, ReviewClipCandidate]
        ] = {}
        self._current_candidate_id: str | None = None
        self._loading_candidates = False
        self._last_worker_message = ""

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.75)
        self.media_player = QMediaPlayer(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.positionChanged.connect(self._preview_position_changed)
        self.media_player.durationChanged.connect(self._preview_duration_changed)
        self.media_player.playbackStateChanged.connect(self._preview_state_changed)
        self.media_player.mediaStatusChanged.connect(self._preview_media_status_changed)
        self.media_player.errorOccurred.connect(self._preview_error)

        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(1000)
        self.elapsed_timer.timeout.connect(self._update_elapsed)

        self.setWindowTitle("Tennis Video Helper")
        self.setMinimumSize(1100, 760)
        self.resize(1440, 920)
        self.setWindowIcon(_make_icon())
        self.setStyleSheet(STYLE_SHEET)
        self._build_menu_bar()

        self.page_scroll = QScrollArea()
        self.page_scroll.setObjectName("pageScroll")
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.setCentralWidget(self.page_scroll)

        central = QWidget()
        central.setObjectName("root")
        self.page_scroll.setWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 8, 20, 8)
        root.setSpacing(8)
        self.root_layout = root

        root.addLayout(self._build_header())
        root.addWidget(self._build_top_bar())
        self.workbench_card = self._build_workbench_card()
        root.addWidget(self.workbench_card, 1)
        self.parameter_card = self._build_parameter_card()
        root.addWidget(self.parameter_card, 1)
        self.parameter_card.setVisible(False)

        self._load_saved_optimization()
        self._set_running(False)
        QTimer.singleShot(0, self._refresh_input_preview)
        QTimer.singleShot(0, self._show_initial_view)
        QTimer.singleShot(0, lambda: _apply_windows_dark_frame(self))

    def _show_initial_view(self) -> None:
        """让首次打开时停留在顶部主工作区。"""

        self.start_button.setFocus()
        self.page_scroll.verticalScrollBar().setValue(0)

    def _build_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(1)

        eyebrow = QLabel("AI TENNIS WORKFLOW")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("长回合自动精选")
        title.setObjectName("heroTitle")
        subtitle = QLabel("声音瞬态 × 人体动作 × NVIDIA GPU 加速")
        subtitle.setObjectName("heroSubtitle")
        text.addWidget(eyebrow)
        text.addWidget(title)
        text.addWidget(subtitle)

        layout.addLayout(text)
        layout.addStretch()
        self.status_badge = QLabel("●  等待任务")
        self.status_badge.setObjectName("statusBadge")
        layout.addWidget(self.status_badge, alignment=Qt.AlignmentFlag.AlignTop)
        return layout

    def _build_menu_bar(self) -> None:
        file_menu = self.menuBar().addMenu("文件(&F)")
        choose_video = QAction("选择视频…", self)
        choose_video.setShortcut("Ctrl+O")
        choose_video.triggered.connect(self._choose_file)
        file_menu.addAction(choose_video)
        choose_folder = QAction("选择视频文件夹…", self)
        choose_folder.setShortcut("Ctrl+Shift+O")
        choose_folder.triggered.connect(self._choose_input_folder)
        file_menu.addAction(choose_folder)
        choose_output = QAction("选择输出文件夹…", self)
        choose_output.triggered.connect(self._choose_output_folder)
        file_menu.addAction(choose_output)
        file_menu.addSeparator()
        open_output = QAction("打开输出文件夹", self)
        open_output.triggered.connect(self._open_output)
        file_menu.addAction(open_output)
        file_menu.addSeparator()
        exit_action = QAction("退出", self)
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        edit_menu = self.menuBar().addMenu("编辑(&E)")
        self.select_all_action = QAction("保留全部候选", self)
        self.select_all_action.setShortcut("Ctrl+A")
        self.select_all_action.triggered.connect(lambda: self._set_all_candidates(True))
        edit_menu.addAction(self.select_all_action)
        self.select_none_action = QAction("取消全部候选", self)
        self.select_none_action.setShortcut("Ctrl+Shift+A")
        self.select_none_action.triggered.connect(lambda: self._set_all_candidates(False))
        edit_menu.addAction(self.select_none_action)

        view_menu = self.menuBar().addMenu("视图(&V)")
        self.parameters_action = QAction("显示常规参数", self)
        self.parameters_action.setCheckable(True)
        self.parameters_action.toggled.connect(self._set_parameter_panel_visible)
        view_menu.addAction(self.parameters_action)

        help_menu = self.menuBar().addMenu("帮助(&H)")
        about_action = QAction("关于 Tennis Video Helper", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(54)
        bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.auto_button = QPushButton("自动精选")
        self.auto_button.setObjectName("modeButton")
        self.auto_button.setCheckable(True)
        self.auto_button.setChecked(True)
        self.auto_button.clicked.connect(
            lambda _checked=False: self.parameters_action.setChecked(False)
        )
        self.settings_button = QPushButton("常规")
        self.settings_button.setObjectName("modeButton")
        self.settings_button.setCheckable(True)
        self.settings_button.clicked.connect(
            lambda checked=False: self.parameters_action.setChecked(checked)
        )
        layout.addWidget(self.auto_button)
        layout.addWidget(self.settings_button)

        default_input = Path.cwd() / "网球"
        default_output = Path.cwd() / "精选输出"
        layout.addWidget(QLabel("输入"))
        self.input_edit = QLineEdit(
            str(default_input) if default_input.exists() else ""
        )
        self.input_edit.setPlaceholderText("在“文件”菜单选择视频或文件夹")
        self.input_edit.editingFinished.connect(self._refresh_input_preview)
        layout.addWidget(self.input_edit, 2)
        layout.addWidget(QLabel("输出"))
        self.output_edit = QLineEdit(str(default_output))
        self.output_edit.setPlaceholderText("在“文件”菜单选择输出目录")
        layout.addWidget(self.output_edit, 2)
        return bar

    def _set_parameter_panel_visible(self, visible: bool) -> None:
        self.workbench_card.setVisible(not visible)
        self.parameter_card.setVisible(visible)
        self.settings_button.setChecked(visible)
        self.auto_button.setChecked(not visible)
        self.page_scroll.verticalScrollBar().setValue(0)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于 Tennis Video Helper",
            "Tennis Video Helper\n\n声音、人体骨架与球拍检测融合的网球回合筛选工具。",
        )

    def _build_workbench_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("workbenchCard")
        card.setMinimumHeight(500)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        candidate_panel = QFrame()
        candidate_panel.setObjectName("reviewPanel")
        candidate_panel.setMinimumWidth(245)
        candidate_panel.setMaximumWidth(310)
        candidate_layout = QVBoxLayout(candidate_panel)
        candidate_layout.setContentsMargins(12, 12, 12, 12)
        candidate_header = QHBoxLayout()
        candidate_title = QLabel("候选片段")
        candidate_title.setObjectName("workbenchTitle")
        self.video_count_label = QLabel("等待分析")
        self.video_count_label.setObjectName("mutedLabel")
        candidate_header.addWidget(candidate_title)
        candidate_header.addStretch()
        candidate_header.addWidget(self.video_count_label)
        candidate_layout.addLayout(candidate_header)
        candidate_hint = QLabel("勾选要保留的片段，单击条目即可预览。")
        candidate_hint.setObjectName("mutedLabel")
        candidate_hint.setWordWrap(True)
        candidate_layout.addWidget(candidate_hint)
        self.candidate_list = QListWidget()
        self.candidate_list.setObjectName("candidateList")
        self.candidate_list.setAlternatingRowColors(False)
        self.candidate_list.currentItemChanged.connect(self._candidate_changed)
        self.candidate_list.itemChanged.connect(self._candidate_check_changed)
        candidate_layout.addWidget(self.candidate_list, 1)
        selection_row = QHBoxLayout()
        select_all_button = QPushButton("全部保留")
        select_all_button.clicked.connect(lambda: self._set_all_candidates(True))
        select_none_button = QPushButton("全部取消")
        select_none_button.clicked.connect(lambda: self._set_all_candidates(False))
        selection_row.addWidget(select_all_button)
        selection_row.addWidget(select_none_button)
        candidate_layout.addLayout(selection_row)
        self.selected_count_label = QLabel("已选 0/0 段")
        self.selected_count_label.setObjectName("taskSummary")
        candidate_layout.addWidget(self.selected_count_label)
        layout.addWidget(candidate_panel)

        preview_panel = QFrame()
        preview_panel.setObjectName("previewPanel")
        preview_column = QVBoxLayout(preview_panel)
        preview_column.setContentsMargins(12, 12, 12, 10)
        preview_column.setSpacing(7)
        preview_header = QHBoxLayout()
        preview_title = QLabel("片段预览与击球点")
        preview_title.setObjectName("workbenchTitle")
        self.current_video_label = QLabel("选择视频后可先查看画面")
        self.current_video_label.setObjectName("currentVideo")
        self.current_video_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        preview_header.addWidget(preview_title)
        preview_header.addStretch()
        preview_header.addWidget(self.current_video_label)
        preview_column.addLayout(preview_header)

        self.preview_stack = QStackedWidget()
        self.preview_stack.setObjectName("previewStack")
        self.preview = PreviewLabel()
        self.preview_stack.addWidget(self.preview)
        self.video_widget = QVideoWidget()
        self.video_widget.setObjectName("videoWidget")
        self.video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.media_player.setVideoOutput(self.video_widget)
        self.preview_stack.addWidget(self.video_widget)
        preview_column.addWidget(self.preview_stack, 1)

        self.hit_timeline = HitTimeline()
        self.hit_timeline.seekRequested.connect(self._seek_preview)
        preview_column.addWidget(self.hit_timeline)
        playback_row = QHBoxLayout()
        self.previous_button = QPushButton("上一段")
        self.previous_button.clicked.connect(self._previous_candidate)
        self.play_button = QPushButton("播放")
        self.play_button.setObjectName("playButton")
        self.play_button.clicked.connect(self._toggle_preview_playback)
        self.next_button = QPushButton("下一段")
        self.next_button.clicked.connect(self._next_candidate)
        self.preview_time_label = QLabel("00:00 / 00:00")
        self.preview_time_label.setObjectName("metricValue")
        self.hit_count_label = QLabel("击球点：0")
        self.hit_count_label.setObjectName("hitCountLabel")
        playback_row.addWidget(self.previous_button)
        playback_row.addWidget(self.play_button)
        playback_row.addWidget(self.next_button)
        playback_row.addStretch()
        playback_row.addWidget(self.hit_count_label)
        playback_row.addWidget(self.preview_time_label)
        preview_column.addLayout(playback_row)
        layout.addWidget(preview_panel, 1)

        status_panel = QFrame()
        status_panel.setObjectName("statusPanel")
        status_panel.setMinimumWidth(250)
        status_panel.setMaximumWidth(300)
        status_layout = QVBoxLayout(status_panel)
        status_layout.setContentsMargins(18, 18, 18, 18)
        status_layout.setSpacing(6)

        button_row = QHBoxLayout()
        self.optimize_button = QPushButton("检测并优化")
        self.optimize_button.setObjectName("optimizeButton")
        self.optimize_button.setMinimumHeight(48)
        self.optimize_button.clicked.connect(self._start_optimization)
        self.start_button = QPushButton("分析候选")
        self.start_button.setObjectName("primaryButton")
        self.start_button.setMinimumHeight(48)
        self.start_button.clicked.connect(self._start_analysis)
        self.stop_button = QPushButton("停止任务")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.setMinimumHeight(48)
        self.stop_button.clicked.connect(self._stop_analysis)
        button_row.addWidget(self.optimize_button, 2)
        button_row.addWidget(self.start_button, 2)
        button_row.addWidget(self.stop_button, 1)
        status_layout.addLayout(button_row)

        self.acceleration_label = QLabel("GPU 加速：等待任务检查")
        self.acceleration_label.setObjectName("accelerationStatus")
        self.acceleration_label.setProperty("mode", "pending")
        self.acceleration_label.setWordWrap(True)
        status_layout.addWidget(self.acceleration_label)
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("percentLabel")
        self.phase_label = QLabel("等待开始")
        self.phase_label.setObjectName("phaseLabel")
        self.phase_label.setWordWrap(True)
        status_layout.addWidget(self.percent_label)
        status_layout.addWidget(self.phase_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setFormat("0.0%")
        self.progress.setTextVisible(True)
        self.progress.setFixedHeight(22)
        status_layout.addWidget(self.progress)
        timing_grid = QGridLayout()
        timing_grid.setHorizontalSpacing(18)
        timing_grid.setVerticalSpacing(4)
        elapsed_title = QLabel("已用时间")
        elapsed_title.setObjectName("metricLabel")
        eta_title = QLabel("预计剩余")
        eta_title.setObjectName("metricLabel")
        self.elapsed_label = QLabel("00:00:00")
        self.elapsed_label.setObjectName("metricValue")
        self.eta_label = QLabel("等待估算")
        self.eta_label.setObjectName("metricValue")
        timing_grid.addWidget(elapsed_title, 0, 0)
        timing_grid.addWidget(eta_title, 0, 1)
        timing_grid.addWidget(self.elapsed_label, 1, 0)
        timing_grid.addWidget(self.eta_label, 1, 1)
        status_layout.addLayout(timing_grid)
        self.task_summary_label = QLabel("从“文件”菜单选择视频，然后分析候选片段。")
        self.task_summary_label.setObjectName("taskSummary")
        self.task_summary_label.setWordWrap(True)
        status_layout.addWidget(self.task_summary_label)
        status_layout.addStretch(1)
        self.publish_button = QPushButton("导出勾选片段")
        self.publish_button.setObjectName("primaryButton")
        self.publish_button.setMinimumHeight(48)
        self.publish_button.clicked.connect(self._publish_selected_candidates)
        self.publish_button.setEnabled(False)
        status_layout.addWidget(self.publish_button)
        layout.addWidget(status_panel)
        return card

    def _build_parameter_card(self) -> QFrame:
        card = _card("常用分析参数")
        layout = card.layout()
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        self.min_rally = _double_spin(10.0, 1.0, 600.0, " 秒")
        self.pre_roll = _double_spin(2.0, 0.0, 30.0, " 秒")
        self.post_roll = _double_spin(3.0, 0.0, 30.0, " 秒")
        self.end_silence = _double_spin(3.5, 0.1, 30.0, " 秒")
        self.analysis_fps = _int_spin(12, 1, 30, " FPS")
        self.audio_sensitivity = _double_spin(1.0, 0.1, 3.0, " ×")
        self.visual_sensitivity = _double_spin(1.0, 0.1, 3.0, " ×")
        self.inference_backend = QComboBox()
        self.inference_backend.setMinimumHeight(40)
        self.inference_backend.setMinimumWidth(102)
        self.inference_backend.addItem("自动", "auto")
        self.inference_backend.addItem("轻量 ONNX GPU", "onnx")
        self.inference_backend.addItem("TensorRT", "tensorrt")
        self.inference_backend.addItem("PyTorch CUDA", "torch")
        self.inference_precision = QComboBox()
        self.inference_precision.setMinimumHeight(40)
        self.inference_precision.setMinimumWidth(102)
        self.inference_precision.addItem("FP16", "fp16")
        self.inference_precision.addItem("FP32", "fp32")
        self.inference_batch_size = _int_spin(16, 1, 64, " 帧")

        specs = [
            ("最短回合", "调大：只留更长回合；调小：短回合会增多。", self.min_rally),
            ("前置保留", "调大：准备动作更完整；调小：片段更紧凑。", self.pre_roll),
            ("后置保留", "调大：收拍反应更完整；调小：结束更利落。", self.post_roll),
            ("结束静默", "调大：不易截断慢回球；调小：切分更敏感。", self.end_silence),
            ("画面分析率", "调大：动作更细但更慢；8 GB 显存建议 8–12。", self.analysis_fps),
            ("声音灵敏度", "调大：弱击球更易检出；背景声音误检会增加。", self.audio_sensitivity),
            ("动作灵敏度", "调大：轻微挥拍更易检出；空挥误检会增加。", self.visual_sensitivity),
            ("GPU 后端", "自动模式优先使用缓存的 TensorRT，并在不可用时回退 PyTorch。", self.inference_backend),
            ("推理精度", "FP16 默认更快；FP32 更稳但速度较慢。", self.inference_precision),
            ("GPU 批量", "RTX 4060 8 GB 推荐 16；过大可能增加显存压力。", self.inference_batch_size),
        ]
        for index, (title, note, control) in enumerate(specs):
            grid.addWidget(ParameterTile(title, note, control), index // 5, index % 5)

        limit_box = QFrame()
        limit_box.setObjectName("parameterTile")
        limit_layout = QHBoxLayout(limit_box)
        limit_layout.setContentsMargins(12, 9, 12, 9)
        self.limit_check = QCheckBox("仅分析前")
        self.limit_minutes = _double_spin(5.0, 0.1, 180.0, " 分钟")
        self.limit_minutes.setEnabled(False)
        self.limit_check.toggled.connect(self.limit_minutes.setEnabled)
        self.require_gpu = QCheckBox("缺少 GPU 时直接停止")
        self.export_original_quality = QCheckBox("以原画质导出")
        self.export_original_quality.setChecked(False)
        self.export_original_quality.setToolTip(
            "未勾选时，超过 1080p 的视频会缩小到 1080p，并保持原始帧率；不会放大低分辨率视频。"
        )
        self.overwrite_existing_output = QCheckBox("覆盖同名旧结果")
        self.overwrite_existing_output.setChecked(True)
        self.overwrite_existing_output.setToolTip(
            "新结果完整生成并验证成功后才替换旧结果；失败或停止不会删除旧结果。"
        )
        limit_layout.addWidget(self.limit_check)
        limit_layout.addWidget(self.limit_minutes)
        limit_layout.addWidget(self.require_gpu)
        limit_layout.addWidget(self.export_original_quality)
        limit_layout.addWidget(self.overwrite_existing_output)
        limit_layout.addStretch()
        self.export_quality_hint = QLabel()
        self.export_quality_hint.setObjectName("parameterNote")
        limit_layout.addWidget(self.export_quality_hint)
        self.export_original_quality.toggled.connect(
            self._update_export_quality_hint
        )
        self._update_export_quality_hint(False)
        grid.addWidget(limit_box, 2, 0, 1, 5)

        layout.addLayout(grid)
        return card

    def _form_values(self) -> AnalysisFormValues:
        input_path, output_path = parse_paths(
            self.input_edit.text(), self.output_edit.text()
        )
        limit = self.limit_minutes.value() * 60 if self.limit_check.isChecked() else None
        return AnalysisFormValues(
            input_path=input_path,
            output_path=output_path,
            min_rally_duration=self.min_rally.value(),
            pre_roll=self.pre_roll.value(),
            post_roll=self.post_roll.value(),
            end_silence=self.end_silence.value(),
            analysis_fps=self.analysis_fps.value(),
            audio_sensitivity=self.audio_sensitivity.value(),
            visual_sensitivity=self.visual_sensitivity.value(),
            limit_duration=limit,
            inference_backend=str(self.inference_backend.currentData()),
            inference_precision=str(self.inference_precision.currentData()),
            inference_batch_size=self.inference_batch_size.value(),
            require_gpu=self.require_gpu.isChecked(),
            export_original_quality=self.export_original_quality.isChecked(),
            overwrite_existing_output=self.overwrite_existing_output.isChecked(),
        )

    def _update_export_quality_hint(self, original_quality: bool) -> None:
        self.export_quality_hint.setText(
            "原画质：保留源分辨率，4K 导出会明显更慢。"
            if original_quality
            else "默认：最高 1080p，保持原始帧率，适合抖音。"
        )

    def _start_analysis(self) -> None:
        try:
            values = self._form_values()
        except ValueError as exc:
            QMessageBox.warning(self, "路径无效", str(exc))
            return
        if not values.input_path.exists():
            QMessageBox.warning(self, "路径无效", "请选择存在的视频或文件夹。")
            return
        if self._review_session is not None:
            answer = QMessageBox.question(
                self,
                "放弃当前复核？",
                "重新分析会删除尚未导出的候选预览。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._discard_current_review()
        if not values.export_original_quality:
            QMessageBox.information(
                self,
                "默认 1080p 导出",
                "当前未勾选“以原画质导出”。本次会把超过 1080p 的视频缩小到 1080p，"
                "并保持原始帧率；1080p 或更低的视频不会放大。",
            )
        if not values.require_gpu and not _cuda_available():
            answer = QMessageBox.question(
                self,
                "确认 CPU 回退",
                "当前没有显卡驱动或可用 CUDA，将自动回退 CPU 处理，速度会显著降低。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUTF8", "1")
        environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("PYTHONUNBUFFERED", "1")
        environment.insert("NO_COLOR", "1")
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(str(Path.cwd()))

        self._stopping = False
        self._process_mode = "analysis"
        self._started_at = time.monotonic()
        self._progress_percent = 0.0
        self._process_output_buffer = ""
        self._process_output_decoder = MixedProcessOutputDecoder()
        self._acceleration_status = {}
        self._review_manifest_path = None
        self._last_worker_message = ""
        self._clear_candidate_view()
        self._set_acceleration_label("pending", "GPU 加速：正在检查……")
        self.progress.setValue(0)
        self.progress.setFormat("0.0%")
        self.percent_label.setText("0%")
        self.phase_label.setText("正在检查运行环境")
        self.eta_label.setText("正在估算")
        self.elapsed_timer.start()
        self._set_running(True)
        program, arguments = process_invocation(build_analyze_arguments(values))
        self.process.start(program, arguments)

    def _start_optimization(self) -> None:
        try:
            values = self._form_values()
        except ValueError as exc:
            QMessageBox.warning(self, "路径无效", str(exc))
            return
        if not values.input_path.exists():
            QMessageBox.warning(self, "路径无效", "请先选择用于基准测试的视频或文件夹。")
            return

        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUTF8", "1")
        environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("PYTHONUNBUFFERED", "1")
        environment.insert("NO_COLOR", "1")
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(str(Path.cwd()))

        self._stopping = False
        self._process_mode = "optimization"
        self._started_at = time.monotonic()
        self._progress_percent = 0.0
        self._process_output_buffer = ""
        self._process_output_decoder = MixedProcessOutputDecoder()
        self._last_worker_message = ""
        self.progress.setValue(0)
        self.progress.setFormat("0.0%")
        self.percent_label.setText("0%")
        self.phase_label.setText("检测硬件与运行时")
        self.eta_label.setText("正在估算")
        self._set_acceleration_label("pending", "本机优化：正在检测硬件……")
        self.elapsed_timer.start()
        self._set_running(True)
        program, arguments = process_invocation(
            build_optimize_arguments(values.input_path)
        )
        self.process.start(program, arguments)

    def _stop_analysis(self) -> None:
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return
        self._stopping = True
        self.task_summary_label.setText("正在停止后台任务，并清理未完成的候选文件……")
        process_id = int(self.process.processId())
        used_tree_kill = self._terminate_process_tree()
        if not used_tree_kill:
            QTimer.singleShot(3000, lambda: self._kill_if_running(process_id))

    def _terminate_process_tree(self) -> bool:
        command = build_stop_command(int(self.process.processId()))
        if command is None:
            self.process.terminate()
            return False
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0 and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        return True

    def _kill_if_running(self, expected_process_id: int) -> None:
        if (
            self.process.state() != QProcess.ProcessState.NotRunning
            and process_ids_match(expected_process_id, int(self.process.processId()))
        ):
            self.process.kill()

    def _read_process_output(self) -> None:
        data = bytes(self.process.readAllStandardOutput())
        text = self._process_output_decoder.decode(data, final=False)
        if not text:
            return
        self._process_output_buffer += text
        while "\n" in self._process_output_buffer:
            line, self._process_output_buffer = self._process_output_buffer.split("\n", 1)
            self._handle_process_line(line.rstrip("\r"))

    def _handle_process_line(self, line: str) -> None:
        review = parse_review_line(line)
        if review is not None:
            manifest = review.get("manifest")
            if manifest:
                self._review_manifest_path = Path(str(manifest))
            return
        optimization = parse_optimization_line(line)
        if optimization is not None:
            self._apply_optimization_result(optimization)
            return
        acceleration = parse_acceleration_line(line)
        if acceleration is not None:
            self._apply_acceleration_status(acceleration)
            return
        payload = parse_progress_line(line)
        if payload is not None:
            self._apply_progress(payload)
            return
        if line:
            self._append_log(line)

    def _apply_acceleration_status(self, payload: dict[str, object]) -> None:
        self._acceleration_status.update(payload)
        status = self._acceleration_status
        cuda_available = bool(status.get("cuda_available"))
        nvenc_available = bool(status.get("nvenc_available"))
        inference = str(status.get("inference_backend") or "检测中")
        precision = str(status.get("precision") or "")
        decoder = str(status.get("decoder") or "检测中")
        encoder = str(status.get("encoder") or ("NVENC" if nvenc_available else "libx265"))
        details = " · ".join(
            part for part in (f"{inference} {precision}".strip(), decoder, encoder) if part
        )

        if cuda_available and nvenc_available:
            mode = "enabled"
            title = "GPU 加速：已启用"
        elif cuda_available or nvenc_available:
            mode = "partial"
            title = "GPU 加速：部分启用"
        else:
            mode = "cpu"
            title = "GPU 加速：未启用，已回退 CPU"
        self._set_acceleration_label(mode, f"{title}\n{details}")
        device_name = status.get("device_name")
        self.acceleration_label.setToolTip(str(device_name or title))
        if self.process.state() != QProcess.ProcessState.NotRunning:
            if cuda_available and nvenc_available:
                self.status_badge.setText("●  GPU 处理中")
            elif cuda_available or nvenc_available:
                self.status_badge.setText("●  CPU/GPU 混合处理")
            else:
                self.status_badge.setText("●  CPU 处理中")

    def _set_acceleration_label(self, mode: str, text: str) -> None:
        self.acceleration_label.setText(text)
        self.acceleration_label.setProperty("mode", mode)
        self.acceleration_label.style().unpolish(self.acceleration_label)
        self.acceleration_label.style().polish(self.acceleration_label)

    def _apply_progress(self, payload: dict[str, object]) -> None:
        try:
            percent = min(100.0, max(0.0, float(payload.get("percent", 0.0))))
        except (TypeError, ValueError):
            return
        self._progress_percent = percent
        self.progress.setValue(round(percent * 10))
        self.progress.setFormat(f"{percent:.1f}%")
        self.percent_label.setText(f"{percent:.0f}%")
        phase = str(payload.get("phase") or "处理中")
        self.phase_label.setText(phase)

        video_index = int(payload.get("video_index") or 0)
        video_total = int(payload.get("video_total") or 0)
        if video_total > 0:
            self.video_count_label.setText(f"第 {video_index}/{video_total} 个视频")
        current_video = payload.get("current_video")
        if current_video:
            self._show_video_preview(Path(str(current_video)))
        self.task_summary_label.setText(
            f"{phase} · {self.current_video_label.text()}"
            if self.current_video_label.text()
            else phase
        )
        self._update_timing_labels()

    def _process_finished(self, exit_code: int, _status) -> None:
        self._read_process_output()
        self._process_output_buffer += self._process_output_decoder.decode(b"", final=True)
        if self._process_output_buffer:
            self._handle_process_line(self._process_output_buffer.rstrip("\r"))
            self._process_output_buffer = ""
        self._process_output_decoder = MixedProcessOutputDecoder()
        self.elapsed_timer.stop()
        self._set_running(False)
        if self._process_mode == "optimization":
            if self._stopping:
                self.status_badge.setText("●  优化已停止")
                self.task_summary_label.setText("本机性能优化已停止，旧配置保持不变。")
            elif exit_code == 0:
                self.status_badge.setText("●  优化完成")
                self._progress_percent = 100.0
                self.progress.setValue(1000)
                self.progress.setFormat("100.0%")
                self.percent_label.setText("100%")
                self.phase_label.setText("本机性能优化完成")
                self.eta_label.setText("已完成")
                self.task_summary_label.setText("最快且通过一致性检查的配置已自动应用。")
            else:
                self.status_badge.setText("●  优化失败")
                self.task_summary_label.setText(
                    self._last_worker_message or f"本机性能优化异常结束，退出代码：{exit_code}"
                )
            self._process_mode = "analysis"
            return
        if self._stopping:
            self.status_badge.setText("●  已停止")
            self.task_summary_label.setText("任务已停止；旧结果没有被覆盖。")
            if self._review_manifest_path and self._review_manifest_path.exists():
                discard_review_session(self._review_manifest_path.parent)
        elif self._review_manifest_path is not None:
            try:
                session = load_review_session(self._review_manifest_path)
                self._set_review_session(session)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                self.status_badge.setText("●  候选清单损坏")
                self.phase_label.setText("无法载入候选片段")
                self.task_summary_label.setText(str(exc))
                return
            self._progress_percent = 100.0
            self.progress.setValue(1000)
            self.progress.setFormat("100.0%")
            self.percent_label.setText("100%")
            candidate_count = len(session.clips)
            self.status_badge.setText("●  等待人工确认")
            self.phase_label.setText(
                f"已生成 {candidate_count} 个候选片段"
                if candidate_count
                else "没有找到满足条件的候选片段"
            )
            self.eta_label.setText("已完成")
            suffix = "；部分源视频处理失败" if exit_code != 0 else ""
            self.task_summary_label.setText(
                f"逐段播放并检查击球点，取消误判后再导出{suffix}。"
                if candidate_count
                else f"可以调整识别参数后重新分析{suffix}。"
            )
        elif exit_code == 0:
            self.status_badge.setText("●  未生成候选")
            self.phase_label.setText("没有找到候选片段")
            self.task_summary_label.setText("可以调低最短回合或灵敏度后重新分析。")
        else:
            self.status_badge.setText("●  处理失败")
            self.task_summary_label.setText(
                self._last_worker_message or f"任务异常结束，退出代码：{exit_code}"
            )

    def _process_error(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.elapsed_timer.stop()
            self._set_running(False)
            self.status_badge.setText("●  启动失败")
            self.task_summary_label.setText(f"无法启动后台任务：{self.process.errorString()}")

    def _set_running(self, running: bool) -> None:
        self.optimize_button.setEnabled(not running)
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.input_edit.setEnabled(not running)
        self.output_edit.setEnabled(not running)
        has_candidates = self._review_session is not None and bool(self._review_session.clips)
        self.publish_button.setEnabled(not running and has_candidates)
        self.select_all_action.setEnabled(not running and has_candidates)
        self.select_none_action.setEnabled(not running and has_candidates)
        if running:
            self.status_badge.setText("●  正在处理")
            self.progress.setRange(0, 1000)
        else:
            self.progress.setRange(0, 1000)
            if not self.status_badge.text():
                self.status_badge.setText("●  等待任务")

    def _set_review_session(self, session: ReviewSession) -> None:
        self._review_session = session
        self._review_candidates = {
            clip.id: (video, clip)
            for video in session.videos
            for clip in video.clips
        }
        self._loading_candidates = True
        self.candidate_list.clear()
        for video in session.videos:
            for clip in video.clips:
                item = QListWidgetItem(
                    f"片段 {clip.index:03d} · {clip.duration:.1f} 秒\n"
                    f"{video.source.name} · {len(clip.hits)} 个击球点"
                )
                item.setData(Qt.ItemDataRole.UserRole, clip.id)
                item.setFlags(
                    item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEnabled
                )
                item.setCheckState(Qt.CheckState.Checked)
                item.setToolTip(
                    f"源视频：{video.source}\n"
                    f"原始区间：{clip.segment.output_start:.2f}–{clip.segment.output_end:.2f} 秒"
                )
                self.candidate_list.addItem(item)
        self._loading_candidates = False
        self.video_count_label.setText(f"{len(session.clips)} 段")
        self._update_selected_count()
        self.publish_button.setEnabled(bool(session.clips))
        self.select_all_action.setEnabled(bool(session.clips))
        self.select_none_action.setEnabled(bool(session.clips))
        if session.clips:
            self.candidate_list.setCurrentRow(0)
        else:
            self._clear_preview_only("没有找到候选片段")

    def _candidate_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return
        candidate_id = str(current.data(Qt.ItemDataRole.UserRole))
        pair = self._review_candidates.get(candidate_id)
        if pair is None:
            return
        video, clip = pair
        self._current_candidate_id = candidate_id
        self.media_player.stop()
        self.media_player.setSource(QUrl.fromLocalFile(str(clip.path)))
        self.preview_stack.setCurrentWidget(self.video_widget)
        self.current_video_label.setText(
            f"{video.source.name} · 片段 {clip.index:03d}"
        )
        duration_ms = round(clip.duration * 1000)
        self.hit_timeline.set_hits(
            duration_ms,
            [round(hit.timestamp * 1000) for hit in clip.hits],
        )
        self.hit_count_label.setText(f"击球点：{len(clip.hits)}")
        self.preview_time_label.setText(
            f"00:00 / {self._preview_clock(duration_ms)}"
        )
        self.play_button.setText("播放")
        self._update_navigation_buttons()

    def _candidate_check_changed(self, _item: QListWidgetItem) -> None:
        if not self._loading_candidates:
            self._update_selected_count()

    def _update_selected_count(self) -> None:
        total = self.candidate_list.count()
        selected = sum(
            self.candidate_list.item(index).checkState() == Qt.CheckState.Checked
            for index in range(total)
        )
        self.selected_count_label.setText(f"已选 {selected}/{total} 段")
        self.publish_button.setEnabled(
            self.process.state() == QProcess.ProcessState.NotRunning
            and self._review_session is not None
            and selected > 0
        )

    def _set_all_candidates(self, selected: bool) -> None:
        self._loading_candidates = True
        state = Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked
        for index in range(self.candidate_list.count()):
            self.candidate_list.item(index).setCheckState(state)
        self._loading_candidates = False
        self._update_selected_count()

    def _selected_candidate_ids(self) -> list[str]:
        return [
            str(item.data(Qt.ItemDataRole.UserRole))
            for index in range(self.candidate_list.count())
            if (item := self.candidate_list.item(index)).checkState()
            == Qt.CheckState.Checked
        ]

    def _publish_selected_candidates(self) -> None:
        if self._review_session is None:
            return
        selected_ids = self._selected_candidate_ids()
        if not selected_ids:
            QMessageBox.warning(self, "没有勾选片段", "请至少勾选一个需要导出的候选片段。")
            return
        self.media_player.stop()
        self.media_player.setSource(QUrl())
        QApplication.processEvents()
        self.publish_button.setEnabled(False)
        self.status_badge.setText("●  正在发布结果")
        self.task_summary_label.setText("正在删除未勾选候选并发布正式结果……")
        try:
            published = publish_review_session(self._review_session, selected_ids)
        except (OSError, ValueError, RuntimeError) as exc:
            self.status_badge.setText("●  导出失败")
            self.task_summary_label.setText(str(exc))
            self.publish_button.setEnabled(True)
            QMessageBox.critical(self, "导出失败", str(exc))
            return

        output_text = "\n".join(str(path) for path in published.output_dirs)
        self._review_session = None
        self._review_manifest_path = None
        self._review_candidates.clear()
        self._clear_candidate_view()
        self.status_badge.setText("●  导出完成")
        self.phase_label.setText(f"已导出 {len(published.clip_paths)} 个片段")
        self.task_summary_label.setText("人工确认后的片段已保存到输出目录。")
        QMessageBox.information(
            self,
            "导出完成",
            f"已导出 {len(published.clip_paths)} 个片段。\n\n{output_text}",
        )

    def _previous_candidate(self) -> None:
        row = self.candidate_list.currentRow()
        if row > 0:
            self.candidate_list.setCurrentRow(row - 1)

    def _next_candidate(self) -> None:
        row = self.candidate_list.currentRow()
        if 0 <= row < self.candidate_list.count() - 1:
            self.candidate_list.setCurrentRow(row + 1)

    def _update_navigation_buttons(self) -> None:
        row = self.candidate_list.currentRow()
        self.previous_button.setEnabled(row > 0)
        self.next_button.setEnabled(0 <= row < self.candidate_list.count() - 1)
        self.play_button.setEnabled(row >= 0)

    def _toggle_preview_playback(self) -> None:
        if self._current_candidate_id is None:
            return
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
        else:
            self.media_player.play()

    def _seek_preview(self, position_ms: int) -> None:
        if self._current_candidate_id is not None:
            self.media_player.setPosition(position_ms)

    def _preview_position_changed(self, position_ms: int) -> None:
        self.hit_timeline.set_position(position_ms)
        duration_ms = max(self.media_player.duration(), self.hit_timeline._duration_ms)
        self.preview_time_label.setText(
            f"{self._preview_clock(position_ms)} / {self._preview_clock(duration_ms)}"
        )

    def _preview_duration_changed(self, duration_ms: int) -> None:
        if duration_ms > 0:
            self.hit_timeline.set_duration(duration_ms)

    def _preview_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.play_button.setText(
            "暂停" if state == QMediaPlayer.PlaybackState.PlayingState else "播放"
        )

    def _preview_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self.media_player.pause()
            self.media_player.setPosition(0)
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.media_player.pause()
            self.media_player.setPosition(0)

    def _preview_error(self, _error, error_text: str) -> None:
        if not error_text or self._current_candidate_id is None:
            return
        pair = self._review_candidates.get(self._current_candidate_id)
        if pair is not None:
            _video, clip = pair
            self.preview.set_source_pixmap(_video_thumbnail(clip.path))
            self.preview_stack.setCurrentWidget(self.preview)
        self.task_summary_label.setText(f"系统播放器无法播放该片段：{error_text}")

    @staticmethod
    def _preview_clock(milliseconds: int) -> str:
        total_seconds = max(0, round(milliseconds / 1000))
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"

    def _clear_preview_only(self, message: str) -> None:
        self.media_player.stop()
        self.media_player.setSource(QUrl())
        self._current_candidate_id = None
        self.preview.set_source_pixmap(None)
        self.preview.setText(message)
        self.preview_stack.setCurrentWidget(self.preview)
        self.hit_timeline.set_hits(0, [])
        self.hit_count_label.setText("击球点：0")
        self.preview_time_label.setText("00:00 / 00:00")
        self.play_button.setText("播放")
        self.play_button.setEnabled(False)

    def _clear_candidate_view(self) -> None:
        self._loading_candidates = True
        self.candidate_list.clear()
        self._loading_candidates = False
        self._review_candidates.clear()
        self.video_count_label.setText("等待分析")
        self.selected_count_label.setText("已选 0/0 段")
        self.publish_button.setEnabled(False)
        self.select_all_action.setEnabled(False)
        self.select_none_action.setEnabled(False)
        self._clear_preview_only("分析完成后，可在这里逐段播放候选视频")
        self._update_navigation_buttons()

    def _discard_current_review(self) -> None:
        self.media_player.stop()
        self.media_player.setSource(QUrl())
        if self._review_session is not None:
            discard_review_session(self._review_session)
        self._review_session = None
        self._review_manifest_path = None
        self._clear_candidate_view()

    def _load_saved_optimization(self) -> None:
        profile = load_profile()
        if profile is None:
            return
        if profile.hardware.cuda_device_name != _cuda_device_name():
            self._set_acceleration_label(
                "pending",
                "本机优化：硬件已变化，请重新检测并优化",
            )
            return
        if (
            profile.inference_backend == "tensorrt"
            and importlib.util.find_spec("tensorrt") is None
        ):
            torch_results = [
                result
                for result in profile.results
                if result.backend == "torch"
                and result.valid
                and result.elapsed_seconds is not None
            ]
            if not torch_results:
                return
            best = min(
                torch_results,
                key=lambda item: item.elapsed_seconds or float("inf"),
            )
            profile = replace(
                profile,
                inference_backend=best.backend,
                inference_precision=best.precision,
                inference_batch_size=best.batch_size,
            )
        self._optimization_profile = profile
        self._apply_profile_controls(profile)
        hardware = profile.hardware.cuda_device_name or "当前设备"
        self._set_acceleration_label(
            "enabled" if profile.hardware.cuda_available else "cpu",
            "本机优化：已加载\n"
            f"{hardware} · {profile.inference_backend} "
            f"{profile.inference_precision.upper()} · 批量 {profile.inference_batch_size}",
        )

    def _apply_optimization_result(self, payload: dict[str, object]) -> None:
        try:
            hardware_payload = payload["hardware"]
            results_payload = payload.get("results", [])
            if not isinstance(hardware_payload, dict) or not isinstance(results_payload, list):
                return
            from tennis_video_helper.optimizer import HardwareSnapshot, BenchmarkResult

            profile = OptimizationProfile(
                **{
                    **payload,
                    "hardware": HardwareSnapshot(**hardware_payload),
                    "results": tuple(BenchmarkResult(**item) for item in results_payload),
                }
            )
        except (KeyError, TypeError, ValueError):
            return
        self._optimization_profile = profile
        self._apply_profile_controls(profile)
        best = next(
            (
                item
                for item in profile.results
                if item.backend == profile.inference_backend
                and item.precision == profile.inference_precision
                and item.batch_size == profile.inference_batch_size
            ),
            None,
        )
        speed = f" · {best.realtime_factor:.1f}×实时" if best and best.realtime_factor else ""
        device = profile.hardware.cuda_device_name or "CPU"
        self._set_acceleration_label(
            "enabled" if profile.hardware.cuda_available else "cpu",
            "本机优化：已完成\n"
            f"{device} · {profile.inference_backend} "
            f"{profile.inference_precision.upper()} · 批量 {profile.inference_batch_size}{speed}",
        )
        self._append_log(
            "已选择最快可靠配置："
            f"{profile.inference_backend} {profile.inference_precision.upper()}，"
            f"批量 {profile.inference_batch_size}{speed}。"
        )

    def _apply_profile_controls(self, profile: OptimizationProfile) -> None:
        backend_index = self.inference_backend.findData(profile.inference_backend)
        if backend_index >= 0:
            self.inference_backend.setCurrentIndex(backend_index)
        precision_index = self.inference_precision.findData(profile.inference_precision)
        if precision_index >= 0:
            self.inference_precision.setCurrentIndex(precision_index)
        self.inference_batch_size.setValue(profile.inference_batch_size)

    def _update_elapsed(self) -> None:
        self._update_timing_labels()

    def _update_timing_labels(self) -> None:
        elapsed = max(0.0, time.monotonic() - self._started_at)
        self.elapsed_label.setText(format_clock(elapsed))
        if self._progress_percent >= 100:
            self.eta_label.setText("已完成")
        elif elapsed < 2 or self._progress_percent < 1:
            self.eta_label.setText("正在估算")
        else:
            remaining = elapsed * (100 - self._progress_percent) / self._progress_percent
            self.eta_label.setText(format_clock(remaining))

    def _append_log(self, message: str) -> None:
        self._last_worker_message = message
        self.task_summary_label.setToolTip(message)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择网球视频",
            self.input_edit.text(),
            VIDEO_FILE_FILTER,
        )
        if path:
            self.input_edit.setText(path)
            self._refresh_input_preview()

    def _choose_input_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "选择视频文件夹", self.input_edit.text()
        )
        if path:
            self.input_edit.setText(path)
            self._refresh_input_preview()

    def _choose_output_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "选择输出文件夹", self.output_edit.text()
        )
        if path:
            self.output_edit.setText(path)

    def _open_output(self) -> None:
        try:
            path = parse_output_path(self.output_edit.text())
            path.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "无法打开输出目录", str(exc))

    def _refresh_input_preview(self) -> None:
        text = self.input_edit.text().strip()
        if not text:
            return
        path = Path(text)
        try:
            if path.is_dir():
                videos = scan_videos(path)
                path = videos[0] if videos else path
            if path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
                self._show_video_preview(path)
                self.video_count_label.setText("已载入预览")
        except (OSError, FileNotFoundError):
            return

    def _show_video_preview(self, path: Path) -> None:
        resolved = path.resolve()
        if self._preview_path == resolved:
            return
        self._preview_path = resolved
        self.current_video_label.setText(resolved.name)
        pixmap = _video_thumbnail(resolved)
        self.preview.set_source_pixmap(pixmap)
        self.preview_stack.setCurrentWidget(self.preview)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API 命名
        if self._review_session is not None:
            answer = QMessageBox.question(
                self,
                "退出并删除候选预览？",
                "当前还有尚未导出的候选片段。退出后会清理这些临时文件，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.media_player.stop()
        self.media_player.setSource(QUrl())
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self._terminate_process_tree()
            if not self.process.waitForFinished(1500):
                self.process.kill()
        if self._review_session is not None:
            discard_review_session(self._review_session)
            self._review_session = None
        event.accept()


def _card(title: str) -> QFrame:
    card = QFrame()
    card.setObjectName("card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 12, 16, 14)
    layout.setSpacing(9)
    label = QLabel(title)
    label.setObjectName("sectionTitle")
    layout.addWidget(label)
    return card


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("fieldLabel")
    label.setFixedWidth(105)
    return label


def _video_thumbnail(path: Path) -> QPixmap | None:
    """读取视频靠前画面作为任务预览。"""

    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            return None
        frame_count = max(0, int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        if frame_count > 10:
            capture.set(cv2.CAP_PROP_POS_FRAMES, min(frame_count - 1, frame_count // 12))
        ok, frame = capture.read()
        if not ok:
            capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = capture.read()
        if not ok or frame is None:
            return None
    finally:
        capture.release()

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    height, width, channels = rgb.shape
    image = QImage(
        rgb.data,
        width,
        height,
        channels * width,
        QImage.Format.Format_RGB888,
    ).copy()
    return QPixmap.fromImage(image)


def _double_spin(
    value: float, minimum: float, maximum: float, suffix: str
) -> QDoubleSpinBox:
    control = LargeArrowDoubleSpinBox()
    control.setRange(minimum, maximum)
    control.setDecimals(1)
    control.setSingleStep(0.5)
    control.setValue(value)
    control.setSuffix(suffix)
    control.setMinimumWidth(102)
    control.setMinimumHeight(40)
    return control


def _int_spin(value: int, minimum: int, maximum: int, suffix: str) -> QSpinBox:
    control = LargeArrowSpinBox()
    control.setRange(minimum, maximum)
    control.setValue(value)
    control.setSuffix(suffix)
    control.setMinimumWidth(102)
    control.setMinimumHeight(40)
    return control


def _make_arrow_icon(*, up: bool) -> QIcon:
    pixmap = QPixmap(18, 12)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#e7eaed"))
    if up:
        points = [(9, 2), (2, 10), (16, 10)]
    else:
        points = [(2, 2), (16, 2), (9, 10)]
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPolygon

    painter.drawPolygon(QPolygon([QPoint(x, y) for x, y in points]))
    painter.end()
    return QIcon(pixmap)


def _make_icon() -> QIcon:
    icon_path = _app_icon_path()
    if icon_path is not None:
        icon = QIcon(str(icon_path))
        if not icon.isNull():
            return icon
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#b9f45a"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(5, 5, 54, 54)
    painter.setPen(QColor("#151713"))
    font = QFont("Segoe UI", 22, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "T")
    painter.end()
    return QIcon(pixmap)


def _app_icon_path() -> Path | None:
    bundle_root = getattr(sys, "_MEIPASS", None)
    icon_names = (
        ("app_icon.ico", "app_icon.png")
        if os.name == "nt"
        else ("app_icon.png", "app_icon.ico")
    )
    asset_roots = [
        Path(bundle_root) / "assets" if bundle_root else None,
        Path(__file__).resolve().parents[2] / "assets",
    ]
    candidates = [
        root / icon_name
        for root in asset_roots
        if root is not None
        for icon_name in icon_names
    ]
    return next(
        (candidate for candidate in candidates if candidate and candidate.is_file()),
        None,
    )


def _set_windows_app_user_model_id() -> None:
    """让源码版和安装版在 Windows 任务栏中使用独立应用身份与图标。"""

    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
            WINDOWS_APP_USER_MODEL_ID
        )
    except (AttributeError, OSError):
        return


def _apply_windows_dark_frame(window: QMainWindow) -> None:
    if os.name != "nt":
        return
    try:
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
            int(window.winId()), 20, ctypes.byref(value), ctypes.sizeof(value)
        )
    except (AttributeError, OSError):
        return


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        from tennis_video_helper.cli import app as cli_app

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        cli_app()
        return
    _set_windows_app_user_model_id()
    app = QApplication(sys.argv)
    app.setApplicationName("Tennis Video Helper")
    app.setOrganizationName("TennisVideoHelper")
    app.setStyle("Fusion")
    app.setWindowIcon(_make_icon())
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


STYLE_SHEET = """
QMainWindow, QMenuBar, QMenu {
    background: #0a0b0d;
    color: #f4f5f6;
    font-family: "Segoe UI", "Microsoft YaHei UI";
}
QMenuBar { border-bottom: 1px solid #25282d; padding: 2px 8px; }
QMenuBar::item { padding: 6px 10px; background: transparent; }
QMenuBar::item:selected, QMenu::item:selected { background: #2b3035; }
QMenu { border: 1px solid #34383e; padding: 5px; }
QMenu::item { padding: 7px 28px 7px 12px; }
QWidget#root {
    background: #0a0b0d;
    color: #f4f5f6;
    font-family: "Segoe UI", "Microsoft YaHei UI";
    font-size: 13px;
}
QScrollArea#pageScroll { background: #0a0b0d; border: none; }
QLabel#eyebrow {
    color: #b9f45a;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
}
QLabel#heroTitle { color: #ffffff; font-size: 27px; font-weight: 700; }
QLabel#heroSubtitle { color: #8d9198; font-size: 13px; }
QLabel#statusBadge {
    color: #c9f77e;
    background: rgba(185, 244, 90, 0.10);
    border: 1px solid rgba(185, 244, 90, 0.24);
    border-radius: 14px;
    padding: 7px 12px;
    font-weight: 600;
}
QFrame#card, QFrame#workbenchCard {
    background: rgba(25, 27, 30, 0.96);
    border: 1px solid #2a2d32;
    border-radius: 15px;
}
QFrame#topBar {
    background: #141619;
    border: 1px solid #2a2d32;
    border-radius: 11px;
}
QFrame#reviewPanel, QFrame#previewPanel {
    background: #17191c;
    border: 1px solid #2c3035;
    border-radius: 12px;
}
QListWidget#candidateList {
    color: #eef1f3;
    background: #0d0f11;
    border: 1px solid #30343a;
    border-radius: 9px;
    padding: 4px;
    outline: none;
}
QListWidget#candidateList::item {
    border-radius: 7px;
    padding: 9px 7px;
    margin: 2px;
}
QListWidget#candidateList::item:selected {
    color: #f8fff0;
    background: #29361d;
    border: 1px solid #618a31;
}
QVideoWidget#videoWidget, QStackedWidget#previewStack {
    background: #050607;
    border: 1px solid #30343a;
    border-radius: 10px;
}
QWidget#hitTimeline {
    background: #101215;
    border: 1px solid #292d32;
    border-radius: 10px;
}
QLabel#hitCountLabel { color: #b9f45a; font-weight: 700; }
QFrame#workbenchCard {
    background: #111316;
    border-color: #30343a;
}
QFrame#statusPanel {
    background: #171a1e;
    border: 1px solid #30353b;
    border-radius: 13px;
}
QLabel#videoPreview {
    color: #777d85;
    background: #070809;
    border: 1px solid #30343a;
    border-radius: 12px;
    padding: 4px;
}
QLabel#workbenchTitle { color: #f5f6f7; font-size: 15px; font-weight: 700; }
QLabel#mutedLabel { color: #858a91; }
QLabel#currentVideo { color: #c6cbd1; font-size: 12px; }
QLabel#percentLabel { color: #b9f45a; font-size: 42px; font-weight: 700; }
QLabel#phaseLabel { color: #f2f4f5; font-size: 16px; font-weight: 600; }
QLabel#accelerationStatus {
    background: #111418;
    border: 1px solid #30353c;
    border-radius: 8px;
    color: #aeb4bc;
    font-size: 11px;
    font-weight: 600;
    padding: 7px 9px;
}
QLabel#accelerationStatus[mode="enabled"] {
    background: #16210f;
    border-color: #5d8529;
    color: #b9f45a;
}
QLabel#accelerationStatus[mode="partial"] {
    background: #241f0e;
    border-color: #8d7427;
    color: #f2cf62;
}
QLabel#accelerationStatus[mode="cpu"] {
    background: #291616;
    border-color: #834040;
    color: #ff9e9e;
}
QLabel#metricLabel { color: #7f858d; font-size: 11px; }
QLabel#metricValue {
    color: #f2f4f5;
    font-size: 16px;
    font-weight: 600;
    font-family: "Cascadia Mono", "Consolas";
}
QLabel#taskSummary { color: #8f959d; font-size: 12px; }
QLabel#sectionTitle { color: #f3f4f5; font-size: 14px; font-weight: 700; }
QLabel#fieldLabel { color: #aeb2b8; font-weight: 600; }
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {
    color: #f1f2f3;
    background: #101215;
    border: 1px solid #30343a;
    border-radius: 10px;
    padding: 8px 10px;
    selection-background-color: #6f9935;
}
QDoubleSpinBox, QSpinBox, QComboBox {
    padding: 4px 34px 4px 9px;
}
QDoubleSpinBox QLineEdit, QSpinBox QLineEdit {
    color: #f1f2f3;
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0;
}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #94c84a;
}
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 28px;
    border-left: 1px solid #30343a;
    border-bottom: 1px solid #262a2f;
    background: #1b1e22;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 28px;
    border-left: 1px solid #30343a;
    background: #1b1e22;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background: #30353b;
}
QToolButton#spinUpButton, QToolButton#spinDownButton {
    background: #1b1e22;
    border: none;
    border-left: 1px solid #30343a;
    border-radius: 0;
    padding: 0;
}
QToolButton#spinUpButton {
    border-bottom: 1px solid #2a2e33;
    border-top-right-radius: 9px;
}
QToolButton#spinDownButton { border-bottom-right-radius: 9px; }
QToolButton#spinUpButton:hover, QToolButton#spinDownButton:hover {
    background: #34393f;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border-left: 1px solid #30343a;
}
QPushButton {
    color: #e7e9ec;
    background: #292c31;
    border: 1px solid #383c42;
    border-radius: 10px;
    padding: 8px 13px;
    font-weight: 600;
}
QPushButton:hover { background: #34383e; border-color: #4a4f57; }
QPushButton:pressed { background: #22252a; }
QPushButton:disabled { color: #666a70; background: #1d1f22; border-color: #292c30; }
QPushButton#primaryButton {
    color: #11150c;
    background: #b9f45a;
    border: 1px solid #c8ff73;
    padding: 11px 24px;
    font-size: 15px;
}
QPushButton#primaryButton:hover { background: #c8ff73; }
QPushButton#dangerButton { color: #ffb7b7; background: #352426; border-color: #573437; }
QPushButton#modeButton:checked {
    color: #11150c;
    background: #b9f45a;
    border-color: #c8ff73;
}
QFrame#parameterTile {
    background: #121417;
    border: 1px solid #292c31;
    border-radius: 12px;
}
QLabel#parameterTitle { color: #e8eaec; font-weight: 700; }
QLabel#parameterNote { color: #777d85; font-size: 10px; }
QCheckBox { color: #d6d8db; spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QCheckBox::indicator:unchecked { background: #0e1012; border: 1px solid #41464d; border-radius: 4px; }
QCheckBox::indicator:checked { background: #b9f45a; border: 1px solid #b9f45a; border-radius: 4px; }
QProgressBar {
    color: #f4f6f7;
    background: #0d0f11;
    border: 1px solid #2d3237;
    border-radius: 10px;
    text-align: center;
    font-size: 11px;
    font-weight: 600;
}
QProgressBar::chunk { background: #8fcf3d; border-radius: 9px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #3a3e44; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


if __name__ == "__main__":
    main()
