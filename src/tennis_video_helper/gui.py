"""TennisVideoHelper 的 PySide6 桌面界面。"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from tennis_video_helper.media import SUPPORTED_VIDEO_EXTENSIONS


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
    ]
    arguments.append("--require-gpu" if values.require_gpu else "--allow-cpu")
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)

        header = QHBoxLayout()
        label = QLabel(title)
        label.setObjectName("parameterTitle")
        header.addWidget(label)
        header.addStretch()
        header.addWidget(control)
        layout.addLayout(header)

        note = QLabel(description)
        note.setObjectName("parameterNote")
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(note)


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

        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(1000)
        self.elapsed_timer.timeout.connect(self._update_elapsed)

        self.setWindowTitle("Tennis Video Helper")
        self.setMinimumSize(980, 720)
        self.resize(1180, 820)
        self.setWindowIcon(_make_icon())
        self.setStyleSheet(STYLE_SHEET)

        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(26, 22, 26, 24)
        root.setSpacing(16)

        root.addLayout(self._build_header())
        root.addWidget(self._build_path_card())
        root.addWidget(self._build_parameter_card())
        root.addWidget(self._build_action_card())
        root.addWidget(self._build_log_card(), 1)

        self._set_running(False)
        QTimer.singleShot(0, lambda: _apply_windows_dark_frame(self))

    def _build_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(2)

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

    def _build_path_card(self) -> QFrame:
        card = _card("输入与输出")
        layout = card.layout()

        default_input = Path.cwd() / "网球"
        default_output = Path.cwd() / "精选输出"
        self.input_edit = QLineEdit(
            str(default_input if default_input.exists() else Path.cwd())
        )
        self.input_edit.setPlaceholderText("选择单个视频，或包含视频的文件夹")
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
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        self.min_rally = _double_spin(10.0, 1.0, 600.0, " 秒")
        self.pre_roll = _double_spin(2.0, 0.0, 30.0, " 秒")
        self.post_roll = _double_spin(3.0, 0.0, 30.0, " 秒")
        self.end_silence = _double_spin(3.5, 0.1, 30.0, " 秒")
        self.analysis_fps = _int_spin(12, 1, 30, " FPS")
        self.audio_sensitivity = _double_spin(1.0, 0.1, 3.0, " ×")
        self.visual_sensitivity = _double_spin(1.0, 0.1, 3.0, " ×")
        self.inference_backend = QComboBox()
        self.inference_backend.addItem("自动（TensorRT 优先）", "auto")
        self.inference_backend.addItem("TensorRT", "tensorrt")
        self.inference_backend.addItem("PyTorch CUDA", "torch")
        self.inference_precision = QComboBox()
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
            grid.addWidget(ParameterTile(title, note, control), index // 4, index % 4)

        limit_box = QFrame()
        limit_box.setObjectName("parameterTile")
        limit_layout = QHBoxLayout(limit_box)
        limit_layout.setContentsMargins(14, 12, 14, 12)
        self.limit_check = QCheckBox("仅分析前")
        self.limit_minutes = _double_spin(5.0, 0.1, 180.0, " 分钟")
        self.limit_minutes.setEnabled(False)
        self.limit_check.toggled.connect(self.limit_minutes.setEnabled)
        self.require_gpu = QCheckBox("缺少 GPU 时直接停止")
        limit_layout.addWidget(self.limit_check)
        limit_layout.addWidget(self.limit_minutes)
        limit_layout.addWidget(self.require_gpu)
        limit_layout.addStretch()
        hint = QLabel("适合快速试跑和调参；关闭后分析完整视频。")
        hint.setObjectName("parameterNote")
        limit_layout.addWidget(hint)
        grid.addWidget(limit_box, 1, 3)

        layout.addLayout(grid)
        return card

    def _build_action_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("actionCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)

        self.start_button = QPushButton("开始筛选")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self._start_analysis)
        self.stop_button = QPushButton("停止任务")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.clicked.connect(self._stop_analysis)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(7)
        self.elapsed_label = QLabel("00:00:00")
        self.elapsed_label.setObjectName("elapsed")

        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.progress, 1)
        layout.addWidget(self.elapsed_label)
        return card

    def _build_log_card(self) -> QFrame:
        card = _card("运行日志")
        layout = card.layout()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("任务开始后，这里会显示环境检查和每个视频的处理结果。")
        self.log.setMaximumBlockCount(2000)
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
        self._append_log("正在检查 FFmpeg、NVENC 与 CUDA 环境……")

        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUTF8", "1")
        environment.insert("PYTHONUNBUFFERED", "1")
        environment.insert("NO_COLOR", "1")
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(str(Path.cwd()))

        self._stopping = False
        self._started_at = time.monotonic()
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
        if text:
            self.log.insertPlainText(text)
            self.log.ensureCursorVisible()

    def _process_finished(self, exit_code: int, _status) -> None:
        self._read_process_output()
        self.elapsed_timer.stop()
        self._set_running(False)
        if self._stopping:
            self.status_badge.setText("●  已停止")
            self._append_log("任务已停止。再次运行时会自动创建新的输出子目录。")
        elif exit_code == 0:
            self.status_badge.setText("●  处理完成")
            self.progress.setValue(1)
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
            self.status_badge.setText("●  GPU 处理中")
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 1)
            if not self.status_badge.text():
                self.status_badge.setText("●  等待任务")

    def _update_elapsed(self) -> None:
        seconds = int(time.monotonic() - self._started_at)
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.elapsed_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

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

    def _choose_input_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "选择视频文件夹", self.input_edit.text()
        )
        if path:
            self.input_edit.setText(path)

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
    layout.setContentsMargins(18, 15, 18, 17)
    layout.setSpacing(12)
    label = QLabel(title)
    label.setObjectName("sectionTitle")
    layout.addWidget(label)
    return card


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("fieldLabel")
    label.setFixedWidth(112)
    return label


def _double_spin(
    value: float, minimum: float, maximum: float, suffix: str
) -> QDoubleSpinBox:
    control = QDoubleSpinBox()
    control.setRange(minimum, maximum)
    control.setDecimals(1)
    control.setSingleStep(0.5)
    control.setValue(value)
    control.setSuffix(suffix)
    control.setMinimumWidth(105)
    return control


def _int_spin(value: int, minimum: int, maximum: int, suffix: str) -> QSpinBox:
    control = QSpinBox()
    control.setRange(minimum, maximum)
    control.setValue(value)
    control.setSuffix(suffix)
    control.setMinimumWidth(105)
    return control


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
QLabel#eyebrow {
    color: #b9f45a;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
}
QLabel#heroTitle { color: #ffffff; font-size: 30px; font-weight: 700; }
QLabel#heroSubtitle { color: #8d9198; font-size: 13px; }
QLabel#statusBadge {
    color: #c9f77e;
    background: rgba(185, 244, 90, 0.10);
    border: 1px solid rgba(185, 244, 90, 0.24);
    border-radius: 14px;
    padding: 7px 12px;
    font-weight: 600;
}
QFrame#card, QFrame#actionCard {
    background: rgba(25, 27, 30, 0.96);
    border: 1px solid #2a2d32;
    border-radius: 18px;
}
QFrame#actionCard { background: rgba(20, 22, 24, 0.98); }
QLabel#sectionTitle { color: #f3f4f5; font-size: 14px; font-weight: 700; }
QLabel#fieldLabel { color: #aeb2b8; font-weight: 600; }
QLineEdit, QPlainTextEdit, QDoubleSpinBox, QSpinBox {
    color: #f1f2f3;
    background: #101215;
    border: 1px solid #30343a;
    border-radius: 10px;
    padding: 8px 10px;
    selection-background-color: #6f9935;
}
QLineEdit:focus, QPlainTextEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {
    border: 1px solid #94c84a;
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
    padding: 10px 24px;
}
QPushButton#primaryButton:hover { background: #c8ff73; }
QPushButton#dangerButton { color: #ffb7b7; background: #352426; border-color: #573437; }
QFrame#parameterTile {
    background: #121417;
    border: 1px solid #292c31;
    border-radius: 12px;
}
QLabel#parameterTitle { color: #e8eaec; font-weight: 700; }
QLabel#parameterNote { color: #7f848c; font-size: 11px; }
QLabel#elapsed { color: #a5a9af; font-family: "Cascadia Mono", "Consolas"; }
QCheckBox { color: #d6d8db; spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QCheckBox::indicator:unchecked { background: #0e1012; border: 1px solid #41464d; border-radius: 4px; }
QCheckBox::indicator:checked { background: #b9f45a; border: 1px solid #b9f45a; border-radius: 4px; }
QProgressBar { background: #181b1e; border: none; border-radius: 3px; }
QProgressBar::chunk { background: #b9f45a; border-radius: 3px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #3a3e44; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


if __name__ == "__main__":
    main()
