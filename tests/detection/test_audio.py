from pathlib import Path
from subprocess import CompletedProcess

import numpy as np
import soundfile as sf

from tennis_video_helper.detection.audio import detect_audio_events, extract_audio, load_audio
from tennis_video_helper.core.config import AnalysisConfig


def _synthetic_hits(
    hit_times: list[float],
    *,
    sample_rate: int = 22_050,
    duration: float = 4.0,
) -> np.ndarray:
    rng = np.random.default_rng(7)
    samples = rng.normal(0.0, 0.002, int(sample_rate * duration)).astype(np.float32)
    burst_length = int(sample_rate * 0.025)
    window = np.hanning(burst_length)
    phase = np.arange(burst_length) / sample_rate
    burst = (0.9 * np.sin(2 * np.pi * 2_800 * phase) * window).astype(np.float32)
    for hit_time in hit_times:
        start = int(hit_time * sample_rate)
        samples[start : start + burst_length] += burst
    return samples


def _add_low_footstep(
    samples: np.ndarray,
    timestamp: float,
    *,
    sample_rate: int = 22_050,
) -> None:
    burst_length = int(sample_rate * 0.09)
    phase = np.arange(burst_length) / sample_rate
    burst = (
        0.95
        * np.sin(2 * np.pi * 120 * phase)
        * np.hanning(burst_length)
    ).astype(np.float32)
    start = int(timestamp * sample_rate)
    samples[start : start + burst_length] += burst


def test_detect_audio_events_finds_synthetic_hit_times() -> None:
    samples = _synthetic_hits([1.0, 2.0, 3.0])

    events = detect_audio_events(samples, 22_050, AnalysisConfig())

    timestamps = [event.timestamp for event in events]
    assert len(timestamps) == 3
    assert np.allclose(timestamps, [1.0, 2.0, 3.0], atol=0.08)
    assert all(0.0 <= event.confidence <= 1.0 for event in events)


def test_detect_audio_events_deduplicates_peaks_that_are_too_close() -> None:
    samples = _synthetic_hits([1.0, 1.1])

    events = detect_audio_events(samples, 22_050, AnalysisConfig())

    assert len(events) == 1


def test_detect_audio_events_scores_racket_hit_above_low_footstep() -> None:
    samples = _synthetic_hits([2.0])
    _add_low_footstep(samples, 1.0)

    events = detect_audio_events(samples, 22_050, AnalysisConfig())

    footstep = min(events, key=lambda event: abs(event.timestamp - 1.0))
    racket_hit = min(events, key=lambda event: abs(event.timestamp - 2.0))
    assert abs(footstep.timestamp - 1.0) < 0.08
    assert abs(racket_hit.timestamp - 2.0) < 0.08
    assert racket_hit.impact_score >= footstep.impact_score + 0.35


def test_extract_audio_uses_mono_pcm_and_configured_sample_rate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: list[str] = []

    def fake_run(command, **kwargs):
        captured.extend(command)
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("tennis_video_helper.detection.audio.subprocess.run", fake_run)
    source = tmp_path / "source.mp4"
    target = tmp_path / "audio.wav"

    extract_audio(source, target, sample_rate=16_000)

    assert Path(captured[0]).name == "ffmpeg.exe"
    assert captured[captured.index("-ac") + 1] == "1"
    assert captured[captured.index("-ar") + 1] == "16000"
    assert captured[-1] == str(target)


def test_load_audio_returns_samples_and_sample_rate(tmp_path: Path) -> None:
    target = tmp_path / "audio.wav"
    expected = np.array([0.0, 0.5, -0.5], dtype=np.float32)
    sf.write(target, expected, 16_000, subtype="FLOAT")

    samples, sample_rate = load_audio(target)

    assert sample_rate == 16_000
    assert np.allclose(samples, expected)
