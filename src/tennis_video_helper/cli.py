"""命令行入口。"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import typer

from tennis_video_helper.config import AnalysisConfig
from tennis_video_helper.optimizer import OPTIMIZATION_PREFIX
from tennis_video_helper.pipeline import (
    ProgressUpdate,
    prepare_review_batch,
    process_batch,
)
from tennis_video_helper.runtime_tools import media_executable, media_tool_available

PROGRESS_PREFIX = "TVH_PROGRESS "
ACCELERATION_PREFIX = "TVH_ACCELERATION "
REVIEW_PREFIX = "TVH_REVIEW "


@dataclass(frozen=True, slots=True)
class RuntimeCapabilities:
    """运行时实际可用的 CUDA 与编码能力。"""

    cuda_available: bool
    nvenc_available: bool
    device_name: str | None

app = typer.Typer(
    name="tennis-video-helper",
    help="使用音画融合筛选并切分网球长回合。",
    no_args_is_help=True,
)


def _configure_utf8_stdio() -> None:
    """Keep worker output UTF-8 regardless of the Windows console code page."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


_configure_utf8_stdio()


@app.callback()
def main() -> None:
    """网球长回合自动筛选工具。"""


@app.command()
def analyze(
    input_path: Path = typer.Argument(
        ...,
        exists=True,
        readable=True,
        help="单个视频或包含视频的文件夹。",
    ),
    output: Path = typer.Option(
        Path("精选输出"),
        "--output",
        "-o",
        help="精选片段和报告输出目录。",
    ),
    limit_duration: float | None = typer.Option(
        None,
        "--limit-duration",
        min=1.0,
        help="只分析每个视频开头的指定秒数，适合快速校准。",
    ),
    min_rally_duration: float = typer.Option(
        10.0,
        "--min-rally-duration",
        min=0.1,
        help="最短有效对打时长；调大后只保留更长回合。",
    ),
    pre_roll: float = typer.Option(
        2.0,
        "--pre-roll",
        min=0.0,
        help="回合开始前保留秒数。",
    ),
    post_roll: float = typer.Option(
        3.0,
        "--post-roll",
        min=0.0,
        help="回合结束后保留秒数。",
    ),
    end_silence: float = typer.Option(
        3.5,
        "--end-silence",
        min=0.1,
        help="无可信击球后等待多久判定回合结束。",
    ),
    analysis_fps: int = typer.Option(
        12,
        "--analysis-fps",
        min=1,
        max=60,
        help="每秒用于动作分析的画面帧数。",
    ),
    audio_sensitivity: float = typer.Option(
        1.0,
        "--audio-sensitivity",
        min=0.1,
        help="击球声音候选灵敏度。",
    ),
    visual_sensitivity: float = typer.Option(
        1.0,
        "--visual-sensitivity",
        min=0.1,
        help="挥拍动作候选灵敏度。",
    ),
    inference_backend: str = typer.Option(
        "auto",
        "--backend",
        help="推理后端：auto、onnx、torch 或 tensorrt。",
    ),
    inference_precision: str = typer.Option(
        "fp16",
        "--precision",
        help="推理精度：fp16、fp32；int8 仅在完成校准后可用。",
    ),
    inference_batch_size: int = typer.Option(
        16,
        "--batch-size",
        min=1,
        max=64,
        help="GPU 推理批量；RTX 4060 8 GB 建议 16。",
    ),
    require_gpu: bool = typer.Option(
        False,
        "--require-gpu/--allow-cpu",
        help="缺少 CUDA 时停止，或明确警告后回退 CPU。",
    ),
    overwrite_existing: bool = typer.Option(
        False,
        "--overwrite-existing/--keep-existing",
        help="新结果成功后替换同名旧结果，或保留并创建带编号的新目录。",
    ),
    original_quality: bool = typer.Option(
        False,
        "--original-quality/--1080p-output",
        help="保留源分辨率，或默认将超过 1080p 的视频缩小到 1080p 并保持原始帧率。",
    ),
    progress_json: bool = typer.Option(
        False,
        "--progress-json",
        hidden=True,
    ),
    prepare_review: bool = typer.Option(
        False,
        "--prepare-review",
        hidden=True,
        help="生成候选预览清单，等待桌面端人工确认后再发布。",
    ),
) -> None:
    """分析视频并通过 NVENC 输出持续时间较长的回合。"""

    progress_lock = threading.Lock()

    def emit_acceleration(payload: dict[str, object]) -> None:
        if not progress_json:
            return
        with progress_lock:
            typer.echo(_format_acceleration_line(payload))

    try:
        runtime = _check_runtime(require_gpu=require_gpu)
    except RuntimeError as exc:
        typer.echo(f"运行环境检查失败：{exc}", err=True)
        raise typer.Exit(code=2) from exc

    config = AnalysisConfig(
        min_rally_duration=min_rally_duration,
        pre_roll=pre_roll,
        post_roll=post_roll,
        end_silence=end_silence,
        analysis_fps=analysis_fps,
        audio_sensitivity=audio_sensitivity,
        visual_sensitivity=visual_sensitivity,
        inference_backend=inference_backend,
        inference_precision=inference_precision,
        inference_batch_size=inference_batch_size,
        require_gpu=require_gpu,
        gpu_available=runtime.nvenc_available,
        export_original_quality=original_quality,
        overwrite_existing_output=overwrite_existing,
        acceleration_callback=emit_acceleration,
    )
    typer.echo(
        "导出画质：保持源视频分辨率和原始帧率。"
        if original_quality
        else "导出画质：默认最高 1080p，保持原始帧率；1080p 或更低的视频不会放大。"
    )
    emit_acceleration(
        {
            "cuda_available": runtime.cuda_available,
            "nvenc_available": runtime.nvenc_available,
            "device_name": runtime.device_name,
            "inference_backend": "检测中" if runtime.cuda_available else "CPU",
            "decoder": "检测中" if runtime.cuda_available else "OpenCV",
            "encoder": "NVENC" if runtime.nvenc_available else "libx265",
        }
    )

    def emit_progress(update: ProgressUpdate) -> None:
        if not progress_json:
            return
        with progress_lock:
            typer.echo(_format_progress_line(update))

    if prepare_review:
        result = prepare_review_batch(
            input_path,
            output,
            config,
            limit_duration=limit_duration,
            progress_callback=emit_progress if progress_json else None,
        )
    else:
        result = process_batch(
            input_path,
            output,
            config,
            limit_duration=limit_duration,
            progress_callback=emit_progress if progress_json else None,
        )
    if not result.results:
        typer.echo(
            "失败：没有找到支持的视频（支持 MP4、MOV、MKV 和 M4V）。",
            err=True,
        )
        raise typer.Exit(code=1)
    for video_result in result.results:
        if video_result.succeeded:
            verified = sum(record.verified for record in video_result.records)
            if prepare_review:
                typer.echo(
                    f"候选已准备：{video_result.source.name}，"
                    f"共 {verified} 个已验证片段，等待人工确认。"
                )
            else:
                typer.echo(
                    f"完成：{video_result.source.name}，"
                    f"输出 {verified}/{len(video_result.records)} 个已验证片段，"
                    f"目录：{video_result.output_dir}"
                )
        else:
            typer.echo(
                f"失败：{video_result.source.name}：{video_result.error}",
                err=True,
            )

    if prepare_review and result.session is not None:
        typer.echo(
            REVIEW_PREFIX
            + json.dumps(
                {
                    "manifest": str(result.session.manifest_path),
                    "candidate_count": len(result.session.clips),
                },
                ensure_ascii=True,
                separators=(",", ":"),
            )
        )
    typer.echo(f"批处理结束：成功 {result.success_count}，失败 {result.failure_count}。")
    if result.failure_count:
        raise typer.Exit(code=1)


