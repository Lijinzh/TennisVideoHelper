"""命令行入口。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import typer

from tennis_video_helper.config import AnalysisConfig
from tennis_video_helper.pipeline import process_batch

app = typer.Typer(
    name="tennis-video-helper",
    help="使用音画融合筛选并切分网球长回合。",
    no_args_is_help=True,
)


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
) -> None:
    """分析视频并通过 NVENC 输出持续时间较长的回合。"""

    try:
        _check_runtime()
    except RuntimeError as exc:
        typer.echo(f"运行环境检查失败：{exc}", err=True)
        raise typer.Exit(code=2) from exc

    config = AnalysisConfig()
    result = process_batch(
        input_path,
        output,
        config,
        limit_duration=limit_duration,
    )
    for video_result in result.results:
        if video_result.succeeded:
            verified = sum(record.verified for record in video_result.records)
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

    typer.echo(
        f"批处理结束：成功 {result.success_count}，失败 {result.failure_count}。"
    )
    if result.failure_count:
        raise typer.Exit(code=1)


def _check_runtime() -> None:
    for executable in ("ffmpeg", "ffprobe"):
        if shutil.which(executable) is None:
            raise RuntimeError(f"找不到 {executable}，请先安装并加入 PATH")

    encoder_check = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if encoder_check.returncode != 0 or "hevc_nvenc" not in encoder_check.stdout:
        raise RuntimeError("当前 FFmpeg 不支持 hevc_nvenc")

    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch CUDA 依赖尚未安装") from exc
    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch 未检测到 CUDA 显卡")


if __name__ == "__main__":
    app()
