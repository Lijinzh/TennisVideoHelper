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
    QSettings,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QGuiApplication,
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
from PySide6.QtWidgets import QMessageBox as _QtMessageBox

from tennis_video_helper.app.cli import ACCELERATION_PREFIX, PROGRESS_PREFIX, REVIEW_PREFIX
from tennis_video_helper import __version__
from tennis_video_helper.media.probe import SUPPORTED_VIDEO_EXTENSIONS, scan_videos
from tennis_video_helper.app.optimizer import (
    OPTIMIZATION_PREFIX,
    OptimizationProfile,
    load_profile,
)
from tennis_video_helper.review.session import (
    ReviewClipCandidate,
    ReviewSession,
    ReviewVideoCandidate,
    discard_review_session,
    load_review_session,
    publish_review_session,
)
from tennis_video_helper.media.runtime import subprocess_no_window_kwargs
from tennis_video_helper.resources import asset_path
from tennis_video_helper.ui.pixel_effects import PixelMotionRail
from tennis_video_helper.ui.update_controller import UpdateController
from tennis_video_helper.ui.i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGE_SETTINGS_KEY,
    normalize_language,
    set_language,
    translate_text,
)


class QLabel(QLabel):
    def __init__(self, text: str = "", *args, **kwargs) -> None:
        super().__init__(translate_text(text), *args, **kwargs)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        super().setText(translate_text(text))


class QPushButton(QPushButton):
    def __init__(self, text: str = "", *args, **kwargs) -> None:
        super().__init__(translate_text(text), *args, **kwargs)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        super().setText(translate_text(text))


class QToolButton(QToolButton):
    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        super().setText(translate_text(text))


class QCheckBox(QCheckBox):
    def __init__(self, text: str = "", *args, **kwargs) -> None:
        super().__init__(translate_text(text), *args, **kwargs)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        super().setText(translate_text(text))


class QLineEdit(QLineEdit):
    def setPlaceholderText(self, text: str) -> None:  # noqa: N802 - Qt API
        super().setPlaceholderText(translate_text(text))


class QComboBox(QComboBox):
    def addItem(self, text: str, userData=None) -> None:  # noqa: N802 - Qt API
        super().addItem(translate_text(text), userData)

    def setItemText(self, index: int, text: str) -> None:  # noqa: N802 - Qt API
        super().setItemText(index, translate_text(text))


class QDoubleSpinBox(QDoubleSpinBox):
    def setSuffix(self, suffix: str) -> None:  # noqa: N802 - Qt API
        super().setSuffix(translate_text(suffix))


class QSpinBox(QSpinBox):
    def setSuffix(self, suffix: str) -> None:  # noqa: N802 - Qt API
        super().setSuffix(translate_text(suffix))


class QAction(QAction):
    def __init__(self, text: str = "", *args, **kwargs) -> None:
        super().__init__(translate_text(text), *args, **kwargs)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        super().setText(translate_text(text))


class QMessageBox(QMessageBox):
    @staticmethod
    def _translated_args(args: tuple) -> tuple:
        return tuple(translate_text(value) if isinstance(value, str) else value for value in args)

    @staticmethod
    def about(*args, **kwargs):
        return _QtMessageBox.about(*QMessageBox._translated_args(args), **kwargs)

    @staticmethod
    def warning(*args, **kwargs):
        return _QtMessageBox.warning(*QMessageBox._translated_args(args), **kwargs)

    @staticmethod
    def information(*args, **kwargs):
        return _QtMessageBox.information(*QMessageBox._translated_args(args), **kwargs)

    @staticmethod
    def critical(*args, **kwargs):
        return _QtMessageBox.critical(*QMessageBox._translated_args(args), **kwargs)

    @staticmethod
    def question(*args, **kwargs):
        return _QtMessageBox.question(*QMessageBox._translated_args(args), **kwargs)


VIDEO_FILE_FILTER = (
    "视频文件 ("
    + " ".join(f"*{extension}" for extension in sorted(SUPPORTED_VIDEO_EXTENSIONS))
    + ");;所有文件 (*)"
)
WINDOWS_APP_USER_MODEL_ID = "TennisVideoHelper.Desktop.0.1"
SETTINGS_ORGANIZATION = "TennisVideoHelper"
SETTINGS_APPLICATION = "TennisVideoHelper"
CANDIDATE_VIEWED_ROLE = int(Qt.ItemDataRole.UserRole) + 1
COURT_BACKGROUND_SETTINGS_KEY = "appearance/court_background"


def _application_settings() -> QSettings:
    return QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)


def _settings_bool(settings, key: str, default: bool) -> bool:
    value = settings.value(key, default)
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _system_uses_dark_theme() -> bool:
    """读取 Qt 的系统配色；Windows 上为未知时再读取应用主题注册表值。"""

    app = QGuiApplication.instance()
    if app is not None:
        scheme = app.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    if os.name == "nt":
        registry = QSettings(
            r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion"
            r"\Themes\Personalize",
            QSettings.Format.NativeFormat,
        )
        try:
            return int(registry.value("AppsUseLightTheme", 1)) == 0
        except (TypeError, ValueError):
            pass
    return False


@dataclass(frozen=True, slots=True)
class CourtBackgroundTheme:
    """可选的软件球场背景。"""

    id: str
    label: str
    description: str
    asset_name: str | None = None
    overlay_alpha: int = 126


COURT_BACKGROUND_THEMES = (
    CourtBackgroundTheme(
        "classic",
        "经典黑色",
        "保留原来的像素黑色界面，并继续跟随 Windows 明暗模式。",
    ),
    CourtBackgroundTheme(
        "shanbei-loess",
        "陕北风黄土球场",
        "黄土高坡、窑洞与暖色夕阳组成的陕北像素球场。",
        "shanbei-loess-court.webp",
        116,
    ),
    CourtBackgroundTheme(
        "roland-garros",
        "法网 · 罗兰·加洛斯红土",
        "以巴黎红土、橙红看台和暖色灯光为主的像素球场。",
        "roland-garros-clay-court.webp",
        126,
    ),
    CourtBackgroundTheme(
        "wimbledon",
        "温布尔登草地",
        "经典草地、深绿色看台与英伦氛围的像素球场。",
        "wimbledon-grass-court.webp",
        120,
    ),
    CourtBackgroundTheme(
        "us-open",
        "美网夜场",
        "深蓝硬地、城市夜色与聚光灯氛围的像素球场。",
        "us-open-night-court.webp",
        116,
    ),
    CourtBackgroundTheme(
        "australian-open",
        "澳网蓝色硬地",
        "明亮蓝色硬地与盛夏天空构成的澳网像素球场。",
        "australian-open-day-court.webp",
        132,
    ),
    CourtBackgroundTheme(
        "shanghai-qizhong",
        "上海大师赛 · 旗忠网球中心",
        "玉兰花瓣屋顶、蓝绿硬地与上海城市气质组成的像素球场。",
        "shanghai-qizhong-court.webp",
        126,
    ),
    CourtBackgroundTheme(
        "beijing-diamond",
        "北京国家网球中心 · 钻石球场",
        "紫蓝硬地、钻石切面场馆与远处鸟巢天际线构成的像素球场。",
        "beijing-national-tennis-center.webp",
        126,
    ),
    CourtBackgroundTheme(
        "madrid-caja-magica",
        "马德里 · 魔力盒球场",
        "砖红红土、深色钢结构和几何屋顶形成强烈舞台感。",
        "madrid-caja-magica-court.webp",
        122,
    ),
    CourtBackgroundTheme(
        "rio-jockey-club",
        "里约 · 赛马会球场",
        "橙红球场、棕榈与热带山景组成明亮的南美像素场景。",
        "rio-jockey-club-court.webp",
        126,
    ),
    CourtBackgroundTheme(
        "indian-wells",
        "印第安维尔斯 · 沙漠花园",
        "蓝色硬地、棕榈与科切拉谷山脉围成沙漠绿洲球场。",
        "indian-wells-desert-court.webp",
        126,
    ),
    CourtBackgroundTheme(
        "dunhuang",
        "敦煌 · 鸣沙山月牙泉",
        "沙丘、月牙泉与丝路驿亭组成的敦煌概念像素球场。",
        "dunhuang-desert-court.webp",
        116,
    ),
    CourtBackgroundTheme(
        "himalaya",
        "喜马拉雅山麓",
        "雪山、经幡与高原天空围绕的喜马拉雅概念像素球场。",
        "himalaya-foothills-court.webp",
        122,
    ),
    CourtBackgroundTheme(
        "larung-gar",
        "喇荣山谷",
        "层叠红房、山谷和高原光线组成的喇荣概念像素球场。",
        "larung-gar-valley-court.webp",
        120,
    ),
    CourtBackgroundTheme(
        "hyrule-inspired",
        "海拉鲁式旷野",
        "草原、远山与幻想遗迹组成的旷野冒险风概念球场。",
        "hyrule-inspired-court.webp",
        118,
    ),
    CourtBackgroundTheme(
        "ashina-inspired",
        "苇名式山城",
        "山城、枫叶与冷峻天色组成的战国幻想风概念球场。",
        "ashina-inspired-court.webp",
        116,
    ),
)
COURT_BACKGROUND_THEME_BY_ID = {
    theme.id: theme for theme in COURT_BACKGROUND_THEMES
}


def _normalize_court_background(theme_id: object) -> str:
    normalized = str(theme_id or "classic")
    return normalized if normalized in COURT_BACKGROUND_THEME_BY_ID else "classic"


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
    min_confirmed_hits: int = 3
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
        "tennis_video_helper.app.cli",
        "analyze",
        str(values.input_path),
        "--output",
        str(values.output_path),
        "--min-rally-duration",
        _number(values.min_rally_duration),
        "--min-confirmed-hits",
        str(values.min_confirmed_hits),
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
        "tennis_video_helper.app.cli",
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


