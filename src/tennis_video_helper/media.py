"""视频扫描与 ffprobe 元数据读取。"""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from tennis_video_helper.models import MediaInfo, MediaProbeError

SUPPORTED_VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".m4v"})


def scan_videos(input_path: Path) -> list[Path]:
    """返回输入文件或目录中的受支持视频，结果按路径稳定排序。"""

    input_path = input_path.resolve()
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS else []
    if not input_path.is_dir():
        raise FileNotFoundError(f"输入路径不存在：{input_path}")

    videos = (
        path
        for path in input_path.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
    )
    return sorted(videos, key=lambda path: str(path).casefold())


def probe_media(path: Path) -> MediaInfo:
    """通过 ffprobe 读取媒体信息。"""

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        payload = json.loads(result.stdout)
    except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise MediaProbeError(f"无法读取媒体信息：{path}") from exc

    return parse_probe_payload(path, payload)


def parse_probe_payload(path: Path, payload: dict[str, Any]) -> MediaInfo:
    """将 ffprobe JSON 转换为强类型媒体信息。"""

    streams = payload.get("streams", [])
    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise MediaProbeError(f"视频流不存在：{path}")

    audio_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"),
        None,
    )
    format_info = payload.get("format", {})
    duration = _parse_float(format_info.get("duration"), default=0.0)
    fps = _parse_frame_rate(video_stream.get("avg_frame_rate"))
    nominal_fps = _parse_frame_rate(video_stream.get("r_frame_rate"))
    if fps <= 0:
        fps = nominal_fps
    is_variable_frame_rate = (
        fps > 0 and nominal_fps > 0 and abs(fps - nominal_fps) > 0.2
    )
    rotation = _parse_rotation(video_stream)
    color_transfer = video_stream.get("color_transfer")
    serialized_stream = json.dumps(video_stream, ensure_ascii=False).lower()
    codec_tag = str(video_stream.get("codec_tag_string", "")).lower()
    is_dolby_vision = codec_tag.startswith("dv") or "dovi" in serialized_stream
    is_hdr10 = color_transfer == "smpte2084" and not is_dolby_vision

    return MediaInfo(
        path=Path(path),
        duration=duration,
        width=int(video_stream.get("width", 0)),
        height=int(video_stream.get("height", 0)),
        fps=fps,
        video_codec=str(video_stream.get("codec_name", "unknown")),
        pixel_format=video_stream.get("pix_fmt"),
        audio_codec=(str(audio_stream.get("codec_name")) if audio_stream else None),
        audio_sample_rate=(
            int(audio_stream["sample_rate"])
            if audio_stream and audio_stream.get("sample_rate")
            else None
        ),
        audio_channels=(
            int(audio_stream["channels"])
            if audio_stream and audio_stream.get("channels") is not None
            else None
        ),
        rotation=rotation,
        color_transfer=color_transfer,
        is_hdr10=is_hdr10,
        is_dolby_vision=is_dolby_vision,
        nominal_fps=nominal_fps,
        is_variable_frame_rate=is_variable_frame_rate,
        color_primaries=video_stream.get("color_primaries"),
        color_space=video_stream.get("color_space"),
        color_range=video_stream.get("color_range"),
        video_profile=video_stream.get("profile"),
    )


def _parse_frame_rate(value: Any) -> float:
    if not value or value == "0/0":
        return 0.0
    try:
        return float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return 0.0


def _parse_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_rotation(video_stream: dict[str, Any]) -> int:
    tags = video_stream.get("tags", {})
    if tags.get("rotate") is not None:
        try:
            return int(float(tags["rotate"])) % 360
        except (TypeError, ValueError):
            pass

    for side_data in video_stream.get("side_data_list", []):
        if side_data.get("rotation") is not None:
            try:
                return int(float(side_data["rotation"])) % 360
            except (TypeError, ValueError):
                continue
    return 0
