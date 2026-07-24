from tennis_video_helper.config import AnalysisConfig
from tennis_video_helper.fusion import build_rally_segments, fuse_events
from tennis_video_helper.models import AudioEvent, FusedEvent, VisualEvent


def _audio(timestamp: float, confidence: float = 1.0) -> AudioEvent:
    return AudioEvent(timestamp=timestamp, confidence=confidence, strength=10.0)


def _visual(timestamp: float, confidence: float = 1.0) -> VisualEvent:
    return VisualEvent(
        timestamp=timestamp,
        confidence=confidence,
        motion_score=confidence,
        global_motion=0.0,
    )


def test_fuse_events_gives_high_score_to_aligned_audio_and_visual() -> None:
    events = fuse_events([_audio(1.0)], [_visual(1.15)], AnalysisConfig())

    assert len(events) == 1
    assert events[0].confidence >= 0.9
    assert events[0].reason == "音画共同确认近端击球"


def test_fuse_events_keeps_plausibly_timed_remote_audio_hits() -> None:
    audio = [_audio(1.0), _audio(2.2), _audio(3.4)]
    visual = [_visual(1.0)]

    events = fuse_events(audio, visual, AnalysisConfig())

    assert events[0].confidence >= 0.9
    assert events[1].confidence >= 0.6
    assert events[2].confidence >= 0.6
    assert events[1].reason == "时间间隔合理的远端击球候选"


def test_fuse_events_marks_isolated_background_audio_as_low_confidence() -> None:
    events = fuse_events([_audio(5.0, 0.7)], [], AnalysisConfig())

    assert events[0].confidence < AnalysisConfig().fusion_threshold


def test_periodic_background_audio_without_visual_context_cannot_form_rally() -> None:
    audio = [_audio(float(timestamp)) for timestamp in range(1, 14)]

    fused = fuse_events(audio, [], AnalysisConfig())
    segments = build_rally_segments(fused, 30.0, AnalysisConfig())

    assert all(event.confidence < AnalysisConfig().fusion_threshold for event in fused)
    assert segments == []


def test_build_rally_segments_keeps_twelve_second_sequence_with_buffers() -> None:
    events = [
        FusedEvent(
            timestamp=float(timestamp),
            audio_confidence=1.0,
            visual_confidence=0.8,
            confidence=0.9,
            reason="测试",
        )
        for timestamp in range(1, 14, 2)
    ]

    segments = build_rally_segments(events, media_duration=30.0, config=AnalysisConfig())

    assert len(segments) == 1
    assert segments[0].active_duration == 12.0
    assert segments[0].output_start == 0.0
    assert segments[0].output_end == 16.0


def test_build_rally_segments_filters_eight_second_sequence() -> None:
    events = [
        FusedEvent(float(timestamp), 1.0, 0.8, 0.9, "测试")
        for timestamp in range(1, 10, 2)
    ]

    assert build_rally_segments(events, 30.0, AnalysisConfig()) == []


def test_build_rally_segments_clamps_post_roll_to_video_duration() -> None:
    config = AnalysisConfig(min_rally_duration=4.0)
    events = [
        FusedEvent(float(timestamp), 1.0, 0.8, 0.9, "测试")
        for timestamp in (14, 16, 18)
    ]

    segments = build_rally_segments(events, media_duration=20.0, config=config)

    assert segments[0].output_end == 20.0
