"""音频提取与击球瞬态候选检测。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import librosa
import numpy as np
from scipy.signal import find_peaks

from tennis_video_helper.config import AnalysisConfig
from tennis_video_helper.models import AudioEvent


class AudioAnalysisError(RuntimeError):
    """音频提取或分析失败。"""


def extract_audio(source: Path, target: Path, *, sample_rate: int) -> None:
    """将视频音轨提取为单声道 PCM WAV。"""

    target.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
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
        subprocess.run(command, check=True, capture_output=True, text=True)
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
    onset_envelope = librosa.onset.onset_strength(
        y=mono,
        sr=sample_rate,
        hop_length=hop_length,
        n_fft=n_fft,
        aggregate=np.max,
    )
    if onset_envelope.size == 0 or float(np.max(onset_envelope)) <= 0:
        return []

    median = float(np.median(onset_envelope))
    mad = float(np.median(np.abs(onset_envelope - median)))
    robust_scale = max(mad * 1.4826, float(np.std(onset_envelope)) * 0.15, 1e-6)
    threshold = median + (4.0 / config.audio_sensitivity) * robust_scale
    minimum_distance = max(1, round(0.25 * sample_rate / hop_length))
    peak_indices, properties = find_peaks(
        onset_envelope,
        height=threshold,
        distance=minimum_distance,
        prominence=robust_scale,
    )
    if peak_indices.size == 0:
        return []

    peak_heights = np.asarray(properties["peak_heights"], dtype=np.float64)
    upper = max(float(np.percentile(peak_heights, 95)), threshold + 1e-6)
    timestamps = librosa.frames_to_time(
        peak_indices,
        sr=sample_rate,
        hop_length=hop_length,
    )
    center_offset = n_fft / (2 * sample_rate)

    events: list[AudioEvent] = []
    for timestamp, height in zip(timestamps, peak_heights, strict=True):
        confidence = float(np.clip((height - threshold) / (upper - threshold), 0.0, 1.0))
        events.append(
            AudioEvent(
                timestamp=max(0.0, float(timestamp) - center_offset),
                confidence=confidence,
                strength=float(height),
            )
        )
    return events

