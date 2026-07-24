import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from tennis_video_helper.config import AnalysisConfig
from tennis_video_helper.exporter import (
    ExportError,
    build_ffmpeg_command,
    export_clip,
    verify_clip,
)
from tennis_video_helper.models import (
    AudioEvent,
    ClipRecord,
    FusedEvent,
    MediaInfo,
    RallySegment,
    VisualEvent,
)
from tennis_video_helper.report import write_reports


def _media(tmp_path: Path, *, hdr10: bool = False, dolby: bool = False) -> MediaInfo:
    return MediaInfo(
        path=tmp_path / "source.mp4",
        duration=60.0,
        width=1920,
        height=1080,
        fps=60.0,
        video_codec="hevc",
        pixel_format="yuv420p10le" if hdr10 else "yuv420p",
        audio_codec="aac",
        audio_sample_rate=48_000,
        audio_channels=2,
        rotation=0,
        color_transfer="smpte2084" if hdr10 else None,
        is_hdr10=hdr10,
        is_dolby_vision=dolby,
    )


def _segment() -> RallySegment:
    return RallySegment(10.0, 22.0, 8.0, 25.0, 12.0, 0.88, 9)


def test_build_ffmpeg_command_preserves_resolution_and_frame_rate(tmp_path: Path) -> None:
    target = tmp_path / "clip.mp4"

    command = build_ffmpeg_command(
        _media(tmp_path),
        _segment(),
        target,
        AnalysisConfig(),
    )

    assert "hevc_nvenc" in command
    assert "-vf" not in command
    assert "-r" not in command
    assert command[command.index("-fps_mode:v:0") + 1] == "passthrough"
    assert command[command.index("-enc_time_base:v:0") + 1] == "-1"
    assert command[command.index("-ss") + 1] == "8.000"
    assert command[command.index("-t") + 1] == "17.000"
    assert command[-1] == str(target)


def test_build_ffmpeg_command_uses_main10_for_hdr10(tmp_path: Path) -> None:
    command = build_ffmpeg_command(
        _media(tmp_path, hdr10=True),
        _segment(),
        tmp_path / "hdr.mp4",
        AnalysisConfig(),
    )

    assert command[command.index("-pix_fmt") + 1] == "p010le"
    assert command[command.index("-profile:v") + 1] == "main10"


def test_build_ffmpeg_command_preserves_rotation_metadata(tmp_path: Path) -> None:
    media = replace(_media(tmp_path), rotation=90)

    command = build_ffmpeg_command(
        media,
        _segment(),
        tmp_path / "rotated.mp4",
        AnalysisConfig(),
    )

    assert "-noautorotate" in command
    assert command[command.index("-metadata:s:v:0") + 1] == "rotate=90"


def test_export_clip_remuxes_display_matrix_for_rotated_video(
    monkeypatch,
    tmp_path: Path,
) -> None:
    media = replace(_media(tmp_path), rotation=270)
    target = tmp_path / "rotated.mp4"
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"encoded")
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("tennis_video_helper.exporter.subprocess.run", fake_run)

    export_clip(media, _segment(), target, AnalysisConfig())

    assert len(commands) == 2
    assert commands[1][commands[1].index("-display_rotation:v:0") + 1] == "-90"
    assert commands[1][commands[1].index("-c") + 1] == "copy"
    assert commands[1][-1] != str(target)
    assert target.read_bytes() == b"encoded"


def test_export_clip_removes_partial_staging_file_after_ffmpeg_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "failed.mp4"

    def fail_after_partial_write(command, **_kwargs):
        Path(command[-1]).write_bytes(b"partial")
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr("tennis_video_helper.exporter.subprocess.run", fail_after_partial_write)

    with pytest.raises(ExportError, match="NVENC 输出失败"):
        export_clip(_media(tmp_path), _segment(), target, AnalysisConfig())

    assert not target.exists()
    assert not list(tmp_path.glob(".*.staging.mp4"))


def test_build_ffmpeg_command_rejects_dolby_vision(tmp_path: Path) -> None:
    with pytest.raises(ExportError, match="Dolby Vision"):
        build_ffmpeg_command(
            _media(tmp_path, dolby=True),
            _segment(),
            tmp_path / "dolby.mp4",
            AnalysisConfig(),
        )


