import pytest

from tennis_video_helper.config import AnalysisConfig


def test_default_config_matches_approved_design() -> None:
    config = AnalysisConfig()

    assert config.min_rally_duration == 10.0
    assert config.min_confirmed_hits == 3
    assert config.pre_roll == 2.0
    assert config.post_roll == 3.0
    assert config.end_silence == 3.5
    assert config.merge_gap == 1.5
    assert config.analysis_fps == 12
    assert config.audio_sample_rate == 22_050
    assert config.aligned_audio_reliability == 0.9
    assert config.aligned_visual_reliability == 0.85
    assert config.rally_support_threshold == 0.38
    assert config.player_handedness == "right"
    assert config.encode_cq == 21
    assert config.inference_backend == "auto"
    assert config.inference_precision == "fp16"
    assert config.inference_batch_size == 16
    assert config.require_gpu is False
    assert config.require_racket_confirmation is True
    assert config.export_original_quality is False
    assert config.overwrite_existing_output is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min_rally_duration", 0),
        ("min_confirmed_hits", 0),
        ("analysis_fps", 0),
        ("audio_sample_rate", 0),
        ("audio_sensitivity", 0),
        ("visual_sensitivity", 0),
        ("aligned_audio_reliability", 0),
        ("aligned_visual_reliability", 1.1),
        ("rally_support_threshold", 0),
        ("fusion_threshold", 1.1),
        ("encode_cq", 52),
        ("inference_batch_size", 0),
    ],
)
def test_config_rejects_invalid_values(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=field):
        AnalysisConfig(**{field: value})


def test_config_rejects_support_threshold_above_confirmation_threshold() -> None:
    with pytest.raises(ValueError, match="rally_support_threshold"):
        AnalysisConfig(rally_support_threshold=0.7, fusion_threshold=0.6)


@pytest.mark.parametrize("value", ["invalid", "directml"])
def test_config_rejects_unknown_inference_backend(value: str) -> None:
    with pytest.raises(ValueError, match="inference_backend"):
        AnalysisConfig(inference_backend=value)


@pytest.mark.parametrize("value", ["invalid", "bf16"])
def test_config_rejects_unknown_inference_precision(value: str) -> None:
    with pytest.raises(ValueError, match="inference_precision"):
        AnalysisConfig(inference_precision=value)


def test_config_rejects_unknown_player_handedness() -> None:
    with pytest.raises(ValueError, match="player_handedness"):
        AnalysisConfig(player_handedness="both")
