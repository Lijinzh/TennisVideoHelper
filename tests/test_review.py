import json
from pathlib import Path

from tennis_video_helper.models import (
    AudioEvent,
    FusedEvent,
    MediaInfo,
    RallySegment,
    VisualEvent,
)
from tennis_video_helper.review import (
    ReviewClipCandidate,
    ReviewHit,
    ReviewSession,
    ReviewVideoCandidate,
    load_review_session,
    publish_review_session,
    save_review_session,
)


def _media(path: Path) -> MediaInfo:
    return MediaInfo(
        path=path,
        duration=30.0,
        width=1920,
        height=1080,
        fps=30.0,
        video_codec="h264",
        pixel_format="yuv420p",
        audio_codec="aac",
        audio_sample_rate=48_000,
        audio_channels=2,
        rotation=0,
        color_transfer=None,
        is_hdr10=False,
        is_dolby_vision=False,
    )


def test_review_session_round_trip_and_publishes_only_selected_clip(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    output_dir = tmp_path / "output" / "source"
    output_dir.mkdir(parents=True)
    (output_dir / "old.txt").write_text("old", encoding="utf-8")
    root = tmp_path / "output" / ".tennis-review-test"
    staging = root / "001_source"
    clips_dir = staging / "clips"
    clips_dir.mkdir(parents=True)

    first_path = clips_dir / "rally_001.mp4"
    second_path = clips_dir / "rally_002.mp4"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")
    first_segment = RallySegment(1, 12, 0, 15, 11, 0.9, 4)
    second_segment = RallySegment(16, 28, 15, 30, 12, 0.8, 5)
    first = ReviewClipCandidate(
        id="1:1",
        index=1,
        path=first_path,
        segment=first_segment,
        hits=(ReviewHit(2.0, 2.0, 0.9, "音画共同确认近端击球"),),
    )
    second = ReviewClipCandidate(
        id="1:2",
        index=2,
        path=second_path,
        segment=second_segment,
        hits=(ReviewHit(3.0, 18.0, 0.8, "骨架时序确认挥拍"),),
    )
    video = ReviewVideoCandidate(
        source=source,
        output_dir=output_dir,
        staging_dir=staging,
        media=_media(source),
        clips=(first, second),
        audio_events=(AudioEvent(2.0, 0.9, 2.0),),
        visual_events=(VisualEvent(2.0, 0.9, 1.0, 0.0),),
        fused_events=(FusedEvent(2.0, 0.9, 0.9, 0.95, "音画共同确认近端击球"),),
    )
    manifest = save_review_session(
        ReviewSession(root, overwrite_existing_output=True, videos=(video,))
    )

    loaded = load_review_session(manifest)
    published = publish_review_session(loaded, ["1:1"])

    assert published.output_dirs == (output_dir,)
    assert published.clip_paths == (output_dir / "clips" / first_path.name,)
    assert (output_dir / "clips" / first_path.name).read_bytes() == b"first"
    assert not (output_dir / "clips" / second_path.name).exists()
    assert not (output_dir / "old.txt").exists()
    assert not root.exists()
    analysis = json.loads((output_dir / "analysis.json").read_text(encoding="utf-8"))
    assert [clip["index"] for clip in analysis["clips"]] == [1]
    selection = json.loads(
        (output_dir / "review-selection.json").read_text(encoding="utf-8")
    )
    assert selection["selected_clip_ids"] == ["1:1"]
