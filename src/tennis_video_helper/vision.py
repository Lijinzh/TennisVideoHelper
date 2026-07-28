"""近端球员选择、姿态运动分析和视频视觉事件生成。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import hashlib
import importlib.util
import logging
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Callable

import cv2
import numpy as np

from tennis_video_helper.config import AnalysisConfig
from tennis_video_helper.models import VisualEvent

ARM_KEYPOINTS = np.array([5, 6, 7, 8, 9, 10])
HIP_KEYPOINTS = np.array([11, 12])
SHOULDER_KEYPOINTS = np.array([5, 6])
LEFT_ARM = (5, 7, 9)
RIGHT_ARM = (6, 8, 10)
LEFT_LEG = (11, 13, 15)
RIGHT_LEG = (12, 14, 16)
KEYPOINT_CONFIDENCE = 0.35
MIN_SWING_WINDOW_SECONDS = 0.07
MAX_SWING_WINDOW_SECONDS = 0.45
POSE_HISTORY_SECONDS = 0.55
POSE_TRACK_GAP_SECONDS = 0.75
VISUAL_EVENT_COOLDOWN_SECONDS = 0.75
MIN_STANDING_POSTURE_SCORE = 0.45
MIN_STROKE_CONFIDENCE = 0.30
MAX_PLAYER_FRAME_HEIGHT_RATIO = 0.55
RACKET_DETECTION_CONFIDENCE = 0.12
RACKET_WRIST_DISTANCE_RATIO = 0.35
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
    frame_height: int


@dataclass(frozen=True, slots=True)
class PoseFrameSample:
    """用于识别完整挥拍轨迹的标准化骨架帧。"""

    timestamp: float
    keypoints: np.ndarray
    posture_score: float


@dataclass(frozen=True, slots=True)
class StrokeMotionMetrics:
    """一次骨架时间差中的挥拍运动分解。"""

    stroke_score: float
    arm_motion: float
    secondary_arm_motion: float
    leg_motion: float
    stroke_type: str


@dataclass(frozen=True, slots=True)
class RacketCandidate:
    """等待球拍目标检测确认的骨架挥拍候选。"""

    event: VisualEvent
    frame: np.ndarray
    wrist_points: tuple[np.ndarray, ...]
    person_height: float
    frame_index: int


class RacketVerifier:
    """只对骨架候选帧运行轻量球拍检测，避免整段双模型推理。"""

    def __init__(self, config: AnalysisConfig, model_path: Path) -> None:
        self.enabled = bool(getattr(config, "require_racket_confirmation", False))
        self._model_path = model_path
        self._model = None
        self._uses_onnx = False

    def verify(
        self,
        candidates: list[RacketCandidate],
        *,
        cuda_tensor=None,
    ) -> list[VisualEvent]:
        if not candidates:
            return []
        if not self.enabled:
            return [candidate.event for candidate in candidates]
        self._ensure_model()
        frames = [candidate.frame for candidate in candidates]
        if cuda_tensor is not None:
            if not self._uses_onnx or not self._model.supports_cuda_tensor:
                from tennis_video_helper.nvdec import NvdecUnavailable

                raise NvdecUnavailable(
                    "GPU 解码路径无法执行球拍确认，已切换到 OpenCV 实帧验证"
                )
            indices = [candidate.frame_index for candidate in candidates]
            predictions = self._model.predict_cuda_tensor(
                cuda_tensor[indices],
                frames,
            )
        elif self._uses_onnx:
            predictions = self._model.predict(frames)
        else:
            import torch

            cuda_available = bool(torch.cuda.is_available())
            results = self._model.predict(
                frames,
                device=0 if cuda_available else "cpu",
                imgsz=640,
                quantize=16 if cuda_available else None,
                batch=len(frames),
                classes=[38],
                conf=0.10,
                verbose=False,
            )
            from tennis_video_helper.onnx_object import RacketDetection

            predictions = []
            for result in results:
                boxes = getattr(result, "boxes", None)
                if boxes is None:
                    predictions.append([])
                    continue
                xyxy = boxes.xyxy.detach().cpu().numpy()
                confidence = boxes.conf.detach().cpu().numpy()
                predictions.append(
                    [
                        RacketDetection(
                            box=np.asarray(box, dtype=np.float32),
                            confidence=float(score),
                        )
                        for box, score in zip(xyxy, confidence, strict=True)
                    ]
                )

        verified: list[VisualEvent] = []
        for candidate, detections in zip(candidates, predictions, strict=True):
            score = _racket_confirmation_score(candidate, detections)
            if score >= RACKET_DETECTION_CONFIDENCE:
                verified.append(replace(candidate.event, racket_confidence=score))
        return verified

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        onnx_path = _resolve_optional_model_path(self._model_path.with_suffix(".onnx"))
        if onnx_path is not None and importlib.util.find_spec("onnxruntime") is not None:
            from tennis_video_helper.onnx_object import OnnxRacketModel

            self._model = OnnxRacketModel(onnx_path)
            self._uses_onnx = True
            return
        pt_path = _resolve_optional_model_path(self._model_path.with_suffix(".pt"))
        if pt_path is None:
            raise VisualAnalysisError("缺少 yolo11n.onnx/yolo11n.pt 球拍检测模型")
        from ultralytics import YOLO

        self._model = YOLO(str(pt_path))


class PoseStrokeDetector:
    """以人体相对坐标和短时轨迹确认真实挥拍。"""

    def __init__(self, config: AnalysisConfig) -> None:
        self._config = config
        self._history: deque[PoseFrameSample] = deque()
        self._last_observed_timestamp: float | None = None

    def note_missing(self, timestamp: float) -> None:
        if (
            self._last_observed_timestamp is not None
            and timestamp - self._last_observed_timestamp > POSE_TRACK_GAP_SECONDS
        ):
            self._history.clear()

    def observe(
        self,
        timestamp: float,
        keypoints: np.ndarray,
        global_motion: float,
        *,
        box: np.ndarray | None = None,
        frame_height: float | None = None,
    ) -> VisualEvent | None:
        if box is not None and frame_height and frame_height > 0:
            box_height = max(0.0, float(box[3] - box[1]))
            if box_height / frame_height > MAX_PLAYER_FRAME_HEIGHT_RATIO:
                # 球员已走到镜头前或人体框严重裁切，不属于正常底线/网前击球区。
                self._history.clear()
                self._last_observed_timestamp = timestamp
                return None

        normalized = _normalize_pose(keypoints)
        if normalized is None:
            self.note_missing(timestamp)
            return None

        if (
            self._last_observed_timestamp is not None
            and timestamp - self._last_observed_timestamp > POSE_TRACK_GAP_SECONDS
        ):
            self._history.clear()
        self._last_observed_timestamp = timestamp

        posture_score = pose_posture_score(keypoints)
        references = [
            sample
            for sample in self._history
            if MIN_SWING_WINDOW_SECONDS
            <= timestamp - sample.timestamp
            <= MAX_SWING_WINDOW_SECONDS
            and sample.posture_score >= MIN_STANDING_POSTURE_SCORE
        ]
        metrics = max(
            (
                stroke_motion_metrics(sample.keypoints, normalized)
                for sample in references
            ),
            key=lambda item: item.stroke_score,
            default=None,
        )

        self._history.append(
            PoseFrameSample(timestamp, normalized, posture_score)
        )
        while (
            self._history
            and timestamp - self._history[0].timestamp > POSE_HISTORY_SECONDS
        ):
            self._history.popleft()

        if metrics is None or posture_score < MIN_STANDING_POSTURE_SCORE:
            return None

        sensitivity = float(getattr(self._config, "visual_sensitivity", 1.0))
        adjusted_motion = metrics.stroke_score * sensitivity
        confidence = float(np.clip((adjusted_motion - 0.22) / 0.50, 0.0, 1.0))
        confidence *= 0.55 + 0.45 * posture_score
        if confidence < MIN_STROKE_CONFIDENCE:
            return None

        return VisualEvent(
            timestamp=timestamp,
            confidence=confidence,
            motion_score=metrics.stroke_score,
            global_motion=global_motion,
            posture_score=posture_score,
            arm_motion_score=metrics.arm_motion,
            leg_motion_score=metrics.leg_motion,
            stroke_type=metrics.stroke_type,
        )


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


def pose_posture_score(keypoints: np.ndarray) -> float:
    """判断球员是否保持可挥拍的站立/准备姿态。"""

    pose = np.asarray(keypoints, dtype=np.float32)
    if pose.shape != (17, 3):
        return 0.0
    shoulders = pose[SHOULDER_KEYPOINTS]
    hips = pose[HIP_KEYPOINTS]
    if (
        np.min(shoulders[:, 2]) < KEYPOINT_CONFIDENCE
        or np.min(hips[:, 2]) < KEYPOINT_CONFIDENCE
    ):
        return 0.0

    shoulder_center = np.mean(shoulders[:, :2], axis=0)
    hip_center = np.mean(hips[:, :2], axis=0)
    torso_vector = shoulder_center - hip_center
    torso_length = float(np.linalg.norm(torso_vector))
    shoulder_width = float(np.linalg.norm(shoulders[0, :2] - shoulders[1, :2]))
    if torso_length < 1e-6 or shoulder_width < 1e-6:
        return 0.0

    # 图像坐标向下为正。肩膀必须明显高于髋部；躯干越接近水平，越像弯腰捡球。
    verticality = float((hip_center[1] - shoulder_center[1]) / torso_length)
    vertical_score = float(np.clip((verticality - 0.42) / 0.43, 0.0, 1.0))
    torso_ratio = torso_length / shoulder_width
    length_score = float(np.clip((torso_ratio - 0.55) / 0.75, 0.0, 1.0))

    head_score = 0.7
    nose = pose[0]
    if nose[2] >= KEYPOINT_CONFIDENCE:
        head_height = float((hip_center[1] - nose[1]) / torso_length)
        head_score = float(np.clip((head_height - 0.55) / 0.80, 0.0, 1.0))

    return float(
        np.clip(
            0.65 * vertical_score + 0.25 * length_score + 0.10 * head_score,
            0.0,
            1.0,
        )
    )


def is_ball_pickup_pose(keypoints: np.ndarray) -> bool:
    """用明显前倾/折叠的躯干过滤低头弯腰捡球。"""

    return pose_posture_score(keypoints) < MIN_STANDING_POSTURE_SCORE


def stroke_motion_metrics(
    previous_normalized: np.ndarray,
    current_normalized: np.ndarray,
) -> StrokeMotionMetrics:
    """分离手臂挥拍、双手协同和跑动腿部摆动。"""

    arm_metrics = [
        _arm_motion_metrics(previous_normalized, current_normalized, LEFT_ARM),
        _arm_motion_metrics(previous_normalized, current_normalized, RIGHT_ARM),
    ]
    ranked = sorted(
        enumerate(arm_metrics),
        key=lambda item: item[1][0],
        reverse=True,
    )
    dominant_index, dominant = ranked[0]
    secondary = ranked[1][1]
    leg_motion = max(
        _leg_motion(previous_normalized, current_normalized, LEFT_LEG),
        _leg_motion(previous_normalized, current_normalized, RIGHT_LEG),
    )

    wrist_motion, lateral_sweep, elbow_motion, extension_change = dominant
    arm_specific_motion = max(0.0, wrist_motion - 0.45 * leg_motion)
    stroke_score = (
        0.62 * arm_specific_motion
        + 0.22 * lateral_sweep
        + 0.08 * extension_change
        + 0.08 * elbow_motion
    )
    secondary_wrist_motion = secondary[0]
    two_handed = (
        secondary_wrist_motion >= 0.22
        and secondary_wrist_motion >= 0.65 * max(wrist_motion, 1e-6)
    )
    if two_handed:
        stroke_score += 0.08 * secondary_wrist_motion
        stroke_type = "双手挥拍"
    else:
        stroke_type = "左手单手挥拍" if dominant_index == 0 else "右手单手挥拍"

    return StrokeMotionMetrics(
        stroke_score=float(stroke_score),
        arm_motion=float(wrist_motion),
        secondary_arm_motion=float(secondary_wrist_motion),
        leg_motion=float(leg_motion),
        stroke_type=stroke_type,
    )


def _arm_motion_metrics(
    previous: np.ndarray,
    current: np.ndarray,
    indices: tuple[int, int, int],
) -> tuple[float, float, float, float]:
    shoulder_index, elbow_index, wrist_index = indices
    if min(
        previous[shoulder_index, 2],
        current[shoulder_index, 2],
        previous[wrist_index, 2],
        current[wrist_index, 2],
    ) < KEYPOINT_CONFIDENCE:
        return 0.0, 0.0, 0.0, 0.0

    previous_wrist = previous[wrist_index, :2] - previous[shoulder_index, :2]
    current_wrist = current[wrist_index, :2] - current[shoulder_index, :2]
    wrist_delta = current_wrist - previous_wrist
    wrist_motion = float(np.linalg.norm(wrist_delta))
    lateral_sweep = float(abs(wrist_delta[0]))
    extension_change = float(
        abs(np.linalg.norm(current_wrist) - np.linalg.norm(previous_wrist))
    )

    elbow_motion = 0.0
    if min(previous[elbow_index, 2], current[elbow_index, 2]) >= KEYPOINT_CONFIDENCE:
        previous_elbow = previous[elbow_index, :2] - previous[shoulder_index, :2]
        current_elbow = current[elbow_index, :2] - current[shoulder_index, :2]
        elbow_motion = float(np.linalg.norm(current_elbow - previous_elbow))
    return wrist_motion, lateral_sweep, elbow_motion, extension_change


def _leg_motion(
    previous: np.ndarray,
    current: np.ndarray,
    indices: tuple[int, int, int],
) -> float:
    hip_index, knee_index, ankle_index = indices
    motions: list[float] = []
    for joint_index in (knee_index, ankle_index):
        if min(
            previous[hip_index, 2],
            current[hip_index, 2],
            previous[joint_index, 2],
            current[joint_index, 2],
        ) < KEYPOINT_CONFIDENCE:
            continue
        previous_joint = previous[joint_index, :2] - previous[hip_index, :2]
        current_joint = current[joint_index, :2] - current[hip_index, :2]
        motions.append(float(np.linalg.norm(current_joint - previous_joint)))
    return max(motions, default=0.0)


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
    equipment_model_path: str = "yolo11n.pt",
    limit_duration: float | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> list[VisualEvent]:
    """使用批量姿态模型分析视频并生成近端动作事件。"""

    racket_verifier = RacketVerifier(config, Path(equipment_model_path))
    backend = getattr(config, "inference_backend", "auto")
    onnx_path = _resolve_onnx_model_path(Path(model_path))
    use_onnx = backend == "onnx" or (
        backend == "auto"
        and onnx_path is not None
        and importlib.util.find_spec("onnxruntime") is not None
    )
    if use_onnx:
        from tennis_video_helper.onnx_pose import OnnxPoseModel

        if onnx_path is None:
            raise VisualAnalysisError("轻量安装版缺少 yolo11n-pose.onnx 模型")
        try:
            model = OnnxPoseModel(onnx_path)
        except (OSError, RuntimeError) as exc:
            raise VisualAnalysisError(f"ONNX 姿态运行时初始化失败：{exc}") from exc
        cuda_available = False
        accelerated = model.accelerated
        if getattr(config, "require_gpu", False) and not accelerated:
            raise VisualAnalysisError("未检测到可用的 GPU 推理后端，且当前要求必须使用 GPU")
        precision = "fp32"
        device: int | str = "cpu"
        use_half = False
        configured_batch_size = max(1, int(getattr(config, "inference_batch_size", 8)))
        batch_size = configured_batch_size if accelerated else min(4, configured_batch_size)
        _report_acceleration(
            config,
            cuda_available=accelerated,
            inference_backend=model.backend_name,
            precision="GPU" if accelerated else "FP32",
            decoder="OpenCV",
        )
    else:
        try:
            import torch
            from ultralytics import YOLO
        except ImportError as exc:
            raise VisualAnalysisError(f"视觉依赖未正确安装：{exc}") from exc

        cuda_available = bool(torch.cuda.is_available())
        if getattr(config, "require_gpu", False) and not cuda_available:
            raise VisualAnalysisError("未检测到可用的 CUDA 显卡，且当前要求必须使用 GPU")

        precision = getattr(config, "inference_precision", "fp16")
        device = 0 if cuda_available else "cpu"
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
        _report_acceleration(
            config,
            cuda_available=cuda_available,
            inference_backend=(
                "TensorRT"
                if using_tensorrt
                else ("PyTorch CUDA" if cuda_available else "CPU")
            ),
            precision=(precision.upper() if cuda_available else "FP32"),
        )
        model = YOLO(str(resolved_model_path))
    using_tensorrt = False if use_onnx else using_tensorrt
    if (
        use_onnx
        and model.provider == "CUDAExecutionProvider"
        and bool(getattr(config, "enable_onnx_nvdec", False))
    ):
        try:
            events = _analyze_video_onnx_nvdec(
                path,
                config,
                model,
                batch_size=batch_size,
                racket_verifier=racket_verifier,
                limit_duration=limit_duration,
                progress_callback=progress_callback,
            )
        except Exception as exc:
            from tennis_video_helper.nvdec import NvdecUnavailable

            if not isinstance(exc, NvdecUnavailable):
                raise
            LOGGER.warning(
                "NVDEC 未启用，已切换到 OpenCV CPU 解码；GPU 姿态推理仍保持启用：%s",
                exc,
            )
            _report_acceleration(config, decoder="OpenCV CPU")
        else:
            LOGGER.info("已启用 NVIDIA ThreadedDecoder NVDEC + ONNX I/O Binding")
            _report_acceleration(config, decoder="Threaded NVDEC")
            return events
    if cuda_available and not use_onnx:
        try:
            events = _analyze_video_nvdec(
                path,
                config,
                model,
                torch_module=torch,
                batch_size=batch_size,
                use_fp16=use_half and not using_tensorrt,
                using_tensorrt=using_tensorrt,
                racket_verifier=racket_verifier,
                limit_duration=limit_duration,
                progress_callback=progress_callback,
            )
        except Exception as exc:
            from tennis_video_helper.nvdec import NvdecUnavailable

            if not isinstance(exc, NvdecUnavailable):
                raise
            LOGGER.warning(
                "NVDEC 未启用，已切换到 OpenCV CPU 解码；GPU 姿态推理仍保持启用：%s",
                exc,
            )
            _report_acceleration(config, decoder="OpenCV CPU")
        else:
            LOGGER.info("已启用 NVIDIA ThreadedDecoder NVDEC GPU 解码")
            _report_acceleration(config, decoder="Threaded NVDEC")
            return events

    if not cuda_available:
        _report_acceleration(config, decoder="OpenCV")
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
    stroke_detector = PoseStrokeDetector(config)
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
        nonlocal previous_center
        if not pending_frames:
            return
        inference_frames = [item.frame for item in pending_frames]
        if cuda_available and len(inference_frames) < batch_size:
            inference_frames.extend(
                [inference_frames[-1]] * (batch_size - len(inference_frames))
            )
        predictions = (
            model.predict(inference_frames)
            if use_onnx
            else _predict_pose_batch(
                model,
                inference_frames,
                torch_module=torch,
                device=device,
                use_fp16=use_half,
            )
        )
        predictions = predictions[: len(pending_frames)]
        if len(predictions) != len(pending_frames):
            raise VisualAnalysisError(
                "姿态模型返回的结果数量与输入批次不一致："
                f"{len(predictions)} != {len(pending_frames)}"
            )
        previous_center = _consume_prediction_results(
            predictions,
            [
                (item.timestamp, item.global_motion, float(item.frame_height))
                for item in pending_frames
            ],
            config,
            events,
            stroke_detector,
            racket_verifier,
            [item.frame for item in pending_frames],
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
                    frame_height=analysis_frame.shape[0],
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


def _resolve_onnx_model_path(model_path: Path) -> Path | None:
    candidate = model_path.with_suffix(".onnx")
    if candidate.is_file():
        return candidate
    bundled = _bundled_resource("models", candidate.name)
    return bundled


def _resolve_optional_model_path(model_path: Path) -> Path | None:
    if model_path.is_file():
        return model_path
    return _bundled_resource("models", model_path.name)


def _resolve_inference_model_path(
    model_path: Path,
    config: AnalysisConfig,
    *,
    cuda_available: bool,
    yolo_class,
    torch_module,
    input_shape: tuple[int, int],
) -> Path:
    if not model_path.is_file():
        bundled_model = _bundled_resource("models", model_path.name)
        if bundled_model is not None:
            model_path = bundled_model
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
    bundled_engine = _bundled_resource("engines", engine_path.name)
    if bundled_engine is not None:
        return bundled_engine

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


def _bundled_resource(directory: str, name: str) -> Path | None:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if not bundle_root:
        return None
    candidate = Path(bundle_root) / directory / name
    return candidate if candidate.is_file() else None


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
    racket_verifier: RacketVerifier,
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
    stroke_detector = PoseStrokeDetector(config)
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
        previous_center = _consume_prediction_results(
            predictions,
            [
                (timestamp, 0.0, float(image.shape[0]))
                for timestamp, image in zip(
                    batch.timestamps,
                    batch.original_images,
                )
            ],
            config,
            events,
            stroke_detector,
            racket_verifier,
            list(batch.original_images[: len(batch.timestamps)]),
            previous_center,
            cuda_tensor=batch.tensor,
        )
        if progress_callback is not None:
            progress_callback(batch.progress)
    if progress_callback is not None:
        progress_callback(1.0)
    return events


def _analyze_video_onnx_nvdec(
    path: Path,
    config: AnalysisConfig,
    model,
    *,
    batch_size: int,
    racket_verifier: RacketVerifier,
    limit_duration: float | None,
    progress_callback: Callable[[float], None] | None,
) -> list[VisualEvent]:
    import torch

    from tennis_video_helper.nvdec import iter_nvdec_batches

    batches = iter_nvdec_batches(
        path,
        analysis_fps=config.analysis_fps,
        batch_size=batch_size,
        limit_duration=limit_duration,
        torch_module=torch,
        use_fp16=False,
        square_input=True,
    )
    events: list[VisualEvent] = []
    stroke_detector = PoseStrokeDetector(config)
    previous_center: np.ndarray | None = None
    for batch in batches:
        actual_count = len(batch.timestamps)
        predictions = model.predict_cuda_tensor(
            batch.tensor,
            batch.original_images,
        )[:actual_count]
        previous_center = _consume_prediction_results(
            predictions,
            [
                (timestamp, 0.0, float(image.shape[0]))
                for timestamp, image in zip(
                    batch.timestamps,
                    batch.original_images,
                )
            ],
            config,
            events,
            stroke_detector,
            racket_verifier,
            list(batch.original_images[: len(batch.timestamps)]),
            previous_center,
            cuda_tensor=batch.tensor,
        )
        if progress_callback is not None:
            progress_callback(batch.progress)
    if progress_callback is not None:
        progress_callback(1.0)
    return events


def _consume_prediction_results(
    predictions,
    frame_signals: list[tuple[float, float, float]],
    config: AnalysisConfig,
    events: list[VisualEvent],
    stroke_detector: PoseStrokeDetector,
    racket_verifier: RacketVerifier,
    frames: list[np.ndarray],
    previous_center: np.ndarray | None,
    *,
    cuda_tensor=None,
) -> np.ndarray | None:
    if len(predictions) != len(frame_signals) or len(frames) != len(frame_signals):
        raise VisualAnalysisError(
            "姿态模型、帧信号与画面数量不一致："
            f"{len(predictions)} / {len(frame_signals)} / {len(frames)}"
        )
    racket_candidates: list[RacketCandidate] = []
    for frame_index, (result, signal, frame) in enumerate(
        zip(predictions, frame_signals, frames, strict=True)
    ):
        timestamp, global_motion, frame_height = signal
        detections = _result_to_detections(result)
        selected = select_primary_detection(detections, previous_center)
        if selected is None:
            stroke_detector.note_missing(timestamp)
            continue
        candidate = stroke_detector.observe(
            timestamp,
            selected.keypoints,
            global_motion,
            box=selected.box,
            frame_height=frame_height,
        )
        if candidate is not None:
            wrist_indices = _moving_wrist_indices(candidate.stroke_type)
            wrist_points = tuple(
                np.asarray(selected.keypoints[index, :2], dtype=np.float32)
                for index in wrist_indices
                if selected.keypoints[index, 2] >= KEYPOINT_CONFIDENCE
            )
            if wrist_points:
                racket_candidates.append(
                    RacketCandidate(
                        event=candidate,
                        frame=frame,
                        wrist_points=wrist_points,
                        person_height=max(1.0, float(selected.box[3] - selected.box[1])),
                        frame_index=frame_index,
                    )
                )
        previous_center = selected.center
    for verified_event in racket_verifier.verify(
        racket_candidates,
        cuda_tensor=cuda_tensor,
    ):
        _append_or_replace_visual_event(events, verified_event)
    return previous_center


def _append_or_replace_visual_event(
    events: list[VisualEvent],
    candidate: VisualEvent,
) -> None:
    """一次挥拍只保留短时窗口中的最高分帧。"""

    if (
        events
        and candidate.timestamp - events[-1].timestamp
        < VISUAL_EVENT_COOLDOWN_SECONDS
    ):
        if candidate.confidence > events[-1].confidence:
            events[-1] = candidate
        return
    events.append(candidate)


def _moving_wrist_indices(stroke_type: str) -> tuple[int, ...]:
    if stroke_type.startswith("左手"):
        return (9,)
    if stroke_type.startswith("右手"):
        return (10,)
    return (9, 10)


def _racket_confirmation_score(
    candidate: RacketCandidate,
    detections,
) -> float:
    margin = candidate.person_height * RACKET_WRIST_DISTANCE_RATIO
    best_score = 0.0
    for detection in detections:
        box = np.asarray(detection.box, dtype=np.float32)
        for wrist in candidate.wrist_points:
            dx = max(float(box[0] - wrist[0]), 0.0, float(wrist[0] - box[2]))
            dy = max(float(box[1] - wrist[1]), 0.0, float(wrist[1] - box[3]))
            if float(np.hypot(dx, dy)) <= margin:
                best_score = max(best_score, float(detection.confidence))
    return best_score


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


def _report_acceleration(config: AnalysisConfig, **payload: object) -> None:
    """把实际选中的推理和解码后端上报给 CLI/UI。"""

    callback = getattr(config, "acceleration_callback", None)
    if callback is not None:
        callback(payload)


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
    if isinstance(result, list):
        return [
            PoseDetection(item.box, item.keypoints, item.confidence)
            for item in result
        ]
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
