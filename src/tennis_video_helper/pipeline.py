"""批量编排音频、视觉、融合、导出和报告流程。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

import numpy as np

from tennis_video_helper.config import AnalysisConfig
from tennis_video_helper.fusion import (
    VISUAL_CONFIRMATION_THRESHOLD,
    build_rally_segments,
    fuse_events,
)
from tennis_video_helper.models import (
    AudioEvent,
    ClipRecord,
    FusedEvent,
    MediaInfo,
    RallySegment,
    VisualEvent,
)
from tennis_video_helper.review import (
    ReviewClipCandidate,
    ReviewHit,
    ReviewSession,
    ReviewVideoCandidate,
    save_review_session,
)


@dataclass(slots=True)
class PipelineServices:
    """管线外部依赖，便于测试时替换。"""

    scan_videos: Callable[[Path], list[Path]]
    probe_media: Callable[[Path], MediaInfo]
    extract_audio: Callable[[Path, Path, int], None]
    load_audio: Callable[[Path], tuple[np.ndarray, int]]
    detect_audio_events: Callable[[np.ndarray, int, AnalysisConfig], list[AudioEvent]]
    analyze_video: Callable[
        [Path, AnalysisConfig, float | None, Callable[[float], None] | None],
        list[VisualEvent],
    ]
    export_clip: Callable[[MediaInfo, RallySegment, Path, AnalysisConfig], None]
    verify_clip: Callable[
        [Path, MediaInfo, RallySegment, AnalysisConfig], tuple[bool, str | None]
    ]
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


@dataclass(frozen=True, slots=True)
class ReviewBatchResult:
    """后台准备好候选片段后返回给 GUI 的复核会话。"""

    results: tuple[VideoProcessResult, ...]
    session: ReviewSession | None

    @property
    def success_count(self) -> int:
        return sum(result.succeeded for result in self.results)

    @property
    def failure_count(self) -> int:
        return len(self.results) - self.success_count


@dataclass(frozen=True, slots=True)
class ProgressUpdate:
    """供 CLI/UI 展示的批处理进度快照。"""

    percent: float
    phase: str
    current_video: Path | None
    video_index: int
    video_total: int


ProgressCallback = Callable[[ProgressUpdate], None]
VideoProgressCallback = Callable[[float, str], None]


@dataclass(frozen=True, slots=True)
class _PreparedVideoAssets:
    media: MediaInfo
    records: tuple[ClipRecord, ...]
    audio_events: tuple[AudioEvent, ...]
    visual_events: tuple[VisualEvent, ...]
    fused_events: tuple[FusedEvent, ...]


def process_batch(
    input_path: Path,
    output_root: Path,
    config: AnalysisConfig,
    *,
    limit_duration: float | None = None,
    services: PipelineServices | None = None,
    progress_callback: ProgressCallback | None = None,
) -> BatchResult:
    """逐个处理视频，单文件失败不阻止后续文件。"""

    active_services = services or PipelineServices.defaults()
    sources = active_services.scan_videos(Path(input_path))
    results: list[VideoProcessResult] = []
    video_total = len(sources)
    if progress_callback is not None:
        progress_callback(ProgressUpdate(0.0, "准备任务", None, 0, video_total))
    for video_index, source in enumerate(sources, start=1):
        def report_video_progress(fraction: float, phase: str) -> None:
            if progress_callback is None:
                return
            bounded = min(1.0, max(0.0, fraction))
            overall = ((video_index - 1) + bounded) / max(1, video_total) * 100
            progress_callback(
                ProgressUpdate(
                    percent=overall,
                    phase=phase,
                    current_video=source,
                    video_index=video_index,
                    video_total=video_total,
                )
            )

        report_video_progress(0.0, "读取视频信息")
        try:
            result = _process_video(
                source,
                Path(output_root),
                config,
                limit_duration,
                active_services,
                report_video_progress,
            )
        except Exception as exc:  # noqa: BLE001 - 单文件错误必须转为批处理结果
            result = VideoProcessResult(
                source=source,
                output_dir=None,
                error=str(exc),
            )
        results.append(result)
        report_video_progress(
            1.0,
            "当前视频完成" if result.succeeded else "当前视频失败",
        )
    if progress_callback is not None:
        final_phase = "没有找到视频"
        if sources:
            final_phase = (
                "全部任务完成"
                if all(result.succeeded for result in results)
                else "全部任务结束（含失败）"
            )
        progress_callback(
            ProgressUpdate(
                100.0,
                final_phase,
                sources[-1] if sources else None,
                video_total,
                video_total,
            )
        )
    return BatchResult(tuple(results))


def prepare_review_batch(
    input_path: Path,
    output_root: Path,
    config: AnalysisConfig,
    *,
    limit_duration: float | None = None,
    services: PipelineServices | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ReviewBatchResult:
    """生成经过验证的候选片段，但在人工勾选前不发布正式结果。"""

    active_services = services or PipelineServices.defaults()
    sources = active_services.scan_videos(Path(input_path))
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    session_root = Path(
        tempfile.mkdtemp(prefix=".tennis-review-", dir=output_root)
    )
    results: list[VideoProcessResult] = []
    review_videos: list[ReviewVideoCandidate] = []
    reserved_outputs: set[Path] = set()
    video_total = len(sources)
    if progress_callback is not None:
        progress_callback(ProgressUpdate(0.0, "准备候选复核", None, 0, video_total))

    for video_index, source in enumerate(sources, start=1):
        def report_video_progress(fraction: float, phase: str) -> None:
            if progress_callback is None:
                return
            bounded = min(1.0, max(0.0, fraction))
            overall = ((video_index - 1) + bounded) / max(1, video_total) * 100
            progress_callback(
                ProgressUpdate(
                    percent=overall,
                    phase=phase,
                    current_video=source,
                    video_index=video_index,
                    video_total=video_total,
                )
            )

        staging_dir = session_root / f"{video_index:03d}_{source.stem}"
        final_output_dir = _planned_output_dir(
            output_root,
            source.stem,
            overwrite=config.overwrite_existing_output,
            reserved=reserved_outputs,
        )
        reserved_outputs.add(final_output_dir)
        report_video_progress(0.0, "读取视频信息")
        try:
            media = _load_supported_media(source, active_services)
            staging_dir.mkdir(parents=True, exist_ok=True)
            assets = _prepare_video_assets(
                source,
                media,
                staging_dir,
                config,
                limit_duration,
                active_services,
                report_video_progress,
            )
            failed_records = [record for record in assets.records if not record.verified]
            if failed_records:
                detail = _failed_record_summary(failed_records)
                raise RuntimeError(f"新候选包含验证失败的片段：{detail}")

            clips = tuple(
                ReviewClipCandidate(
                    id=f"{video_index}:{record.index}",
                    index=record.index,
                    path=record.path,
                    segment=record.segment,
                    hits=_review_hits(record.segment, assets.fused_events, config),
                )
                for record in assets.records
            )
            review_videos.append(
                ReviewVideoCandidate(
                    source=source,
                    output_dir=final_output_dir,
                    staging_dir=staging_dir,
                    media=assets.media,
                    clips=clips,
                    audio_events=assets.audio_events,
                    visual_events=assets.visual_events,
                    fused_events=assets.fused_events,
                )
            )
            results.append(
                VideoProcessResult(
                    source=source,
                    output_dir=final_output_dir,
                    records=assets.records,
                    error=None,
                )
            )
            report_video_progress(1.0, "候选片段已准备")
        except Exception as exc:  # noqa: BLE001 - 单文件错误不阻断批处理
            shutil.rmtree(staging_dir, ignore_errors=True)
            results.append(
                VideoProcessResult(source=source, output_dir=None, error=str(exc))
            )
            report_video_progress(1.0, "当前视频失败")

    session: ReviewSession | None = None
    if review_videos:
        session = ReviewSession(
            root_dir=session_root,
            overwrite_existing_output=config.overwrite_existing_output,
            videos=tuple(review_videos),
        )
        save_review_session(session)
    else:
        shutil.rmtree(session_root, ignore_errors=True)

    if progress_callback is not None:
        final_phase = "没有找到视频"
        if sources:
            final_phase = (
                "等待人工确认候选片段"
                if session is not None
                else "全部任务结束（含失败）"
            )
        progress_callback(
            ProgressUpdate(
                100.0,
                final_phase,
                sources[-1] if sources else None,
                video_total,
                video_total,
            )
        )
    return ReviewBatchResult(tuple(results), session)


def _process_video(
    source: Path,
    output_root: Path,
    config: AnalysisConfig,
    limit_duration: float | None,
    services: PipelineServices,
    progress_callback: VideoProgressCallback,
) -> VideoProcessResult:
    media = _load_supported_media(source, services)

    output_dir, working_output_dir = _prepare_output_dir(
        output_root,
        source.stem,
        overwrite=config.overwrite_existing_output,
    )
    try:
        assets = _prepare_video_assets(
            source,
            media,
            working_output_dir,
            config,
            limit_duration,
            services,
            progress_callback,
        )
        published_records = [
            replace(record, path=output_dir / "clips" / record.path.name)
            for record in assets.records
        ]
        failed_records = [record for record in published_records if not record.verified]
        if config.overwrite_existing_output and failed_records:
            summary = _failed_record_summary(failed_records)
            raise RuntimeError(f"新结果有 {len(failed_records)} 个片段失败：{summary}，旧结果已保留")

        progress_callback(0.98, "生成分析报告")
        services.write_reports(
            working_output_dir,
            assets.media,
            published_records,
            list(assets.audio_events),
            list(assets.visual_events),
            list(assets.fused_events),
        )
        _write_processing_log(
            working_output_dir,
            source,
            len(assets.audio_events),
            len(assets.visual_events),
            len(assets.fused_events),
            published_records,
        )
        if working_output_dir != output_dir:
            _replace_output_dir(working_output_dir, output_dir)
        return VideoProcessResult(source, output_dir, tuple(published_records), None)
    except Exception:
        if working_output_dir != output_dir:
            shutil.rmtree(working_output_dir, ignore_errors=True)
        raise


def _analyze_audio_track(
    source: Path,
    audio_path: Path,
    config: AnalysisConfig,
    limit_duration: float | None,
    services: PipelineServices,
) -> list[AudioEvent]:
    services.extract_audio(source, audio_path, config.audio_sample_rate)
    samples, sample_rate = services.load_audio(audio_path)
    if limit_duration is not None:
        samples = samples[: int(limit_duration * sample_rate)]
    return services.detect_audio_events(samples, sample_rate, config)


def _export_and_verify_segment(
    index: int,
    segment: RallySegment,
    clips_dir: Path,
    media: MediaInfo,
    config: AnalysisConfig,
    services: PipelineServices,
) -> ClipRecord:
    target = clips_dir / _clip_filename(index, segment)
    try:
        services.export_clip(media, segment, target, config)
        verified, error = services.verify_clip(target, media, segment, config)
    except Exception as exc:  # noqa: BLE001 - 记录单片段错误并继续
        verified, error = False, str(exc)
    if not verified:
        target.unlink(missing_ok=True)
    return ClipRecord(
        index=index,
        path=target,
        segment=segment,
        verified=verified,
        error=error,
    )


def _next_available_output_dir(output_root: Path, stem: str) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    candidate = output_root / stem
    suffix = 2
    while candidate.exists():
        candidate = output_root / f"{stem}_{suffix}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def _planned_output_dir(
    output_root: Path,
    stem: str,
    *,
    overwrite: bool,
    reserved: set[Path],
) -> Path:
    """为复核会话预留最终路径，但在用户确认前不创建正式目录。"""

    candidate = output_root / stem
    if overwrite:
        if candidate not in reserved:
            return candidate
        suffix = 2
        while output_root / f"{stem}_{suffix}" in reserved:
            suffix += 1
        return output_root / f"{stem}_{suffix}"

    suffix = 2
    while candidate.exists() or candidate in reserved:
        candidate = output_root / f"{stem}_{suffix}"
        suffix += 1
    return candidate


def _prepare_output_dir(
    output_root: Path,
    stem: str,
    *,
    overwrite: bool,
) -> tuple[Path, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    if not overwrite:
        output_dir = _next_available_output_dir(output_root, stem)
        return output_dir, output_dir
    output_dir = output_root / stem
    working_dir = Path(
        tempfile.mkdtemp(prefix=f".{stem}.staging-", dir=output_root)
    )
    return output_dir, working_dir


def _replace_output_dir(working_dir: Path, output_dir: Path) -> None:
    """成功完成后替换旧目录；替换失败时尽量恢复旧结果。"""

    backup_dir: Path | None = None
    if output_dir.exists():
        backup_dir = output_dir.with_name(
            f".{output_dir.name}.backup-{uuid.uuid4().hex}"
        )
        _replace_path_with_retry(output_dir, backup_dir)
    try:
        _replace_path_with_retry(working_dir, output_dir)
    except Exception:
        if backup_dir is not None and backup_dir.exists() and not output_dir.exists():
            _replace_path_with_retry(backup_dir, output_dir)
        raise
    if backup_dir is not None:
        shutil.rmtree(backup_dir, ignore_errors=True)


def _load_supported_media(source: Path, services: PipelineServices) -> MediaInfo:
    media = services.probe_media(source)
    if not media.audio_codec:
        raise RuntimeError(f"视频没有音轨，第一版无法执行音画融合：{source}")
    if media.is_dolby_vision and not media.has_hlg_compatible_dolby_base_layer:
        raise RuntimeError(
            f"检测到不支持的 Dolby Vision Profile，仅放行 HLG 兼容的 Profile 8.4：{source}"
        )
    return media


def _prepare_video_assets(
    source: Path,
    media: MediaInfo,
    working_output_dir: Path,
    config: AnalysisConfig,
    limit_duration: float | None,
    services: PipelineServices,
    progress_callback: VideoProgressCallback,
) -> _PreparedVideoAssets:
    progress_callback(0.04, "检查媒体信息")
    clips_dir = working_output_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    progress_callback(0.07, "并行分析声音与画面")

    def report_visual_progress(fraction: float) -> None:
        progress_callback(
            0.08 + min(1.0, max(0.0, fraction)) * 0.67,
            "GPU 分析画面",
        )

    with tempfile.TemporaryDirectory(prefix="tennis-video-helper-") as temporary:
        audio_path = Path(temporary) / "audio.wav"
        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="tennis-analysis",
        ) as executor:
            audio_future = executor.submit(
                _analyze_audio_track,
                source,
                audio_path,
                config,
                limit_duration,
                services,
            )
            visual_future = executor.submit(
                services.analyze_video,
                source,
                config,
                limit_duration,
                report_visual_progress,
            )
            audio_events = audio_future.result()
            visual_events = visual_future.result()
    progress_callback(0.76, "融合声音与动作")
    fused_events = fuse_events(audio_events, visual_events, config)
    effective_duration = (
        min(media.duration, limit_duration)
        if limit_duration is not None
        else media.duration
    )
    segments = build_rally_segments(fused_events, effective_duration, config)
    progress_callback(0.80, "生成候选预览片段")

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="tennis-export") as executor:
        export_futures = {
            executor.submit(
                _export_and_verify_segment,
                index,
                segment,
                clips_dir,
                media,
                config,
                services,
            ): index
            for index, segment in enumerate(segments, start=1)
        }
        records: list[ClipRecord] = []
        for completed_count, future in enumerate(as_completed(export_futures), start=1):
            records.append(future.result())
            progress_callback(
                0.80 + 0.17 * completed_count / max(1, len(export_futures)),
                f"生成候选预览 {completed_count}/{len(export_futures)}",
            )
    records.sort(key=lambda record: record.index)
    return _PreparedVideoAssets(
        media=media,
        records=tuple(records),
        audio_events=tuple(audio_events),
        visual_events=tuple(visual_events),
        fused_events=tuple(fused_events),
    )


def _review_hits(
    segment: RallySegment,
    fused_events: tuple[FusedEvent, ...],
    config: AnalysisConfig,
) -> tuple[ReviewHit, ...]:
    hits = [
        ReviewHit(
            timestamp=round(event.timestamp - segment.output_start, 3),
            source_timestamp=round(event.timestamp, 3),
            confidence=round(event.confidence, 4),
            reason=event.reason,
        )
        for event in fused_events
        if segment.output_start <= event.timestamp <= segment.output_end
        and event.visual_confidence >= VISUAL_CONFIRMATION_THRESHOLD
        and event.confidence >= config.rally_support_threshold
    ]
    return tuple(hits)


def _failed_record_summary(records: list[ClipRecord]) -> str:
    error_details = list(dict.fromkeys(record.error for record in records if record.error))
    detail = "；".join(error_details[:3])
    if len(error_details) > 3:
        detail += f"；另有 {len(error_details) - 3} 种错误"
    return detail or "未知验证错误"


def _replace_path_with_retry(
    source: Path,
    target: Path,
    *,
    attempts: int = 12,
    delay_seconds: float = 0.5,
) -> None:
    """容忍 Defender、缩略图和索引服务造成的短暂 Windows 目录锁。"""

    last_error: PermissionError | None = None
    for attempt in range(attempts):
        try:
            source.replace(target)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(delay_seconds)
    assert last_error is not None
    raise last_error


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
    progress_callback: Callable[[float], None] | None,
) -> list[VisualEvent]:
    from tennis_video_helper.vision import analyze_video

    return analyze_video(
        path,
        config,
        limit_duration=limit_duration,
        progress_callback=progress_callback,
    )


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
    config: AnalysisConfig,
) -> tuple[bool, str | None]:
    from tennis_video_helper.exporter import verify_clip

    return verify_clip(path, media, segment, config)


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
