"""跨模块共享的数据结构。"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MediaInfo:
    """ffprobe 解析得到的媒体信息。"""

    path: Path
    duration: float
    width: int
    height: int
    fps: float
    video_codec: str
    pixel_format: str | None
    audio_codec: str | None
    audio_sample_rate: int | None
    audio_channels: int | None
    rotation: int
    color_transfer: str | None
    is_hdr10: bool
    is_dolby_vision: bool


class MediaProbeError(RuntimeError):
    """媒体元数据无法读取。"""


@dataclass(frozen=True, slots=True)
class AudioEvent:
    """音频瞬态候选事件。"""

    timestamp: float
    confidence: float
    strength: float

