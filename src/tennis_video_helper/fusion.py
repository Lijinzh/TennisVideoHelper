"""音画事件融合与长回合区间生成。"""

from __future__ import annotations

from statistics import fmean

from tennis_video_helper.config import AnalysisConfig
from tennis_video_helper.models import (
    AudioEvent,
    FusedEvent,
    RallySegment,
    VisualEvent,
)

VISUAL_MATCH_WINDOW = 0.45
VISUAL_CONFIRMATION_THRESHOLD = 0.30
MAX_VISUAL_ANCHOR_GAP_FACTOR = 2.0
STRONG_SWING_ARM_MOTION = 0.85
MIN_STRONG_SWING_AUDIO_CONFIDENCE = 0.10


def fuse_events(
    audio_events: list[AudioEvent],
    visual_events: list[VisualEvent],
    config: AnalysisConfig,
) -> list[FusedEvent]:
    """按时间对齐音频和视觉事件，并保留判定理由。"""

    fused: list[FusedEvent] = []
    matched_visual_indices: set[int] = set()
    ordered_visual_events = sorted(visual_events, key=lambda item: item.timestamp)
    ordered_audio_events = sorted(audio_events, key=lambda item: item.timestamp)
    for audio_event in ordered_audio_events:
        match_index = _nearest_visual_index(
            audio_event.timestamp,
            ordered_visual_events,
            matched_visual_indices,
        )
        if match_index is not None:
            visual_event = ordered_visual_events[match_index]
            matched_visual_indices.add(match_index)
            audio_evidence = (
                config.aligned_audio_reliability * audio_event.confidence
            )
            visual_evidence = (
                config.aligned_visual_reliability * visual_event.confidence
            )
            confidence = min(
                1.0,
                1.0 - (1.0 - audio_evidence) * (1.0 - visual_evidence),
            )
            reason = "音画共同确认近端击球"
            visual_confidence = visual_event.confidence
            visual_arm_motion_score = visual_event.arm_motion_score
            timestamp = (audio_event.timestamp + visual_event.timestamp) / 2
        else:
            # 未经骨架确认的声音只能作为候选，不能独立启动或延长回合。
            confidence = min(
                config.rally_support_threshold * 0.75,
                0.18 + 0.12 * audio_event.confidence,
            )
            reason = "声音候选（未通过骨架确认）"
            visual_confidence = 0.0
            visual_arm_motion_score = 0.0
            timestamp = audio_event.timestamp

        fused.append(
            FusedEvent(
                timestamp=timestamp,
                audio_confidence=audio_event.confidence,
                visual_confidence=visual_confidence,
                confidence=confidence,
                reason=reason,
                visual_arm_motion_score=visual_arm_motion_score,
            )
        )
    for index, visual_event in enumerate(ordered_visual_events):
        if index in matched_visual_indices:
            continue
        fused.append(
            FusedEvent(
                timestamp=visual_event.timestamp,
                audio_confidence=0.0,
                visual_confidence=visual_event.confidence,
                confidence=min(0.8, 0.35 + 0.45 * visual_event.confidence),
                reason="骨架时序确认挥拍（缺少击球声支持）",
                visual_arm_motion_score=visual_event.arm_motion_score,
            )
        )

    return sorted(fused, key=lambda item: item.timestamp)


def build_rally_segments(
    events: list[FusedEvent],
    media_duration: float,
    config: AnalysisConfig,
) -> list[RallySegment]:
    """仅用骨架确认挥拍确定边界，声音只桥接两个视觉锚点。"""

    ordered_events = sorted(events, key=lambda item: item.timestamp)
    visual_anchors = [
        event
        for event in ordered_events
        if event.visual_confidence >= VISUAL_CONFIRMATION_THRESHOLD
        and event.confidence >= config.rally_support_threshold
    ]
    if not visual_anchors:
        return []

    groups: list[list[FusedEvent]] = [[visual_anchors[0]]]
    for anchor in visual_anchors[1:]:
        if _visual_anchors_connected(
            groups[-1][-1],
            anchor,
            ordered_events,
            config,
        ):
            groups[-1].append(anchor)
        else:
            groups.append([anchor])

    segments: list[RallySegment] = []
    for group in groups:
        if len(group) < 2:
            continue
        confirmation_count = sum(
            event.confidence >= config.fusion_threshold for event in group
        )
        if confirmation_count < 2:
            continue
        strong_swings = [
            event
            for event in group
            if event.visual_confidence >= VISUAL_CONFIRMATION_THRESHOLD
            and event.visual_arm_motion_score >= STRONG_SWING_ARM_MOTION
        ]
        if len(strong_swings) < 2:
            continue
        if not any(
            event.audio_confidence >= MIN_STRONG_SWING_AUDIO_CONFIDENCE
            and event.visual_confidence >= VISUAL_CONFIRMATION_THRESHOLD
            for event in group
        ):
            continue
        active_start = group[0].timestamp
        active_end = group[-1].timestamp
        active_duration = active_end - active_start
        if active_duration < config.min_rally_duration:
            continue
        segments.append(
            RallySegment(
                active_start=active_start,
                active_end=active_end,
                output_start=max(0.0, active_start - config.pre_roll),
                output_end=min(media_duration, active_end + config.post_roll),
                active_duration=active_duration,
                average_confidence=fmean(event.confidence for event in group),
                event_count=len(group),
            )
        )
    return segments


def _nearest_visual_index(
    timestamp: float,
    visual_events: list[VisualEvent],
    used_indices: set[int],
) -> int | None:
    candidates = [
        (abs(event.timestamp - timestamp), index)
        for index, event in enumerate(visual_events)
        if index not in used_indices
        and abs(event.timestamp - timestamp) <= VISUAL_MATCH_WINDOW
    ]
    return min(candidates)[1] if candidates else None


def _visual_anchors_connected(
    previous: FusedEvent,
    current: FusedEvent,
    events: list[FusedEvent],
    config: AnalysisConfig,
) -> bool:
    gap = current.timestamp - previous.timestamp
    if gap <= config.end_silence:
        return True
    if gap > config.end_silence * MAX_VISUAL_ANCHOR_GAP_FACTOR:
        return False

    # 允许画面中的本方球员两次挥拍之间存在对手回球声，但两端必须都有骨架动作。
    bridge_times = [previous.timestamp]
    bridge_times.extend(
        event.timestamp
        for event in events
        if previous.timestamp < event.timestamp < current.timestamp
        and event.audio_confidence >= 0.25
    )
    bridge_times.append(current.timestamp)
    return len(bridge_times) > 2 and all(
        right - left <= config.end_silence
        for left, right in zip(bridge_times, bridge_times[1:])
    )
