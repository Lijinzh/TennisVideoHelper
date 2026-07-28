from pathlib import Path
import time

from tennis_video_helper.models import VisualEvent
from tennis_video_helper.optimizer import (
    BenchmarkResult,
    Candidate,
    HardwareSnapshot,
    OptimizationProfile,
    candidate_matrix,
    load_profile,
    optimize_hardware,
)


def _snapshot(*, cuda: bool = True) -> HardwareSnapshot:
    return HardwareSnapshot(
        system="Windows",
        machine="AMD64",
        cpu="CPU",
        logical_cpus=16,
        memory_gib=32.0,
        display_adapters=("NVIDIA GeForce RTX 3070",),
        cuda_available=cuda,
        cuda_device_count=1 if cuda else 0,
        cuda_device_name="NVIDIA GeForce RTX 3070" if cuda else None,
        cuda_compute_capability="8.6" if cuda else None,
        cuda_memory_gib=8.0 if cuda else None,
        cuda_runtime="12.8" if cuda else None,
        driver_version="610.62" if cuda else None,
        tensorrt_version="11.1.0" if cuda else None,
        pynvvideocodec_available=cuda,
        ffmpeg_available=True,
        ffprobe_available=True,
        ffmpeg_hwaccels=("cuda",),
        ffmpeg_encoders=("hevc_nvenc", "libx265"),
    )


def test_candidate_matrix_uses_gpu_memory_without_changing_quality_settings() -> None:
    candidates = candidate_matrix(_snapshot())

    assert Candidate("tensorrt", "fp16", 16) in candidates
    assert Candidate("torch", "fp16", 32) in candidates
    assert all(candidate.precision == "fp16" for candidate in candidates)
    assert all(candidate.batch_size <= 32 for candidate in candidates)


def test_optimizer_selects_fastest_valid_candidate_and_persists_profile(
    monkeypatch, tmp_path: Path
) -> None:
    sample = tmp_path / "sample.mov"
    sample.touch()
    monkeypatch.setattr(
        "tennis_video_helper.optimizer.detect_hardware",
        lambda: _snapshot(),
    )
    monkeypatch.setattr(
        "tennis_video_helper.optimizer.scan_videos",
        lambda _path: [sample],
    )

    def fake_analyze(_path, config, *, limit_duration):
        if limit_duration > 5:
            time.sleep(0.012 if config.inference_batch_size == 8 else 0.003)
        return [VisualEvent(1.0, 0.8, 0.8, 0.0)]

    target = tmp_path / "profile.json"
    profile = optimize_hardware(
        sample,
        benchmark_seconds=30,
        profile_path=target,
        analyze=fake_analyze,
        candidates=(
            Candidate("tensorrt", "fp16", 8),
            Candidate("tensorrt", "fp16", 16),
        ),
    )

    assert profile.inference_batch_size == 16
    assert profile.decoder == "threaded_nvdec"
    loaded = load_profile(target)
    assert loaded is not None
    assert loaded.hardware_fingerprint == profile.hardware_fingerprint
    assert loaded.inference_batch_size == 16


def test_profile_result_schema_remains_json_round_trip_safe() -> None:
    result = BenchmarkResult("tensorrt", "fp16", 16, 3.0, 20.0, 100, True)
    profile = OptimizationProfile(
        profile_version=1,
        created_at="2026-07-26T00:00:00+0800",
        hardware_fingerprint=_snapshot().fingerprint,
        hardware=_snapshot(),
        sample_path="sample.mov",
        benchmark_seconds=60.0,
        inference_backend="tensorrt",
        inference_precision="fp16",
        inference_batch_size=16,
        decoder="threaded_nvdec",
        queue_depth=3,
        cuda_streams=2,
        cuda_graph=True,
        export_workers=2,
        results=(result,),
    )

    assert profile.to_dict()["results"][0]["realtime_factor"] == 20.0
