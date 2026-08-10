from tennis_video_helper.config import AnalysisConfig
from tennis_video_helper.fusion import build_rally_segments, fuse_events, is_confirmed_hit
from tennis_video_helper.models import AudioEvent, FusedEvent, VisualEvent


def _audio(
    timestamp: float,
    confidence: float = 1.0,
    *,
    impact_score: float = 1.0,
) -> AudioEvent:
    return AudioEvent(
        timestamp=timestamp,
        confidence=confidence,
        strength=10.0,
        impact_score=impact_score,
    )


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


def test_two_handed_backhand_uses_wider_audio_alignment_window() -> None:
    backhand = VisualEvent(
        timestamp=1.60,
        confidence=0.9,
        motion_score=0.9,
        global_motion=0.0,
        arm_motion_score=0.9,
        stroke_type="双手挥拍",
        racket_confidence=0.5,
    )
    forehand = VisualEvent(
        timestamp=1.60,
        confidence=0.9,
        motion_score=0.9,
        global_motion=0.0,
        arm_motion_score=0.9,
        stroke_type="右手单手挥拍",
        racket_confidence=0.5,
    )

    matched_backhand = fuse_events([_audio(1.0)], [backhand], AnalysisConfig())
    unmatched_forehand = fuse_events([_audio(1.0)], [forehand], AnalysisConfig())

    assert len(matched_backhand) == 1
    assert matched_backhand[0].reason == "音画共同确认近端击球"
    assert len(unmatched_forehand) == 2


def test_ball_hit_sound_wins_over_earlier_footstep_near_same_swing() -> None:
    events = fuse_events(
        [
            _audio(9.70, 0.95, impact_score=0.10),
            _audio(10.06, 0.72, impact_score=0.95),
        ],
        [_visual(10.0)],
        AnalysisConfig(),
    )

    paired = next(event for event in events if event.visual_confidence > 0)
    footstep = next(event for event in events if event.visual_confidence == 0)
    assert paired.timestamp == 10.06
    assert paired.audio_impact_score == 0.95
    assert is_confirmed_hit(paired, AnalysisConfig()) is True
    assert footstep.timestamp == 9.70
    assert is_confirmed_hit(footstep, AnalysisConfig()) is False


def test_clean_hit_sound_and_racket_allow_smaller_real_swing() -> None:
    supported_swing = FusedEvent(
        timestamp=5.0,
        audio_confidence=0.8,
        visual_confidence=0.8,
        confidence=0.9,
        reason="清晰击球声与球拍共同确认",
        visual_arm_motion_score=0.70,
        audio_impact_score=0.9,
        visual_racket_confidence=0.6,
    )
    footstep_swing = FusedEvent(
        timestamp=5.0,
        audio_confidence=0.9,
        visual_confidence=0.8,
        confidence=0.9,
        reason="踏地声靠近普通摆臂",
        visual_arm_motion_score=0.70,
        audio_impact_score=0.1,
        visual_racket_confidence=0.6,
    )

    assert is_confirmed_hit(supported_swing, AnalysisConfig()) is True
    assert is_confirmed_hit(footstep_swing, AnalysisConfig()) is False


def test_fuse_events_keeps_moderate_aligned_audio_and_pose_as_support() -> None:
    events = fuse_events(
        [_audio(1.0, 0.327)],
        [_visual(1.05, 0.206)],
        AnalysisConfig(),
    )

    assert events[0].confidence >= AnalysisConfig().rally_support_threshold


def test_fuse_events_keeps_remote_audio_below_rally_support_threshold() -> None:
    audio = [_audio(1.0), _audio(2.2), _audio(3.4)]
    visual = [_visual(1.0)]

    events = fuse_events(audio, visual, AnalysisConfig())

    assert events[0].confidence >= 0.9
    assert events[1].confidence < AnalysisConfig().rally_support_threshold
    assert events[2].confidence < AnalysisConfig().rally_support_threshold
    assert events[1].reason == "声音候选（未通过骨架确认）"


def test_fuse_events_does_not_promote_audio_before_later_visual_context() -> None:
    events = fuse_events(
        [_audio(1.0), _audio(2.2)],
        [_visual(3.0)],
        AnalysisConfig(),
    )

    first_audio_event = next(event for event in events if event.timestamp == 1.0)
    assert first_audio_event.confidence < AnalysisConfig().rally_support_threshold
    assert first_audio_event.reason == "声音候选（未通过骨架确认）"


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
        FusedEvent(14.0, 0.8, 0.0, 0.28, "前置声音候选"),
        FusedEvent(15.0, 0.8, 0.8, 0.90, "骨架强确认"),
        FusedEvent(18.0, 0.9, 0.7, 0.88, "骨架强确认"),
        FusedEvent(21.0, 0.8, 0.0, 0.28, "对手回球声"),
        FusedEvent(23.5, 0.7, 0.0, 0.27, "对手回球声"),
        FusedEvent(25.0, 0.8, 0.9, 0.94, "骨架强确认"),
        FusedEvent(28.0, 0.9, 0.0, 0.28, "后置声音候选"),
    ]

    segments = build_rally_segments(events, media_duration=30.0, config=AnalysisConfig())

    assert len(segments) == 1
    assert segments[0].active_start == 15.0
    assert segments[0].active_end == 25.0
    assert segments[0].event_count == 3


