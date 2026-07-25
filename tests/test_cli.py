from typer.testing import CliRunner

from tennis_video_helper import cli
from tennis_video_helper.cli import app
from tennis_video_helper.pipeline import BatchResult, VideoProcessResult


runner = CliRunner()


def test_cli_help_lists_analyze_command() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "analyze" in result.stdout


def test_cli_builds_analysis_config_from_options(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.touch()
    captured = {}

    monkeypatch.setattr(cli, "_check_runtime", lambda **_kwargs: True)

    def fake_process_batch(input_path, output, config, *, limit_duration=None):
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
            "--backend",
            "torch",
            "--precision",
            "fp32",
            "--batch-size",
            "8",
            "--require-gpu",
            "--limit-duration",
            "120",
        ],
    )

    assert result.exit_code == 0
    config = captured["config"]
    assert config.min_rally_duration == 18.0
    assert config.pre_roll == 3.0
    assert config.post_roll == 4.0
    assert config.end_silence == 5.0
    assert config.analysis_fps == 8
    assert config.audio_sensitivity == 1.2
    assert config.visual_sensitivity == 0.8
    assert config.inference_backend == "torch"
    assert config.inference_precision == "fp32"
    assert config.inference_batch_size == 8
    assert config.require_gpu is True
    assert config.gpu_available is True
    assert captured["limit_duration"] == 120.0


def test_cli_fails_when_no_supported_videos_are_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "_check_runtime", lambda **_kwargs: True)
    monkeypatch.setattr(cli, "process_batch", lambda *_args, **_kwargs: BatchResult(()))

    result = runner.invoke(app, ["analyze", str(tmp_path)])

    assert result.exit_code == 1
    assert "没有找到支持的视频" in result.stderr
