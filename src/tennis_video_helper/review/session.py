"""候选片段复核会话的持久化与最终发布。"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any, Iterable

from tennis_video_helper.core.models import (
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
    published_clip_ids: tuple[str, ...] = ()

    @property
    def manifest_path(self) -> Path:
        return self.root_dir / REVIEW_MANIFEST_NAME

    @property
    def clips(self) -> tuple[ReviewClipCandidate, ...]:
        return tuple(clip for video in self.videos for clip in video.clips)

    @property
    def pending_clips(self) -> tuple[ReviewClipCandidate, ...]:
        """尚未导出、仍需用户筛选的候选片段。"""

        published = set(self.published_clip_ids)
        return tuple(clip for clip in self.clips if clip.id not in published)


@dataclass(frozen=True, slots=True)
class PublishedReview:
    """人工确认后实际发布的目录和片段。"""

    output_dirs: tuple[Path, ...]
    clip_paths: tuple[Path, ...]
    remaining_session: ReviewSession | None


def save_review_session(session: ReviewSession) -> Path:
    """原子写入复核清单，供后台进程和 GUI 交换数据。"""

    session.root_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": REVIEW_MANIFEST_VERSION,
        "root_dir": str(session.root_dir),
        "overwrite_existing_output": session.overwrite_existing_output,
        "published_clip_ids": list(session.published_clip_ids),
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
        published_clip_ids=tuple(
            str(clip_id) for clip_id in payload.get("published_clip_ids", [])
        ),
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
    """增量发布用户勾选的片段，并保留其余候选供后续筛选。"""

    selected = set(selected_clip_ids)
    known = {clip.id for clip in session.clips}
    unknown = selected - known
    if unknown:
        raise ValueError(f"包含未知候选片段：{sorted(unknown)[0]}")
    if not selected:
        raise ValueError("请至少选择一个需要导出的候选片段")

    already_published = selected.intersection(session.published_clip_ids)
    if already_published:
        raise ValueError(f"候选片段已经导出：{sorted(already_published)[0]}")

    published_ids = set(session.published_clip_ids)
    published_ids.update(selected)
    ordered_published_ids = tuple(
        clip.id for clip in session.clips if clip.id in published_ids
    )

    output_dirs: list[Path] = []
    clip_paths: list[Path] = []
    for video in session.videos:
        chosen = [clip for clip in video.clips if clip.id in selected]
        if not chosen:
            continue
        cumulative = [clip for clip in video.clips if clip.id in published_ids]
        previous = [
            clip for clip in video.clips if clip.id in session.published_clip_ids
        ]
        _publish_video_selection(
            session,
            video,
            cumulative,
            chosen,
            previous,
        )
        output_dirs.append(video.output_dir)
        clip_paths.extend(video.output_dir / "clips" / clip.path.name for clip in chosen)

    updated_session = replace(
        session,
        published_clip_ids=ordered_published_ids,
    )
    remaining_session: ReviewSession | None = updated_session
    if updated_session.pending_clips:
        save_review_session(updated_session)
    else:
        discard_review_session(updated_session)
        remaining_session = None
    return PublishedReview(
        tuple(output_dirs),
        tuple(clip_paths),
        remaining_session,
    )


def _publish_video_selection(
    session: ReviewSession,
    video: ReviewVideoCandidate,
    cumulative: list[ReviewClipCandidate],
    chosen: list[ReviewClipCandidate],
    previous: list[ReviewClipCandidate],
) -> None:
    """在独立暂存目录中累计结果，再原子替换正式输出。"""

    video.output_dir.parent.mkdir(parents=True, exist_ok=True)
    publishing_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{video.output_dir.name}.review-publish-",
            dir=video.output_dir.parent,
        )
    )
    try:
        if previous and video.output_dir.exists():
            shutil.copytree(video.output_dir, publishing_dir, dirs_exist_ok=True)
        elif not previous and not session.overwrite_existing_output and video.output_dir.exists():
            raise FileExistsError(f"输出目录已存在：{video.output_dir}")

        clips_dir = publishing_dir / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        for clip in cumulative:
            target = clips_dir / clip.path.name
            if clip.path.is_file():
                shutil.copy2(clip.path, target)
            elif not target.is_file():
                raise FileNotFoundError(f"候选片段缓存不存在：{clip.path}")

        published_records = [
            ClipRecord(
                index=clip.index,
                path=video.output_dir / "clips" / clip.path.name,
                segment=clip.segment,
                verified=True,
                error=None,
            )
            for clip in cumulative
        ]
        from tennis_video_helper.review.reporting import write_reports

        write_reports(
            publishing_dir,
            video.media,
            published_records,
            list(video.audio_events),
            list(video.visual_events),
            list(video.fused_events),
        )
        cumulative_ids = [clip.id for clip in cumulative]
        cumulative_id_set = set(cumulative_ids)
        selection_payload = {
            "source": str(video.source),
            "selected_clip_ids": cumulative_ids,
            "last_exported_clip_ids": [clip.id for clip in chosen],
            "remaining_clip_ids": [
                clip.id for clip in video.clips if clip.id not in cumulative_id_set
            ],
            "selected_count": len(cumulative),
            "candidate_count": len(video.clips),
        }
        (publishing_dir / "review-selection.json").write_text(
            json.dumps(selection_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        from tennis_video_helper.media.publication import replace_output_directory

        replace_output_directory(publishing_dir, video.output_dir)
    except Exception:
        shutil.rmtree(publishing_dir, ignore_errors=True)
        raise


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
