"""候选片段复核会话的持久化与最终发布。"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Iterable

from tennis_video_helper.models import (
    AudioEvent,
    ClipRecord,
    FusedEvent,
    MediaInfo,
    RallySegment,
    VisualEvent,
)


REVIEW_MANIFEST_NAME = "review-session.json"
REVIEW_MANIFEST_VERSION = 1


@dataclass(frozen=True, slots=True)
class ReviewHit:
    """候选片段内的一个已识别击球点。"""

    timestamp: float
    source_timestamp: float
    confidence: float
    reason: str


@dataclass(frozen=True, slots=True)
class ReviewClipCandidate:
    """供 GUI 播放、勾选的单个候选片段。"""

    id: str
    index: int
    path: Path
    segment: RallySegment
    hits: tuple[ReviewHit, ...]

    @property
    def duration(self) -> float:
        return max(0.0, self.segment.output_end - self.segment.output_start)


@dataclass(frozen=True, slots=True)
class ReviewVideoCandidate:
    """一个源视频及其全部候选片段和分析证据。"""

    source: Path
    output_dir: Path
    staging_dir: Path
    media: MediaInfo
    clips: tuple[ReviewClipCandidate, ...]
    audio_events: tuple[AudioEvent, ...]
    visual_events: tuple[VisualEvent, ...]
    fused_events: tuple[FusedEvent, ...]


@dataclass(frozen=True, slots=True)
class ReviewSession:
    """一次等待人工确认的批处理会话。"""

    root_dir: Path
    overwrite_existing_output: bool
    videos: tuple[ReviewVideoCandidate, ...]

    @property
    def manifest_path(self) -> Path:
        return self.root_dir / REVIEW_MANIFEST_NAME

    @property
    def clips(self) -> tuple[ReviewClipCandidate, ...]:
        return tuple(clip for video in self.videos for clip in video.clips)


@dataclass(frozen=True, slots=True)
class PublishedReview:
    """人工确认后实际发布的目录和片段。"""

    output_dirs: tuple[Path, ...]
    clip_paths: tuple[Path, ...]


def save_review_session(session: ReviewSession) -> Path:
    """原子写入复核清单，供后台进程和 GUI 交换数据。"""

    session.root_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": REVIEW_MANIFEST_VERSION,
        "root_dir": str(session.root_dir),
        "overwrite_existing_output": session.overwrite_existing_output,
        "videos": [_video_payload(video) for video in session.videos],
    }
    temporary = session.manifest_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(session.manifest_path)
    return session.manifest_path


def load_review_session(manifest_path: Path) -> ReviewSession:
    """读取并校验后台生成的候选复核清单。"""

    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != REVIEW_MANIFEST_VERSION:
        raise ValueError("候选复核清单版本不受支持")
    videos = tuple(_video_from_payload(item) for item in payload.get("videos", []))
    session = ReviewSession(
        root_dir=Path(payload.get("root_dir") or path.parent),
        overwrite_existing_output=bool(payload.get("overwrite_existing_output")),
        videos=videos,
    )
    if session.manifest_path.resolve() != path.resolve():
        raise ValueError("候选复核清单路径与会话目录不一致")
    return session


def discard_review_session(session: ReviewSession | Path) -> None:
    """删除尚未发布的候选临时文件。"""

    root = session.root_dir if isinstance(session, ReviewSession) else Path(session)
    shutil.rmtree(root, ignore_errors=True)


def publish_review_session(
    session: ReviewSession,
    selected_clip_ids: Iterable[str],
) -> PublishedReview:
    """只发布用户勾选的片段，并为它们生成最终报告。"""

    selected = set(selected_clip_ids)
    known = {clip.id for clip in session.clips}
    unknown = selected - known
    if unknown:
        raise ValueError(f"包含未知候选片段：{sorted(unknown)[0]}")

    output_dirs: list[Path] = []
    clip_paths: list[Path] = []
    for video in session.videos:
        chosen = [clip for clip in video.clips if clip.id in selected]
        if not chosen:
            shutil.rmtree(video.staging_dir, ignore_errors=True)
            continue

        chosen_ids = {clip.id for clip in chosen}
        for clip in video.clips:
            if clip.id not in chosen_ids:
                clip.path.unlink(missing_ok=True)

        published_records = [
            ClipRecord(
                index=clip.index,
                path=video.output_dir / "clips" / clip.path.name,
                segment=clip.segment,
                verified=True,
                error=None,
            )
            for clip in chosen
        ]
        from tennis_video_helper.report import write_reports

        write_reports(
            video.staging_dir,
            video.media,
            published_records,
            list(video.audio_events),
            list(video.visual_events),
            list(video.fused_events),
        )
        selection_payload = {
            "source": str(video.source),
            "selected_clip_ids": [clip.id for clip in chosen],
            "selected_count": len(chosen),
            "candidate_count": len(video.clips),
        }
        (video.staging_dir / "review-selection.json").write_text(
            json.dumps(selection_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        video.output_dir.parent.mkdir(parents=True, exist_ok=True)
        from tennis_video_helper.pipeline import (
            _replace_output_dir,
            _replace_path_with_retry,
        )
        if session.overwrite_existing_output:
            _replace_output_dir(video.staging_dir, video.output_dir)
        else:
            _replace_path_with_retry(video.staging_dir, video.output_dir)
        output_dirs.append(video.output_dir)
        clip_paths.extend(record.path for record in published_records)

    discard_review_session(session)
    return PublishedReview(tuple(output_dirs), tuple(clip_paths))


def _video_payload(video: ReviewVideoCandidate) -> dict[str, Any]:
    return {
        "source": str(video.source),
        "output_dir": str(video.output_dir),
        "staging_dir": str(video.staging_dir),
        "media": _jsonable(asdict(video.media)),
        "clips": [_jsonable(asdict(clip)) for clip in video.clips],
        "audio_events": [_jsonable(asdict(event)) for event in video.audio_events],
        "visual_events": [_jsonable(asdict(event)) for event in video.visual_events],
        "fused_events": [_jsonable(asdict(event)) for event in video.fused_events],
    }


def _video_from_payload(payload: dict[str, Any]) -> ReviewVideoCandidate:
    media_payload = dict(payload["media"])
    media_payload["path"] = Path(media_payload["path"])
    clips = []
    for item in payload.get("clips", []):
        segment = RallySegment(**item["segment"])
        hits = tuple(ReviewHit(**hit) for hit in item.get("hits", []))
        clips.append(
            ReviewClipCandidate(
                id=str(item["id"]),
                index=int(item["index"]),
                path=Path(item["path"]),
                segment=segment,
                hits=hits,
            )
        )
    return ReviewVideoCandidate(
        source=Path(payload["source"]),
        output_dir=Path(payload["output_dir"]),
        staging_dir=Path(payload["staging_dir"]),
        media=MediaInfo(**media_payload),
        clips=tuple(clips),
        audio_events=tuple(
            AudioEvent(**_known_fields(AudioEvent, item))
            for item in payload.get("audio_events", [])
        ),
        visual_events=tuple(
            VisualEvent(**_known_fields(VisualEvent, item))
            for item in payload.get("visual_events", [])
        ),
        fused_events=tuple(
            FusedEvent(**_known_fields(FusedEvent, item))
            for item in payload.get("fused_events", [])
        ),
    )


def _known_fields(model_type, payload: dict[str, Any]) -> dict[str, Any]:
    """忽略未来版本新增字段，让旧候选清单仍能被当前界面载入。"""

    names = {item.name for item in fields(model_type)}
    return {key: value for key, value in payload.items() if key in names}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value
