"""CSV 与 JSON 分析报告。"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tennis_video_helper.models import (
    AudioEvent,
    ClipRecord,
    FusedEvent,
    MediaInfo,
    VisualEvent,
)


def write_reports(
    output_dir: Path,
    media: MediaInfo,
    records: list[ClipRecord],
    audio_events: list[AudioEvent],
    visual_events: list[VisualEvent],
    fused_events: list[FusedEvent],
) -> None:
    """原子写入面向人工的 CSV 和机器可读 JSON。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        output_dir / "segments.csv",
        records,
        audio_events,
        visual_events,
    )
    payload = {
        "source": _jsonable(asdict(media)),
        "clips": [_jsonable(asdict(record)) for record in records],
        "audio_events": [
            _event_payload(event, source="audio", reason="声音瞬态候选")
            for event in audio_events
        ],
        "visual_events": [
            _event_payload(event, source="visual", reason="骨架时序确认挥拍")
            for event in visual_events
        ],
        "fused_events": [
            _event_payload(event, source=_fused_event_source(event))
            for event in fused_events
        ],
    }
    _atomic_write_text(
        output_dir / "analysis.json",
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_csv(
    path: Path,
    records: list[ClipRecord],
    audio_events: list[AudioEvent],
    visual_events: list[VisualEvent],
) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "index",
                "file",
                "active_start",
                "active_end",
                "output_start",
                "output_end",
                "active_duration",
                "audio_event_count",
                "visual_event_count",
                "average_confidence",
                "event_count",
                "verified",
                "error",
            ],
        )
        writer.writeheader()
        for record in records:
            segment = record.segment
            writer.writerow(
                {
                    "index": record.index,
                    "file": record.path.name,
                    "active_start": f"{segment.active_start:.3f}",
                    "active_end": f"{segment.active_end:.3f}",
                    "output_start": f"{segment.output_start:.3f}",
                    "output_end": f"{segment.output_end:.3f}",
                    "active_duration": f"{segment.active_duration:.3f}",
                    "audio_event_count": _count_events_in_segment(
                        audio_events,
                        segment.active_start,
                        segment.active_end,
                    ),
                    "visual_event_count": _count_events_in_segment(
                        visual_events,
                        segment.active_start,
                        segment.active_end,
                    ),
                    "average_confidence": f"{segment.average_confidence:.4f}",
                    "event_count": segment.event_count,
                    "verified": record.verified,
                    "error": record.error or "",
                }
            )
    temporary.replace(path)


def _count_events_in_segment(
    events: list[AudioEvent] | list[VisualEvent],
    start: float,
    end: float,
) -> int:
    return sum(start <= event.timestamp <= end for event in events)


def _atomic_write_text(path: Path, content: str, *, encoding: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding=encoding)
    temporary.replace(path)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _event_payload(
    event: AudioEvent | VisualEvent | FusedEvent,
    *,
    source: str,
    reason: str | None = None,
) -> dict[str, Any]:
    payload = _jsonable(asdict(event))
    payload["source"] = source
    if reason is not None:
        payload["reason"] = reason
    return payload


def _fused_event_source(event: FusedEvent) -> str:
    if event.audio_confidence > 0 and event.visual_confidence > 0:
        return "audio_visual"
    if event.audio_confidence > 0:
        return "audio_only"
    return "visual_only"
