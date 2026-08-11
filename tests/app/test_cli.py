import json
from typer.testing import CliRunner

from tennis_video_helper.app import cli
from tennis_video_helper.app.cli import app
from pathlib import Path

from tennis_video_helper.app.pipeline import (
    BatchResult,
    ProgressUpdate,
    ReviewBatchResult,
    VideoProcessResult,
)
from tennis_video_helper.review.session import ReviewSession


runner = CliRunner()


def test_cli_help_lists_analyze_command() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "analyze" in result.stdout


def test_cli_builds_analysis_config_from_options(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.touch()
    captured = {}

    monkeypatch.setattr(
        cli,
        "_check_runtime",
        lambda **_kwargs: cli.RuntimeCapabilities(True, True, "Test GPU"),
    )

    def fake_process_batch(
        input_path,
        output,
        config,
        *,
        limit_duration=None,
        progress_callback=None,
    ):
        captured["input_path"] = input_path
        captured["output"] = output
        captured["config"] = config
        captured["limit_duration"] = limit_duration
        return BatchResult((VideoProcessResult(source, output),))

    monkeypatch.setattr(cli, "process_batch", fake_process_batch)

    result = runner.invoke(
        app,
        [
            "analyze",
            str(source),
            "--output",
            str(tmp_path / "output"),
            "--min-rally-duration",
            "18",
            "--min-confirmed-hits",
            "4",
            "--pre-roll",
            "3",
            "--post-roll",
            "4",
            "--end-silence",
            "5",
            "--analysis-fps",
            "8",
            "--audio-sensitivity",
            "1.2",
            "--visual-sensitivity",
            "0.8",
            "--handedness",
            "left",
            "--backend",
            "torch",
            "--precision",
            "fp32",
            "--batch-size",
            "8",
            "--require-gpu",
            "--original-quality",
            "--limit-duration",
            "120",
        ],
    )

    assert result.exit_code == 0
    config = captured["config"]
    assert config.min_rally_duration == 18.0
    assert config.min_confirmed_hits == 4
    assert config.pre_roll == 3.0
    assert config.post_roll == 4.0
    assert config.end_silence == 5.0
    assert config.analysis_fps == 8
    assert config.audio_sensitivity == 1.2
    assert config.visual_sensitivity == 0.8
    assert config.player_handedness == "left"
    assert config.inference_backend == "torch"
    assert config.inference_precision == "fp32"
    assert config.inference_batch_size == 8
    assert config.require_gpu is True
    assert config.gpu_available is True
    assert config.export_original_quality is True
    assert config.overwrite_existing_output is True
    assert captured["limit_duration"] == 120.0


def test_progress_line_contains_machine_readable_payload() -> None:
    line = cli._format_progress_line(
        ProgressUpdate(42.5, "GPU 分析画面", Path("D:/videos/match.mp4"), 2, 4)
    )

    assert line.startswith(cli.PROGRESS_PREFIX)
    payload = json.loads(line.removeprefix(cli.PROGRESS_PREFIX))
    assert payload["percent"] == 42.5
    assert payload["phase"] == "GPU 分析画面"
    assert payload["candidate_count"] == 0


def test_review_candidates_are_emitted_before_batch_completion(
    tmp_path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.mp4"
    source.touch()
    session = ReviewSession(tmp_path / ".review", True, ())
    monkeypatch.setattr(
        cli,
        "_check_runtime",
        lambda **_kwargs: cli.RuntimeCapabilities(True, True, "Test GPU"),
    )

    def fake_prepare_review_batch(
        input_path,
        output,
        config,
        *,
        limit_duration=None,
        progress_callback=None,
        review_update_callback=None,
    ):
        assert review_update_callback is not None
        review_update_callback(session)
        return ReviewBatchResult((VideoProcessResult(source, output),), session)

    monkeypatch.setattr(cli, "prepare_review_batch", fake_prepare_review_batch)

    result = runner.invoke(
        app,
        [
            "analyze",
            str(source),
            "--output",
            str(tmp_path / "output"),
            "--prepare-review",
            "--progress-json",
        ],
    )

    assert result.exit_code == 0
    review_payloads = [
        json.loads(line.removeprefix(cli.REVIEW_PREFIX))
        for line in result.stdout.splitlines()
        if line.startswith(cli.REVIEW_PREFIX)
    ]
    assert [payload["complete"] for payload in review_payloads] == [False, True]


def test_cli_fails_when_no_supported_videos_are_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        cli,
        "_check_runtime",
        lambda **_kwargs: cli.RuntimeCapabilities(True, True, "Test GPU"),
    )
    monkeypatch.setattr(cli, "process_batch", lambda *_args, **_kwargs: BatchResult(()))

    result = runner.invoke(app, ["analyze", str(tmp_path)])

    assert result.exit_code == 1
    assert "没有找到支持的视频" in result.stderr