def format_analysis_scope(limit_duration: float | None) -> str:
    """Return a user-facing description of the actual video range being scanned."""

    if limit_duration is None:
        return "分析范围：完整视频"
    return (
        f"分析范围：仅前 {_number(limit_duration / 60)} 分钟"
        "（其余内容不会检查）"
    )


def empty_candidate_guidance(limit_duration: float | None) -> str:
    """Explain an empty result without hiding an active duration limit."""

    if limit_duration is None:
        return "完整视频中没有找到候选；可以调低最短回合或灵敏度后重新分析。"
    return (
        f"本次只分析了前 {_number(limit_duration / 60)} 分钟；"
        "此范围内没有候选。关闭“仅分析前”后可检查完整视频。"
    )


def incompatible_analysis_scope_message(
    limit_duration: float | None,
    min_rally_duration: float,
) -> str | None:
    """Explain when the selected scan range cannot contain a valid rally."""

    if limit_duration is None or limit_duration >= min_rally_duration:
        return None
    return (
        f"当前只分析前 {_number(limit_duration)} 秒，但最短回合设置为 "
        f"{_number(min_rally_duration)} 秒，因此必然无法生成候选片段。"
        "请关闭“仅分析前”，或增大分析范围。"
    )


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


def resolve_input_folder(input_text: str) -> Path:
    """把输入视频或输入目录转换为可在资源管理器中打开的目录。"""

    if not input_text.strip():
        raise ValueError("请选择源视频或文件夹。")
    path = Path(input_text.strip())
    if path.is_dir():
        return path.resolve()
    if path.is_file():
        return path.parent.resolve()
    raise ValueError(f"输入路径不存在：{path}")


def open_local_folder(path: Path) -> None:
    """使用当前平台的文件管理器打开一个已存在目录。"""

    resolved = path.resolve()
    if not resolved.is_dir():
        raise OSError(f"文件夹不存在：{resolved}")
    if os.name == "nt":
        os.startfile(resolved)  # type: ignore[attr-defined]
        return
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved))):
        raise OSError(f"系统无法打开文件夹：{resolved}")


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


class CourtBackgroundViewport(QWidget):
    """在滚动内容背后绘制自适应裁切的球场背景。"""

    def __init__(self) -> None:
        super().__init__()
        self._source_pixmap = QPixmap()
        self._overlay_alpha = 0
        self._dark = True

    @property
    def has_background(self) -> bool:
        return not self._source_pixmap.isNull()

    def set_background(
        self,
        path: Path | None,
        *,
        overlay_alpha: int = 0,
        dark: bool = True,
    ) -> None:
        self._source_pixmap = QPixmap(str(path)) if path is not None else QPixmap()
        self._overlay_alpha = max(0, min(255, int(overlay_alpha)))
        self._dark = bool(dark)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0a0b0d" if self._dark else "#f3f5f7"))
        if self._source_pixmap.isNull() or self.width() <= 0 or self.height() <= 0:
            painter.end()
            return
        scaled = self._source_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        source = QRectF(
            max(0, (scaled.width() - self.width()) / 2),
            max(0, (scaled.height() - self.height()) / 2),
            self.width(),
            self.height(),
        )
        painter.drawPixmap(QRectF(self.rect()), scaled, source)
        painter.fillRect(self.rect(), QColor(2, 5, 9, self._overlay_alpha))
        painter.end()


class ContainedVideoWidget(QVideoWidget):
    """始终服从预览容器尺寸，不用竖屏视频原始分辨率撑开布局。"""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(0, 0)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(0, 0)


