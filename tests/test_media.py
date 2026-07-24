import json
from pathlib import Path
from subprocess import CompletedProcess

from tennis_video_helper.media import parse_probe_payload, probe_media, scan_videos


def test_parse_probe_payload_reads_video_audio_and_rotation(tmp_path: Path) -> None:
    video_path = tmp_path / "sample.mov"
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "profile": "Main 10",
                "codec_tag_string": "hvc1",
                "width": 1920,
                "height": 1080,
                "pix_fmt": "yuv420p10le",
                "avg_frame_rate": "60000/1001",
                "r_frame_rate": "60/1",
                "color_transfer": "smpte2084",
                "color_primaries": "bt2020",
                "color_space": "bt2020nc",
                "color_range": "tv",
                "tags": {"rotate": "90"},
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
            },
        ],
        "format": {"duration": "42.5", "size": "123456"},
    }

    media = parse_probe_payload(video_path, payload)

    assert media.path == video_path
    assert media.duration == 42.5
    assert media.width == 1920
    assert media.height == 1080
    assert media.fps == 60000 / 1001
    assert media.video_codec == "hevc"
    assert media.audio_codec == "aac"
    assert media.audio_sample_rate == 48_000
    assert media.rotation == 90
    assert media.is_hdr10 is True
    assert media.is_dolby_vision is False
    assert media.nominal_fps == 60.0
    assert media.is_variable_frame_rate is False
    assert media.color_primaries == "bt2020"
    assert media.color_space == "bt2020nc"
    assert media.color_range == "tv"
    assert media.video_profile == "Main 10"


def test_parse_probe_payload_marks_mixed_30_60_video_as_variable_frame_rate(
    tmp_path: Path,
) -> None:
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 3840,
                "height": 2160,
                "avg_frame_rate": "1865700381/40026554",
                "r_frame_rate": "30/1",
            }
        ],
        "format": {"duration": "1333.0"},
    }

    media = parse_probe_payload(tmp_path / "mixed.mp4", payload)

    assert media.fps > 46.0
    assert media.nominal_fps == 30.0
    assert media.is_variable_frame_rate is True


def test_parse_probe_payload_detects_dolby_vision(tmp_path: Path) -> None:
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "codec_tag_string": "dvhe",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30/1",
                "color_transfer": "arib-std-b67",
                "side_data_list": [
                    {
                        "side_data_type": "DOVI configuration record",
                        "dv_profile": 8,
                        "dv_bl_signal_compatibility_id": 4,
                    }
                ],
            }
        ],
        "format": {"duration": "5.0"},
    }

    media = parse_probe_payload(tmp_path / "dolby.mov", payload)

    assert media.is_dolby_vision is True
    assert media.dolby_vision_profile == 8
    assert media.dolby_vision_bl_compatibility_id == 4
    assert media.has_hlg_compatible_dolby_base_layer is True


def test_scan_videos_filters_supported_extensions_and_sorts(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (tmp_path / "b.MOV").touch()
    (tmp_path / "a.mp4").touch()
    (nested / "c.mkv").touch()
    (nested / "ignored.txt").touch()

    result = scan_videos(tmp_path)

    assert result == [tmp_path / "a.mp4", tmp_path / "b.MOV", nested / "c.mkv"]


def test_scan_videos_accepts_single_file(tmp_path: Path) -> None:
    video = tmp_path / "single.m4v"
    video.touch()

    assert scan_videos(video) == [video]


def test_probe_media_calls_ffprobe_with_argument_list(monkeypatch, tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.touch()
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1280,
                "height": 720,
                "avg_frame_rate": "30/1",
            }
        ],
        "format": {"duration": "3.0"},
    }
    captured: list[str] = []

    def fake_run(command, **kwargs):
        captured.extend(command)
        return CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr("tennis_video_helper.media.subprocess.run", fake_run)

    media = probe_media(video)

    assert captured[0] == "ffprobe"
    assert captured[-1] == str(video)
    assert media.duration == 3.0
