from dataclasses import replace
from pathlib import Path

import numpy as np

from tennis_video_helper.config import AnalysisConfig
from tennis_video_helper.models import AudioEvent, MediaInfo, VisualEvent
from tennis_video_helper.pipeline import PipelineServices, process_batch


def _media(path: Path, *, audio: bool = True) -> MediaInfo:
    return MediaInfo(
        path=path,
        duration=30.0,
        width=1920,
        height=1080,
        fps=30.0,
        video_codec="h264",
        pixel_format="yuv420p",
        audio_codec="aac" if audio else None,
        audio_sample_rate=48_000 if audio else None,
        audio_channels=2 if audio else None,
        rotation=0,
        color_transfer=None,
        is_hdr10=False,
        is_dolby_vision=False,
    )


def test_process_batch_continues_after_one_video_fails(tmp_path: Path) -> None:
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    output = tmp_path / "output"
    exported_targets: list[Path] = []
    reports: list[Path] = []

    def probe(path: Path) -> MediaInfo:
        if path == second:
            raise RuntimeError("损坏视频")
        return _media(path)

    services = PipelineServices(
        scan_videos=lambda _: [first, second],
        probe_media=probe,
        extract_audio=lambda source, target, sample_rate: target.touch(),
        load_audio=lambda _: (np.zeros(100, dtype=np.float32), 22_050),
        detect_audio_events=lambda samples, sample_rate, config: [
            AudioEvent(float(timestamp), 1.0, 10.0)
            for timestamp in range(1, 14, 2)
        ],
        analyze_video=lambda path, config, limit_duration: [
            VisualEvent(float(timestamp), 1.0, 1.0, 0.0)
            for timestamp in range(1, 14, 2)
        ],
        export_clip=lambda media, segment, target, config: exported_targets.append(target),
        verify_clip=lambda path, media, duration: (True, None),
        write_reports=lambda directory, media, records, audio, visual, fused: reports.append(directory),
    )

    result = process_batch(first.parent, output, AnalysisConfig(), services=services)

    assert result.success_count == 1
    assert result.failure_count == 1
    assert exported_targets
    assert all(output in target.parents for target in exported_targets)
    assert all(target not in (first, second) for target in exported_targets)
    assert reports == [result.results[0].output_dir]


def test_process_batch_rejects_video_without_audio(tmp_path: Path) -> None:
    source = tmp_path / "silent.mp4"
    services = PipelineServices.defaults()
    services = services.replace(
        scan_videos=lambda _: [source],
        probe_media=lambda _: _media(source, audio=False),
    )

    result = process_batch(source, tmp_path / "output", AnalysisConfig(), services=services)

    assert result.failure_count == 1
    assert "没有音轨" in (result.results[0].error or "")


def test_process_batch_allows_profile_84_hlg_base_layer(tmp_path: Path) -> None:
    source = tmp_path / "profile84.mov"
    media = replace(
        _media(source),
        pixel_format="yuv420p10le",
        color_transfer="arib-std-b67",
        is_dolby_vision=True,
        dolby_vision_profile=8,
        dolby_vision_bl_compatibility_id=4,
    )
    services = PipelineServices(
        scan_videos=lambda _: [source],
        probe_media=lambda _: media,
        extract_audio=lambda _source, target, _sample_rate: target.touch(),
        load_audio=lambda _: (np.zeros(100, dtype=np.float32), 22_050),
        detect_audio_events=lambda *_args: [],
        analyze_video=lambda *_args: [],
        export_clip=lambda *_args: None,
        verify_clip=lambda *_args: (True, None),
        write_reports=lambda *_args: None,
    )

    result = process_batch(source, tmp_path / "output", AnalysisConfig(), services=services)

    assert result.success_count == 1


def test_process_batch_rejects_unsupported_dolby_vision(tmp_path: Path) -> None:
    source = tmp_path / "dolby.mov"
    services = PipelineServices.defaults().replace(
        scan_videos=lambda _: [source],
        probe_media=lambda _: replace(_media(source), is_dolby_vision=True),
    )

    result = process_batch(source, tmp_path / "output", AnalysisConfig(), services=services)

    assert result.failure_count == 1
    assert "Dolby Vision" in (result.results[0].error or "")


def test_process_batch_removes_clip_that_fails_verification(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "output"

    def export_partial(_media, _segment, target: Path, _config) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"invalid")

    services = PipelineServices(
        scan_videos=lambda _: [source],
        probe_media=lambda _: _media(source),
        extract_audio=lambda _source, target, _sample_rate: target.touch(),
        load_audio=lambda _: (np.zeros(100, dtype=np.float32), 22_050),
        detect_audio_events=lambda _samples, _sample_rate, _config: [
            AudioEvent(float(timestamp), 1.0, 10.0)
            for timestamp in range(1, 14, 2)
        ],
        analyze_video=lambda _path, _config, _limit: [
            VisualEvent(float(timestamp), 1.0, 1.0, 0.0)
            for timestamp in range(1, 14, 2)
        ],
        export_clip=export_partial,
        verify_clip=lambda _path, _media, _duration: (False, "验证失败"),
        write_reports=lambda *_args: None,
    )

    result = process_batch(source, output, AnalysisConfig(), services=services)

    record = result.results[0].records[0]
    assert record.verified is False
    assert not record.path.exists()
