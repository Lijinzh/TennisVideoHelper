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

VISUAL_MATCH_WINDOW = 0.3
PLAUSIBLE_HIT_INTERVAL = (0.35, 2.8)


def fuse_events(
    audio_events: list[AudioEvent],
    visual_events: list[VisualEvent],
    config: AnalysisConfig,
) -> list[FusedEvent]:
    """按时间对齐音频和视觉事件，并保留判定理由。"""

    fused: list[FusedEvent] = []
    matched_visual_indices: set[int] = set()
    previous_audio_time: float | None = None

    for audio_event in sorted(audio_events, key=lambda item: item.timestamp):
        match_index = _nearest_visual_index(
            audio_event.timestamp,
            visual_events,
            matched_visual_indices,
        )
        if match_index is not None:
            visual_event = visual_events[match_index]
            matched_visual_indices.add(match_index)
            confidence = min(
                1.0,
                0.55 * audio_event.confidence + 0.45 * visual_event.confidence,
            )
            reason = "音画共同确认近端击球"
            visual_confidence = visual_event.confidence
            timestamp = (audio_event.timestamp + visual_event.timestamp) / 2
        else:
            interval = (
                audio_event.timestamp - previous_audio_time
                if previous_audio_time is not None
                else None
            )
            has_visual_context = any(
                abs(visual.timestamp - audio_event.timestamp) <= config.end_silence
                for visual in visual_events
            )
            if (
                interval is not None
                and PLAUSIBLE_HIT_INTERVAL[0] <= interval <= PLAUSIBLE_HIT_INTERVAL[1]
                and has_visual_context
            ):
                confidence = min(0.85, 0.65 * audio_event.confidence + 0.2)
                reason = "时间间隔合理的远端击球候选"
            else:
                confidence = 0.45 * audio_event.confidence
                reason = "缺少动作支持的孤立声音"
            visual_confidence = 0.0
            timestamp = audio_event.timestamp

        fused.append(
            FusedEvent(
                timestamp=timestamp,
                audio_confidence=audio_event.confidence,
                visual_confidence=visual_confidence,
                confidence=confidence,
                reason=reason,
            )
        )
        previous_audio_time = audio_event.timestamp

    for index, visual_event in enumerate(visual_events):
        if index in matched_visual_indices:
            continue
        fused.append(
            FusedEvent(
                timestamp=visual_event.timestamp,
                audio_confidence=0.0,
                visual_confidence=visual_event.confidence,
                confidence=0.45 * visual_event.confidence,
                reason="缺少声音支持的挥拍动作",
            )
        )

    return sorted(fused, key=lambda item: item.timestamp)


def build_rally_segments(
    events: list[FusedEvent],
    media_duration: float,
    config: AnalysisConfig,
) -> list[RallySegment]:
    """用强事件确认回合，并用支撑事件维持满足时长阈值的连续区间。"""

    supported = sorted(
        (
            event
            for event in events
            if event.confidence >= config.rally_support_threshold
        ),
        key=lambda item: item.timestamp,
    )
    if not supported:
        return []

    groups: list[list[FusedEvent]] = [[supported[0]]]
    for event in supported[1:]:
        if event.timestamp - groups[-1][-1].timestamp <= config.end_silence:
            groups[-1].append(event)
        else:
            groups.append([event])

    groups = _merge_event_groups(groups, config.merge_gap)
    segments: list[RallySegment] = []
    for group in groups:
        confirmation_count = sum(
            event.confidence >= config.fusion_threshold for event in group
        )
        if confirmation_count < 2:
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


def _merge_event_groups(
    groups: list[list[FusedEvent]],
    merge_gap: float,
) -> list[list[FusedEvent]]:
    if not groups:
        return []
    merged = [groups[0][:]]
    for group in groups[1:]:
        if group[0].timestamp - merged[-1][-1].timestamp <= merge_gap:
            merged[-1].extend(group)
        else:
            merged.append(group[:])
    return merged