@app.command()
def optimize(
    input_path: Path = typer.Argument(
        ...,
        exists=True,
        readable=True,
        help="用于本机基准测试的单个视频或视频文件夹。",
    ),
    benchmark_seconds: float = typer.Option(
        60.0,
        "--benchmark-seconds",
        min=10.0,
        max=300.0,
        help="每个候选配置分析的视频时长。",
    ),
    progress_json: bool = typer.Option(False, "--progress-json", hidden=True),
) -> None:
    """检测本机硬件，并用真实视频选择最快的可靠配置。"""

    from tennis_video_helper.optimizer import optimize_hardware

    def emit_progress(percent: float, phase: str) -> None:
        if not progress_json:
            typer.echo(f"[{percent:5.1f}%] {phase}")
            return
        update = ProgressUpdate(
            percent=percent,
            phase=phase,
            current_video=Path(input_path),
            video_index=1,
            video_total=1,
        )
        typer.echo(_format_progress_line(update))

    try:
        profile = optimize_hardware(
            input_path,
            benchmark_seconds=benchmark_seconds,
            progress=emit_progress,
        )
    except RuntimeError as exc:
        typer.echo(f"自动优化失败：{exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(
        OPTIMIZATION_PREFIX
        + json.dumps(
            profile.to_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
        )
    )
    typer.echo(
        "自动优化完成："
        f"{profile.inference_backend} {profile.inference_precision.upper()}，"
        f"批量 {profile.inference_batch_size}，"
        f"解码器 {profile.decoder}。"
    )