class PixelProgressBar(QProgressBar):
    """使用离散方块绘制的像素风进度条。"""

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        painter = QPainter(self)
        dark = bool(getattr(self.window(), "_dark_theme", True))
        border_color = QColor("#596574" if dark else "#7e8996")
        background_color = QColor("#090b0e" if dark else "#ffffff")
        empty_color = QColor("#202630" if dark else "#dfe5ea")
        fill_color = QColor("#b9f45a" if dark else "#78ad2e")
        text_color = QColor("#f4f7ed" if dark else "#17200c")
        if not self.isEnabled():
            fill_color = QColor("#525a63" if dark else "#aab2ba")

        outer = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QPen(border_color, 2))
        painter.setBrush(background_color)
        painter.drawRect(outer)

        inner = outer.adjusted(4, 4, -4, -4)
        segment_gap = 2
        segment_count = max(8, inner.width() // 18)
        total_gap = segment_gap * (segment_count - 1)
        segment_width = max(2, (inner.width() - total_gap) // segment_count)
        available = max(0, self.maximum() - self.minimum())
        fraction = (
            0.0
            if available <= 0
            else (self.value() - self.minimum()) / available
        )
        filled = round(max(0.0, min(1.0, fraction)) * segment_count)
        painter.setPen(Qt.PenStyle.NoPen)
        x = inner.x()
        for index in range(segment_count):
            painter.setBrush(fill_color if index < filled else empty_color)
            painter.drawRect(x, inner.y(), segment_width, inner.height())
            x += segment_width + segment_gap

        font = QFont("Cascadia Mono", 9, QFont.Weight.Bold)
        font.setStyleHint(QFont.StyleHint.Monospace)
        painter.setFont(font)
        painter.setPen(text_color)
        painter.drawText(outer, Qt.AlignmentFlag.AlignCenter, self.text())
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
        self.setToolTip("点击时间线可跳转；绿色方块表示识别出的击球位置")

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
        dark = bool(getattr(self.window(), "_dark_theme", True))
        track = QRectF(18, self.height() / 2 - 2, max(1, self.width() - 36), 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#343d48" if dark else "#c4ccd4"))
        painter.drawRect(track)

        progress_fraction = self._fraction(self._position_ms)
        progress_track = QRectF(track.x(), track.y(), track.width() * progress_fraction, 4)
        painter.setBrush(QColor("#9add43" if dark else "#78ad2e"))
        painter.drawRect(progress_track)

        active_window_ms = 320
        for hit_ms in self._hit_positions_ms:
            x = track.x() + track.width() * self._fraction(hit_ms)
            active = abs(self._position_ms - hit_ms) <= active_window_ms
            passed = hit_ms < self._position_ms
            if active:
                painter.setBrush(QColor("#111316" if dark else "#ffffff"))
                painter.setPen(QPen(QColor("#c8ff73" if dark else "#527b13"), 3))
                painter.drawRect(QRectF(x - 7, track.center().y() - 7, 14, 14))
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(
                    QColor(
                        "#9add43"
                        if passed
                        else ("#d8f5a8" if dark else "#b6d888")
                    )
                )
                size = 8 if passed else 6
                painter.drawRect(
                    QRectF(x - size / 2, track.center().y() - size / 2, size, size)
                )

        playhead_x = track.x() + track.width() * progress_fraction
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff" if dark else "#26313a"))
        painter.drawRect(
            QRectF(
                int(playhead_x) - 1,
                int(track.center().y() - 13),
                3,
                26,
            )
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

    def set_arrow_color(self, color: str) -> None:
        self._up_button.setIcon(_make_arrow_icon(up=True, color=color))
        self._down_button.setIcon(_make_arrow_icon(up=False, color=color))


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
        self.setMinimumHeight(92)
        self.control = control
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        label = QLabel(title)
        label.setObjectName("parameterTitle")
        header.addWidget(label)
        header.addStretch()
        header.addWidget(control)
        layout.addLayout(header)
        layout.addSpacing(2)

        self.note = QLabel(description)
        self.note.setObjectName("parameterNote")
        self.note.setWordWrap(True)
        self.note.setMinimumHeight(22)
        self.note.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.note)


class MainWindow(QMainWindow):
    """跟随系统明暗主题的主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.settings = _application_settings()
        self._language = normalize_language(
            self.settings.value(LANGUAGE_SETTINGS_KEY, DEFAULT_LANGUAGE)
        )
        set_language(DEFAULT_LANGUAGE)
        self._motion_enabled = _settings_bool(
            self.settings, "appearance/motion_enabled", True
        )
        self._court_background_id = _normalize_court_background(
            self.settings.value(COURT_BACKGROUND_SETTINGS_KEY, "classic")
        )
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_process_output)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)
        self.update_controller = UpdateController(
            self,
            self.settings,
            current_version=__version__,
            task_running=lambda: self.process.state()
            != QProcess.ProcessState.NotRunning,
        )
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
        self._active_analysis_limit_duration: float | None = None
        self._review_candidates: dict[
            str, tuple[ReviewVideoCandidate, ReviewClipCandidate]
        ] = {}
        self._viewed_candidate_ids: set[str] = set()
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
        self._dark_theme = (
            True
            if self._court_background_id != "classic"
            else _system_uses_dark_theme()
        )
        self.setStyleSheet(self._composed_style_sheet(self._dark_theme))
        self._build_menu_bar()

        self.page_scroll = QScrollArea()
        self.page_scroll.setObjectName("pageScroll")
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.setCentralWidget(self.page_scroll)

        central = CourtBackgroundViewport()
        central.setObjectName("root")
        self.background_viewport = central
        self.page_scroll.setWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 8, 20, 8)
        root.setSpacing(8)
        self.root_layout = root

        root.addLayout(self._build_header())
        self.motion_rail = PixelMotionRail(animation_enabled=self._motion_enabled)
        root.addWidget(self.motion_rail)
        root.addWidget(self._build_top_bar())
        self.workbench_card = self._build_workbench_card()
        root.addWidget(self.workbench_card, 1)
        self.parameter_card = self._build_parameter_card()
        root.addWidget(self.parameter_card, 1)
        self.parameter_card.setVisible(False)

        style_hints = QGuiApplication.styleHints()
        if hasattr(style_hints, "colorSchemeChanged"):
            style_hints.colorSchemeChanged.connect(self._system_theme_changed)
        self._refresh_court_background()
        self._refresh_theme_dependent_widgets()
        self._install_runtime_translator()

        self._load_saved_optimization()
        self._set_running(False)
        QTimer.singleShot(0, self._refresh_input_preview)
        QTimer.singleShot(0, self._show_initial_view)
        QTimer.singleShot(
            0, lambda: _apply_windows_frame_theme(self, dark=self._dark_theme)
        )
        QTimer.singleShot(2500, self.update_controller.schedule_auto_check)

    def _show_initial_view(self) -> None:
        """让首次打开时停留在顶部主工作区。"""

        self.start_button.setFocus()
        self.page_scroll.verticalScrollBar().setValue(0)

    def _build_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(1)

        eyebrow = QLabel("■ AI TENNIS WORKFLOW / PIXEL MODE")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("网球回合精选")
        title.setObjectName("heroTitle")
        subtitle = QLabel("[自动识别]  →  [逐段预览]  →  [勾选导出]")
        subtitle.setObjectName("heroSubtitle")
        text.addWidget(eyebrow)
        text.addWidget(title)
        text.addWidget(subtitle)

        layout.addLayout(text)
        layout.addStretch()
        self.status_badge = QLabel("■  等待任务")
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
        open_input = QAction("打开输入文件夹", self)
        open_input.triggered.connect(self._open_input)
        file_menu.addAction(open_input)
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
        self.parameters_action = QAction("参数调节", self)
        self.parameters_action.triggered.connect(self._show_parameter_panel)
        view_menu.addAction(self.parameters_action)
        self.motion_action = QAction("像素动画", self)
        self.motion_action.setCheckable(True)
        self.motion_action.setChecked(self._motion_enabled)
        self.motion_action.setToolTip("显示或关闭顶部流水灯与网球小人动画")
        self.motion_action.toggled.connect(self._set_motion_enabled)
        view_menu.addAction(self.motion_action)

        help_menu = self.menuBar().addMenu("帮助(&H)")
        self.check_updates_action = QAction("检查更新…", self)
        self.check_updates_action.triggered.connect(
            lambda: self.update_controller.check_for_updates(manual=True)
        )
        help_menu.addAction(self.check_updates_action)
        self.auto_updates_action = QAction("自动检查更新", self)
        self.auto_updates_action.setCheckable(True)
        self.auto_updates_action.setChecked(self.update_controller.auto_enabled)
        self.auto_updates_action.toggled.connect(
            self.update_controller.set_auto_enabled
        )
        help_menu.addAction(self.auto_updates_action)
        help_menu.addSeparator()
        about_action = QAction("关于 Tennis Video Helper", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(64)
        bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.settings_button = QPushButton("参数调节")
        self.settings_button.setObjectName("navigationButton")
        self.settings_button.setMinimumHeight(46)
        self.settings_button.setToolTip("调节识别、GPU 和导出参数")
        self.settings_button.clicked.connect(self._show_parameter_panel)
        layout.addWidget(self.settings_button)

        default_input = Path.cwd() / "网球"
        default_output = Path.cwd() / "精选输出"
        saved_input = str(self.settings.value("paths/input", "") or "").strip()
        layout.addWidget(QLabel("输入"))
        self.input_edit = QLineEdit(
            saved_input
            or (str(default_input) if default_input.exists() else "")
        )
        self.input_edit.setPlaceholderText("在“文件”菜单选择视频或文件夹")
        self.input_edit.editingFinished.connect(self._input_editing_finished)
        layout.addWidget(self.input_edit, 2)
        self.open_input_button = QPushButton("打开")
        self.open_input_button.setObjectName("pathOpenButton")
        self.open_input_button.setFixedWidth(58)
        self.open_input_button.setMinimumHeight(42)
        self.open_input_button.setToolTip(translate_text("打开输入视频所在文件夹"))
        self.open_input_button.clicked.connect(self._open_input)
        layout.addWidget(self.open_input_button)
        layout.addWidget(QLabel("输出"))
        self.output_edit = QLineEdit(str(default_output))
        self.output_edit.setPlaceholderText("在“文件”菜单选择输出目录")
        layout.addWidget(self.output_edit, 2)
        self.open_output_button = QPushButton("打开")
        self.open_output_button.setObjectName("pathOpenButton")
        self.open_output_button.setFixedWidth(58)
        self.open_output_button.setMinimumHeight(42)
        self.open_output_button.setToolTip(translate_text("打开当前输出文件夹"))
        self.open_output_button.clicked.connect(self._open_output)
        layout.addWidget(self.open_output_button)
        return bar

    def _show_parameter_panel(self, _checked: bool = False) -> None:
        self.workbench_card.setVisible(False)
        self.parameter_card.setVisible(True)
        self.settings_button.setVisible(False)
        self.page_scroll.verticalScrollBar().setValue(0)

    def _show_review_workspace(self, _checked: bool = False) -> None:
        self.parameter_card.setVisible(False)
        self.workbench_card.setVisible(True)
        self.settings_button.setVisible(True)
        self.page_scroll.verticalScrollBar().setValue(0)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于 Tennis Video Helper",
            f"Tennis Video Helper {__version__}\n\n"
            "声音、人体骨架与球拍检测融合的网球回合筛选工具。",
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
        self.preview_stack.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.preview = PreviewLabel()
        self.preview_stack.addWidget(self.preview)
        self.video_widget = ContainedVideoWidget()
        self.video_widget.setObjectName("videoWidget")
        self.video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.media_player.setVideoOutput(self.video_widget)
        self.preview_stack.addWidget(self.video_widget)
        preview_column.addWidget(self.preview_stack, 1)

        self.analysis_feedback = QFrame()
        self.analysis_feedback.setObjectName("analysisFeedback")
        feedback_layout = QVBoxLayout(self.analysis_feedback)
        feedback_layout.setContentsMargins(12, 9, 12, 10)
        feedback_layout.setSpacing(5)
        feedback_header = QHBoxLayout()
        self.analysis_feedback_title = QLabel("正在分析当前视频")
        self.analysis_feedback_title.setObjectName("analysisFeedbackTitle")
        self.analysis_feedback_percent = QLabel("0.0%")
        self.analysis_feedback_percent.setObjectName("analysisFeedbackPercent")
        feedback_header.addWidget(self.analysis_feedback_title)
        feedback_header.addStretch()
        feedback_header.addWidget(self.analysis_feedback_percent)
        feedback_layout.addLayout(feedback_header)
        self.analysis_feedback_phase = QLabel("正在准备分析环境")
        self.analysis_feedback_phase.setObjectName("analysisFeedbackPhase")
        feedback_layout.addWidget(self.analysis_feedback_phase)
        self.analysis_progress = PixelProgressBar()
        self.analysis_progress.setRange(0, 1000)
        self.analysis_progress.setValue(0)
        self.analysis_progress.setFormat("0.0%")
        self.analysis_progress.setTextVisible(True)
        self.analysis_progress.setFixedHeight(20)
        feedback_layout.addWidget(self.analysis_progress)
        self.analysis_feedback.setVisible(False)
        preview_column.addWidget(self.analysis_feedback)

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
        self.playback_rate_control = LargeArrowDoubleSpinBox()
        self.playback_rate_control.setObjectName("playbackRateControl")
        self.playback_rate_control.setToolTip("输入 0.25× 至 4.00× 的候选预览速度")
        self.playback_rate_control.setRange(0.25, 4.0)
        self.playback_rate_control.setDecimals(2)
        self.playback_rate_control.setSingleStep(0.25)
        self.playback_rate_control.setSuffix(" ×")
        self.playback_rate_control.setMinimumWidth(102)
        self.playback_rate_control.setMinimumHeight(40)
        try:
            saved_rate = float(self.settings.value("preview/playback_rate", 1.0))
        except (TypeError, ValueError):
            saved_rate = 1.0
        self.playback_rate_control.setValue(min(4.0, max(0.25, saved_rate)))
        self.media_player.setPlaybackRate(self.playback_rate_control.value())
        self.playback_rate_control.valueChanged.connect(
            self._set_preview_playback_rate
        )
        self.playback_rate_label = QLabel("倍速")
        self.playback_rate_label.setObjectName("mutedLabel")
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
        playback_row.addWidget(self.playback_rate_label)
        playback_row.addWidget(self.playback_rate_control)
        preview_column.addLayout(playback_row)
        layout.addWidget(preview_panel, 1)

        status_panel = QFrame()
        status_panel.setObjectName("statusPanel")
        status_panel.setMinimumWidth(250)
        status_panel.setMaximumWidth(300)
        status_layout = QVBoxLayout(status_panel)
        status_layout.setContentsMargins(18, 18, 18, 18)
        status_layout.setSpacing(6)

        self.start_button = QPushButton("开始分析")
        self.start_button.setObjectName("primaryButton")
        self.start_button.setMinimumHeight(48)
        self.start_button.setMinimumWidth(120)
        self.start_button.clicked.connect(self._start_analysis)
        status_layout.addWidget(self.start_button)

        secondary_button_row = QHBoxLayout()
        self.optimize_button = QPushButton("检测并优化")
        self.optimize_button.setObjectName("optimizeButton")
        self.optimize_button.setMinimumHeight(48)
        self.optimize_button.clicked.connect(self._start_optimization)
        self.stop_button = QPushButton("停止任务")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.setMinimumHeight(48)
        self.stop_button.clicked.connect(self._stop_analysis)
        secondary_button_row.addWidget(self.optimize_button)
        secondary_button_row.addWidget(self.stop_button)
        status_layout.addLayout(secondary_button_row)

        self.analysis_scope_label = QLabel(format_analysis_scope(None))
        self.analysis_scope_label.setObjectName("analysisScope")
        self.analysis_scope_label.setProperty("mode", "complete")
        self.analysis_scope_label.setWordWrap(True)
        status_layout.addWidget(self.analysis_scope_label)

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
        self.progress = PixelProgressBar()
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
        self.task_summary_label = QLabel(
            "选择视频后点击“开始分析”，完成后逐段复核并勾选导出。"
        )
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
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(9)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        header = QHBoxLayout()
        title = QLabel("参数调节")
        title.setObjectName("sectionTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        title.setFixedHeight(32)
        header.addWidget(title)
        header.addStretch()
        self.back_to_review_button = QPushButton("← 返回候选片段")
        self.back_to_review_button.setObjectName("navigationButton")
        self.back_to_review_button.setToolTip("返回候选片段预览与导出页面")
        self.back_to_review_button.clicked.connect(self._show_review_workspace)
        header.addWidget(self.back_to_review_button)
        layout.addLayout(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        self.min_rally = _double_spin(10.0, 1.0, 600.0, " 秒")
        self.min_confirmed_hits = _int_spin(3, 1, 50, " 次")
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
            (
                "最少击球",
                "默认与最短时长同时满足；设为 1 可主要按时长筛选。",
                self.min_confirmed_hits,
            ),
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
        self.limit_check.toggled.connect(self._update_analysis_scope)
        self.limit_minutes.valueChanged.connect(self._update_analysis_scope)
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
        parameter_columns = 5
        limit_row = (len(specs) + parameter_columns - 1) // parameter_columns
        grid.addWidget(limit_box, limit_row, 0, 1, parameter_columns)

        layout.addLayout(grid)

        theme_panel = QFrame()
        theme_panel.setObjectName("themeSelectorPanel")
        theme_layout = QHBoxLayout(theme_panel)
        theme_layout.setContentsMargins(12, 10, 12, 10)
        theme_layout.setSpacing(14)
        theme_copy = QVBoxLayout()
        theme_copy.setSpacing(4)
        theme_title = QLabel("软件背景")
        theme_title.setObjectName("parameterTitle")
        theme_copy.addWidget(theme_title)
        self.court_background_description = QLabel()
        self.court_background_description.setObjectName("parameterNote")
        self.court_background_description.setWordWrap(True)
        theme_copy.addWidget(self.court_background_description)
        self.court_background_combo = QComboBox()
        self.court_background_combo.setObjectName("courtBackgroundCombo")
        self.court_background_combo.setMinimumWidth(280)
        self.court_background_combo.setMinimumHeight(42)
        for theme in COURT_BACKGROUND_THEMES:
            self.court_background_combo.addItem(theme.label, theme.id)
        selected_index = self.court_background_combo.findData(
            self._court_background_id
        )
        self.court_background_combo.setCurrentIndex(max(0, selected_index))
        self.court_background_combo.currentIndexChanged.connect(
            self._court_background_changed
        )
        theme_copy.addWidget(self.court_background_combo, 0, Qt.AlignmentFlag.AlignLeft)
        theme_layout.addLayout(theme_copy, 1)
        self.court_background_preview = QLabel("经典像素界面")
        self.court_background_preview.setObjectName("courtBackgroundPreview")
        self.court_background_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.court_background_preview.setFixedSize(230, 104)
        theme_layout.addWidget(self.court_background_preview)
        layout.addWidget(theme_panel)

        language_panel = QFrame()
        language_panel.setObjectName("themeSelectorPanel")
        language_layout = QHBoxLayout(language_panel)
        language_layout.setContentsMargins(12, 10, 12, 10)
        language_layout.setSpacing(14)
        language_copy = QVBoxLayout()
        language_copy.setSpacing(4)
        self.language_title = QLabel("界面语言")
        self.language_title.setObjectName("parameterTitle")
        language_copy.addWidget(self.language_title)
        self.language_description = QLabel("切换后立即生效，并在下次启动时保持。")
        self.language_description.setObjectName("parameterNote")
        self.language_description.setWordWrap(True)
        language_copy.addWidget(self.language_description)
        self.language_combo = QComboBox()
        self.language_combo.setObjectName("languageCombo")
        self.language_combo.setMinimumWidth(280)
        self.language_combo.setMinimumHeight(42)
        self.language_combo.addItem("简体中文", "zh_CN")
        self.language_combo.addItem("English", "en")
        language_index = self.language_combo.findData(self._language)
        self.language_combo.setCurrentIndex(max(0, language_index))
        self.language_combo.currentIndexChanged.connect(self._language_changed)
        language_copy.addWidget(self.language_combo, 0, Qt.AlignmentFlag.AlignLeft)
        language_layout.addLayout(language_copy, 1)
        self.language_preview = QLabel("中 / EN")
        self.language_preview.setObjectName("courtBackgroundPreview")
        self.language_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.language_preview.setFixedSize(230, 70)
        language_layout.addWidget(self.language_preview)
        layout.addWidget(language_panel)

        self._update_analysis_scope()
        return card

    def _install_runtime_translator(self) -> None:
        """Translate widget text at runtime while preserving canonical Chinese copy."""

        self._translation_source: dict[int, dict[str, str]] = {}
        self._capture_translation_sources()
        self._apply_language()

    def _capture_translation_sources(self) -> None:
        for widget in [self, *self.findChildren(QWidget)]:
            source: dict[str, str] = {}
            for name, getter in (
                ("text", getattr(widget, "text", None)),
                ("title", getattr(widget, "title", None)),
                ("placeholder", getattr(widget, "placeholderText", None)),
                ("tooltip", getattr(widget, "toolTip", None)),
            ):
                if callable(getter):
                    try:
                        value = str(getter())
                    except TypeError:
                        continue
                    if value:
                        source[name] = value
            if source:
                self._translation_source[id(widget)] = source
        for action in self.findChildren(QAction):
            source = {
                "text": action.text(),
                "tooltip": action.toolTip(),
            }
            self._translation_source[id(action)] = {
                key: value for key, value in source.items() if value
            }

    def _language_changed(self, index: int) -> None:
        language = normalize_language(self.language_combo.itemData(index))
        if language == self._language:
            return
        self._language = set_language(language)
        self.settings.setValue(LANGUAGE_SETTINGS_KEY, language)
        self._apply_language()

    def _apply_language(self) -> None:
        set_language(self._language)
        for widget in [self, *self.findChildren(QWidget), *self.findChildren(QAction)]:
            source = self._translation_source.get(id(widget), {})
            if "text" in source and callable(getattr(widget, "setText", None)):
                widget.setText(translate_text(source["text"], self._language))
            if "title" in source and callable(getattr(widget, "setTitle", None)):
                widget.setTitle(translate_text(source["title"], self._language))
            if "placeholder" in source and callable(
                getattr(widget, "setPlaceholderText", None)
            ):
                widget.setPlaceholderText(
                    translate_text(source["placeholder"], self._language)
                )
            if "tooltip" in source and callable(getattr(widget, "setToolTip", None)):
                widget.setToolTip(translate_text(source["tooltip"], self._language))
            if isinstance(widget, QComboBox) and widget is not self.language_combo:
                current_data = widget.currentData()
                for item_index in range(widget.count()):
                    key = (id(widget), "item", item_index)
                    item_source = self._translation_source.setdefault(
                        hash(key), {"text": widget.itemText(item_index)}
                    )["text"]
                    widget.setItemText(
                        item_index, translate_text(item_source, self._language)
                    )
                data_index = widget.findData(current_data)
                if data_index >= 0:
                    widget.setCurrentIndex(data_index)
        self.language_combo.blockSignals(True)
        self.language_combo.setCurrentIndex(
            max(0, self.language_combo.findData(self._language))
        )
        self.language_combo.blockSignals(False)
        self._refresh_court_background()
        self._update_analysis_scope()
        self._update_export_quality_hint(self.export_original_quality.isChecked())

    def _update_analysis_scope(self, *_args) -> None:
        limit_duration = (
            self.limit_minutes.value() * 60 if self.limit_check.isChecked() else None
        )
        limited = limit_duration is not None
        self.analysis_scope_label.setText(format_analysis_scope(limit_duration))
        self.analysis_scope_label.setProperty(
            "mode", "limited" if limited else "complete"
        )
        self.analysis_scope_label.style().unpolish(self.analysis_scope_label)
        self.analysis_scope_label.style().polish(self.analysis_scope_label)

    def _form_values(self) -> AnalysisFormValues:
        input_path, output_path = parse_paths(
            self.input_edit.text(), self.output_edit.text()
        )
        limit = self.limit_minutes.value() * 60 if self.limit_check.isChecked() else None
        return AnalysisFormValues(
            input_path=input_path,
            output_path=output_path,
            min_rally_duration=self.min_rally.value(),
            min_confirmed_hits=self.min_confirmed_hits.value(),
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
        self._remember_input_path(str(values.input_path))
        if not values.input_path.exists():
            QMessageBox.warning(self, "路径无效", "请选择存在的视频或文件夹。")
            return
        scope_error = incompatible_analysis_scope_message(
            values.limit_duration,
            values.min_rally_duration,
        )
        if scope_error is not None:
            QMessageBox.warning(self, "分析范围过短", scope_error)
            return
        if values.limit_duration is not None:
            answer = QMessageBox.question(
                self,
                "确认分析范围",
                f"当前只会分析视频前 {_number(values.limit_duration / 60)} 分钟，"
                "其余内容不会检查。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
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
        self._active_analysis_limit_duration = values.limit_duration
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
            **subprocess_no_window_kwargs(),
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
                try:
                    session = load_review_session(self._review_manifest_path)
                except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                    self._append_log(f"候选列表暂时无法刷新：{exc}")
                else:
                    self._set_review_session(session)
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
                self.status_badge.setText("■  GPU 处理中")
            elif cuda_available or nvenc_available:
                self.status_badge.setText("■  CPU/GPU 混合处理")
            else:
                self.status_badge.setText("■  CPU 处理中")

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
        self.analysis_progress.setValue(round(percent * 10))
        self.analysis_progress.setFormat(f"{percent:.1f}%")
        self.analysis_feedback_percent.setText(f"{percent:.1f}%")
        self.analysis_feedback_phase.setText(phase)

        video_index = int(payload.get("video_index") or 0)
        video_total = int(payload.get("video_total") or 0)
        candidate_count = int(payload.get("candidate_count") or 0)
        if video_total > 0:
            self.video_count_label.setText(f"第 {video_index}/{video_total} 个视频")
        current_video = payload.get("current_video")
        if current_video:
            current_path = Path(str(current_video))
            if self._current_candidate_id is None:
                self._show_video_preview(current_path)
            self.analysis_feedback_title.setText(f"正在分析：{current_path.name}")
        if candidate_count > 0:
            if self.candidate_list.count() > 0:
                self._update_selected_count()
                self.task_summary_label.setText(
                    f"{phase} · 已生成 {candidate_count} 个候选，可边分析边预览"
                )
            else:
                staged_message = f"正在载入已生成的 {candidate_count} 个候选"
                self.selected_count_label.setText(staged_message)
                self.task_summary_label.setText(f"{phase} · {staged_message}")
        else:
            self.selected_count_label.setText("处理中；候选生成后会立即显示")
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
                self.status_badge.setText("■  优化已停止")
                self.task_summary_label.setText("本机性能优化已停止，旧配置保持不变。")
            elif exit_code == 0:
                self.status_badge.setText("■  优化完成")
                self._progress_percent = 100.0
                self.progress.setValue(1000)
                self.progress.setFormat("100.0%")
                self.percent_label.setText("100%")
                self.phase_label.setText("本机性能优化完成")
                self.eta_label.setText("已完成")
                self.task_summary_label.setText("最快且通过一致性检查的配置已自动应用。")
            else:
                self.status_badge.setText("■  优化失败")
                self.task_summary_label.setText(
                    self._last_worker_message or f"本机性能优化异常结束，退出代码：{exit_code}"
                )
            self._process_mode = "analysis"
            return
        if self._stopping:
            self.status_badge.setText("■  已停止")
            self.task_summary_label.setText("任务已停止；旧结果没有被覆盖。")
            if self._review_manifest_path and self._review_manifest_path.exists():
                discard_review_session(self._review_manifest_path.parent)
        elif self._review_manifest_path is not None:
            try:
                session = load_review_session(self._review_manifest_path)
                self._set_review_session(session)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                self.status_badge.setText("■  候选清单损坏")
                self.phase_label.setText("无法载入候选片段")
                self.task_summary_label.setText(str(exc))
                return
            self._progress_percent = 100.0
            self.progress.setValue(1000)
            self.progress.setFormat("100.0%")
            self.percent_label.setText("100%")
            candidate_count = len(session.clips)
            self.status_badge.setText("■  等待人工确认")
            self.phase_label.setText(
                f"已生成 {candidate_count} 个候选片段"
                if candidate_count
                else "所选分析范围内没有找到候选片段"
            )
            self.eta_label.setText("已完成")
            suffix = "；部分源视频处理失败" if exit_code != 0 else ""
            self.task_summary_label.setText(
                f"逐段播放并检查击球点，取消误判后再导出{suffix}。"
                if candidate_count
                else empty_candidate_guidance(
                    self._active_analysis_limit_duration
                )
                + suffix
            )
        elif exit_code == 0:
            self.status_badge.setText("■  未生成候选")
            self.phase_label.setText("没有找到候选片段")
            self.task_summary_label.setText(
                empty_candidate_guidance(self._active_analysis_limit_duration)
            )
        else:
            self.status_badge.setText("■  处理失败")
            self.task_summary_label.setText(
                self._last_worker_message or f"任务异常结束，退出代码：{exit_code}"
            )

    def _process_error(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.elapsed_timer.stop()
            self._set_running(False)
            self.status_badge.setText("■  启动失败")
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
            self.status_badge.setText("■  正在处理")
            self.progress.setRange(0, 1000)
            self.analysis_feedback.setVisible(True)
            self.analysis_feedback_title.setText(
                "正在检测和优化本机性能"
                if self._process_mode == "optimization"
                else "正在分析当前视频"
            )
            self.analysis_feedback_phase.setText(self.phase_label.text())
            self.analysis_feedback_percent.setText(f"{self._progress_percent:.1f}%")
            self.analysis_progress.setValue(round(self._progress_percent * 10))
            self.analysis_progress.setFormat(f"{self._progress_percent:.1f}%")
        else:
            self.progress.setRange(0, 1000)
            self.analysis_feedback.setVisible(False)
            if not self.status_badge.text():
                self.status_badge.setText("■  等待任务")

    def _set_review_session(self, session: ReviewSession) -> None:
        published_ids = set(session.published_clip_ids)
        next_candidates = {
            clip.id: (video, clip)
            for video in session.videos
            for clip in video.clips
            if clip.id not in published_ids
        }
        same_session = (
            self._review_session is not None
            and self._review_session.root_dir == session.root_dir
        )
        previous_row = self.candidate_list.currentRow()
        previous_candidate_id = self._current_candidate_id
        if not same_session:
            self._loading_candidates = True
            self.candidate_list.clear()
            self._loading_candidates = False
            self._review_candidates.clear()
            self._viewed_candidate_ids.clear()
            self._current_candidate_id = None

        self._loading_candidates = True
        signals_were_blocked = self.candidate_list.blockSignals(True)
        if same_session:
            for index in range(self.candidate_list.count() - 1, -1, -1):
                item = self.candidate_list.item(index)
                candidate_id = str(item.data(Qt.ItemDataRole.UserRole))
                if candidate_id not in next_candidates:
                    self.candidate_list.takeItem(index)
            self._viewed_candidate_ids.intersection_update(next_candidates)
            if previous_candidate_id not in next_candidates:
                self._current_candidate_id = None

        existing_ids = {
            str(self.candidate_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.candidate_list.count())
        }
        self._review_session = session
        self._review_candidates = next_candidates
        for video in session.videos:
            for clip in video.clips:
                if clip.id in published_ids or clip.id in existing_ids:
                    continue
                item = QListWidgetItem(
                    self._candidate_item_text(video, clip, viewed=False)
                )
                item.setData(Qt.ItemDataRole.UserRole, clip.id)
                item.setData(CANDIDATE_VIEWED_ROLE, False)
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
        self.candidate_list.blockSignals(signals_were_blocked)
        self._loading_candidates = False
        pending_count = len(next_candidates)
        self.video_count_label.setText(f"{pending_count} 段")
        self._update_selected_count()
        idle = self.process.state() == QProcess.ProcessState.NotRunning
        self.select_all_action.setEnabled(idle and bool(next_candidates))
        self.select_none_action.setEnabled(idle and bool(next_candidates))
        if next_candidates:
            target_row = min(max(previous_row, 0), self.candidate_list.count() - 1)
            if previous_candidate_id in next_candidates:
                for index in range(self.candidate_list.count()):
                    item = self.candidate_list.item(index)
                    if str(item.data(Qt.ItemDataRole.UserRole)) == previous_candidate_id:
                        target_row = index
                        break
            self.candidate_list.setCurrentRow(target_row)
            current = self.candidate_list.item(target_row)
            current_id = str(current.data(Qt.ItemDataRole.UserRole))
            if self._current_candidate_id != current_id:
                self._candidate_changed(current, None)
        else:
            self._clear_preview_only("所有候选片段均已导出")
            self._update_navigation_buttons()

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
        self._mark_candidate_viewed(current, video, clip)
        self.media_player.stop()
        self.media_player.setSource(QUrl.fromLocalFile(str(clip.path)))
        self.media_player.setPlaybackRate(self.playback_rate_control.value())
        self.preview.set_source_pixmap(_video_thumbnail(clip.path))
        self.preview_stack.setCurrentWidget(self.preview)
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

    @staticmethod
    def _candidate_item_text(
        video: ReviewVideoCandidate,
        clip: ReviewClipCandidate,
        *,
        viewed: bool,
    ) -> str:
        prefix = "已看 · " if viewed else ""
        return (
            f"{prefix}片段 {clip.index:03d} · {clip.duration:.1f} 秒\n"
            f"{video.source.name} · {len(clip.hits)} 个击球点"
        )

    def _mark_candidate_viewed(
        self,
        item: QListWidgetItem,
        video: ReviewVideoCandidate,
        clip: ReviewClipCandidate,
    ) -> None:
        self._viewed_candidate_ids.add(clip.id)
        item.setData(CANDIDATE_VIEWED_ROLE, True)
        item.setText(self._candidate_item_text(video, clip, viewed=True))
        self._apply_candidate_item_appearance(item)

    def _apply_candidate_item_appearance(self, item: QListWidgetItem) -> None:
        viewed = bool(item.data(CANDIDATE_VIEWED_ROLE))
        if viewed:
            viewed_color = "#7f858d" if self._dark_theme else "#707780"
            item.setForeground(QBrush(QColor(viewed_color)))
            item.setToolTip(f"已查看\n{item.toolTip().removeprefix('已查看\n')}")
        else:
            item.setForeground(QBrush())

    def _refresh_candidate_item_appearances(self) -> None:
        for index in range(self.candidate_list.count()):
            self._apply_candidate_item_appearance(self.candidate_list.item(index))

    def _system_theme_changed(self, *_args) -> None:
        if self._court_background_id == "classic":
            self._apply_theme(_system_uses_dark_theme())

    def _court_background_changed(self, index: int) -> None:
        self._set_court_background(self.court_background_combo.itemData(index))

    def _set_court_background(self, theme_id: object) -> None:
        self._court_background_id = _normalize_court_background(theme_id)
        self.settings.setValue(
            COURT_BACKGROUND_SETTINGS_KEY, self._court_background_id
        )
        self.settings.sync()
        if hasattr(self, "court_background_combo"):
            combo_index = self.court_background_combo.findData(
                self._court_background_id
            )
            if combo_index >= 0 and combo_index != self.court_background_combo.currentIndex():
                blocked = self.court_background_combo.blockSignals(True)
                self.court_background_combo.setCurrentIndex(combo_index)
                self.court_background_combo.blockSignals(blocked)
        dark = (
            True
            if self._court_background_id != "classic"
            else _system_uses_dark_theme()
        )
        self._apply_theme(dark)

    def _composed_style_sheet(self, dark: bool) -> str:
        base = DARK_STYLE_SHEET if dark else LIGHT_STYLE_SHEET
        if self._court_background_id == "classic":
            return base
        return base + COURT_BACKGROUND_STYLE

    def _refresh_court_background(self) -> None:
        theme = COURT_BACKGROUND_THEME_BY_ID[self._court_background_id]
        background_path = (
            asset_path("backgrounds", theme.asset_name)
            if theme.asset_name is not None
            else None
        )
        if hasattr(self, "background_viewport"):
            self.background_viewport.set_background(
                background_path,
                overlay_alpha=theme.overlay_alpha,
                dark=self._dark_theme,
            )
        if hasattr(self, "court_background_description"):
            self.court_background_description.setText(theme.description)
        if not hasattr(self, "court_background_preview"):
            return
        if background_path is None:
            self.court_background_preview.setPixmap(QPixmap())
            self.court_background_preview.setText("经典像素界面")
            return
        preview = QPixmap(str(background_path))
        if preview.isNull():
            self.court_background_preview.setPixmap(QPixmap())
            self.court_background_preview.setText("背景资源暂不可用")
            return
        self.court_background_preview.setText("")
        self.court_background_preview.setPixmap(
            preview.scaled(
                self.court_background_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _set_motion_enabled(self, enabled: bool) -> None:
        self._motion_enabled = bool(enabled)
        self.settings.setValue("appearance/motion_enabled", self._motion_enabled)
        if hasattr(self, "motion_rail"):
            self.motion_rail.set_animation_enabled(self._motion_enabled)

    def _apply_theme(self, dark: bool) -> None:
        self._dark_theme = dark
        self.setStyleSheet(self._composed_style_sheet(dark))
        self._refresh_court_background()
        self._refresh_theme_dependent_widgets()
        _apply_windows_frame_theme(self, dark=dark)

    def _refresh_theme_dependent_widgets(self) -> None:
        arrow_color = "#e7eaed" if self._dark_theme else "#26313a"
        controls = [
            *self.findChildren(LargeArrowDoubleSpinBox),
            *self.findChildren(LargeArrowSpinBox),
        ]
        for control in controls:
            control.set_arrow_color(arrow_color)
        if hasattr(self, "candidate_list"):
            self._refresh_candidate_item_appearances()

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
        self.status_badge.setText("■  正在发布结果")
        self.task_summary_label.setText("正在导出勾选片段，未导出的候选会继续保留……")
        try:
            published = publish_review_session(self._review_session, selected_ids)
        except (OSError, ValueError, RuntimeError) as exc:
            self.status_badge.setText("■  导出失败")
            self.task_summary_label.setText(str(exc))
            self.publish_button.setEnabled(True)
            QMessageBox.critical(self, "导出失败", str(exc))
            return

        output_text = "\n".join(str(path) for path in published.output_dirs)
        self.status_badge.setText("■  导出完成")
        exported_count = len(published.clip_paths)
        remaining_session = published.remaining_session
        if remaining_session is not None:
            remaining_count = len(remaining_session.pending_clips)
            self._review_manifest_path = remaining_session.manifest_path
            self._set_review_session(remaining_session)
            self.phase_label.setText(
                f"本次已导出 {exported_count} 个片段，剩余 {remaining_count} 个待筛选"
            )
            self.task_summary_label.setText(
                "未导出的候选片段仍保留在列表中，可以继续筛选和分批导出。"
            )
            message = (
                f"已导出 {exported_count} 个片段。\n"
                f"剩余 {remaining_count} 个候选仍保留，可以继续筛选。\n\n"
                f"{output_text}"
            )
        else:
            self._review_session = None
            self._review_manifest_path = None
            self._review_candidates.clear()
            self._viewed_candidate_ids.clear()
            self._clear_candidate_view()
            self.phase_label.setText(f"已导出 {exported_count} 个片段")
            self.task_summary_label.setText("人工确认后的片段已保存到输出目录。")
            message = f"已导出 {exported_count} 个片段。\n\n{output_text}"
        QMessageBox.information(
            self,
            "导出完成",
            message,
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
            self.preview_stack.setCurrentWidget(self.video_widget)
            self.media_player.play()

    def _set_preview_playback_rate(self, rate: float) -> None:
        playback_rate = min(4.0, max(0.25, float(rate)))
        self.media_player.setPlaybackRate(playback_rate)
        self.settings.setValue("preview/playback_rate", playback_rate)
        self.settings.sync()

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
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.preview_stack.setCurrentWidget(self.video_widget)
        self.play_button.setText(
            "暂停" if state == QMediaPlayer.PlaybackState.PlayingState else "播放"
        )

    def _preview_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        # Windows 的媒体后端可能在 pause() 时同步再次发出 LoadedMedia。
        # 不要在 LoadedMedia 回调中反向操作播放器，否则候选片段加载后会
        # 无限递归并以 0xC00000FD（栈溢出）直接终止整个 GUI。
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            QTimer.singleShot(0, self._rewind_finished_preview)

    def _rewind_finished_preview(self) -> None:
        if self._current_candidate_id is not None:
            self.media_player.setPosition(0)
            self.preview_stack.setCurrentWidget(self.preview)

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
        self._preview_path = None
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
        self._clear_preview_only("候选生成后会立即出现在这里，可边分析边预览")
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
            from tennis_video_helper.app.optimizer import HardwareSnapshot, BenchmarkResult

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
            translate_text("选择网球视频"),
            self.input_edit.text(),
            translate_text(VIDEO_FILE_FILTER),
        )
        if path:
            self.input_edit.setText(path)
            self._remember_input_path(path)
            self._refresh_input_preview()

    def _choose_input_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, translate_text("选择视频文件夹"), self.input_edit.text()
        )
        if path:
            self.input_edit.setText(path)
            self._remember_input_path(path)
            self._refresh_input_preview()

    def _input_editing_finished(self) -> None:
        self._remember_input_path(self.input_edit.text())
        self._refresh_input_preview()

    def _remember_input_path(self, path: str) -> None:
        normalized = path.strip()
        if not normalized:
            return
        self.settings.setValue("paths/input", normalized)
        self.settings.sync()

    def _choose_output_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, translate_text("选择输出文件夹"), self.output_edit.text()
        )
        if path:
            self.output_edit.setText(path)

    def _open_input(self) -> None:
        try:
            open_local_folder(resolve_input_folder(self.input_edit.text()))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "无法打开输入目录", str(exc))

    def _open_output(self) -> None:
        try:
            path = parse_output_path(self.output_edit.text())
            path.mkdir(parents=True, exist_ok=True)
            open_local_folder(path)
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
        self.update_controller.shutdown()
        self.media_player.stop()
        self.media_player.setSource(QUrl())
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self._terminate_process_tree()
            if not self.process.waitForFinished(1500):
                self.process.kill()
        if self._review_session is not None:
            discard_review_session(self._review_session)
            self._review_session = None
        self._remember_input_path(self.input_edit.text())
        event.accept()


def _card(title: str) -> QFrame:
    card = QFrame()
    card.setObjectName("card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 12, 16, 14)
    layout.setSpacing(9)
    label = QLabel(title)
    label.setObjectName("sectionTitle")
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    label.setFixedHeight(24)
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


def _make_arrow_icon(*, up: bool, color: str = "#e7eaed") -> QIcon:
    pixmap = QPixmap(18, 12)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    if up:
        rectangles = ((8, 1, 2, 2), (6, 3, 6, 2), (4, 5, 10, 2), (2, 7, 14, 3))
    else:
        rectangles = ((2, 2, 14, 3), (4, 5, 10, 2), (6, 7, 6, 2), (8, 9, 2, 2))
    for rectangle in rectangles:
        painter.drawRect(*rectangle)
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
    icon_names = (
        ("app_icon.ico", "app_icon.png")
        if os.name == "nt"
        else ("app_icon.png", "app_icon.ico")
    )
    return next(
        (
            resolved
            for icon_name in icon_names
            if (resolved := asset_path("icons", icon_name)) is not None
        ),
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


def _apply_windows_frame_theme(window: QMainWindow, *, dark: bool) -> None:
    if os.name != "nt":
        return
    try:
        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
            int(window.winId()), 20, ctypes.byref(value), ctypes.sizeof(value)
        )
    except (AttributeError, OSError):
        return


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        from tennis_video_helper.app.cli import app as cli_app

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


DARK_STYLE_SHEET = """
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
QFrame#analysisFeedback {
    background: #111410;
    border: 1px solid rgba(185, 244, 90, 0.36);
    border-radius: 10px;
}
QLabel#analysisFeedbackTitle { color: #f3f5f1; font-weight: 700; }
QLabel#analysisFeedbackPercent { color: #b9f45a; font-weight: 700; }
QLabel#analysisFeedbackPhase { color: #9da59a; font-size: 11px; }
QLabel#analysisScope {
    color: #c9d1c1;
    background: #131713;
    border: 1px solid #30382b;
    border-radius: 8px;
    padding: 7px 9px;
    font-weight: 600;
}
QLabel#analysisScope[mode="limited"] {
    color: #ffd56a;
    background: #211b0c;
    border-color: #8f6f18;
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
QPushButton#navigationButton {
    color: #dfe3e7;
    background: #24272c;
    border-color: #3a3e45;
}
QPushButton#navigationButton:hover {
    color: #ffffff;
    background: #30343a;
    border-color: #59606a;
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


