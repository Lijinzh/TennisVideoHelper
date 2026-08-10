"""音频提取与击球瞬态候选检测。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from tennis_video_helper.config import AnalysisConfig
from tennis_video_helper.models import AudioEvent
from tennis_video_helper.runtime_tools import (
    media_executable,
    subprocess_no_window_kwargs,
)


class AudioAnalysisError(RuntimeError):
    """音频提取或分析失败。"""


def extract_audio(source: Path, target: Path, *, sample_rate: int) -> None:
    """将视频音轨提取为单声道 PCM WAV。"""

    target.parent.mkdir(parents=True, exist_ok=True)
    command = [
        media_executable("ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(target),
    ]
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            **subprocess_no_window_kwargs(),
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise AudioAnalysisError(f"无法提取音轨：{source}") from exc


def detect_audio_events(
    samples: np.ndarray,
    sample_rate: int,
    config: AnalysisConfig,
) -> list[AudioEvent]:
    """使用频谱通量和动态噪声阈值检测短促声音事件。"""

    mono = np.asarray(samples, dtype=np.float32).reshape(-1)
    if mono.size == 0 or not np.any(np.abs(mono) > 1e-8):
        return []

    hop_length = 256
    n_fft = 1024
    if mono.size < n_fft:
        mono = np.pad(mono, (0, n_fft - mono.size))
    frame_count = 1 + (mono.size - n_fft) // hop_length
    frames = np.lib.stride_tricks.sliding_window_view(mono, n_fft)[::hop_length]
    frames = frames[:frame_count] * np.hanning(n_fft)
    spectrum = np.abs(np.fft.rfft(frames, axis=1))
    onset_envelope = np.zeros(len(spectrum), dtype=np.float64)
    high_frequency_flux = np.zeros(len(spectrum), dtype=np.float64)
    low_frequency_flux = np.zeros(len(spectrum), dtype=np.float64)
    total_flux = np.zeros(len(spectrum), dtype=np.float64)
    if len(spectrum) > 1:
        positive_flux = np.maximum(np.diff(spectrum, axis=0), 0.0)
        onset_envelope[1:] = np.mean(positive_flux, axis=1)
        frequencies = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
        high_frequency_flux[1:] = np.sum(
            positive_flux[:, frequencies >= 1_500.0],
            axis=1,
        )
        low_frequency_flux[1:] = np.sum(
            positive_flux[:, frequencies <= 500.0],
            axis=1,
        )
        total_flux[1:] = np.sum(positive_flux, axis=1)
        del positive_flux
    del spectrum
    if onset_envelope.size == 0 or float(np.max(onset_envelope)) <= 0:
        return []

    median = float(np.median(onset_envelope))
    mad = float(np.median(np.abs(onset_envelope - median)))
    robust_scale = max(mad * 1.4826, float(np.std(onset_envelope)) * 0.15, 1e-6)
    threshold = median + (4.0 / config.audio_sensitivity) * robust_scale
    minimum_distance = max(1, round(0.25 * sample_rate / hop_length))
    peak_indices = _find_separated_peaks(onset_envelope, threshold, minimum_distance)
    if peak_indices.size == 0:
        return []

    peak_heights = onset_envelope[peak_indices]
    upper = max(float(np.percentile(peak_heights, 95)), threshold + 1e-6)
    timestamps = peak_indices * hop_length / sample_rate
    center_offset = n_fft / (2 * sample_rate)

    events: list[AudioEvent] = []
    for timestamp, height in zip(timestamps, peak_heights, strict=True):
        confidence = float(np.clip((height - threshold) / (upper - threshold), 0.0, 1.0))
        events.append(
            AudioEvent(
                timestamp=max(0.0, float(timestamp) - center_offset),
                confidence=confidence,
                strength=float(height),
                impact_score=_impact_score(
                    int(round(timestamp * sample_rate / hop_length)),
                    onset_envelope,
                    high_frequency_flux,
                    low_frequency_flux,
                    total_flux,
                ),
            )
        )
    return events


def _impact_score(
    peak_index: int,
    onset_envelope: np.ndarray,
    high_frequency_flux: np.ndarray,
    low_frequency_flux: np.ndarray,
    total_flux: np.ndarray,
) -> float:
    """区分清脆短促的球拍触球声与偏低频、持续更久的踏地声。"""

    total = max(float(total_flux[peak_index]), 1e-12)
    high_ratio = float(high_frequency_flux[peak_index]) / total
    low_ratio = float(low_frequency_flux[peak_index]) / total
    frequency_score = float(np.clip((high_ratio - 0.18) / 0.42, 0.0, 1.0))
    low_frequency_penalty = float(np.clip((low_ratio - 0.35) / 0.45, 0.0, 1.0))

    peak = max(float(onset_envelope[peak_index]), 1e-12)
    decay_end = min(len(onset_envelope), peak_index + 5)
    trailing = onset_envelope[peak_index + 1 : decay_end]
    trailing_level = float(np.mean(trailing)) if trailing.size else 0.0
    impulsiveness = float(np.clip(1.0 - trailing_level / peak, 0.0, 1.0))
    return float(
        np.clip(
            0.70 * frequency_score
            + 0.30 * impulsiveness
            - 0.25 * low_frequency_penalty,
            0.0,
            1.0,
        )
    )


def _find_separated_peaks(
    values: np.ndarray,
    threshold: float,
    minimum_distance: int,
) -> np.ndarray:
    """Select local maxima above threshold without depending on SciPy."""

    if values.size < 3:
        return np.empty(0, dtype=int)
    candidates = np.flatnonzero(
        (values[1:-1] >= values[:-2])
        & (values[1:-1] > values[2:])
        & (values[1:-1] >= threshold)
    ) + 1
    selected: list[int] = []
    for index in candidates[np.argsort(values[candidates])[::-1]]:
        if all(abs(int(index) - previous) >= minimum_distance for previous in selected):
            selected.append(int(index))
    return np.asarray(sorted(selected), dtype=int)


def load_audio(path: Path) -> tuple[np.ndarray, int]:
    """读取单声道 WAV，并返回浮点采样和采样率。"""

    try:
        samples, sample_rate = sf.read(path, dtype="float32", always_2d=False)
    except (OSError, RuntimeError) as exc:
        raise AudioAnalysisError(f"无法读取音频：{path}") from exc
    mono = np.asarray(samples, dtype=np.float32)
    if mono.ndim > 1:
        mono = np.mean(mono, axis=1, dtype=np.float32)
    return mono.reshape(-1), int(sample_rate)
