"""近端球员选择、姿态运动分析和视频视觉事件生成。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from tennis_video_helper.config import AnalysisConfig
from tennis_video_helper.models import VisualEvent

ARM_KEYPOINTS = np.array([5, 6, 7, 8, 9, 10])
HIP_KEYPOINTS = np.array([11, 12])


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
) -> list[VisualEvent]:
    """使用 CUDA 姿态模型分析视频并生成近端动作事件。"""

    try:
        import torch
        from ultralytics import YOLO
    except ImportError as exc:
        raise VisualAnalysisError("视觉依赖未正确安装") from exc

    if not torch.cuda.is_available():
        raise VisualAnalysisError("未检测到可用的 CUDA 显卡")

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise VisualAnalysisError(f"无法打开视频：{path}")

    source_fps = float(capture.get(cv2.CAP_PROP_FPS))
    if source_fps <= 0:
        capture.release()
        raise VisualAnalysisError(f"无法读取视频帧率：{path}")

    model = YOLO(model_path)
    events: list[VisualEvent] = []
    previous_pose: np.ndarray | None = None
    previous_center: np.ndarray | None = None
    previous_gray: np.ndarray | None = None
    frame_index = 0
    previous_timestamp = -1.0
    next_analysis_timestamp = 0.0

    try:
        while True:
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

            analysis_frame = _resize_for_analysis(frame)
            gray = cv2.cvtColor(analysis_frame, cv2.COLOR_BGR2GRAY)
            global_dx, global_dy = (
                estimate_global_motion(previous_gray, gray)
                if previous_gray is not None
                else (0.0, 0.0)
            )
            result = model.predict(
                analysis_frame,
                device=0,
                imgsz=640,
                quantize=16,
                verbose=False,
            )[0]
            detections = _result_to_detections(result)
            selected = select_primary_detection(detections, previous_center)
            if selected is not None:
                motion = (
                    pose_motion_score(previous_pose, selected.keypoints)
                    if previous_pose is not None
                    else 0.0
                )
                confidence = float(
                    np.clip(motion * config.visual_sensitivity, 0.0, 1.0)
                )
                if confidence >= 0.12:
                    events.append(
                        VisualEvent(
                            timestamp=timestamp,
                            confidence=confidence,
                            motion_score=motion,
                            global_motion=float(np.hypot(global_dx, global_dy)),
                        )
                    )
                previous_pose = selected.keypoints
                previous_center = selected.center
            previous_gray = gray
    finally:
        capture.release()

    return events


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