LIGHT_STYLE_SHEET = """
QMainWindow, QMenuBar, QMenu {
    background: #f3f5f7;
    color: #20262c;
    font-family: "Segoe UI", "Microsoft YaHei UI";
}
QMenuBar { border-bottom: 1px solid #d6dbe1; padding: 2px 8px; }
QMenuBar::item { padding: 6px 10px; background: transparent; }
QMenuBar::item:selected, QMenu::item:selected { background: #e4e8ed; }
QMenu { border: 1px solid #cbd1d8; padding: 5px; }
QMenu::item { padding: 7px 28px 7px 12px; }
QWidget#root {
    background: #f3f5f7;
    color: #20262c;
    font-family: "Segoe UI", "Microsoft YaHei UI";
    font-size: 13px;
}
QScrollArea#pageScroll { background: #f3f5f7; border: none; }
QLabel#eyebrow { color: #527b13; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
QLabel#heroTitle { color: #151a1f; font-size: 27px; font-weight: 700; }
QLabel#heroSubtitle { color: #69717a; font-size: 13px; }
QLabel#statusBadge {
    color: #466c0c;
    background: rgba(116, 166, 43, 0.12);
    border: 1px solid rgba(92, 137, 26, 0.34);
    border-radius: 14px;
    padding: 7px 12px;
    font-weight: 600;
}
QFrame#card, QFrame#workbenchCard {
    background: #ffffff;
    border: 1px solid #d2d7dd;
    border-radius: 15px;
}
QFrame#topBar {
    background: #ffffff;
    border: 1px solid #d2d7dd;
    border-radius: 11px;
}
QFrame#reviewPanel, QFrame#previewPanel {
    background: #ffffff;
    border: 1px solid #d5dae0;
    border-radius: 12px;
}
QFrame#analysisFeedback {
    background: #f6faef;
    border: 1px solid rgba(92, 137, 26, 0.40);
    border-radius: 10px;
}
QLabel#analysisFeedbackTitle { color: #273020; font-weight: 700; }
QLabel#analysisFeedbackPercent { color: #527b13; font-weight: 700; }
QLabel#analysisFeedbackPhase { color: #64705c; font-size: 11px; }
QLabel#analysisScope {
    color: #43513a;
    background: #f2f7ec;
    border: 1px solid #ccd9bf;
    border-radius: 8px;
    padding: 7px 9px;
    font-weight: 600;
}
QLabel#analysisScope[mode="limited"] { color: #795800; background: #fff8df; border-color: #c5a33d; }
QListWidget#candidateList {
    color: #252b31;
    background: #f8f9fb;
    border: 1px solid #cfd5dc;
    border-radius: 9px;
    padding: 4px;
    outline: none;
}
QListWidget#candidateList::item { border-radius: 7px; padding: 9px 7px; margin: 2px; }
QListWidget#candidateList::item:selected {
    color: #253313;
    background: #e7f3d4;
    border: 1px solid #87ac51;
}
QVideoWidget#videoWidget, QStackedWidget#previewStack {
    background: #111315;
    border: 1px solid #cfd5dc;
    border-radius: 10px;
}
QWidget#hitTimeline { background: #f8f9fb; border: 1px solid #d4d9df; border-radius: 10px; }
QLabel#hitCountLabel { color: #527b13; font-weight: 700; }
QFrame#workbenchCard { background: #ffffff; border-color: #cfd5dc; }
QFrame#statusPanel { background: #f8f9fb; border: 1px solid #d1d7de; border-radius: 13px; }
QLabel#videoPreview {
    color: #6e757d;
    background: #111315;
    border: 1px solid #cfd5dc;
    border-radius: 12px;
    padding: 4px;
}
QLabel#workbenchTitle { color: #20262c; font-size: 15px; font-weight: 700; }
QLabel#mutedLabel { color: #6f767e; }
QLabel#currentVideo { color: #4f5861; font-size: 12px; }
QLabel#percentLabel { color: #527b13; font-size: 42px; font-weight: 700; }
QLabel#phaseLabel { color: #20262c; font-size: 16px; font-weight: 600; }
QLabel#accelerationStatus {
    background: #f5f7fa;
    border: 1px solid #cfd5dc;
    border-radius: 8px;
    color: #59636d;
    font-size: 11px;
    font-weight: 600;
    padding: 7px 9px;
}
QLabel#accelerationStatus[mode="enabled"] { background: #edf7df; border-color: #87ac51; color: #466c0c; }
QLabel#accelerationStatus[mode="partial"] { background: #fff8df; border-color: #c5a33d; color: #795800; }
QLabel#accelerationStatus[mode="cpu"] { background: #fff0f0; border-color: #c77878; color: #9d3131; }
QLabel#metricLabel { color: #707780; font-size: 11px; }
QLabel#metricValue {
    color: #252b31;
    font-size: 16px;
    font-weight: 600;
    font-family: "Cascadia Mono", "Consolas";
}
QLabel#taskSummary { color: #69717a; font-size: 12px; }
QLabel#sectionTitle { color: #20262c; font-size: 14px; font-weight: 700; }
QLabel#fieldLabel { color: #515a63; font-weight: 600; }
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {
    color: #20262c;
    background: #ffffff;
    border: 1px solid #cbd1d8;
    border-radius: 10px;
    padding: 8px 10px;
    selection-background-color: #91bc52;
}
QDoubleSpinBox, QSpinBox, QComboBox { padding: 4px 34px 4px 9px; }
QDoubleSpinBox QLineEdit, QSpinBox QLineEdit {
    color: #20262c;
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0;
}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus { border: 1px solid #75a435; }
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right; width: 28px;
    border-left: 1px solid #cbd1d8; border-bottom: 1px solid #d7dce2; background: #edf0f3;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right; width: 28px;
    border-left: 1px solid #cbd1d8; background: #edf0f3;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: #dfe4e9; }
QToolButton#spinUpButton, QToolButton#spinDownButton {
    background: #edf0f3;
    border: none;
    border-left: 1px solid #cbd1d8;
    border-radius: 0;
    padding: 0;
}
QToolButton#spinUpButton { border-bottom: 1px solid #d7dce2; border-top-right-radius: 9px; }
QToolButton#spinDownButton { border-bottom-right-radius: 9px; }
QToolButton#spinUpButton:hover, QToolButton#spinDownButton:hover { background: #dfe4e9; }
QComboBox::drop-down {
    subcontrol-origin: padding; subcontrol-position: top right; width: 28px; border-left: 1px solid #cbd1d8;
}
QPushButton {
    color: #283038;
    background: #e9edf1;
    border: 1px solid #c9cfd6;
    border-radius: 10px;
    padding: 8px 13px;
    font-weight: 600;
}
QPushButton:hover { background: #dfe4e9; border-color: #aeb6bf; }
QPushButton:pressed { background: #d5dbe1; }
QPushButton:disabled { color: #9aa1a9; background: #f0f2f4; border-color: #dce0e4; }
QPushButton#primaryButton { color: #17200c; background: #a9df51; border: 1px solid #8fc436; padding: 11px 24px; font-size: 15px; }
QPushButton#primaryButton:hover { background: #b6e96a; }
QPushButton#dangerButton { color: #9d3131; background: #fff0f0; border-color: #d39a9a; }
QPushButton#navigationButton { color: #303840; background: #edf0f3; border-color: #c9cfd6; }
QPushButton#navigationButton:hover { color: #151a1f; background: #dfe4e9; border-color: #aab2bb; }
QFrame#parameterTile { background: #f8f9fb; border: 1px solid #d4d9df; border-radius: 12px; }
QLabel#parameterTitle { color: #252b31; font-weight: 700; }
QLabel#parameterNote { color: #6e757d; font-size: 10px; }
QCheckBox { color: #30373e; spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QCheckBox::indicator:unchecked { background: #ffffff; border: 1px solid #aeb5bd; border-radius: 4px; }
QCheckBox::indicator:checked { background: #95cb43; border: 1px solid #7caf2f; border-radius: 4px; }
QProgressBar {
    color: #20262c;
    background: #eef1f4;
    border: 1px solid #cbd1d8;
    border-radius: 10px;
    text-align: center;
    font-size: 11px;
    font-weight: 600;
}
QProgressBar::chunk { background: #8fcf3d; border-radius: 9px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #b7bec6; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


PIXEL_COMMON_STYLE = """
* {
    font-family: "Microsoft YaHei UI", "Segoe UI", "Cascadia Mono";
}
QMenuBar, QMenu, QToolTip,
QFrame#card, QFrame#workbenchCard, QFrame#topBar,
QFrame#reviewPanel, QFrame#previewPanel, QFrame#statusPanel,
QFrame#analysisFeedback, QFrame#parameterTile,
QLabel#statusBadge, QLabel#analysisScope, QLabel#accelerationStatus,
QLabel#videoPreview, QListWidget#candidateList,
QVideoWidget#videoWidget, QStackedWidget#previewStack,
QWidget#hitTimeline, QWidget#pixelMotionRail,
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox,
QPushButton, QCheckBox::indicator, QProgressBar {
    border-radius: 0px;
}
QLabel#eyebrow {
    font-family: "Cascadia Mono", "Consolas";
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}
QLabel#heroTitle {
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 28px;
    font-weight: 800;
    letter-spacing: 1px;
}
QLabel#heroSubtitle { font-size: 12px; }
QLabel#statusBadge {
    border-width: 2px;
    padding: 7px 11px;
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-weight: 700;
}
QFrame#card, QFrame#workbenchCard, QFrame#topBar,
QFrame#reviewPanel, QFrame#previewPanel, QFrame#statusPanel,
QFrame#analysisFeedback, QFrame#parameterTile {
    border-width: 2px;
}
QListWidget#candidateList {
    border-width: 2px;
    padding: 4px;
}
QListWidget#candidateList::item {
    border-radius: 0px;
    border: 1px solid transparent;
    padding: 9px 8px;
    margin: 3px 1px;
}
QListWidget#candidateList::item:selected { border-width: 2px; }
QVideoWidget#videoWidget, QStackedWidget#previewStack,
QLabel#videoPreview, QWidget#hitTimeline { border-width: 2px; }
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {
    border-width: 2px;
    padding: 7px 10px;
}
QDoubleSpinBox, QSpinBox, QComboBox { padding-right: 36px; }
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {
    border-width: 2px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button,
QComboBox::drop-down {
    width: 30px;
    border-left-width: 2px;
}
QToolButton#spinUpButton, QToolButton#spinDownButton {
    border-radius: 0px;
    border-left-width: 2px;
}
QPushButton {
    border-style: solid;
    border-width: 3px;
    border-bottom-width: 6px;
    padding: 7px 14px 10px 14px;
    font-weight: 700;
}
QPushButton:pressed {
    border-top-width: 5px;
    border-bottom-width: 3px;
    padding-top: 9px;
    padding-bottom: 8px;
}
QPushButton#primaryButton {
    border-width: 3px;
    border-bottom-width: 7px;
    font-size: 14px;
    font-weight: 800;
    letter-spacing: 1px;
}
QPushButton#primaryButton:pressed {
    border-top-width: 6px;
    border-bottom-width: 3px;
}
QCheckBox { spacing: 9px; }
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border-width: 2px;
}
QProgressBar {
    background: transparent;
    border: none;
    color: transparent;
}
QScrollBar:vertical {
    width: 14px;
    margin: 1px;
}
QScrollBar::handle:vertical {
    border-radius: 0px;
    border-width: 2px;
    min-height: 28px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QLabel#percentLabel {
    font-family: "Cascadia Mono", "Consolas";
    font-size: 40px;
    font-weight: 800;
}
QLabel#metricValue, QLabel#analysisFeedbackPercent {
    font-family: "Cascadia Mono", "Consolas";
    font-weight: 700;
}
"""

PIXEL_DARK_STYLE = """
QMenuBar { border-bottom: 2px solid #313944; background: #080b10; }
QMenu { border: 2px solid #4b5664; }
QMenuBar::item:selected, QMenu::item:selected { background: #29323d; color: #baff39; }
QFrame#card, QFrame#workbenchCard { border-color: #3e4855; border-top-color: #667482; }
QFrame#topBar { border-color: #46515f; border-left-color: #24d8ff; border-right-color: #ff3b9d; background: #11161c; }
QFrame#reviewPanel, QFrame#previewPanel, QFrame#statusPanel { border-color: #3c4652; }
QFrame#analysisFeedback { border-color: #79aa35; }
QFrame#parameterTile { border-color: #353f4b; }
QLabel#statusBadge { border-color: #79aa35; border-left-color: #24d8ff; background: #17210f; color: #c8ff73; }
QListWidget#candidateList { border-color: #45505d; background: #090c10; }
QListWidget#candidateList::item:hover { background: #1a222b; border-color: #3f4b58; }
QListWidget#candidateList::item:selected { background: #253419; border-color: #9add43; color: #f5ffe8; }
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox { border-color: #46515e; background: #0d1116; }
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus { border-color: #b9f45a; }
QPushButton {
    background: #202832;
    border-top-color: #8191a1;
    border-left-color: #6a7887;
    border-right-color: #080a0d;
    border-bottom-color: #080a0d;
}
QPushButton:hover { background: #2a3541; border-top-color: #a8b7c5; border-left-color: #8798a8; color: #ffffff; }
QPushButton:pressed { background: #161c23; border-top-color: #080a0d; border-left-color: #080a0d; border-right-color: #596775; border-bottom-color: #596775; }
QPushButton:disabled { background: #161b21; color: #59636d; border-top-color: #303944; border-left-color: #303944; border-right-color: #090b0e; border-bottom-color: #090b0e; }
QPushButton#primaryButton { background: #baff39; color: #10150a; border-top-color: #edffb7; border-left-color: #d8ff82; border-right-color: #416111; border-bottom-color: #416111; }
QPushButton#primaryButton:hover { background: #c8ff73; border-top-color: #ffffff; border-left-color: #edffb7; }
QPushButton#primaryButton:pressed { background: #9dda31; border-top-color: #416111; border-left-color: #416111; border-right-color: #d8ff82; border-bottom-color: #d8ff82; }
QPushButton#dangerButton { background: #48232d; color: #ffc2d9; border-top-color: #a95d70; border-left-color: #884858; border-right-color: #18090b; border-bottom-color: #18090b; }
QPushButton#dangerButton:pressed { border-top-color: #18090b; border-left-color: #18090b; border-right-color: #a95d70; border-bottom-color: #a95d70; }
QCheckBox::indicator:unchecked { background: #090c10; border-color: #63707e; }
QCheckBox::indicator:checked { background: #b9f45a; border-color: #e1ff9e; }
QScrollBar::handle:vertical { background: #3a4652; border: 2px solid #596675; }
QToolTip { background: #111820; color: #f5f7f0; border: 2px solid #667583; padding: 5px; }
"""

PIXEL_LIGHT_STYLE = """
QMenuBar { border-bottom: 2px solid #aab4bf; background: #edf2f6; }
QMenu { border: 2px solid #7e8995; }
QMenuBar::item:selected, QMenu::item:selected { background: #dbe4ec; color: #355806; }
QFrame#card, QFrame#workbenchCard { border-color: #9ca8b4; border-top-color: #657581; }
QFrame#topBar { border-color: #9aa6b2; border-left-color: #007c98; border-right-color: #b51e68; background: #ffffff; }
QFrame#reviewPanel, QFrame#previewPanel, QFrame#statusPanel { border-color: #a5b0bb; }
QFrame#analysisFeedback { border-color: #6e9b31; }
QFrame#parameterTile { border-color: #aeb8c2; }
QLabel#statusBadge { border-color: #6e9b31; border-left-color: #007c98; background: #eef8df; color: #355806; }
QListWidget#candidateList { border-color: #9ca8b4; background: #f7f9fb; }
QListWidget#candidateList::item:hover { background: #e8edf2; border-color: #a6b1bc; }
QListWidget#candidateList::item:selected { background: #e3f2cc; border-color: #6f9d31; color: #213508; }
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox { border-color: #9ca8b4; background: #ffffff; }
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus { border-color: #5f8e25; }
QPushButton { background: #e4eaf0; border-top-color: #ffffff; border-left-color: #ffffff; border-right-color: #74818d; border-bottom-color: #74818d; }
QPushButton:hover { background: #d8e1e9; border-top-color: #ffffff; border-left-color: #eef3f7; color: #151a1f; }
QPushButton:pressed { background: #cbd5de; border-top-color: #74818d; border-left-color: #74818d; border-right-color: #ffffff; border-bottom-color: #ffffff; }
QPushButton:disabled { background: #e8ecef; color: #a1a9b0; border-top-color: #f7f9fa; border-left-color: #f7f9fa; border-right-color: #bfc7ce; border-bottom-color: #bfc7ce; }
QPushButton#primaryButton { background: #9bdc34; color: #17200c; border-top-color: #e4ffae; border-left-color: #caff73; border-right-color: #466f13; border-bottom-color: #466f13; }
QPushButton#primaryButton:hover { background: #aae75a; border-top-color: #f4ffd8; border-left-color: #dcff99; }
QPushButton#primaryButton:pressed { background: #86c22a; border-top-color: #466f13; border-left-color: #466f13; border-right-color: #dcff99; border-bottom-color: #dcff99; }
QPushButton#dangerButton { background: #ffe1ec; color: #8c174a; border-top-color: #ffffff; border-left-color: #fff5f9; border-right-color: #a84b72; border-bottom-color: #a84b72; }
QPushButton#dangerButton:pressed { border-top-color: #a84b72; border-left-color: #a84b72; border-right-color: #fff5f9; border-bottom-color: #fff5f9; }
QCheckBox::indicator:unchecked { background: #ffffff; border-color: #7f8b96; }
QCheckBox::indicator:checked { background: #8fcf3d; border-color: #527d20; }
QScrollBar::handle:vertical { background: #c4cdd5; border: 2px solid #929da8; }
QToolTip { background: #ffffff; color: #20262c; border: 2px solid #7e8995; padding: 5px; }
"""

COURT_BACKGROUND_STYLE = """
QWidget#root, QScrollArea#pageScroll { background: transparent; }
QFrame#card, QFrame#workbenchCard { background: rgba(10, 13, 17, 224); }
QFrame#topBar { background: rgba(11, 15, 20, 218); }
QFrame#reviewPanel, QFrame#previewPanel, QFrame#statusPanel,
QFrame#analysisFeedback, QFrame#parameterTile,
QFrame#themeSelectorPanel { background: rgba(12, 16, 21, 230); }
QListWidget#candidateList, QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {
    background: rgba(7, 10, 14, 238);
}
QLabel#courtBackgroundPreview {
    color: #c7ced6;
    background: rgba(5, 8, 12, 230);
    border: 2px solid #536171;
    padding: 2px;
}
"""

DARK_STYLE_SHEET += PIXEL_COMMON_STYLE + PIXEL_DARK_STYLE
LIGHT_STYLE_SHEET += PIXEL_COMMON_STYLE + PIXEL_LIGHT_STYLE


if __name__ == "__main__":
    main()
