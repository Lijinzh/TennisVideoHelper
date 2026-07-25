"""TennisVideoHelper 的 PySide6 桌面界面。"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2

from PySide6.QtCore import QProcess, QProcessEnvironment, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QImage,
    QPainter,
    QPixmap,
)
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
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tennis_video_helper.cli import ACCELERATION_PREFIX, PROGRESS_PREFIX
from tennis_video_helper.media import SUPPORTED_VIDEO_EXTENSIONS, scan_videos


VIDEO_FILE_FILTER = (
    "视频文件 ("
    + " ".join(f"*{extension}" for extension in sorted(SUPPORTED_VIDEO_EXTENSIONS))
    + ");;所有文件 (*)"
)


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
    ]
    arguments.append("--require-gpu" if values.require_gpu else "--allow-cpu")
    arguments.append(
        "--overwrite-existing"
        if values.overwrite_existing_output
        else "--keep-existing"
    )
    if values.limit_duration is not None:
        arguments.extend(["--limit-duration", _number(values.limit_duration)])
    return arguments


def _number(value: float) -> str:
    return f"{value:g}"


def _cuda_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return bool(torch.cuda.is_available())


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
        self.setMinimumSize(220, 255)
        self.setMaximumSize(260, 310)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

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
        self._preview_path: Path | None = None
        self._acceleration_status: dict[str, object] = {}

        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(1000)
        self.elapsed_timer.timeout.connect(self._update_elapsed)

        self.setWindowTitle("Tennis Video Helper")
        self.setMinimumSize(1100, 760)
        self.resize(1440, 920)
        self.setWindowIcon(_make_icon())
        self.setStyleSheet(STYLE_SHEET)

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
        self.workbench_card = self._build_workbench_card()
        root.addWidget(self.workbench_card)
        self.parameter_card = self._build_parameter_card()
        root.addWidget(self.parameter_card)
        root.addStretch(1)

        self._set_running(False)
        QTimer.singleShot(0, self._refresh_input_preview)
        QTimer.singleShot(0, self._show_initial_view)
        QTimer.singleShot(0, self._fit_workbench_height)
        QTimer.singleShot(0, lambda: _apply_windows_dark_frame(self))

    def _show_initial_view(self) -> None:
        """让首次打开时停留在顶部主工作区。"""

        self.start_button.setFocus()
        self.page_scroll.verticalScrollBar().setValue(0)

    def _fit_workbench_height(self) -> None:
        """以紧凑布局为下限，把额外高度留给日志和状态间距。"""

        margins = self.root_layout.contentsMargins()
        fixed_height = (
            margins.top()
            + margins.bottom()
            + self.root_layout.itemAt(0).sizeHint().height()
            + self.parameter_card.sizeHint().height()
            + self.root_layout.spacing() * 2
        )
        target = self.page_scroll.viewport().height() - fixed_height
        self.workbench_card.setFixedHeight(max(352, min(400, target)))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if hasattr(self, "workbench_card") and hasattr(self, "parameter_card"):
            QTimer.singleShot(0, self._fit_workbench_height)
            QTimer.singleShot(60, self._fit_workbench_height)

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

    def _build_workbench_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("workbenchCard")
        card.setMinimumHeight(352)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(18)

        preview_panel = QWidget()
        preview_panel.setObjectName("previewColumn")
        preview_panel.setMinimumWidth(240)
        preview_panel.setMaximumWidth(280)
        preview_column = QVBoxLayout(preview_panel)
        preview_column.setContentsMargins(0, 0, 0, 0)
        preview_column.setSpacing(8)
        preview_header = QHBoxLayout()
        preview_title = QLabel("当前处理视频")
        preview_title.setObjectName("workbenchTitle")
        self.video_count_label = QLabel("等待选择视频")
        self.video_count_label.setObjectName("mutedLabel")
        preview_header.addWidget(preview_title)
        preview_header.addStretch()
        preview_header.addWidget(self.video_count_label)
        preview_column.addLayout(preview_header)

        self.preview = PreviewLabel()
        preview_column.addWidget(self.preview, 1)
        self.current_video_label = QLabel("尚未开始任务")
        self.current_video_label.setObjectName("currentVideo")
        self.current_video_label.setWordWrap(True)
        preview_column.addWidget(self.current_video_label)
        layout.addWidget(preview_panel)

        status_panel = QFrame()
        status_panel.setObjectName("statusPanel")
        status_panel.setMinimumWidth(280)
        status_panel.setMaximumWidth(350)
        status_layout = QVBoxLayout(status_panel)
        status_layout.setContentsMargins(18, 18, 18, 18)
        status_layout.setSpacing(6)

        button_row = QHBoxLayout()
        self.start_button = QPushButton("开始筛选")
        self.start_button.setObjectName("primaryButton")
        self.start_button.setMinimumHeight(48)
        self.start_button.clicked.connect(self._start_analysis)
        self.stop_button = QPushButton("停止任务")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.setMinimumHeight(48)
        self.stop_button.clicked.connect(self._stop_analysis)
        button_row.addWidget(self.start_button, 2)
        button_row.addWidget(self.stop_button, 1)
        status_layout.addLayout(button_row)

        self.acceleration_label = QLabel("GPU 加速：等待任务检查")
        self.acceleration_label.setObjectName("accelerationStatus")
        self.acceleration_label.setProperty("mode", "pending")
        self.acceleration_label.setWordWrap(True)
        status_layout.addWidget(self.acceleration_label)
        status_layout.addStretch(1)

        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("percentLabel")
        self.phase_label = QLabel("等待开始")
        self.phase_label.setObjectName("phaseLabel")
        self.phase_label.setWordWrap(True)
        status_layout.addWidget(self.percent_label)
        status_layout.addWidget(self.phase_label)
        status_layout.addStretch(1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setFormat("0.0%")
        self.progress.setTextVisible(True)
        self.progress.setFixedHeight(22)
        status_layout.addWidget(self.progress)
        status_layout.addStretch(1)

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
        status_layout.addStretch(1)

        self.task_summary_label = QLabel("选择视频后即可开始 GPU 筛选")
        self.task_summary_label.setObjectName("taskSummary")
        self.task_summary_label.setWordWrap(True)
        status_layout.addWidget(self.task_summary_label)
        layout.addWidget(status_panel)

        utility_column = QVBoxLayout()
        utility_column.setSpacing(10)
        utility_column.addWidget(self._build_path_card())
        utility_column.addWidget(self._build_log_card(), 1)
        layout.addLayout(utility_column, 1)
        return card

    def _build_path_card(self) -> QFrame:
        card = _card("输入与输出")
        layout = card.layout()

        default_input = Path.cwd() / "网球"
        default_output = Path.cwd() / "精选输出"
        self.input_edit = QLineEdit(
            str(default_input if default_input.exists() else Path.cwd())
        )
        self.input_edit.setPlaceholderText("选择单个视频，或包含视频的文件夹")
        self.input_edit.editingFinished.connect(self._refresh_input_preview)
        self.output_edit = QLineEdit(str(default_output))
        self.output_edit.setPlaceholderText("选择精选片段保存目录")

        input_row = QHBoxLayout()
        input_row.addWidget(_field_label("源视频 / 文件夹"))
        input_row.addWidget(self.input_edit, 1)
        choose_file = QPushButton("选择视频")
        choose_file.clicked.connect(self._choose_file)
        choose_folder = QPushButton("选择文件夹")
        choose_folder.clicked.connect(self._choose_input_folder)
        input_row.addWidget(choose_file)
        input_row.addWidget(choose_folder)

        output_row = QHBoxLayout()
        output_row.addWidget(_field_label("输出文件夹"))
        output_row.addWidget(self.output_edit, 1)
        choose_output = QPushButton("选择目录")
        choose_output.clicked.connect(self._choose_output_folder)
        output_row.addWidget(choose_output)
        self.open_output_button = QPushButton("打开输出")
        self.open_output_button.clicked.connect(self._open_output)
        output_row.addWidget(self.open_output_button)

        layout.addLayout(input_row)
        layout.addLayout(output_row)
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
        self.overwrite_existing_output = QCheckBox("覆盖同名旧结果")
        self.overwrite_existing_output.setChecked(True)
        self.overwrite_existing_output.setToolTip(
            "新结果完整生成并验证成功后才替换旧结果；失败或停止不会删除旧结果。"
        )
        limit_layout.addWidget(self.limit_check)
        limit_layout.addWidget(self.limit_minutes)
        limit_layout.addWidget(self.require_gpu)
        limit_layout.addWidget(self.overwrite_existing_output)
        limit_layout.addStretch()
        hint = QLabel("适合快速试跑和调参；关闭后分析完整视频。")
        hint.setObjectName("parameterNote")
        limit_layout.addWidget(hint)
        grid.addWidget(limit_box, 2, 0, 1, 5)

        layout.addLayout(grid)
        return card

    def _build_log_card(self) -> QFrame:
        card = _card("运行日志")
        layout = card.layout()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("任务开始后，这里会显示环境检查和每个视频的处理结果。")
        self.log.setMaximumBlockCount(2000)
        self.log.setMinimumHeight(90)
        self.log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.log)
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
            overwrite_existing_output=self.overwrite_existing_output.isChecked(),
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

        self.log.clear()
        self._append_log(f"开始处理：{values.input_path}")
        self._append_log(f"输出目录：{values.output_path}")
        self._append_log(
            "同名结果：成功后覆盖旧结果"
            if values.overwrite_existing_output
            else "同名结果：保留旧结果并创建编号目录"
        )
        self._append_log("正在检查 FFmpeg、NVENC 与 CUDA 环境……")

        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUTF8", "1")
        environment.insert("PYTHONUNBUFFERED", "1")
        environment.insert("NO_COLOR", "1")
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(str(Path.cwd()))

        self._stopping = False
        self._started_at = time.monotonic()
        self._progress_percent = 0.0
        self._process_output_buffer = ""
        self._acceleration_status = {}
        self._set_acceleration_label("pending", "GPU 加速：正在检查……")
        self.progress.setValue(0)
        self.progress.setFormat("0.0%")
        self.percent_label.setText("0%")
        self.phase_label.setText("正在检查运行环境")
        self.eta_label.setText("正在估算")
        self.elapsed_timer.start()
        self._set_running(True)
        self.process.start(sys.executable, build_analyze_arguments(values))

    def _stop_analysis(self) -> None:
        if self.process.state() == QProcess.ProcessState.NotRunning:
            return
        self._stopping = True
        self._append_log("正在停止任务；当前未完成片段可能会保留为临时文件……")
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
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if not text:
            return
        self._process_output_buffer += text
        while "\n" in self._process_output_buffer:
            line, self._process_output_buffer = self._process_output_buffer.split("\n", 1)
            self._handle_process_line(line.rstrip("\r"))

    def _handle_process_line(self, line: str) -> None:
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
        if self._process_output_buffer:
            self._handle_process_line(self._process_output_buffer.rstrip("\r"))
            self._process_output_buffer = ""
        self.elapsed_timer.stop()
        self._set_running(False)
        if self._stopping:
            self.status_badge.setText("●  已停止")
            self._append_log("任务已停止；已有成功结果不会被覆盖。")
        elif exit_code == 0:
            self.status_badge.setText("●  处理完成")
            self._progress_percent = 100.0
            self.progress.setValue(1000)
            self.progress.setFormat("100.0%")
            self.percent_label.setText("100%")
            self.phase_label.setText("全部任务完成")
            self.eta_label.setText("已完成")
            self._append_log("全部任务完成，可以打开输出目录查看精选片段。")
        else:
            self.status_badge.setText("●  处理失败")
            self._append_log(f"任务异常结束，退出代码：{exit_code}")

    def _process_error(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.elapsed_timer.stop()
            self._set_running(False)
            self.status_badge.setText("●  启动失败")
            self._append_log(f"无法启动后台任务：{self.process.errorString()}")

    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.input_edit.setEnabled(not running)
        self.output_edit.setEnabled(not running)
        if running:
            self.status_badge.setText("●  正在处理")
            self.progress.setRange(0, 1000)
        else:
            self.progress.setRange(0, 1000)
            if not self.status_badge.text():
                self.status_badge.setText("●  等待任务")

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
        self.log.appendPlainText(message)

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

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API 命名
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self._terminate_process_tree()
            if not self.process.waitForFinished(1500):
                self.process.kill()
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
    app = QApplication(sys.argv)
    app.setApplicationName("Tennis Video Helper")
    app.setOrganizationName("TennisVideoHelper")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


STYLE_SHEET = """
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
QLineEdit, QPlainTextEdit, QDoubleSpinBox, QSpinBox, QComboBox {
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
QLineEdit:focus, QPlainTextEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {
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
QPlainTextEdit {
    font-family: "Cascadia Mono", "Consolas";
    font-size: 12px;
    padding: 12px;
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
