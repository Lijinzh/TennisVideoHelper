import sys
from types import SimpleNamespace

import numpy as np
import pytest

from tennis_video_helper.vision import (
    PoseDetection,
    PoseStrokeDetector,
    RacketCandidate,
    _racket_confirmation_score,
    analyze_video,
    estimate_global_motion,
    is_ball_pickup_pose,
    pose_motion_score,
    pose_posture_score,
    select_primary_detection,
)
from tennis_video_helper.models import VisualEvent


def _pose(*, offset_x: float = 0.0, wrist_shift: float = 0.0) -> np.ndarray:
    keypoints = np.zeros((17, 3), dtype=np.float32)
    keypoints[:, 2] = 1.0
    keypoints[0, :2] = [50 + offset_x, 10]
    keypoints[5, :2] = [40 + offset_x, 30]
    keypoints[6, :2] = [60 + offset_x, 30]
    keypoints[7, :2] = [35 + offset_x, 50]
    keypoints[8, :2] = [65 + offset_x, 50]
    keypoints[9, :2] = [30 + offset_x - wrist_shift, 70]
    keypoints[10, :2] = [70 + offset_x + wrist_shift, 70]
    keypoints[11, :2] = [43 + offset_x, 75]
    keypoints[12, :2] = [57 + offset_x, 75]
    keypoints[13, :2] = [42 + offset_x, 105]
    keypoints[14, :2] = [58 + offset_x, 105]
    keypoints[15, :2] = [40 + offset_x, 135]
    keypoints[16, :2] = [60 + offset_x, 135]
    return keypoints


def _pickup_pose(*, wrist_shift: float = 0.0) -> np.ndarray:
    keypoints = _pose(wrist_shift=wrist_shift)
    keypoints[0, :2] = [84, 55]
    keypoints[5, :2] = [80, 68]
    keypoints[6, :2] = [100, 68]
    keypoints[7, :2] = [76, 83]
    keypoints[8, :2] = [96, 83]
    keypoints[9, :2] = [70 - wrist_shift, 112]
    keypoints[10, :2] = [90 + wrist_shift, 112]
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


def test_pose_posture_score_rejects_bending_to_pick_up_ball() -> None:
    assert pose_posture_score(_pose()) > 0.8
    assert pose_posture_score(_pickup_pose()) < 0.45
    assert is_ball_pickup_pose(_pickup_pose()) is True


def test_pose_stroke_detector_requires_upright_swing_trajectory() -> None:
    detector = PoseStrokeDetector(SimpleNamespace(visual_sensitivity=1.0))

    assert detector.observe(0.0, _pose(), 0.0) is None
    event = detector.observe(0.2, _pose(wrist_shift=30), 0.0)

    assert event is not None
    assert event.posture_score > 0.8
    assert event.arm_motion_score > event.leg_motion_score


def test_pose_stroke_detector_rejects_pickup_even_when_arms_move() -> None:
    detector = PoseStrokeDetector(SimpleNamespace(visual_sensitivity=1.0))

    assert detector.observe(0.0, _pickup_pose(), 0.0) is None
    assert detector.observe(0.2, _pickup_pose(wrist_shift=35), 0.0) is None


def test_pose_stroke_detector_rejects_running_arm_swing() -> None:
    detector = PoseStrokeDetector(SimpleNamespace(visual_sensitivity=1.0))
    running = _pose(wrist_shift=12)
    running[13, 0] -= 22
    running[15, 0] -= 26
    running[14, 0] += 22
    running[16, 0] += 26

    assert detector.observe(0.0, _pose(), 0.0) is None
    assert detector.observe(0.2, running, 0.0) is None


def test_pose_stroke_detector_rejects_person_walking_into_camera() -> None:
    detector = PoseStrokeDetector(SimpleNamespace(visual_sensitivity=1.0))
    close_box = np.array([20.0, 20.0, 300.0, 650.0], dtype=np.float32)

    assert detector.observe(
        0.0,
        _pose(),
        0.0,
        box=close_box,
        frame_height=720,
    ) is None
    assert detector.observe(
        0.2,
        _pose(wrist_shift=40),
        0.0,
        box=close_box,
        frame_height=720,
    ) is None


def test_racket_confirmation_requires_detection_near_moving_wrist() -> None:
    candidate = RacketCandidate(
        event=VisualEvent(1.0, 0.9, 0.9, 0.0),
        frame=np.zeros((120, 160, 3), dtype=np.uint8),
        wrist_points=(np.array([80.0, 60.0], dtype=np.float32),),
        person_height=100.0,
        frame_index=0,
    )
    near = SimpleNamespace(
        box=np.array([85.0, 55.0, 110.0, 90.0], dtype=np.float32),
        confidence=0.6,
    )
    far = SimpleNamespace(
        box=np.array([140.0, 100.0, 155.0, 118.0], dtype=np.float32),
        confidence=0.9,
    )

    assert _racket_confirmation_score(candidate, [near]) == 0.6
    assert _racket_confirmation_score(candidate, [far]) == 0.0


