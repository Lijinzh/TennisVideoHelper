"""近端球员选择、姿态运动分析和视频视觉事件生成。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import logging
from pathlib import Path
import shutil
import tempfile
from typing import Callable

import cv2
import numpy as np

from tennis_video_helper.config import AnalysisConfig
from tennis_video_helper.models import VisualEvent

ARM_KEYPOINTS = np.array([5, 6, 7, 8, 9, 10])
HIP_KEYPOINTS = np.array([11, 12])
LOGGER = logging.getLogger(__name__)


class VisualAnalysisError(RuntimeError):
    """姿态模型或视频视觉分析失败。"""


@dataclass(frozen=True, slots=True)
class PoseDetection:
    """单个人体框及 COCO 17 点姿态。"""

    box: np.ndarray
    keypoints: np.ndarray
    confidence: float

    @property
    def center(self) -> np.ndarray:
        x1, y1, x2, y2 = self.box
        return np.array([(x1 + x2) / 2, (y1 + y2) / 2], dtype=np.float32)

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.box
        return max(0.0, float(x2 - x1)) * max(0.0, float(y2 - y1))


@dataclass(frozen=True, slots=True)
class PendingFrame:
    """等待批量姿态推理的单帧及其时序信息。"""

    timestamp: float
    frame: np.ndarray
    global_motion: float


def select_primary_detection(
    detections: list[PoseDetection],
    previous_center: np.ndarray | None,
) -> PoseDetection | None:
    """选择面积大且与上一位置连续的近端球员。"""

    if not detections:
        return None
    if previous_center is None:
        return max(detections, key=lambda item: item.area * item.confidence)

    def tracking_score(item: PoseDetection) -> float:
        area_score = np.log1p(item.area) + item.confidence
        distance_penalty = float(np.linalg.norm(item.center - previous_center)) / 100.0
        return area_score - distance_penalty

    return max(detections, key=tracking_score)


def pose_motion_score(previous: np.ndarray, current: np.ndarray) -> float:
    """计算相对躯干坐标中的手臂运动，抵消整体画面平移。"""

    previous_normalized = _normalize_pose(previous)
    current_normalized = _normalize_pose(current)
    if previous_normalized is None or current_normalized is None:
        return 0.0

    deltas = np.linalg.norm(
        current_normalized[ARM_KEYPOINTS, :2]
        - previous_normalized[ARM_KEYPOINTS, :2],
        axis=1,
    )
    visibility = np.minimum(
        previous[ARM_KEYPOINTS, 2],
        current[ARM_KEYPOINTS, 2],
    )
    visible_deltas = deltas[visibility >= 0.35]
    return float(np.max(visible_deltas)) if visible_deltas.size else 0.0


def estimate_global_motion(
    previous_gray: np.ndarray,
    current_gray: np.ndarray,
) -> tuple[float, float]:
    """通过背景稀疏光流估计相机的整体平移。"""

    features = cv2.goodFeaturesToTrack(
        previous_gray,
        maxCorners=120,
        qualityLevel=0.01,
        minDistance=8,
        blockSize=7,
    )
    if features is None or len(features) < 2:
        return 0.0, 0.0

    tracked, status, _ = cv2.calcOpticalFlowPyrLK(
        previous_gray,
        current_gray,
        features,
        None,
    )
    if tracked is None or status is None:
        return 0.0, 0.0

    valid = status.reshape(-1).astype(bool)
    if np.count_nonzero(valid) < 2:
        return 0.0, 0.0

    displacement = tracked.reshape(-1, 2)[valid] - features.reshape(-1, 2)[valid]
    dx, dy = np.median(displacement, axis=0)
    return float(dx), float(dy)


def analyze_video(
    path: Path,
    config: AnalysisConfig,
    *,
    model_path: str = "yolo11n-pose.pt",
    limit_duration: float | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> list[VisualEvent]:
    """使用批量姿态模型分析视频并生成近端动作事件。"""

    try:
        import torch
        from ultralytics import YOLO
    except ImportError as exc:
        raise VisualAnalysisError("视觉依赖未正确安装") from exc

    cuda_available = bool(torch.cuda.is_available())
    if getattr(config, "require_gpu", False) and not cuda_available:
        raise VisualAnalysisError("未检测到可用的 CUDA 显卡，且当前要求必须使用 GPU")

    precision = getattr(config, "inference_precision", "fp16")
    device: int | str = 0 if cuda_available else "cpu"
    use_half = cuda_available and precision == "fp16"
    configured_batch_size = max(1, int(getattr(config, "inference_batch_size", 16)))
    batch_size = configured_batch_size if cuda_available else min(4, configured_batch_size)
    _configure_torch_runtime(torch, cuda_available)
    if not cuda_available:
        LOGGER.warning(
            "当前没有可用的 CUDA 显卡或显卡驱动，已自动回退到 CPU 处理；速度会显著降低。"
        )

    resolved_model_path = _resolve_inference_model_path(
        Path(model_path),
        config,
        cuda_available=cuda_available,
        yolo_class=YOLO,
        torch_module=torch,
        input_shape=_model_input_shape(path),
    )
    using_tensorrt = resolved_model_path.suffix.lower() == ".engine"
    model = YOLO(str(resolved_model_path))
    if cuda_available:
        try:
            events = _analyze_video_nvdec(
                path,
                config,
                model,
                torch_module=torch,
                batch_size=batch_size,
                use_fp16=use_half and not using_tensorrt,
                using_tensorrt=using_tensorrt,
                limit_duration=limit_duration,
                progress_callback=progress_callback,
            )
        except Exception as exc:
            from tennis_video_helper.nvdec import NvdecUnavailable

            if not isinstance(exc, NvdecUnavailable):
                raise
            LOGGER.warning("NVDEC 不可用，已回退到 OpenCV 解码：%s", exc)
        else:
            LOGGER.info("已启用 NVIDIA NVDEC GPU 解码")
            return events

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise VisualAnalysisError(f"无法打开视频：{path}")

    source_fps = float(capture.get(cv2.CAP_PROP_FPS))
    if source_fps <= 0:
        capture.release()
        raise VisualAnalysisError(f"无法读取视频帧率：{path}")
    frame_count = max(0.0, float(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
    source_duration = frame_count / source_fps if frame_count > 0 else 0.0
    effective_duration = (
        min(source_duration, limit_duration)
        if limit_duration is not None and source_duration > 0
        else (limit_duration or source_duration)
    )

    events: list[VisualEvent] = []
    previous_pose: np.ndarray | None = None
    previous_center: np.ndarray | None = None
    previous_gray: np.ndarray | None = None
    frame_index = 0
    previous_timestamp = -1.0
    next_analysis_timestamp = 0.0
    pending_frames: list[PendingFrame] = []
    supports_grab = callable(getattr(capture, "grab", None)) and callable(
        getattr(capture, "retrieve", None)
    )

    def flush_pending_frames() -> None:
        nonlocal previous_pose, previous_center
        if not pending_frames:
            return
        inference_frames = [item.frame for item in pending_frames]
        if cuda_available and len(inference_frames) < batch_size:
            inference_frames.extend(
                [inference_frames[-1]] * (batch_size - len(inference_frames))
            )
        predictions = _predict_pose_batch(
            model,
            inference_frames,
            torch_module=torch,
            device=device,
            use_fp16=use_half,
        )
        predictions = predictions[: len(pending_frames)]
        if len(predictions) != len(pending_frames):
            raise VisualAnalysisError(
                "姿态模型返回的结果数量与输入批次不一致："
                f"{len(predictions)} != {len(pending_frames)}"
            )
        previous_pose, previous_center = _consume_prediction_results(
            predictions,
            [(item.timestamp, item.global_motion) for item in pending_frames],
            config,
            events,
            previous_pose,
            previous_center,
        )
        pending_frames.clear()
        if progress_callback is not None and effective_duration > 0:
            progress_callback(min(1.0, previous_timestamp / effective_duration))

    try:
        while True:
            if supports_grab:
                if not capture.grab():
                    break
                frame = None
            else:
                ok, frame = capture.read()
                if not ok:
                    break
            timestamp = _capture_timestamp(
                capture,
                frame_index,
                source_fps,
                previous_timestamp,
            )
            frame_index += 1
            previous_timestamp = timestamp
            if limit_duration is not None and timestamp > limit_duration:
                break
            if timestamp + 1e-9 < next_analysis_timestamp:
                continue
            next_analysis_timestamp = timestamp + 1.0 / config.analysis_fps
            if supports_grab:
                ok, frame = capture.retrieve()
                if not ok:
                    break
            if frame is None:
                raise VisualAnalysisError("视频解码器没有返回有效画面")

            analysis_frame = _resize_for_analysis(frame)
            gray = cv2.cvtColor(analysis_frame, cv2.COLOR_BGR2GRAY)
            global_dx, global_dy = (
                estimate_global_motion(previous_gray, gray)
                if previous_gray is not None
                else (0.0, 0.0)
            )
            pending_frames.append(
                PendingFrame(
                    timestamp=timestamp,
                    frame=analysis_frame,
                    global_motion=float(np.hypot(global_dx, global_dy)),
                )
            )
            previous_gray = gray
            if len(pending_frames) >= batch_size:
                flush_pending_frames()
        flush_pending_frames()
    finally:
        capture.release()

    if progress_callback is not None:
        progress_callback(1.0)
    return events


def _model_input_shape(path: Path) -> tuple[int, int]:
    """计算与 Ultralytics rect letterbox 一致的固定 TensorRT 输入尺寸。"""

    capture = cv2.VideoCapture(str(path))
    try:
        width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
        height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    finally:
        capture.release()
    if width <= 0 or height <= 0:
        return 640, 640
    scale = min(640 / height, 640 / width)
    resized_height = round(height * scale)
    resized_width = round(width * scale)
    pad_height = (640 - resized_height) % 32
    pad_width = (640 - resized_width) % 32
    return resized_height + pad_height, resized_width + pad_width


def _resolve_inference_model_path(
    model_path: Path,
    config: AnalysisConfig,
    *,
    cuda_available: bool,
    yolo_class,
    torch_module,
    input_shape: tuple[int, int],
) -> Path:
    backend = getattr(config, "inference_backend", "auto")
    precision = getattr(config, "inference_precision", "fp16")
    if model_path.suffix.lower() == ".engine":
        if not cuda_available:
            raise VisualAnalysisError("TensorRT 引擎必须使用 NVIDIA CUDA 显卡")
        return model_path
    if precision == "int8":
        raise VisualAnalysisError(
            "INT8 必须先使用真实网球素材完成校准；当前版本不会使用未校准 INT8 以免漏检长回合"
        )
    if backend == "torch" or not cuda_available:
        return model_path

    missing = [
        name
        for name in ("tensorrt", "onnx", "onnxslim", "modelopt")
        if importlib.util.find_spec(name) is None
    ]
    if missing:
        message = (
            "TensorRT 组件未完整安装（缺少 "
            + "、".join(missing)
            + "）；请运行 uv sync --extra gpu-max"
        )
        if backend == "tensorrt":
            raise VisualAnalysisError(message)
        LOGGER.info("%s，自动使用 PyTorch CUDA", message)
        return model_path
    if not model_path.is_file():
        if backend == "tensorrt":
            raise VisualAnalysisError(f"无法为不存在的模型构建 TensorRT 引擎：{model_path}")
        return model_path

    engine_path = _engine_cache_path(
        model_path,
        config,
        torch_module=torch_module,
        input_shape=input_shape,
    )
    if engine_path.is_file():
        return engine_path

    try:
        _build_tensorrt_engine(
            model_path,
            engine_path,
            config,
            yolo_class=yolo_class,
            input_shape=input_shape,
        )
    except Exception as exc:  # noqa: BLE001 - auto 模式允许安全回退
        message = f"TensorRT 引擎构建失败：{exc}"
        if backend == "tensorrt":
            raise VisualAnalysisError(message) from exc
        LOGGER.warning("%s；自动使用 PyTorch CUDA", message)
        return model_path
    return engine_path


def _engine_cache_path(
    model_path: Path,
    config: AnalysisConfig,
    *,
    torch_module,
    input_shape: tuple[int, int],
) -> Path:
    import tensorrt

    model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()[:12]
    capability = "".join(str(value) for value in torch_module.cuda.get_device_capability(0))
    tensorrt_version = ".".join(tensorrt.__version__.split(".")[:2])
    cache_root = Path.home() / ".cache" / "tennis-video-helper" / "engines"
    name = (
        f"{model_path.stem}-{model_hash}-sm{capability}-trt{tensorrt_version}-"
        f"{input_shape[0]}x{input_shape[1]}-b{config.inference_batch_size}-"
        f"{config.inference_precision}.engine"
    )
    return cache_root / name


def _build_tensorrt_engine(
    model_path: Path,
    engine_path: Path,
    config: AnalysisConfig,
    *,
    yolo_class,
    input_shape: tuple[int, int],
) -> None:
    engine_path.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.warning(
        "首次运行正在构建 TensorRT %s 引擎，通常需要数分钟；缓存位置：%s",
        config.inference_precision.upper(),
        engine_path,
    )
    with tempfile.TemporaryDirectory(prefix="tennis-video-helper-trt-") as temporary:
        temporary_model = Path(temporary) / model_path.name
        shutil.copy2(model_path, temporary_model)
        exported = yolo_class(str(temporary_model)).export(
            format="engine",
            device=0,
            imgsz=input_shape,
            batch=config.inference_batch_size,
            quantize=16 if config.inference_precision == "fp16" else None,
            workspace=4,
            dynamic=False,
            simplify=True,
            verbose=False,
        )
        exported_path = Path(exported)
        if not exported_path.is_file():
            raise VisualAnalysisError("Ultralytics 没有生成 TensorRT 引擎文件")
        staging_path = engine_path.with_suffix(".engine.staging")
        shutil.copy2(exported_path, staging_path)
        staging_path.replace(engine_path)
    LOGGER.info("TensorRT 引擎已缓存：%s", engine_path)


def _analyze_video_nvdec(
    path: Path,
    config: AnalysisConfig,
    model,
    *,
    torch_module,
    batch_size: int,
    use_fp16: bool,
    using_tensorrt: bool,
    limit_duration: float | None,
    progress_callback: Callable[[float], None] | None,
) -> list[VisualEvent]:
    from tennis_video_helper.nvdec import iter_nvdec_batches

    batches = iter_nvdec_batches(
        path,
        analysis_fps=config.analysis_fps,
        batch_size=batch_size,
        limit_duration=limit_duration,
        torch_module=torch_module,
        use_fp16=use_fp16,
        square_input=False,
    )
    events: list[VisualEvent] = []
    previous_pose: np.ndarray | None = None
    previous_center: np.ndarray | None = None
    predictor = None
    for batch in batches:
        if predictor is None:
            warmup_source = (
                torch_module.zeros_like(batch.tensor)
                if using_tensorrt
                else batch.original_images[0]
            )
            model.predict(
                warmup_source,
                device=0,
                imgsz=640,
                quantize=16 if use_fp16 else None,
                verbose=False,
            )
            predictor = model.predictor
        predictor.batch = (
            [f"nvdec-frame-{index}" for index in range(batch_size)],
            list(batch.original_images),
            [""] * batch_size,
        )
        with torch_module.inference_mode():
            raw_predictions = predictor.inference(batch.tensor)
            predictions = predictor.postprocess(
                raw_predictions,
                batch.tensor,
                list(batch.original_images),
            )[: len(batch.timestamps)]
        previous_pose, previous_center = _consume_prediction_results(
            predictions,
            [(timestamp, 0.0) for timestamp in batch.timestamps],
            config,
            events,
            previous_pose,
            previous_center,
        )
        if progress_callback is not None:
            progress_callback(batch.progress)
    if progress_callback is not None:
        progress_callback(1.0)
    return events


def _consume_prediction_results(
    predictions,
    frame_signals: list[tuple[float, float]],
    config: AnalysisConfig,
    events: list[VisualEvent],
    previous_pose: np.ndarray | None,
    previous_center: np.ndarray | None,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    if len(predictions) != len(frame_signals):
        raise VisualAnalysisError(
            "姿态模型返回的结果数量与输入批次不一致："
            f"{len(predictions)} != {len(frame_signals)}"
        )
    for result, (timestamp, global_motion) in zip(
        predictions,
        frame_signals,
        strict=True,
    ):
        detections = _result_to_detections(result)
        selected = select_primary_detection(detections, previous_center)
        if selected is None:
            continue
        motion = (
            pose_motion_score(previous_pose, selected.keypoints)
            if previous_pose is not None
            else 0.0
        )
        confidence = float(np.clip(motion * config.visual_sensitivity, 0.0, 1.0))
        if confidence >= 0.12:
            events.append(
                VisualEvent(
                    timestamp=timestamp,
                    confidence=confidence,
                    motion_score=motion,
                    global_motion=global_motion,
                )
            )
        previous_pose = selected.keypoints
        previous_center = selected.center
    return previous_pose, previous_center


def _predict_pose_batch(
    model,
    frames: list[np.ndarray],
    *,
    torch_module,
    device: int | str,
    use_fp16: bool,
):
    """绕过逐次数据源初始化，直接执行预处理、CUDA 推理和后处理。"""

    quantize = 16 if use_fp16 else None
    if device == "cpu":
        return model.predict(
            frames,
            device="cpu",
            imgsz=640,
            quantize=None,
            batch=len(frames),
            verbose=False,
        )

    predictor = getattr(model, "predictor", None)
    if predictor is None:
        model.predict(
            frames[0],
            device=device,
            imgsz=640,
            quantize=quantize,
            verbose=False,
        )
        predictor = model.predictor

    predictor.batch = (
        [f"memory-frame-{index}" for index in range(len(frames))],
        frames,
        [""] * len(frames),
    )
    with torch_module.inference_mode():
        tensor = predictor.preprocess(frames)
        raw_predictions = predictor.inference(tensor)
        return predictor.postprocess(raw_predictions, tensor, frames)


def _configure_torch_runtime(torch_module, cuda_available: bool) -> None:
    """启用适合固定尺寸推理的 CUDA 性能选项。"""

    if not cuda_available:
        return
    backends = getattr(torch_module, "backends", None)
    cudnn = getattr(backends, "cudnn", None)
    if cudnn is not None:
        cudnn.benchmark = False
        cudnn.allow_tf32 = True
    cuda_backend = getattr(backends, "cuda", None)
    matmul = getattr(cuda_backend, "matmul", None)
    if matmul is not None:
        matmul.allow_tf32 = True


def _capture_timestamp(
    capture: cv2.VideoCapture,
    frame_index: int,
    source_fps: float,
    previous_timestamp: float,
) -> float:
    """优先使用容器帧时间戳，异常时退回平均帧率估算。"""

    timestamp = float(capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000.0
    if np.isfinite(timestamp) and timestamp >= 0:
        if frame_index == 0 or timestamp > previous_timestamp:
            return timestamp

    fallback = frame_index / source_fps
    if fallback > previous_timestamp:
        return fallback
    return previous_timestamp + 1.0 / source_fps


def _normalize_pose(keypoints: np.ndarray) -> np.ndarray | None:
    pose = np.asarray(keypoints, dtype=np.float32)
    if pose.shape != (17, 3):
        return None
    hips = pose[HIP_KEYPOINTS]
    shoulders = pose[[5, 6]]
    if np.min(hips[:, 2]) < 0.35 or np.min(shoulders[:, 2]) < 0.35:
        return None

    hip_center = np.mean(hips[:, :2], axis=0)
    shoulder_center = np.mean(shoulders[:, :2], axis=0)
    torso_length = float(np.linalg.norm(shoulder_center - hip_center))
    if torso_length < 1e-6:
        return None

    normalized = pose.copy()
    normalized[:, :2] = (normalized[:, :2] - hip_center) / torso_length
    return normalized


def _resize_for_analysis(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    if height <= 720:
        return frame
    scale = 720 / height
    return cv2.resize(
        frame,
        (max(2, round(width * scale)), 720),
        interpolation=cv2.INTER_AREA,
    )


def _result_to_detections(result) -> list[PoseDetection]:
    if result.boxes is None or result.keypoints is None:
        return []
    boxes = result.boxes.xyxy.detach().cpu().numpy()
    confidences = result.boxes.conf.detach().cpu().numpy()
    keypoints_xy = result.keypoints.xy.detach().cpu().numpy()
    keypoints_conf = result.keypoints.conf.detach().cpu().numpy()

    detections: list[PoseDetection] = []
    for box, confidence, points, point_confidence in zip(
        boxes,
        confidences,
        keypoints_xy,
        keypoints_conf,
        strict=True,
    ):
        keypoints = np.column_stack((points, point_confidence)).astype(np.float32)
        detections.append(
            PoseDetection(
                box=np.asarray(box, dtype=np.float32),
                keypoints=keypoints,
                confidence=float(confidence),
            )
        )
    return detections
