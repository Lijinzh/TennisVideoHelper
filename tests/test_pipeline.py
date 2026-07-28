from dataclasses import replace
from pathlib import Path

import numpy as np

from tennis_video_helper.config import AnalysisConfig
from tennis_video_helper.models import AudioEvent, MediaInfo, VisualEvent
from tennis_video_helper.pipeline import (
    PipelineServices,
    _replace_output_dir,
    process_batch,
)


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


def test_replace_output_dir_retries_transient_permission_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "result"
    working = tmp_path / ".result.staging"
    output.mkdir()
    working.mkdir()
    (output / "old.txt").write_text("old", encoding="utf-8")
    (working / "new.txt").write_text("new", encoding="utf-8")
    original_replace = Path.replace
    attempts = 0

    def flaky_replace(path: Path, target: Path):
        nonlocal attempts
        if path == working and attempts < 2:
            attempts += 1
            raise PermissionError("temporary scanner lock")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    monkeypatch.setattr("tennis_video_helper.pipeline.time.sleep", lambda _delay: None)

    _replace_output_dir(working, output)

    assert attempts == 2
    assert (output / "new.txt").read_text(encoding="utf-8") == "new"
    assert not (output / "old.txt").exists()


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
        analyze_video=lambda path, config, limit_duration, progress: [
            VisualEvent(float(timestamp), 1.0, 1.0, 0.0)
            for timestamp in range(1, 14, 2)
        ],
        export_clip=lambda media, segment, target, config: exported_targets.append(target),
        verify_clip=lambda path, media, duration, config: (True, None),
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
        analyze_video=lambda _path, _config, _limit, _progress: [
            VisualEvent(float(timestamp), 1.0, 1.0, 0.0)
            for timestamp in range(1, 14, 2)
        ],
        export_clip=export_partial,
        verify_clip=lambda _path, _media, _duration, _config: (False, "验证失败"),
        write_reports=lambda *_args: None,
    )

    result = process_batch(source, output, AnalysisConfig(), services=services)

    record = result.results[0].records[0]
    assert record.verified is False
    assert not record.path.exists()


def test_process_batch_reports_monotonic_progress(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    updates = []

    def analyze(_path, _config, _limit, progress) -> list[VisualEvent]:
        progress(0.25)
        progress(0.75)
        progress(1.0)
        return []

    services = PipelineServices(
        scan_videos=lambda _: [source],
        probe_media=lambda _: _media(source),
        extract_audio=lambda _source, target, _sample_rate: target.touch(),
        load_audio=lambda _: (np.zeros(100, dtype=np.float32), 22_050),
        detect_audio_events=lambda *_args: [],
        analyze_video=analyze,
        export_clip=lambda *_args: None,
        verify_clip=lambda *_args: (True, None),
        write_reports=lambda *_args: None,
    )

    process_batch(
        source,
        tmp_path / "output",
        AnalysisConfig(),
        services=services,
        progress_callback=updates.append,
    )

    percentages = [update.percent for update in updates]
    assert percentages == sorted(percentages)
    assert percentages[-1] == 100.0
    assert any(update.phase == "GPU 分析画面" for update in updates)
    assert updates[-1].current_video == source
    assert updates[-1].phase == "全部任务完成"


def test_overwrite_replaces_old_result_only_after_success(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "output"
    old_output = output / source.stem
    old_output.mkdir(parents=True)
    (old_output / "old.txt").write_text("old", encoding="utf-8")

    def export_clip(_media, _segment, target: Path, _config) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"new")

    def write_reports(directory: Path, *_args) -> None:
        (directory / "new.txt").write_text("new", encoding="utf-8")

    services = PipelineServices(
        scan_videos=lambda _: [source],
        probe_media=lambda _: _media(source),
        extract_audio=lambda _source, target, _sample_rate: target.touch(),
        load_audio=lambda _: (np.zeros(100, dtype=np.float32), 22_050),
        detect_audio_events=lambda *_args: [
            AudioEvent(float(timestamp), 1.0, 10.0)
            for timestamp in range(1, 14, 2)
        ],
        analyze_video=lambda *_args: [
            VisualEvent(float(timestamp), 1.0, 1.0, 0.0)
            for timestamp in range(1, 14, 2)
        ],
        export_clip=export_clip,
        verify_clip=lambda *_args: (True, None),
        write_reports=write_reports,
    )

    result = process_batch(
        source,
        output,
        AnalysisConfig(overwrite_existing_output=True),
        services=services,
    )

    assert result.success_count == 1
    assert result.results[0].output_dir == old_output
    assert not (old_output / "old.txt").exists()
    assert (old_output / "new.txt").read_text(encoding="utf-8") == "new"
    assert all(
        record.path.parent == old_output / "clips"
        for record in result.results[0].records
    )
    assert not (output / "source_2").exists()
    assert not list(output.glob(".source.staging-*"))
    assert not list(output.glob(".source.backup-*"))


def test_overwrite_preserves_old_result_when_new_clip_fails_verification(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "output"
    old_output = output / source.stem
    old_output.mkdir(parents=True)
    marker = old_output / "old.txt"
    marker.write_text("keep", encoding="utf-8")

    def export_clip(_media, _segment, target: Path, _config) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"invalid")

    services = PipelineServices(
        scan_videos=lambda _: [source],
        probe_media=lambda _: _media(source),
        extract_audio=lambda _source, target, _sample_rate: target.touch(),
        load_audio=lambda _: (np.zeros(100, dtype=np.float32), 22_050),
        detect_audio_events=lambda *_args: [
            AudioEvent(float(timestamp), 1.0, 10.0)
            for timestamp in range(1, 14, 2)
        ],
        analyze_video=lambda *_args: [
            VisualEvent(float(timestamp), 1.0, 1.0, 0.0)
            for timestamp in range(1, 14, 2)
        ],
        export_clip=export_clip,
        verify_clip=lambda *_args: (False, "验证失败"),
        write_reports=lambda *_args: None,
    )

    result = process_batch(
        source,
        output,
        AnalysisConfig(overwrite_existing_output=True),
        services=services,
    )

    assert result.failure_count == 1
    assert "新结果有 1 个片段失败：验证失败" in (result.results[0].error or "")
    assert "旧结果已保留" in (result.results[0].error or "")
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not list(output.glob(".source.staging-*"))
    assert not list(output.glob(".source.backup-*"))
