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


def test_fuse_events_keeps_moderate_aligned_audio_and_pose_as_support() -> None:
    events = fuse_events(
        [_audio(1.0, 0.327)],
        [_visual(1.05, 0.206)],
        AnalysisConfig(),
    )

    assert events[0].confidence >= AnalysisConfig().rally_support_threshold


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


def test_build_rally_segments_uses_support_events_to_keep_confirmed_rally_connected() -> None:
    events = [
        FusedEvent(15.42, 0.8, 0.2, 0.51, "支撑事件"),
        FusedEvent(17.71, 0.5, 0.3, 0.42, "支撑事件"),
        FusedEvent(18.57, 1.0, 0.9, 0.95, "强确认事件"),
        FusedEvent(20.81, 0.9, 0.4, 0.68, "强确认事件"),
        FusedEvent(22.94, 1.0, 0.0, 0.85, "强确认事件"),
        FusedEvent(25.35, 0.6, 0.1, 0.40, "支撑事件"),
        FusedEvent(27.29, 0.0, 1.0, 0.45, "支撑事件"),
    ]

    segments = build_rally_segments(events, media_duration=30.0, config=AnalysisConfig())

    assert len(segments) == 1
    assert segments[0].active_start == 15.42
    assert segments[0].active_end == 27.29
    assert segments[0].event_count == 7


def test_build_rally_segments_keeps_joint_evidence_across_slow_return_gaps() -> None:
    events = [
        FusedEvent(206.3, 0.7, 0.2, 0.46, "音画支撑"),
        FusedEvent(207.8, 0.8, 0.6, 0.80, "强确认"),
        FusedEvent(210.2, 0.0, 1.0, 0.45, "动作支撑"),
        FusedEvent(213.7, 0.6, 0.3, 0.50, "音画支撑"),
        FusedEvent(215.1, 0.5, 1.0, 0.75, "强确认"),
        FusedEvent(216.6, 0.7, 0.5, 0.70, "强确认"),
        FusedEvent(218.9, 0.0, 1.0, 0.45, "动作支撑"),
        FusedEvent(220.6, 0.5, 0.2, 0.50, "音画支撑"),
        FusedEvent(222.1, 1.0, 1.0, 0.95, "强确认"),
        FusedEvent(223.0, 0.6, 0.5, 0.65, "强确认"),
        FusedEvent(225.1, 1.0, 1.0, 0.95, "强确认"),
        FusedEvent(226.6, 0.7, 0.2, 0.50, "音画支撑"),
        FusedEvent(229.0, 0.3, 0.2, 0.41, "音画支撑"),
        FusedEvent(231.8, 0.7, 1.0, 0.85, "强确认"),
        FusedEvent(235.1, 0.9, 0.2, 0.70, "强确认"),
        FusedEvent(238.4, 0.9, 0.8, 0.90, "强确认"),
        FusedEvent(241.8, 0.5, 0.2, 0.50, "音画支撑"),
        FusedEvent(244.2, 0.6, 1.0, 0.80, "强确认"),
        FusedEvent(247.6, 0.6, 1.0, 0.80, "强确认"),
    ]

    segments = build_rally_segments(events, 300.0, AnalysisConfig())

    assert len(segments) == 1
    assert segments[0].active_start == 206.3
    assert segments[0].active_end == 247.6


def test_build_rally_segments_does_not_start_rally_from_support_events_only() -> None:
    events = [
        FusedEvent(float(timestamp), 0.0, 1.0, 0.45, "只有支撑事件")
        for timestamp in range(1, 14, 2)
    ]

    assert build_rally_segments(events, 30.0, AnalysisConfig()) == []


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