def test_write_reports_creates_csv_and_json(tmp_path: Path) -> None:
    media = _media(tmp_path)
    record = ClipRecord(
        index=1,
        path=tmp_path / "clips" / "rally_001.mp4",
        segment=_segment(),
        verified=True,
        error=None,
    )

    audio_events = [AudioEvent(11.0, 0.9, 12.0), AudioEvent(30.0, 0.7, 8.0)]
    visual_events = [VisualEvent(11.1, 0.8, 0.6, 0.1)]
    fused_events = [FusedEvent(11.05, 0.9, 0.8, 0.86, "音画共同确认近端击球")]

    write_reports(
        tmp_path,
        media,
        [record],
        audio_events,
        visual_events,
        fused_events,
    )

    csv_text = (tmp_path / "segments.csv").read_text(encoding="utf-8-sig")
    payload = json.loads((tmp_path / "analysis.json").read_text(encoding="utf-8"))
    assert "rally_001.mp4" in csv_text
    assert payload["source"]["width"] == 1920
    assert payload["clips"][0]["verified"] is True
    assert payload["audio_events"][0]["strength"] == 12.0
    assert payload["audio_events"][0]["source"] == "audio"
    assert payload["visual_events"][0]["motion_score"] == 0.6
    assert payload["visual_events"][0]["source"] == "visual"
    assert payload["fused_events"][0]["reason"] == "音画共同确认近端击球"
    assert payload["fused_events"][0]["source"] == "audio_visual"
    assert "audio_event_count" in csv_text
    assert "visual_event_count" in csv_text
    assert ",1,1," in csv_text


def test_verify_clip_accepts_segment_specific_average_fps_for_vfr_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = replace(_media(tmp_path), fps=46.6, is_variable_frame_rate=True)
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"encoded")
    clip_media = replace(source, path=output, duration=17.0, fps=60.0)

    monkeypatch.setattr("tennis_video_helper.exporter.probe_media", lambda _path: clip_media)
    monkeypatch.setattr(
        "tennis_video_helper.exporter._probe_frame_timestamps",
        lambda path, start, duration: [0.0, 1 / 30, 2 / 30, 3 / 30],
    )
    monkeypatch.setattr(
        "tennis_video_helper.exporter.subprocess.run",
        lambda *args, **kwargs: type("Result", (), {"returncode": 0})(),
    )

    verified, error = verify_clip(output, source, _segment())

    assert verified is True
    assert error is None


def test_verify_clip_rejects_wrong_pixel_format(monkeypatch, tmp_path: Path) -> None:
    source = _media(tmp_path)
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"encoded")
    clip_media = replace(source, path=output, duration=17.0, pixel_format="yuv444p")

    monkeypatch.setattr("tennis_video_helper.exporter.probe_media", lambda _path: clip_media)

    verified, error = verify_clip(output, source, _segment())

    assert verified is False
    assert error == "输出像素格式与源视频策略不一致"


def test_verify_clip_rejects_changed_fps_for_cfr_source(monkeypatch, tmp_path: Path) -> None:
    source = _media(tmp_path)
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"encoded")
    clip_media = replace(source, path=output, duration=17.0, fps=30.0)

    monkeypatch.setattr("tennis_video_helper.exporter.probe_media", lambda _path: clip_media)

    verified, error = verify_clip(output, source, _segment())

    assert verified is False
    assert error == "输出帧率与源视频不一致"


def test_verify_clip_rejects_changed_hdr_transfer_function(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = replace(
        _media(tmp_path, hdr10=True),
        color_primaries="bt2020",
        color_space="bt2020nc",
        color_range="tv",
    )
    output = tmp_path / "hdr.mp4"
    output.write_bytes(b"encoded")
    clip_media = replace(
        source,
        path=output,
        duration=17.0,
        pixel_format="yuv420p10le",
        video_profile="Main 10",
        color_transfer="bt709",
    )

    monkeypatch.setattr("tennis_video_helper.exporter.probe_media", lambda _path: clip_media)

    verified, error = verify_clip(output, source, _segment())

    assert verified is False
    assert error == "输出传递函数与源视频不一致"


def test_verify_clip_rejects_vfr_source_flattened_to_cfr(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = replace(_media(tmp_path), fps=45.0, is_variable_frame_rate=True)
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"encoded")
    clip_media = replace(source, path=output, duration=17.0, fps=30.0)
    source_timestamps = [0.0, 1 / 60, 2 / 60, 3 / 60, 4 / 60, 4 / 60 + 1 / 30]
    output_timestamps = [0.0, 1 / 30, 2 / 30, 3 / 30, 4 / 30, 5 / 30]

    monkeypatch.setattr("tennis_video_helper.exporter.probe_media", lambda _path: clip_media)
    monkeypatch.setattr(
        "tennis_video_helper.exporter._probe_frame_timestamps",
        lambda path, start, duration: (
            source_timestamps if path == source.path else output_timestamps
        ),
    )

    verified, error = verify_clip(output, source, _segment())

    assert verified is False
    assert error == "输出可变帧率时间关系与源片段不一致"
