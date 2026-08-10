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
    nominal_fps: float = 0.0
    is_variable_frame_rate: bool = False
    color_primaries: str | None = None
    color_space: str | None = None
    color_range: str | None = None
    video_profile: str | None = None
    dolby_vision_profile: int | None = None
    dolby_vision_bl_compatibility_id: int | None = None

    @property
    def has_hlg_compatible_dolby_base_layer(self) -> bool:
        """是否为可作为标准 HLG 读取的 Dolby Vision Profile 8.4。"""

        return (
            self.is_dolby_vision
            and self.dolby_vision_profile == 8
            and self.dolby_vision_bl_compatibility_id == 4
            and self.color_transfer == "arib-std-b67"
        )

    @property
    def requires_main10_output(self) -> bool:
        """导出时是否必须保留 10-bit HEVC Main10。"""

        return self.is_hdr10 or self.has_hlg_compatible_dolby_base_layer


class MediaProbeError(RuntimeError):
    """媒体元数据无法读取。"""


@dataclass(frozen=True, slots=True)
class AudioEvent:
    """音频瞬态候选事件。"""

    timestamp: float
    confidence: float
    strength: float
    impact_score: float = 1.0


@dataclass(frozen=True, slots=True)
class VisualEvent:
    """通过姿态、时序轨迹和站立状态确认的近端挥拍事件。"""

    timestamp: float
    confidence: float
    motion_score: float
    global_motion: float
    posture_score: float = 1.0
    arm_motion_score: float = 1.0
    leg_motion_score: float = 0.0
    stroke_type: str = "挥拍"
    racket_confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class FusedEvent:
    """融合后的击球候选事件。"""

    timestamp: float
    audio_confidence: float
    visual_confidence: float
    confidence: float
    reason: str
    visual_arm_motion_score: float = 1.0
    visual_stroke_type: str = "挥拍"
    audio_impact_score: float = 1.0
    visual_racket_confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class RallySegment:
    """通过时长筛选的回合及最终输出区间。"""

    active_start: float
    active_end: float
    output_start: float
    output_end: float
    active_duration: float
    average_confidence: float
    event_count: int


@dataclass(frozen=True, slots=True)
class ClipRecord:
    """单个输出片段及验证结果。"""

    index: int
    path: Path
    segment: RallySegment
    verified: bool
    error: str | None