def test_estimate_global_motion_detects_shared_frame_translation() -> None:
    previous = np.zeros((120, 160), dtype=np.uint8)
    previous[20:30, 20:30] = 255
    previous[70:80, 80:90] = 255
    current = np.roll(previous, shift=(2, 4), axis=(0, 1))

    dx, dy = estimate_global_motion(previous, current)

    assert abs(dx - 4) < 1.0
    assert abs(dy - 2) < 1.0


def test_analyze_video_batches_cuda_fp16_predictions(monkeypatch, tmp_path) -> None:
    prediction_calls: list[tuple[int, int | str, bool]] = []
    progress_updates: list[float] = []

    class FakeCapture:
        def __init__(self, _path: str) -> None:
            self.frames = [
                np.zeros((120, 160, 3), dtype=np.uint8),
                np.zeros((120, 160, 3), dtype=np.uint8),
                np.zeros((120, 160, 3), dtype=np.uint8),
                np.zeros((120, 160, 3), dtype=np.uint8),
            ]

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

    def fake_predict_batch(
        _model,
        frames,
        *,
        torch_module,
        device,
        use_fp16,
    ):
        prediction_calls.append((len(frames), device, use_fp16))
        return [SimpleNamespace(boxes=None, keypoints=None) for _ in frames]

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)))
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=FakeModel))
    monkeypatch.setattr("tennis_video_helper.vision.cv2.VideoCapture", FakeCapture)
    monkeypatch.setattr("tennis_video_helper.vision._predict_pose_batch", fake_predict_batch)

    analyze_video(
        tmp_path / "sample.mp4",
        SimpleNamespace(
            analysis_fps=30,
            inference_batch_size=2,
            inference_backend="torch",
            inference_precision="fp16",
            require_gpu=False,
        ),
        progress_callback=progress_updates.append,
    )

    assert [size for size, _device, _fp16 in prediction_calls] == [2, 2]
    assert all(device == 0 for _size, device, _fp16 in prediction_calls)
    assert all(use_fp16 is True for _size, _device, use_fp16 in prediction_calls)
    assert progress_updates[-1] == 1.0


def test_analyze_video_falls_back_to_cpu_explicitly(monkeypatch, tmp_path) -> None:
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

        def predict(self, frames, **options):
            prediction_options.update(options)
            return [SimpleNamespace(boxes=None, keypoints=None) for _ in frames]

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=FakeModel))
    monkeypatch.setattr("tennis_video_helper.vision.cv2.VideoCapture", FakeCapture)

    analyze_video(
        tmp_path / "sample.mp4",
        SimpleNamespace(
            analysis_fps=30,
            inference_batch_size=16,
            inference_backend="torch",
            inference_precision="fp16",
            require_gpu=False,
        ),
    )

    assert prediction_options["device"] == "cpu"
    assert prediction_options["quantize"] is None


def test_analyze_video_rejects_cpu_when_gpu_is_required(monkeypatch, tmp_path) -> None:
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=object))

    with pytest.raises(Exception, match="CUDA"):
        analyze_video(
            tmp_path / "sample.mp4",
            SimpleNamespace(
                analysis_fps=30,
                inference_batch_size=16,
                inference_backend="torch",
                inference_precision="fp16",
                require_gpu=True,
            ),
        )


def test_analyze_video_uses_real_frame_timestamps_for_variable_fps(monkeypatch, tmp_path) -> None:
    poses = iter(
        [
            [PoseDetection(np.array([0, 0, 100, 60]), _pose(), 0.9)],
            [PoseDetection(np.array([0, 0, 100, 60]), _pose(wrist_shift=30), 0.9)],
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

        def predict(self, frames, **_options):
            return [object() for _ in frames]

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)))
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=FakeModel))
    monkeypatch.setattr("tennis_video_helper.vision.cv2.VideoCapture", FakeCapture)
    monkeypatch.setattr(
        "tennis_video_helper.vision._predict_pose_batch",
        lambda model, frames, **_options: model.predict(frames),
    )
    monkeypatch.setattr("tennis_video_helper.vision._result_to_detections", lambda _result: next(poses))

    events = analyze_video(
        tmp_path / "variable-fps.mp4",
        SimpleNamespace(
            analysis_fps=60,
            visual_sensitivity=1.0,
            inference_backend="torch",
        ),
    )

    assert len(events) == 1
    assert events[0].timestamp == 0.1
