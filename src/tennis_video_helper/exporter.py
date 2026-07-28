"""使用 FFmpeg 和 NVENC 输出并验证回合片段。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from tennis_video_helper.config import AnalysisConfig
from tennis_video_helper.media import probe_media
from tennis_video_helper.models import MediaInfo, RallySegment
from tennis_video_helper.runtime_tools import media_executable


class ExportError(RuntimeError):
    """片段编码或验证失败。"""


def output_dimensions(media: MediaInfo, config: AnalysisConfig) -> tuple[int, int]:
    """返回导出编码尺寸；默认限制为横屏 1920x1080 或竖屏 1080x1920。"""

    if config.export_original_quality:
        return media.width, media.height
    max_width, max_height = (
        (1920, 1080) if media.width >= media.height else (1080, 1920)
    )
    scale = min(1.0, max_width / media.width, max_height / media.height)
    width = max(2, int(media.width * scale) // 2 * 2)
    height = max(2, int(media.height * scale) // 2 * 2)
    return width, height


def _cuda_decoder(media: MediaInfo, config: AnalysisConfig) -> str | None:
    if config.gpu_available is False:
        return None
    return {
        "h264": "h264_cuvid",
        "hevc": "hevc_cuvid",
    }.get(media.video_codec.casefold())


def build_ffmpeg_command(
    media: MediaInfo,
    segment: RallySegment,
    target: Path,
    config: AnalysisConfig,
) -> list[str]:
    """构造不缩放、不强制改帧率的 NVENC 精确切片命令。"""

    if media.is_dolby_vision and not media.has_hlg_compatible_dolby_base_layer:
        raise ExportError("仅支持带 HLG 兼容基础层的 Dolby Vision Profile 8.4")

    duration = segment.output_end - segment.output_start
    target_width, target_height = output_dimensions(media, config)
    downscaling = (target_width, target_height) != (media.width, media.height)
    cuda_decoder = _cuda_decoder(media, config) if downscaling else None
    command = [
        media_executable("ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
    ]
    if cuda_decoder:
        command.extend(
            [
                "-hwaccel",
                "cuda",
                "-hwaccel_output_format",
                "cuda",
                "-c:v",
                cuda_decoder,
            ]
        )
    command.extend(["-ss", f"{segment.output_start:.3f}"])
    if media.rotation:
        command.append("-noautorotate")
    command.extend(
        [
            "-i",
            str(media.path),
            "-t",
            f"{duration:.3f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
        ]
    )
    if config.gpu_available is False:
        command.extend(
            [
                "-c:v",
                "libx265",
                "-preset",
                "medium",
                "-crf",
                str(config.encode_cq),
                "-tag:v",
                "hvc1",
            ]
        )
    else:
        command.extend(
            [
                "-c:v",
                "hevc_nvenc",
                "-preset",
                "p4",
                "-tune",
                "hq",
                "-rc",
                "vbr",
                "-cq",
                str(config.encode_cq),
                "-b:v",
                "0",
            ]
        )
    if downscaling:
        scale_filter = (
            f"scale_cuda={target_width}:{target_height}:"
            "interp_algo=bilinear:passthrough=0"
            if cuda_decoder
            else f"scale={target_width}:{target_height}:flags=lanczos"
        )
        command.extend(["-vf", scale_filter])
    command.extend(
        [
            "-fps_mode:v:0",
            "passthrough",
        ]
    )
    if media.is_variable_frame_rate:
        # NVENC otherwise derives its encoder time base from r_frame_rate.  A
        # mixed 30/60 fps iPhone recording can therefore be quantized to 1/30,
        # giving adjacent 60 fps frames identical PTS values.  Use the common
        # MP4 90 kHz clock so passthrough mode can retain every source frame's
        # presentation time without relying on NVENC's unsupported special -1
        # time-base value.
        command.extend(["-enc_time_base:v:0", "1:90000"])
    if media.requires_main10_output:
        if not cuda_decoder:
            command.extend(["-pix_fmt", "p010le"])
        command.extend(
            [
                "-profile:v",
                "main10",
            ]
        )
    else:
        if not cuda_decoder:
            command.extend(["-pix_fmt", "yuv420p"])
        command.extend(["-profile:v", "main"])

    for option, value in (
        ("-color_trc", media.color_transfer),
        ("-color_primaries", media.color_primaries),
        ("-colorspace", media.color_space),
        ("-color_range", media.color_range),
    ):
        if value:
            command.extend([option, value])

    if media.rotation:
        command.extend(["-metadata:s:v:0", f"rotate={media.rotation}"])

    command.extend(
        [
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(target),
        ]
    )
    return command


def export_clip(
    media: MediaInfo,
    segment: RallySegment,
    target: Path,
    config: AnalysisConfig,
) -> None:
    """编码单个回合片段。"""

    target.parent.mkdir(parents=True, exist_ok=True)
    staging_target = target.with_name(f".{target.stem}.staging{target.suffix}")
    encoded_target = (
        target.with_name(f".{target.stem}.encoded{target.suffix}")
        if media.rotation
        else staging_target
    )
    command = build_ffmpeg_command(media, segment, encoded_target, config)
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        if media.rotation:
            signed_rotation = (
                media.rotation if media.rotation <= 180 else media.rotation - 360
            )
            remux_command = [
                media_executable("ffmpeg"),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-display_rotation:v:0",
                str(signed_rotation),
                "-i",
                str(encoded_target),
                "-map",
                "0",
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(staging_target),
            ]
            subprocess.run(
                remux_command,
                check=True,
                capture_output=True,
                text=True,
            )
        staging_target.replace(target)
    except FileNotFoundError as exc:
        raise ExportError(f"视频输出失败：找不到 FFmpeg：{target}") from exc
    except subprocess.CalledProcessError as exc:
        detail = _subprocess_error_detail(exc)
        suffix = f"：{detail}" if detail else ""
        raise ExportError(f"视频输出失败{suffix}（{target.name}）") from exc
    finally:
        encoded_target.unlink(missing_ok=True)
        staging_target.unlink(missing_ok=True)


def _subprocess_error_detail(exc: subprocess.CalledProcessError) -> str | None:
    """提取 FFmpeg 最后一行有意义的错误，避免界面只显示笼统失败。"""

    output = exc.stderr or exc.stdout
    if not isinstance(output, str):
        return None
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else None


def verify_clip(
    path: Path,
    source_media: MediaInfo,
    segment: RallySegment,
    config: AnalysisConfig | None = None,
) -> tuple[bool, str | None]:
    """检查输出媒体参数，并解码片段头尾。"""

    if not path.is_file() or path.stat().st_size == 0:
        return False, "输出文件不存在或为空"
    try:
        media = probe_media(path)
    except Exception as exc:  # noqa: BLE001 - 统一转换为报告错误
        return False, f"ffprobe 验证失败：{exc}"

    expected_dimensions = (
        (source_media.width, source_media.height)
        if config is None
        else output_dimensions(source_media, config)
    )
    if (media.width, media.height) != expected_dimensions:
        return False, "输出分辨率与导出画质设置不一致"
    if media.rotation != source_media.rotation:
        return False, "输出画面旋转信息与源视频不一致"
    expected_pixel_formats = (
        {"yuv420p10le", "p010le"}
        if source_media.requires_main10_output
        else {"yuv420p"}
    )
    if media.pixel_format not in expected_pixel_formats:
        return False, "输出像素格式与源视频策略不一致"
    if source_media.requires_main10_output and (media.video_profile or "").casefold() not in {
        "main 10",
        "main10",
    }:
        return False, "输出视频配置不是 HEVC Main 10"
    if (
        not source_media.is_variable_frame_rate
        and source_media.fps
        and abs(media.fps - source_media.fps) > 0.2
    ):
        return False, "输出帧率与源视频不一致"
    for source_value, output_value, label in (
        (source_media.color_transfer, media.color_transfer, "传递函数"),
        (source_media.color_primaries, media.color_primaries, "色彩原色"),
        (source_media.color_space, media.color_space, "色彩空间"),
        (source_media.color_range, media.color_range, "色彩范围"),
    ):
        if source_value and output_value != source_value:
            return False, f"输出{label}与源视频不一致"
    expected_duration = segment.output_end - segment.output_start
    if source_media.is_variable_frame_rate:
        try:
            source_timestamps = _probe_frame_timestamps(
                source_media.path,
                segment.output_start,
                expected_duration,
            )
            output_timestamps = _probe_frame_timestamps(
                path,
                0.0,
                expected_duration,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError):
            return False, "无法验证可变帧率时间关系"
        if not _frame_timings_match(source_timestamps, output_timestamps):
            return False, "输出可变帧率时间关系与源片段不一致"
    if source_media.audio_codec and not media.audio_codec:
        return False, "输出片段缺少音频流"
    if abs(media.duration - expected_duration) > 0.75:
        return False, "输出时长超出允许误差"

    for seek_arguments in (["-ss", "0", "-t", "1"], ["-sseof", "-1"]):
        command = [
            media_executable("ffmpeg"),
            "-hide_banner",
            "-loglevel",
            "error",
            *seek_arguments,
            "-i",
            str(path),
            "-f",
            "null",
            os.devnull,
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            return False, "片段头尾解码检查失败"
    return True, None


def _probe_frame_timestamps(
    path: Path,
    start: float,
    duration: float,
) -> list[float]:
    seek_margin = 5.0 if start > 0 else 0.5
    command = [
        media_executable("ffprobe"),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-read_intervals",
        f"{start:.6f}%+{duration + seek_margin:.6f}",
        "-show_entries",
        "packet=pts_time",
        "-show_packets",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    payload = json.loads(result.stdout)
    timestamps: list[float] = []
    for packet in payload.get("packets", []):
        value = packet.get("pts_time")
        try:
            timestamp = float(value)
        except (TypeError, ValueError):
            continue
        if start - 1e-3 <= timestamp <= start + duration + 1e-3:
            timestamps.append(timestamp)
    # Compressed packets can be emitted in decode order when B-frames are used;
    # PTS sorting restores presentation order without decoding every 4K frame.
    return sorted(timestamps)


def _frame_timings_match(source: list[float], output: list[float]) -> bool:
    source_intervals = _positive_frame_intervals(source)
    output_intervals = _positive_frame_intervals(output)
    if len(source_intervals) < 2 or len(output_intervals) < 2:
        return False

    frame_tolerance = max(3, round(len(source) * 0.05))
    if abs(len(source) - len(output)) > frame_tolerance:
        return False

    source_signature = tuple(
        _percentile(source_intervals, percentile)
        for percentile in (0.1, 0.5, 0.9)
    )
    output_signature = tuple(
        _percentile(output_intervals, percentile)
        for percentile in (0.1, 0.5, 0.9)
    )
    return all(
        abs(source_value - output_value) <= 0.004
        for source_value, output_value in zip(
            source_signature,
            output_signature,
            strict=True,
        )
    )


def _positive_frame_intervals(timestamps: list[float]) -> list[float]:
    return [
        current - previous
        for previous, current in zip(timestamps, timestamps[1:])
        if 1e-6 < current - previous < 1.0
    ]


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight
