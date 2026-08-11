"""音画事件融合与长回合区间生成。"""

from __future__ import annotations

from statistics import fmean

from tennis_video_helper.core.config import AnalysisConfig
from tennis_video_helper.core.models import (
    AudioEvent,
    FusedEvent,
    RallySegment,
    VisualEvent,
)

VISUAL_MATCH_WINDOW = 0.45
VISUAL_CONFIRMATION_THRESHOLD = 0.30
MAX_VISUAL_ANCHOR_GAP_FACTOR = 2.5
STRONG_SWING_ARM_MOTION = 0.85
SUPPORTED_SWING_ARM_MOTION = 0.65
MIN_CONFIRMED_HIT_AUDIO_CONFIDENCE = 0.25
STRONG_AUDIO_IMPACT_SCORE = 0.60
STRONG_AUDIO_CONFIDENCE = 0.55
CONTINUATION_AUDIO_IMPACT_SCORE = 0.30
CONTINUATION_VISUAL_ARM_MOTION = 0.50
MAX_TRAILING_CONTINUATION_SECONDS = 10.0


def fuse_events(
    audio_events: list[AudioEvent],
    visual_events: list[VisualEvent],
    config: AnalysisConfig,
) -> list[FusedEvent]:
    """按时间对齐音频和视觉事件，并保留判定理由。"""

    fused: list[FusedEvent] = []
    ordered_visual_events = sorted(visual_events, key=lambda item: item.timestamp)
    ordered_audio_events = sorted(audio_events, key=lambda item: item.timestamp)
    matched_audio_indices, matched_visual_indices = _match_audio_and_visual_events(
        ordered_audio_events,
        ordered_visual_events,
    )
    for audio_index, audio_event in enumerate(ordered_audio_events):
        match_index = matched_audio_indices.get(audio_index)
        if match_index is not None:
            visual_event = ordered_visual_events[match_index]
            audio_evidence = (
                config.aligned_audio_reliability * audio_event.confidence
                * (0.75 + 0.25 * audio_event.impact_score)
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
            visual_stroke_type = visual_event.stroke_type
            visual_racket_confidence = visual_event.racket_confidence
            timestamp = audio_event.timestamp
        else:
            # 未经骨架确认的声音只能作为候选，不能独立启动或延长回合。
            confidence = min(
                config.rally_support_threshold * 0.75,
                0.18 + 0.12 * audio_event.confidence,
            )
            reason = "声音候选（未通过骨架确认）"
            visual_confidence = 0.0
            visual_arm_motion_score = 0.0
            visual_stroke_type = "无骨架动作"
            visual_racket_confidence = 0.0
            timestamp = audio_event.timestamp

        fused.append(
            FusedEvent(
                timestamp=timestamp,
                audio_confidence=audio_event.confidence,
                visual_confidence=visual_confidence,
                confidence=confidence,
                reason=reason,
                visual_arm_motion_score=visual_arm_motion_score,
                visual_stroke_type=visual_stroke_type,
                audio_impact_score=audio_event.impact_score,
                visual_racket_confidence=visual_racket_confidence,
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
                visual_stroke_type=visual_event.stroke_type,
                audio_impact_score=0.0,
                visual_racket_confidence=visual_event.racket_confidence,
            )
        )

    return sorted(fused, key=lambda item: item.timestamp)


def build_rally_segments(
    events: list[FusedEvent],
    media_duration: float,
    config: AnalysisConfig,
) -> list[RallySegment]:
    """只用“声音候选 + 强骨架挥拍”确定击球点和回合边界。"""

    ordered_events = sorted(events, key=lambda item: item.timestamp)
    confirmed_hits = [
        event for event in ordered_events if is_confirmed_hit(event, config)
    ]
    if not confirmed_hits:
        return []

    groups: list[list[FusedEvent]] = [[confirmed_hits[0]]]
    for anchor in confirmed_hits[1:]:
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
        if len(group) < config.min_confirmed_hits:
            continue
        active_start = group[0].timestamp
        active_end = _extend_confirmed_rally_end(
            group[-1].timestamp,
            ordered_events,
            config,
        )
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


def is_confirmed_hit(event: FusedEvent, config: AnalysisConfig) -> bool:
    """声音只提出候选；球拍确认的强骨架挥拍负责最终判定。"""

    arm_motion_threshold = STRONG_SWING_ARM_MOTION
    if (
        event.audio_confidence >= STRONG_AUDIO_CONFIDENCE
        and event.audio_impact_score >= STRONG_AUDIO_IMPACT_SCORE
        and event.visual_racket_confidence >= 0.12
    ):
        arm_motion_threshold = SUPPORTED_SWING_ARM_MOTION
    return (
        event.audio_confidence >= MIN_CONFIRMED_HIT_AUDIO_CONFIDENCE
        and event.visual_confidence >= VISUAL_CONFIRMATION_THRESHOLD
        and event.visual_arm_motion_score >= arm_motion_threshold
        and event.confidence >= config.fusion_threshold
        and _stroke_matches_handedness(
            event.visual_stroke_type,
            config.player_handedness,
        )
    )


def _stroke_matches_handedness(stroke_type: str, handedness: str) -> bool:
    if handedness == "auto" or stroke_type == "挥拍":
        return True
    if stroke_type.startswith("双手"):
        return True
    expected_prefix = "右手" if handedness == "right" else "左手"
    return stroke_type.startswith(expected_prefix)


def _match_audio_and_visual_events(
    audio_events: list[AudioEvent],
    visual_events: list[VisualEvent],
) -> tuple[dict[int, int], set[int]]:
    """全局优先选择最像击球声的音画组合，避免踏地声先占用挥拍。"""

    candidates: list[tuple[float, float, int, int]] = []
    for audio_index, audio_event in enumerate(audio_events):
        for visual_index, visual_event in enumerate(visual_events):
            distance = abs(audio_event.timestamp - visual_event.timestamp)
            if distance > VISUAL_MATCH_WINDOW:
                continue
            proximity = 1.0 - distance / VISUAL_MATCH_WINDOW
            score = (
                0.60 * audio_event.impact_score
                + 0.25 * audio_event.confidence
                + 0.15 * proximity
            )
            candidates.append((score, -distance, audio_index, visual_index))

    matched_audio: dict[int, int] = {}
    matched_visual: set[int] = set()
    for _score, _negative_distance, audio_index, visual_index in sorted(
        candidates,
        reverse=True,
    ):
        if audio_index in matched_audio or visual_index in matched_visual:
            continue
        matched_audio[audio_index] = visual_index
        matched_visual.add(visual_index)
    return matched_audio, matched_visual


def _visual_anchors_connected(
    previous: FusedEvent,
    current: FusedEvent,
    events: list[FusedEvent],
    config: AnalysisConfig,
) -> bool:
    gap = current.timestamp - previous.timestamp
    bridge_gap_limit = config.end_silence + config.merge_gap
    if gap <= bridge_gap_limit:
        return True
    if gap > bridge_gap_limit * MAX_VISUAL_ANCHOR_GAP_FACTOR:
        return False

    # 回合一旦有最终击球锚点，连续出现的声音/球拍动作可桥接多次漏检；
    # 支撑事件本身仍不能独立启动一个回合。
    bridge_times = [previous.timestamp]
    bridge_times.extend(
        event.timestamp
        for event in events
        if previous.timestamp < event.timestamp < current.timestamp
        and _is_rally_continuation_event(event)
    )
    bridge_times.append(current.timestamp)
    return len(bridge_times) > 2 and all(
        right - left <= bridge_gap_limit
        for left, right in zip(bridge_times, bridge_times[1:])
    )


def _extend_confirmed_rally_end(
    confirmed_end: float,
    events: list[FusedEvent],
    config: AnalysisConfig,
) -> float:
    """已成立的回合继续吸收尾部支撑，直到真正出现持续静默。"""

    continuation_end = confirmed_end
    gap_limit = config.end_silence + config.merge_gap
    for event in events:
        if event.timestamp <= confirmed_end:
            continue
        if event.timestamp - confirmed_end > MAX_TRAILING_CONTINUATION_SECONDS:
            break
        if event.timestamp - continuation_end > gap_limit:
            break
        if is_confirmed_hit(event, config):
            break
        if _is_rally_continuation_event(event, allow_visual=False):
            continuation_end = event.timestamp
    return continuation_end


def _is_rally_continuation_event(
    event: FusedEvent,
    *,
    allow_visual: bool = True,
) -> bool:
    audio_support = (
        event.audio_confidence >= MIN_CONFIRMED_HIT_AUDIO_CONFIDENCE
        and event.audio_impact_score >= CONTINUATION_AUDIO_IMPACT_SCORE
    )
    visual_support = allow_visual and (
        event.visual_confidence >= VISUAL_CONFIRMATION_THRESHOLD
        and event.visual_arm_motion_score >= CONTINUATION_VISUAL_ARM_MOTION
        and event.visual_racket_confidence >= 0.12
    )
    return audio_support or visual_support
