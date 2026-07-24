"""批量编排音频、视觉、融合、导出和报告流程。"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

import numpy as np

from tennis_video_helper.config import AnalysisConfig
from tennis_video_helper.fusion import build_rally_segments, fuse_events
from tennis_video_helper.models import (
    AudioEvent,
    ClipRecord,
    FusedEvent,
    MediaInfo,
    RallySegment,
    VisualEvent,
)


@dataclass(slots=True)
class PipelineServices:
    """管线外部依赖，便于测试时替换。"""

    scan_videos: Callable[[Path], list[Path]]
    probe_media: Callable[[Path], MediaInfo]
    extract_audio: Callable[[Path, Path, int], None]
    load_audio: Callable[[Path], tuple[np.ndarray, int]]
    detect_audio_events: Callable[[np.ndarray, int, AnalysisConfig], list[AudioEvent]]
    analyze_video: Callable[[Path, AnalysisConfig, float | None], list[VisualEvent]]
    export_clip: Callable[[MediaInfo, RallySegment, Path, AnalysisConfig], None]
    verify_clip: Callable[[Path, MediaInfo, RallySegment], tuple[bool, str | None]]
    write_reports: Callable[
        [
            Path,
            MediaInfo,
            list[ClipRecord],
            list[AudioEvent],
            list[VisualEvent],
            list[FusedEvent],
        ],
        None,
    ]

    @classmethod
    def defaults(cls) -> "PipelineServices":
        return cls(
            scan_videos=_scan_videos,
            probe_media=_probe_media,
            extract_audio=_extract_audio,
            load_audio=_load_audio,
            detect_audio_events=_detect_audio_events,
            analyze_video=_analyze_video,
            export_clip=_export_clip,
            verify_clip=_verify_clip,
            write_reports=_write_reports,
        )

    def replace(self, **changes) -> "PipelineServices":
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class VideoProcessResult:
    source: Path
    output_dir: Path | None
    records: tuple[ClipRecord, ...] = field(default_factory=tuple)
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass(frozen=True, slots=True)
class BatchResult:
    results: tuple[VideoProcessResult, ...]

    @property
    def success_count(self) -> int:
        return sum(result.succeeded for result in self.results)

    @property
    def failure_count(self) -> int:
        return len(self.results) - self.success_count


def process_batch(
    input_path: Path,
    output_root: Path,
    config: AnalysisConfig,
    *,
    limit_duration: float | None = None,
    services: PipelineServices | None = None,
) -> BatchResult:
    """逐个处理视频，单文件失败不阻止后续文件。"""

    active_services = services or PipelineServices.defaults()
    sources = active_services.scan_videos(Path(input_path))
    results: list[VideoProcessResult] = []
    for source in sources:
        try:
            result = _process_video(
                source,
                Path(output_root),
                config,
                limit_duration,
                active_services,
            )
        except Exception as exc:  # noqa: BLE001 - 单文件错误必须转为批处理结果
            result = VideoProcessResult(
                source=source,
                output_dir=None,
                error=str(exc),
            )
        results.append(result)
    return BatchResult(tuple(results))


def _process_video(
    source: Path,
    output_root: Path,
    config: AnalysisConfig,
    limit_duration: float | None,
    services: PipelineServices,
) -> VideoProcessResult:
    media = services.probe_media(source)
    if not media.audio_codec:
        raise RuntimeError(f"视频没有音轨，第一版无法执行音画融合：{source}")
    if media.is_dolby_vision:
        raise RuntimeError(f"检测到 Dolby Vision，第一版为避免偏色已停止：{source}")

    output_dir = _next_available_output_dir(output_root, source.stem)
    clips_dir = output_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="tennis-video-helper-") as temporary:
        audio_path = Path(temporary) / "audio.wav"
        services.extract_audio(source, audio_path, config.audio_sample_rate)
        samples, sample_rate = services.load_audio(audio_path)
        if limit_duration is not None:
            samples = samples[: int(limit_duration * sample_rate)]
        audio_events = services.detect_audio_events(samples, sample_rate, config)

    visual_events = services.analyze_video(source, config, limit_duration)
    fused_events = fuse_events(audio_events, visual_events, config)
    effective_duration = (
        min(media.duration, limit_duration)
        if limit_duration is not None
        else media.duration
    )
    segments = build_rally_segments(fused_events, effective_duration, config)

    records: list[ClipRecord] = []
    for index, segment in enumerate(segments, start=1):
        target = clips_dir / _clip_filename(index, segment)
        try:
            services.export_clip(media, segment, target, config)
            verified, error = services.verify_clip(
                target,
                media,
                segment,
            )
        except Exception as exc:  # noqa: BLE001 - 记录单片段错误并继续
            verified, error = False, str(exc)
        if not verified:
            target.unlink(missing_ok=True)
        records.append(
            ClipRecord(
                index=index,
                path=target,
                segment=segment,
                verified=verified,
                error=error,
            )
        )

    services.write_reports(
        output_dir,
        media,
        records,
        audio_events,
        visual_events,
        fused_events,
    )
    _write_processing_log(
        output_dir,
        source,
        len(audio_events),
        len(visual_events),
        len(fused_events),
        records,
    )
    return VideoProcessResult(source, output_dir, tuple(records), None)


def _next_available_output_dir(output_root: Path, stem: str) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    candidate = output_root / stem
    suffix = 2
    while candidate.exists():
        candidate = output_root / f"{stem}_{suffix}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def _clip_filename(index: int, segment: RallySegment) -> str:
    time_label = _format_seconds(segment.active_start)
    return f"rally_{index:03d}_{time_label}_{segment.active_duration:.1f}s.mp4"


def _format_seconds(value: float) -> str:
    total_seconds = max(0, round(value))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}-{minutes:02d}-{seconds:02d}"


def _write_processing_log(
    output_dir: Path,
    source: Path,
    audio_count: int,
    visual_count: int,
    fused_count: int,
    records: list[ClipRecord],
) -> None:
    verified_count = sum(record.verified for record in records)
    content = "\n".join(
        [
            f"源视频：{source}",
            f"音频候选：{audio_count}",
            f"视觉候选：{visual_count}",
            f"融合事件：{fused_count}",
            f"候选片段：{len(records)}",
            f"验证成功：{verified_count}",
        ]
    )
    (output_dir / "processing.log").write_text(content + "\n", encoding="utf-8")


def _scan_videos(path: Path) -> list[Path]:
    from tennis_video_helper.media import scan_videos

    return scan_videos(path)


def _probe_media(path: Path) -> MediaInfo:
    from tennis_video_helper.media import probe_media

    return probe_media(path)


def _extract_audio(source: Path, target: Path, sample_rate: int) -> None:
    from tennis_video_helper.audio import extract_audio

    extract_audio(source, target, sample_rate=sample_rate)


def _load_audio(path: Path) -> tuple[np.ndarray, int]:
    from tennis_video_helper.audio import load_audio

    return load_audio(path)


def _detect_audio_events(
    samples: np.ndarray,
    sample_rate: int,
    config: AnalysisConfig,
) -> list[AudioEvent]:
    from tennis_video_helper.audio import detect_audio_events

    return detect_audio_events(samples, sample_rate, config)


def _analyze_video(
    path: Path,
    config: AnalysisConfig,
    limit_duration: float | None,
) -> list[VisualEvent]:
    from tennis_video_helper.vision import analyze_video

    return analyze_video(path, config, limit_duration=limit_duration)


def _export_clip(
    media: MediaInfo,
    segment: RallySegment,
    target: Path,
    config: AnalysisConfig,
) -> None:
    from tennis_video_helper.exporter import export_clip

    export_clip(media, segment, target, config)


def _verify_clip(
    path: Path,
    media: MediaInfo,
    segment: RallySegment,
) -> tuple[bool, str | None]:
    from tennis_video_helper.exporter import verify_clip

    return verify_clip(path, media, segment)


def _write_reports(
    output_dir: Path,
    media: MediaInfo,
    records: list[ClipRecord],
    audio_events: list[AudioEvent],
    visual_events: list[VisualEvent],
    fused_events: list[FusedEvent],
) -> None:
    from tennis_video_helper.report import write_reports

    write_reports(
        output_dir,
        media,
        records,
        audio_events,
        visual_events,
        fused_events,
    )