def _check_runtime(*, require_gpu: bool = False) -> RuntimeCapabilities:
    for executable in ("ffmpeg", "ffprobe"):
        if not media_tool_available(executable):
            raise RuntimeError(
                f"找不到 {executable}。请安装到 PATH，或随程序放入 runtime 目录"
            )

    encoder_check = subprocess.run(
        [media_executable("ffmpeg"), "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if encoder_check.returncode != 0:
        raise RuntimeError("无法读取 FFmpeg 编码器列表")

    cuda_available = False
    device_name = None
    try:
        import torch

        cuda_available = bool(torch.cuda.is_available())
        device_name = torch.cuda.get_device_name(0) if cuda_available else None
    except ImportError:
        try:
            import onnxruntime as ort

            providers = set(ort.get_available_providers())
            cuda_available = bool(
                providers
                & {
                    "TensorrtExecutionProvider",
                    "CUDAExecutionProvider",
                    "DmlExecutionProvider",
                }
            )
            if cuda_available:
                device_name = "ONNX GPU"
        except (ImportError, OSError):
            pass
    nvenc_available = "hevc_nvenc" in encoder_check.stdout
    if require_gpu and not (cuda_available and nvenc_available):
        raise RuntimeError("当前没有显卡驱动或可用 CUDA/NVENC，且已指定 --require-gpu")
    if not nvenc_available and "libx265" not in encoder_check.stdout:
        raise RuntimeError("当前没有可用 NVENC，FFmpeg 也不支持 CPU 编码器 libx265")
    if not cuda_available and not nvenc_available:
        typer.echo(
            "警告：当前没有显卡驱动或可用 CUDA/NVENC，已自动回退 CPU 处理；速度会显著降低。",
            err=True,
        )
    elif not cuda_available:
        typer.echo("警告：CUDA 不可用，姿态推理已回退 CPU；视频仍使用 NVENC 编码。", err=True)
    elif not nvenc_available:
        typer.echo("警告：NVENC 不可用，视频编码已回退 libx265；姿态推理仍使用 CUDA。", err=True)
    return RuntimeCapabilities(cuda_available, nvenc_available, device_name)


def _format_progress_line(update: ProgressUpdate) -> str:
    payload = {
        "percent": round(update.percent, 2),
        "phase": update.phase,
        "current_video": str(update.current_video) if update.current_video else None,
        "video_index": update.video_index,
        "video_total": update.video_total,
    }
    return PROGRESS_PREFIX + json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _format_acceleration_line(payload: dict[str, object]) -> str:
    return ACCELERATION_PREFIX + json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
    )


if __name__ == "__main__":
    app()
