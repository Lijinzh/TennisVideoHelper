import sys
from types import SimpleNamespace

import numpy as np

from tennis_video_helper.vision import (
    PoseDetection,
    analyze_video,
    estimate_global_motion,
    pose_motion_score,
    select_primary_detection,
)


def _pose(*, offset_x: float = 0.0, wrist_shift: float = 0.0) -> np.ndarray:
    keypoints = np.zeros((17, 3), dtype=np.float32)
    keypoints[:, 2] = 1.0
    keypoints[5, :2] = [40 + offset_x, 30]
    keypoints[6, :2] = [60 + offset_x, 30]
    keypoints[7, :2] = [35 + offset_x, 50]
    keypoints[8, :2] = [65 + offset_x, 50]
    keypoints[9, :2] = [30 + offset_x - wrist_shift, 70]
    keypoints[10, :2] = [70 + offset_x + wrist_shift, 70]
    keypoints[11, :2] = [43 + offset_x, 75]
    keypoints[12, :2] = [57 + offset_x, 75]
    return keypoints


def test_select_primary_detection_prefers_large_nearby_person() -> None:
    detections = [
        PoseDetection(np.array([0, 0, 20, 40]), _pose(), 0.9),
        PoseDetection(np.array([10, 10, 110, 210]), _pose(), 0.8),
    ]

    selected = select_primary_detection(detections, previous_center=None)

    assert selected is detections[1]


def test_select_primary_detection_uses_track_continuity() -> None:
    nearby = PoseDetection(np.array([90, 90, 170, 250]), _pose(offset_x=100), 0.8)
    far_larger = PoseDetection(np.array([500, 20, 650, 300]), _pose(offset_x=500), 0.9)

    selected = select_primary_detection(
        [nearby, far_larger],
        previous_center=np.array([130.0, 170.0]),
    )

    assert selected is nearby


def test_pose_motion_score_ignores_camera_translation() -> None:
    previous = _pose()
    translated = _pose(offset_x=25)

    assert pose_motion_score(previous, translated) < 0.01


def test_pose_motion_score_detects_wrist_acceleration() -> None:
    previous = _pose()
    swinging = _pose(wrist_shift=30)

    assert pose_motion_score(previous, swinging) > 0.5


def test_estimate_global_motion_detects_shared_frame_translation() -> None:
    previous = np.zeros((120, 160), dtype=np.uint8)
    previous[20:30, 20:30] = 255
    previous[70:80, 80:90] = 255
    current = np.roll(previous, shift=(2, 4), axis=(0, 1))

    dx, dy = estimate_global_motion(previous, current)

    assert abs(dx - 4) < 1.0
    assert abs(dy - 2) < 1.0


def test_analyze_video_uses_current_fp16_quantize_option(monkeypatch, tmp_path) -> None:
    prediction_options: dict[str, object] = {}

    class FakeCapture:
        def __init__(self, _path: str) -> None:
            self.frames = [np.zeros((120, 160, 3), dtype=np.uint8)]

        def isOpened(self) -> bool:
            return True

        def get(self, _property: int) -> float:
            return 30.0

        def read(self):
            return (True, self.frames.pop(0)) if self.frames else (False, None)

        def release(self) -> None:
            return None

    class FakeModel:
        def __init__(self, _model_path: str) -> None:
            return None

        def predict(self, _frame, **options):
            prediction_options.update(options)
            return [SimpleNamespace(boxes=None, keypoints=None)]

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)))
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=FakeModel))
    monkeypatch.setattr("tennis_video_helper.vision.cv2.VideoCapture", FakeCapture)

    analyze_video(tmp_path / "sample.mp4", SimpleNamespace(analysis_fps=12))

    assert prediction_options["quantize"] == 16
    assert "half" not in prediction_options


def test_analyze_video_uses_real_frame_timestamps_for_variable_fps(monkeypatch, tmp_path) -> None:
    poses = iter(
        [
            [PoseDetection(np.array([0, 0, 100, 100]), _pose(), 0.9)],
            [PoseDetection(np.array([0, 0, 100, 100]), _pose(wrist_shift=30), 0.9)],
        ]
    )

    class FakeCapture:
        def __init__(self, _path: str) -> None:
            self.frames = [
                np.zeros((120, 160, 3), dtype=np.uint8),
                np.zeros((120, 160, 3), dtype=np.uint8),
            ]
            self.timestamps_ms = [0.0, 100.0]
            self.read_count = 0

        def isOpened(self) -> bool:
            return True

        def get(self, property_id: int) -> float:
            import cv2

            if property_id == cv2.CAP_PROP_FPS:
                return 60.0
            if property_id == cv2.CAP_PROP_POS_MSEC:
                return self.timestamps_ms[max(0, self.read_count - 1)]
            return 0.0

        def read(self):
            if self.read_count >= len(self.frames):
                return False, None
            frame = self.frames[self.read_count]
            self.read_count += 1
            return True, frame

        def release(self) -> None:
            return None

    class FakeModel:
        def __init__(self, _model_path: str) -> None:
            return None

        def predict(self, _frame, **_options):
            return [object()]

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)))
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=FakeModel))
    monkeypatch.setattr("tennis_video_helper.vision.cv2.VideoCapture", FakeCapture)
    monkeypatch.setattr("tennis_video_helper.vision._result_to_detections", lambda _result: next(poses))

    events = analyze_video(
        tmp_path / "variable-fps.mp4",
        SimpleNamespace(analysis_fps=60, visual_sensitivity=1.0),
    )

    assert len(events) == 1
    assert events[0].timestamp == 0.1