def test_midcourt_racket_action_bridges_occasional_missed_hit() -> None:
    events = [
        FusedEvent(1.0, 0.9, 0.9, 0.95, "底线确认击球"),
        FusedEvent(4.0, 0.8, 0.9, 0.92, "底线确认击球"),
        FusedEvent(
            7.5,
            0.0,
            0.9,
            0.75,
            "移动到中场时声音漏检的双反",
            visual_arm_motion_score=0.9,
            visual_stroke_type="双手挥拍",
            audio_impact_score=0.0,
            visual_racket_confidence=0.5,
        ),
        FusedEvent(11.0, 0.9, 0.9, 0.95, "中场确认击球"),
    ]

    segments = build_rally_segments(events, 20.0, AnalysisConfig())

    assert len(segments) == 1
    assert segments[0].active_start == 1.0
    assert segments[0].active_end == 11.0


def test_long_gap_without_audio_or_racket_support_still_splits_rally() -> None:
    events = [
        FusedEvent(1.0, 0.9, 0.9, 0.95, "确认击球"),
        FusedEvent(4.0, 0.9, 0.9, 0.95, "确认击球"),
        FusedEvent(11.0, 0.9, 0.9, 0.95, "下一段确认击球"),
    ]

    assert build_rally_segments(events, 20.0, AnalysisConfig()) == []


def test_build_rally_segments_keeps_joint_evidence_across_slow_return_gaps() -> None:
    events = [
        FusedEvent(206.3, 0.7, 0.2, 0.46, "音画支撑"),
        FusedEvent(207.8, 0.8, 0.6, 0.80, "强确认"),
        FusedEvent(
            210.2,
            0.0,
            1.0,
            0.45,
            "动作支撑",
            visual_racket_confidence=0.0,
        ),
        FusedEvent(213.7, 0.6, 0.3, 0.50, "音画支撑"),
        FusedEvent(215.1, 0.5, 1.0, 0.75, "强确认"),
        FusedEvent(216.6, 0.7, 0.5, 0.70, "强确认"),
        FusedEvent(
            218.9,
            0.0,
            1.0,
            0.45,
            "动作支撑",
            visual_racket_confidence=0.0,
        ),
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
    assert segments[0].active_start == 215.1
    assert segments[0].active_end == 247.6


def test_build_rally_segments_does_not_start_rally_from_support_events_only() -> None:
    events = [
        FusedEvent(float(timestamp), 0.0, 1.0, 0.45, "只有支撑事件")
        for timestamp in range(1, 14, 2)
    ]

    assert build_rally_segments(events, 30.0, AnalysisConfig()) == []


def test_build_rally_segments_requires_multiple_sound_aligned_strong_swings() -> None:
    events = [
        FusedEvent(
            float(timestamp),
            0.8 if timestamp in (1, 7) else 0.0,
            0.9,
            0.75,
            "走路持拍摆臂",
            visual_arm_motion_score=1.0,
        )
        for timestamp in range(1, 14, 2)
    ]

    assert build_rally_segments(events, 30.0, AnalysisConfig()) == []


def test_build_rally_segments_keeps_three_confirmed_hits() -> None:
    events = [
        FusedEvent(1.0, 0.8, 0.9, 0.75, "音画一致强挥拍"),
        FusedEvent(4.0, 0.5, 0.0, 0.25, "对手回球声"),
        FusedEvent(7.0, 0.8, 0.9, 0.75, "音画一致强挥拍"),
        FusedEvent(10.0, 0.5, 0.0, 0.25, "对手回球声"),
        FusedEvent(13.0, 0.8, 0.9, 0.75, "音画一致强挥拍"),
    ]

    assert len(build_rally_segments(events, 30.0, AnalysisConfig())) == 1


def test_unaligned_visual_motion_cannot_extend_confirmed_rally_boundaries() -> None:
    events = [
        FusedEvent(1.0, 0.0, 1.0, 0.8, "走路摆臂"),
        FusedEvent(5.0, 1.0, 1.0, 0.95, "音画共同确认近端击球"),
        FusedEvent(8.0, 1.0, 1.0, 0.95, "音画共同确认近端击球"),
        FusedEvent(11.0, 1.0, 1.0, 0.95, "音画共同确认近端击球"),
        FusedEvent(15.0, 0.0, 1.0, 0.8, "走路摆臂"),
    ]

    segments = build_rally_segments(
        events,
        30.0,
        AnalysisConfig(min_rally_duration=6.0),
    )

    assert len(segments) == 1
    assert segments[0].active_start == 5.0
    assert segments[0].active_end == 11.0
    assert segments[0].event_count == 3


def test_right_handed_mode_rejects_left_only_swings_but_keeps_two_handed() -> None:
    left_only = FusedEvent(
        1.0,
        1.0,
        1.0,
        0.95,
        "音画共同确认近端击球",
        visual_stroke_type="左手单手挥拍",
    )
    two_handed = FusedEvent(
        1.0,
        1.0,
        1.0,
        0.95,
        "音画共同确认近端击球",
        visual_stroke_type="双手挥拍",
    )

    assert is_confirmed_hit(left_only, AnalysisConfig()) is False
    assert is_confirmed_hit(two_handed, AnalysisConfig()) is True
    assert is_confirmed_hit(
        left_only,
        AnalysisConfig(player_handedness="auto"),
    ) is True


def test_build_rally_segments_rejects_repeated_talking_gestures() -> None:
    events = [
        FusedEvent(
            float(timestamp),
            0.4 if timestamp == 7 else 0.0,
            0.9,
            0.9,
            "站立讲话手势",
            visual_arm_motion_score=0.80,
        )
        for timestamp in range(1, 14, 2)
    ]

    assert build_rally_segments(events, 30.0, AnalysisConfig()) == []


def test_build_rally_segments_requires_nontrivial_audio_on_strong_swing() -> None:
    events = [
        FusedEvent(
            float(timestamp),
            0.05 if timestamp == 7 else 0.0,
            0.9,
            0.9,
            "强动作但声音过弱",
            visual_arm_motion_score=1.0,
        )
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
