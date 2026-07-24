import pytest

from tennis_video_helper.config import AnalysisConfig


def test_default_config_matches_approved_design() -> None:
    config = AnalysisConfig()

    assert config.min_rally_duration == 10.0
    assert config.pre_roll == 2.0
    assert config.post_roll == 3.0
    assert config.end_silence == 3.0
    assert config.merge_gap == 1.5
    assert config.analysis_fps == 12
    assert config.audio_sample_rate == 22_050
    assert config.rally_support_threshold == 0.4
    assert config.encode_cq == 21


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min_rally_duration", 0),
        ("analysis_fps", 0),
        ("audio_sample_rate", 0),
        ("audio_sensitivity", 0),
        ("visual_sensitivity", 0),
        ("rally_support_threshold", 0),
        ("fusion_threshold", 1.1),
        ("encode_cq", 52),
    ],
)
def test_config_rejects_invalid_values(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=field):
        AnalysisConfig(**{field: value})


def test_config_rejects_support_threshold_above_confirmation_threshold() -> None:
    with pytest.raises(ValueError, match="rally_support_threshold"):
        AnalysisConfig(rally_support_threshold=0.7, fusion_threshold=0.6)
