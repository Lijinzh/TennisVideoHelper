"""可选的 NVIDIA NVDEC 采样解码与 GPU 预处理。"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import importlib.util
import math
import os
from pathlib import Path

import cv2
import numpy as np

from tennis_video_helper.media import probe_media


class NvdecUnavailable(RuntimeError):
    """当前环境无法使用 PyNvVideoCodec/NVDEC。"""


@dataclass(frozen=True, slots=True)
class NvdecBatch:
    tensor: object
    timestamps: tuple[float, ...]
    original_images: tuple[np.ndarray, ...]
    progress: float


_DLL_DIRECTORIES: list[object] = []
_NVDEC_UNSUPPORTED_CODECS = {
    "prores": "Apple ProRes",
    "dnxhd": "Avid DNxHD/DNxHR",
    "cfhd": "GoPro CineForm",
}


def nvdec_unsupported_reason(codec: str) -> str | None:
    """返回已知不能由 NVIDIA NVDEC 解码的中间编码格式说明。"""

    label = _NVDEC_UNSUPPORTED_CODECS.get(codec.casefold())
    if label is None:
        return None
    return (
        f"源视频编码为 {label}，NVIDIA NVDEC 不支持该格式；"
        "将使用 CPU/OpenCV 解码，CUDA 姿态推理和 NVENC 导出仍可继续使用"
    )


def iter_nvdec_batches(
    path: Path,
    *,
    analysis_fps: int,
    batch_size: int,
    limit_duration: float | None,
    torch_module,
    use_fp16: bool,
    square_input: bool = False,
):
    """按分析帧率直接在 GPU 上解码、旋转、缩放并生成固定尺寸批次。"""

    try:
        media = probe_media(path)
    except Exception:  # noqa: BLE001 - 预检查失败时仍交给实际解码器判断
        pass
    else:
        unsupported_reason = nvdec_unsupported_reason(media.video_codec)
        if unsupported_reason:
            raise NvdecUnavailable(unsupported_reason)

    nvc = _import_pynvvideocodec(torch_module)
    try:
        decoder = _create_decoder(nvc, path, batch_size=batch_size)
        metadata = decoder.get_stream_metadata()
    except Exception as exc:  # noqa: BLE001 - 可选后端失败时由调用方回退
        raise NvdecUnavailable(f"NVDEC 无法打开视频：{exc}") from exc

    source_fps = float(metadata.average_fps)
    total_frames = int(metadata.num_frames)
    if source_fps <= 0 or total_frames <= 0:
        raise NvdecUnavailable("NVDEC 无法读取有效的帧率或帧数")
    progress_frame_total = _progress_frame_total(
        total_frames,
        source_fps,
        limit_duration,
    )

    orientation, display_width, display_height = _display_geometry(path, metadata)
    analysis_scale = min(1.0, 720 / display_height)
    analysis_height = max(2, round(display_height * analysis_scale))
    analysis_width = max(2, round(display_width * analysis_scale))
    placeholder = np.empty((analysis_height, analysis_width, 3), dtype=np.uint8)
    try:
        pending_tensor = None
        pending_timestamps: list[float] = []
        source_index = 0
        decode_batch_size = max(32, batch_size)
        first_pts: int | None = None
        pts_scale = 0.0
        nominal_frame_duration = 1.0 / source_fps
        previous_timestamp = -1.0
        next_analysis_timestamp = 0.0
        reached_limit = False
        while source_index < total_frames and not reached_limit:
            request_size = _decode_request_size(
                source_index,
                total_frames,
                decode_batch_size,
            )
            decoded_frames = decoder.get_batch_frames(request_size)
            if not decoded_frames:
                break
            if first_pts is None:
                first_pts, pts_scale, nominal_frame_duration = _timestamp_calibration(
                    path,
                    decoded_frames,
                    source_fps,
                )
            selected: list[tuple[float, object]] = []
            for offset, frame in enumerate(decoded_frames):
                pts = int(frame.getPTS())
                timestamp = (pts - first_pts) * pts_scale
                if not np.isfinite(timestamp) or timestamp <= previous_timestamp:
                    timestamp = (
                        source_index + offset
                    ) * nominal_frame_duration
                    if timestamp <= previous_timestamp:
                        timestamp = previous_timestamp + nominal_frame_duration
                previous_timestamp = timestamp
                if limit_duration is not None and timestamp > limit_duration:
                    reached_limit = True
                    break
                if timestamp + 1e-9 < next_analysis_timestamp:
                    continue
                next_analysis_timestamp = timestamp + 1.0 / analysis_fps
                selected.append((timestamp, frame))
            source_index += len(decoded_frames)
            if not selected:
                continue
            chunk = torch_module.stack(
                [torch_module.from_dlpack(frame) for _, frame in selected]
            )
            pending_tensor = (
                chunk
                if pending_tensor is None
                else torch_module.cat((pending_tensor, chunk))
            )
            pending_timestamps.extend(timestamp for timestamp, _ in selected)
            while len(pending_timestamps) >= batch_size:
                yield _build_batch(
                    pending_tensor[:batch_size],
                    pending_timestamps[:batch_size],
                    placeholder,
                    orientation,
                    torch_module,
                    use_fp16,
                    batch_size,
                    square_input,
                    min(1.0, source_index / progress_frame_total),
                )
                pending_tensor = pending_tensor[batch_size:]
                del pending_timestamps[:batch_size]

        if pending_timestamps and pending_tensor is not None:
            yield _build_batch(
                pending_tensor,
                pending_timestamps,
                placeholder,
                orientation,
                torch_module,
                use_fp16,
                batch_size,
                square_input,
                min(1.0, source_index / progress_frame_total),
            )
    except Exception as exc:  # noqa: BLE001 - 解码期异常统一转换为可回退错误
        raise NvdecUnavailable(f"NVDEC 解码失败：{exc}") from exc
    finally:
        end = getattr(decoder, "end", None)
        if callable(end):
            end()


def _create_decoder(nvc, path: Path, *, batch_size: int):
    """优先使用后台线程解码，并为推理保留数个预取批次。"""

    common = {
        "gpu_id": 0,
        "use_device_memory": True,
        "output_color_type": nvc.OutputColorType.RGBP,
    }
    threaded = getattr(nvc, "ThreadedDecoder", None)
    if threaded is not None:
        return threaded(
            str(path),
            buffer_size=max(64, batch_size * 4),
            decoder_cache_size=2,
            **common,
        )
    return nvc.SimpleDecoder(str(path), **common)


def _decode_request_size(
    source_index: int,
    total_frames: int,
    preferred_batch_size: int,
) -> int:
    """限制最后一次解码请求，避免访问视频结尾之后的帧索引。"""

    return min(preferred_batch_size, max(0, total_frames - source_index))


def _progress_frame_total(
    total_frames: int,
    source_fps: float,
    limit_duration: float | None,
) -> int:
    """返回完整分析或限时分析实际需要推进的帧数。"""

    if limit_duration is None:
        return total_frames
    return min(total_frames, max(1, math.ceil(limit_duration * source_fps)))


def _import_pynvvideocodec(torch_module):
    spec = importlib.util.find_spec("PyNvVideoCodec")
    if spec is None or not spec.submodule_search_locations:
        raise NvdecUnavailable(
            "未安装可选组件 PyNvVideoCodec；请运行 uv sync --extra gpu-max"
        )

    if os.name == "nt":
        package_dir = Path(next(iter(spec.submodule_search_locations))).resolve()
        torch_file = getattr(torch_module, "__file__", None)
        if torch_file is None:
            raise NvdecUnavailable("无法定位 PyTorch CUDA 运行库")
        torch_lib = Path(torch_file).resolve().parent / "lib"
        for directory in (package_dir, torch_lib):
            if directory.is_dir():
                _DLL_DIRECTORIES.append(os.add_dll_directory(str(directory)))
    try:
        return importlib.import_module("PyNvVideoCodec")
    except (ImportError, OSError, RuntimeError) as exc:
        raise NvdecUnavailable(f"PyNvVideoCodec 无法加载：{exc}") from exc


def _display_geometry(path: Path, metadata) -> tuple[int, int, int]:
    capture = cv2.VideoCapture(str(path))
    try:
        orientation = int(round(capture.get(cv2.CAP_PROP_ORIENTATION_META))) % 360
        width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
        height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    finally:
        capture.release()

    if width <= 0 or height <= 0:
        width = int(metadata.width)
        height = int(metadata.height)
        if orientation in {90, 270}:
            width, height = height, width
    return orientation, width, height


def _timestamp_calibration(
    path: Path,
    decoded_frames,
    source_fps: float,
) -> tuple[int, float, float]:
    capture = cv2.VideoCapture(str(path))
    timestamps: list[float] = []
    try:
        for _ in range(min(8, len(decoded_frames))):
            ok, _frame = capture.read()
            if not ok:
                break
            timestamps.append(float(capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000.0)
    finally:
        capture.release()

    first_pts = int(decoded_frames[0].getPTS())
    ratios: list[float] = []
    frame_durations: list[float] = []
    for index in range(1, min(len(timestamps), len(decoded_frames))):
        timestamp_delta = timestamps[index] - timestamps[index - 1]
        pts_delta = int(decoded_frames[index].getPTS()) - int(
            decoded_frames[index - 1].getPTS()
        )
        if timestamp_delta > 0 and pts_delta > 0:
            ratios.append(timestamp_delta / pts_delta)
            frame_durations.append(timestamp_delta)
    if not ratios:
        return first_pts, 1.0 / source_fps, 1.0 / source_fps
    return first_pts, float(np.median(ratios)), float(np.median(frame_durations))


def _build_batch(
    tensor,
    timestamps: list[float],
    placeholder: np.ndarray,
    orientation: int,
    torch_module,
    use_fp16: bool,
    batch_size: int,
    square_input: bool,
    progress: float,
) -> NvdecBatch:
    actual_count = len(timestamps)
    if actual_count < batch_size:
        tensor = torch_module.cat(
            (
                tensor,
                tensor[-1:].expand(batch_size - actual_count, -1, -1, -1),
            )
        )
    tensor = _orient_tensor(tensor, orientation, torch_module)
    tensor = tensor.to(
        dtype=torch_module.float16 if use_fp16 else torch_module.float32
    ).div_(255)
    tensor = _resize_for_analysis_tensor(tensor, torch_module)
    tensor = _letterbox_tensor(tensor, torch_module, square_input=square_input)
    return NvdecBatch(
        tensor=tensor,
        timestamps=tuple(timestamps),
        original_images=(placeholder,) * batch_size,
        progress=progress,
    )


def _orient_tensor(tensor, orientation: int, torch_module):
    if orientation == 90:
        return torch_module.rot90(tensor, k=-1, dims=(2, 3))
    if orientation == 180:
        return torch_module.rot90(tensor, k=2, dims=(2, 3))
    if orientation == 270:
        return torch_module.rot90(tensor, k=1, dims=(2, 3))
    return tensor


def _letterbox_tensor(tensor, torch_module, *, square_input: bool = False):
    functional = torch_module.nn.functional
    height, width = tensor.shape[2:]
    scale = min(640 / height, 640 / width)
    resized_height = round(height * scale)
    resized_width = round(width * scale)
    tensor = functional.interpolate(
        tensor,
        size=(resized_height, resized_width),
        mode="bilinear",
        align_corners=False,
    )
    pad_height = 640 - resized_height
    pad_width = 640 - resized_width
    if not square_input:
        pad_height %= 32
        pad_width %= 32
    top = round(pad_height / 2 - 0.1)
    bottom = round(pad_height / 2 + 0.1)
    left = round(pad_width / 2 - 0.1)
    right = round(pad_width / 2 + 0.1)
    return functional.pad(
        tensor,
        (left, right, top, bottom),
        value=114 / 255,
    )


def _resize_for_analysis_tensor(tensor, torch_module):
    """在 GPU 上复刻 OpenCV 路径的 720p INTER_AREA 分析缩放。"""

    height, width = tensor.shape[2:]
    if height <= 720:
        return tensor
    resized_width = max(2, round(width * 720 / height))
    return torch_module.nn.functional.interpolate(
        tensor,
        size=(720, resized_width),
        mode="area",
    )
