"""本机硬件探测、性能基准和自动优化配置。"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import asdict, dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import time
from typing import Callable, Iterable

from tennis_video_helper.config import AnalysisConfig
from tennis_video_helper.media import scan_videos
from tennis_video_helper.models import VisualEvent
from tennis_video_helper.runtime_tools import media_executable, media_tool_available


PROFILE_VERSION = 1
OPTIMIZATION_PREFIX = "TVH_OPTIMIZATION "
OptimizationProgress = Callable[[float, str], None]
AnalyzeVideo = Callable[..., list[VisualEvent]]


@dataclass(frozen=True, slots=True)
class HardwareSnapshot:
    """与后端选择有关的稳定硬件和运行时能力。"""

    system: str
    machine: str
    cpu: str
    logical_cpus: int
    memory_gib: float | None
    display_adapters: tuple[str, ...]
    cuda_available: bool
    cuda_device_count: int
    cuda_device_name: str | None
    cuda_compute_capability: str | None
    cuda_memory_gib: float | None
    cuda_runtime: str | None
    driver_version: str | None
    tensorrt_version: str | None
    pynvvideocodec_available: bool
    ffmpeg_available: bool
    ffprobe_available: bool
    ffmpeg_hwaccels: tuple[str, ...]
    ffmpeg_encoders: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        stable = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True, slots=True)
class Candidate:
    backend: str
    precision: str
    batch_size: int


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    backend: str
    precision: str
    batch_size: int
    elapsed_seconds: float | None
    realtime_factor: float | None
    event_count: int | None
    valid: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class OptimizationProfile:
    profile_version: int
    created_at: str
    hardware_fingerprint: str
    hardware: HardwareSnapshot
    sample_path: str
    benchmark_seconds: float
    inference_backend: str
    inference_precision: str
    inference_batch_size: int
    decoder: str
    queue_depth: int
    cuda_streams: int
    cuda_graph: bool
    export_workers: int
    results: tuple[BenchmarkResult, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def default_profile_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config"))
    return root / "TennisVideoHelper" / "optimization-profile.json"


def save_profile(profile: OptimizationProfile, path: Path | None = None) -> Path:
    target = path or default_profile_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_suffix(target.suffix + ".staging")
    staging.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    staging.replace(target)
    return target


def load_profile(path: Path | None = None) -> OptimizationProfile | None:
    target = path or default_profile_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if int(payload.get("profile_version", -1)) != PROFILE_VERSION:
            return None
        hardware = HardwareSnapshot(**payload["hardware"])
        results = tuple(BenchmarkResult(**item) for item in payload.get("results", []))
        return OptimizationProfile(
            **{
                **payload,
                "hardware": hardware,
                "results": results,
            }
        )
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None


def detect_hardware() -> HardwareSnapshot:
    """探测所有显示适配器以及当前可实际调用的加速能力。"""

    display_adapters = _windows_display_adapters() if os.name == "nt" else ()
    ffmpeg_available = media_tool_available("ffmpeg")
    ffprobe_available = media_tool_available("ffprobe")
    ffmpeg = media_executable("ffmpeg")
    hwaccels = _ffmpeg_lines([ffmpeg, "-hide_banner", "-hwaccels"], skip=1)
    encoder_text = _run_text([ffmpeg, "-hide_banner", "-encoders"])
    known_encoders = (
        "hevc_nvenc",
        "h264_nvenc",
        "av1_nvenc",
        "hevc_amf",
        "h264_amf",
        "av1_amf",
        "hevc_qsv",
        "h264_qsv",
        "av1_qsv",
        "libx265",
    )
    encoders = tuple(name for name in known_encoders if name in encoder_text)

    cuda_available = False
    cuda_device_count = 0
    cuda_device_name = None
    compute_capability = None
    cuda_memory_gib = None
    cuda_runtime = None
    driver_version = None
    try:
        import torch

        cuda_available = bool(torch.cuda.is_available())
        cuda_device_count = int(torch.cuda.device_count()) if cuda_available else 0
        cuda_runtime = str(torch.version.cuda) if torch.version.cuda else None
        if cuda_available:
            properties = torch.cuda.get_device_properties(0)
            cuda_device_name = torch.cuda.get_device_name(0)
            major, minor = torch.cuda.get_device_capability(0)
            compute_capability = f"{major}.{minor}"
            cuda_memory_gib = round(properties.total_memory / (1024**3), 2)
    except (ImportError, RuntimeError):
        pass

    if not cuda_available:
        try:
            import onnxruntime as ort

            providers = set(ort.get_available_providers())
            selected_provider = next(
                (
                    name
                    for name in (
                        "TensorrtExecutionProvider",
                        "CUDAExecutionProvider",
                        "DmlExecutionProvider",
                    )
                    if name in providers
                ),
                None,
            )
            if selected_provider:
                cuda_available = True
                cuda_device_count = 1
                cuda_device_name = display_adapters[0] if display_adapters else "ONNX GPU"
                cuda_runtime = f"onnx:{selected_provider}"
        except (ImportError, RuntimeError, OSError):
            pass

    driver_line = _run_text(
        [
            "nvidia-smi",
            "--query-gpu=driver_version",
            "--format=csv,noheader,nounits",
        ]
    ).strip()
    if driver_line:
        driver_version = driver_line.splitlines()[0].strip()

    tensorrt_version = None
    if importlib.util.find_spec("tensorrt") is not None:
        try:
            import tensorrt

            tensorrt_version = str(tensorrt.__version__)
        except (ImportError, OSError):
            pass

    pynvvideocodec_available = importlib.util.find_spec("PyNvVideoCodec") is not None
    return HardwareSnapshot(
        system=platform.platform(),
        machine=platform.machine(),
        cpu=platform.processor() or platform.machine(),
        logical_cpus=os.cpu_count() or 1,
        memory_gib=_physical_memory_gib(),
        display_adapters=display_adapters,
        cuda_available=cuda_available,
        cuda_device_count=cuda_device_count,
        cuda_device_name=cuda_device_name,
        cuda_compute_capability=compute_capability,
        cuda_memory_gib=cuda_memory_gib,
        cuda_runtime=cuda_runtime,
        driver_version=driver_version,
        tensorrt_version=tensorrt_version,
        pynvvideocodec_available=pynvvideocodec_available,
        ffmpeg_available=ffmpeg_available,
        ffprobe_available=ffprobe_available,
        ffmpeg_hwaccels=hwaccels,
        ffmpeg_encoders=encoders,
    )


def candidate_matrix(snapshot: HardwareSnapshot) -> tuple[Candidate, ...]:
    """根据能力生成候选；不改变画面分析率等质量参数。"""

    if not snapshot.cuda_available:
        return (Candidate("onnx", "fp32", 4),)
    batches = [8, 16, 32]
    if (snapshot.cuda_memory_gib or 0) >= 12:
        batches.append(64)
    candidates: list[Candidate] = []
    if (snapshot.cuda_runtime or "").startswith("onnx:"):
        return tuple(Candidate("onnx", "fp32", batch) for batch in batches)
    if snapshot.tensorrt_version:
        candidates.extend(Candidate("tensorrt", "fp16", batch) for batch in batches)
    candidates.extend(Candidate("torch", "fp16", batch) for batch in batches)
    return tuple(candidates)


def optimize_hardware(
    input_path: Path,
    *,
    benchmark_seconds: float = 60.0,
    profile_path: Path | None = None,
    progress: OptimizationProgress | None = None,
    analyze: AnalyzeVideo | None = None,
    candidates: Iterable[Candidate] | None = None,
) -> OptimizationProfile:
    """用真实素材基准候选配置，保存满足一致性约束的最快配置。"""

    emit = progress or (lambda _percent, _phase: None)
    emit(2.0, "检测CPU、GPU、编码器和运行时")
    snapshot = detect_hardware()
    if not snapshot.ffmpeg_available or not snapshot.ffprobe_available:
        raise RuntimeError("自动优化需要可用的 ffmpeg 和 ffprobe")
    videos = scan_videos(Path(input_path))
    if not videos:
        raise RuntimeError("没有找到可用于基准测试的视频")
    sample = videos[0]
    matrix = tuple(candidates or candidate_matrix(snapshot))
    if not matrix:
        raise RuntimeError("没有可用的推理候选后端")

    if analyze is None:
        from tennis_video_helper.vision import analyze_video

        analyze = analyze_video

    results: list[BenchmarkResult] = []
    reference: list[VisualEvent] | None = None
    for index, candidate in enumerate(matrix, start=1):
        emit(
            5.0 + (index - 1) / len(matrix) * 88.0,
            f"预热 {candidate.backend} {candidate.precision.upper()} 批量 {candidate.batch_size}",
        )
        config = AnalysisConfig(
            inference_backend=candidate.backend,
            inference_precision=candidate.precision,
            inference_batch_size=candidate.batch_size,
            require_gpu=snapshot.cuda_available,
            gpu_available="hevc_nvenc" in snapshot.ffmpeg_encoders,
        )
        try:
            # Engine export and CUDA context creation are one-time setup work. Warm them
            # outside the measured region so a new candidate is not unfairly penalized.
            analyze(sample, config, limit_duration=min(5.0, benchmark_seconds))
            emit(
                5.0 + (index - 0.5) / len(matrix) * 88.0,
                f"基准 {candidate.backend} {candidate.precision.upper()} 批量 {candidate.batch_size}",
            )
            started = time.perf_counter()
            events = analyze(sample, config, limit_duration=benchmark_seconds)
            elapsed = time.perf_counter() - started
            valid = reference is None or _events_match(reference, events)
            if reference is None:
                reference = events
                valid = True
            results.append(
                BenchmarkResult(
                    backend=candidate.backend,
                    precision=candidate.precision,
                    batch_size=candidate.batch_size,
                    elapsed_seconds=round(elapsed, 4),
                    realtime_factor=round(benchmark_seconds / max(elapsed, 1e-6), 3),
                    event_count=len(events),
                    valid=valid,
                )
            )
        except Exception as exc:  # noqa: BLE001 - 单候选失败不能中止整个优化
            results.append(
                BenchmarkResult(
                    backend=candidate.backend,
                    precision=candidate.precision,
                    batch_size=candidate.batch_size,
                    elapsed_seconds=None,
                    realtime_factor=None,
                    event_count=None,
                    valid=False,
                    error=str(exc),
                )
            )

    successful = [
        item for item in results if item.valid and item.elapsed_seconds is not None
    ]
    if not successful:
        errors = "; ".join(item.error or "结果一致性未通过" for item in results)
        raise RuntimeError(f"所有候选配置均失败：{errors}")
    best = min(successful, key=lambda item: item.elapsed_seconds or float("inf"))
    emit(96.0, "保存本机专属优化配置")
    profile = OptimizationProfile(
        profile_version=PROFILE_VERSION,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        hardware_fingerprint=snapshot.fingerprint,
        hardware=snapshot,
        sample_path=str(sample),
        benchmark_seconds=benchmark_seconds,
        inference_backend=best.backend,
        inference_precision=best.precision,
        inference_batch_size=best.batch_size,
        decoder="threaded_nvdec" if snapshot.pynvvideocodec_available else "opencv",
        queue_depth=3 if snapshot.cuda_available else 1,
        cuda_streams=2 if snapshot.cuda_available else 0,
        cuda_graph=bool(snapshot.tensorrt_version),
        export_workers=2 if "hevc_nvenc" in snapshot.ffmpeg_encoders else 1,
        results=tuple(results),
    )
    save_profile(profile, profile_path)
    emit(100.0, "本机性能优化完成")
    return profile


def _events_match(reference: list[VisualEvent], candidate: list[VisualEvent]) -> bool:
    if not reference:
        return not candidate
    allowed_count_delta = max(5, round(len(reference) * 0.08))
    if abs(len(reference) - len(candidate)) > allowed_count_delta:
        return False
    candidate_times = sorted(event.timestamp for event in candidate)
    if not candidate_times:
        return False
    matched = 0
    for event in reference:
        index = bisect_left(candidate_times, event.timestamp)
        nearest = []
        if index < len(candidate_times):
            nearest.append(abs(candidate_times[index] - event.timestamp))
        if index:
            nearest.append(abs(candidate_times[index - 1] - event.timestamp))
        if nearest and min(nearest) <= 0.25:
            matched += 1
    return matched / len(reference) >= 0.9


def _run_text(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _ffmpeg_lines(command: list[str], *, skip: int = 0) -> tuple[str, ...]:
    lines = [line.strip() for line in _run_text(command).splitlines() if line.strip()]
    return tuple(lines[skip:])


def _windows_display_adapters() -> tuple[str, ...]:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterRAM,DriverVersion,PNPDeviceID | "
        "ConvertTo-Json -Compress",
    ]
    text = _run_text(command).strip()
    if not text:
        return ()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ()
    items = payload if isinstance(payload, list) else [payload]
    return tuple(
        str(item.get("Name"))
        for item in items
        if isinstance(item, dict) and item.get("Name")
    )


def _physical_memory_gib() -> float | None:
    if os.name != "nt":
        return None
    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return round(status.ullTotalPhys / (1024**3), 2)
    except (AttributeError, OSError):
        pass
    return None
