"""Lightweight YOLO pose inference through ONNX Runtime."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import sys

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class OnnxPoseDetection:
    box: np.ndarray
    keypoints: np.ndarray
    confidence: float


@dataclass(frozen=True, slots=True)
class _Letterbox:
    scale: float
    pad_x: float
    pad_y: float
    width: int
    height: int


class OnnxPoseModel:
    """Small runtime adapter for the exported YOLO11 pose model."""

    def __init__(self, model_path: Path) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError("缺少轻量 ONNX Runtime 运行组件") from exc

        self._dll_directory = _add_torch_cuda_dll_directory()
        available = set(ort.get_available_providers())
        if (
            "CUDAExecutionProvider" in available
            and hasattr(ort, "preload_dlls")
            and "torch" not in sys.modules
        ):
            try:
                # ONNX Runtime can reuse the CUDA/cuDNN DLLs shipped with PyTorch.
                # Without this call Windows reports CUDA as available but silently
                # falls back to CPU because cublasLt/cudnn cannot be found.
                ort.preload_dlls()
            except (OSError, RuntimeError):
                pass
        preferred = (
            "CUDAExecutionProvider",
            "DmlExecutionProvider",
            "CPUExecutionProvider",
        )
        providers = [name for name in preferred if name in available]
        if not providers:
            raise RuntimeError("ONNX Runtime 没有可用的执行后端")
        session_options = ort.SessionOptions()
        session_options.log_severity_level = 3
        self.session = ort.InferenceSession(
            str(model_path),
            sess_options=session_options,
            providers=providers,
        )
        self._ort = ort
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.provider = self.session.get_providers()[0]

    @property
    def accelerated(self) -> bool:
        return self.provider != "CPUExecutionProvider"

    @property
    def backend_name(self) -> str:
        names = {
            "TensorrtExecutionProvider": "ONNX TensorRT",
            "CUDAExecutionProvider": "ONNX CUDA",
            "DmlExecutionProvider": "ONNX DirectML",
            "CPUExecutionProvider": "ONNX CPU",
        }
        return names.get(self.provider, self.provider)

    def predict(self, frames: list[np.ndarray]) -> list[list[OnnxPoseDetection]]:
        tensors: list[np.ndarray] = []
        transforms: list[_Letterbox] = []
        for frame in frames:
            tensor, transform = _preprocess(frame)
            tensors.append(tensor)
            transforms.append(transform)
        batch = np.stack(tensors).astype(np.float32, copy=False)
        output = np.asarray(self.session.run(None, {self.input_name: batch})[0])
        if output.ndim != 3:
            raise RuntimeError(f"姿态模型输出维度异常：{output.shape}")
        if output.shape[1] == 56:
            output = output.transpose(0, 2, 1)
        return [
            _postprocess(prediction, transform)
            for prediction, transform in zip(output, transforms, strict=True)
        ]

    def predict_cuda_tensor(
        self,
        tensor,
        original_images: tuple[np.ndarray, ...],
    ) -> list[list[OnnxPoseDetection]]:
        """Run a preprocessed CUDA tensor through ONNX without a CPU input copy."""

        if self.provider != "CUDAExecutionProvider":
            raise RuntimeError("当前 ONNX 后端不支持 CUDA 张量直接输入")
        if not bool(getattr(tensor, "is_cuda", False)):
            raise RuntimeError("ONNX CUDA 直接输入需要 CUDA 张量")
        tensor = tensor.float().contiguous()
        binding = self.session.io_binding()
        binding.bind_input(
            name=self.input_name,
            device_type="cuda",
            device_id=int(tensor.device.index or 0),
            element_type=np.float32,
            shape=tuple(tensor.shape),
            buffer_ptr=int(tensor.data_ptr()),
        )
        binding.bind_output(self.output_name, device_type="cuda", device_id=0)
        self.session.run_with_iobinding(binding)
        output = np.asarray(binding.copy_outputs_to_cpu()[0])
        if output.ndim != 3:
            raise RuntimeError(f"姿态模型输出维度异常：{output.shape}")
        if output.shape[1] == 56:
            output = output.transpose(0, 2, 1)
        transforms = [_transform_for_image(image) for image in original_images]
        return [
            _postprocess(prediction, transform)
            for prediction, transform in zip(output, transforms, strict=True)
        ]


def _add_torch_cuda_dll_directory() -> object | None:
    """让 ONNX Runtime 复用 PyTorch 已经携带的 CUDA、cuDNN 和 NVRTC DLL。"""

    if os.name != "nt":
        return None
    spec = importlib.util.find_spec("torch")
    locations = tuple(spec.submodule_search_locations or ()) if spec else ()
    if not locations:
        return None
    torch_lib = Path(locations[0]) / "lib"
    if not torch_lib.is_dir():
        return None
    current_path = os.environ.get("PATH", "")
    path_parts = current_path.split(os.pathsep) if current_path else []
    if str(torch_lib).casefold() not in {part.casefold() for part in path_parts}:
        os.environ["PATH"] = str(torch_lib) + (os.pathsep + current_path if current_path else "")
    try:
        return os.add_dll_directory(str(torch_lib))
    except (AttributeError, FileNotFoundError, OSError):
        return None


def _preprocess(frame: np.ndarray) -> tuple[np.ndarray, _Letterbox]:
    height, width = frame.shape[:2]
    transform = _transform_for_image(frame)
    scale = transform.scale
    resized_width = max(1, round(width * scale))
    resized_height = max(1, round(height * scale))
    resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
    pad_x = transform.pad_x
    pad_y = transform.pad_y
    left, top = int(round(pad_x - 0.1)), int(round(pad_y - 0.1))
    right = 640 - resized_width - left
    bottom = 640 - resized_height - top
    padded = cv2.copyMakeBorder(
        resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114)
    )
    rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    tensor = np.transpose(rgb, (2, 0, 1)) / 255.0
    return tensor, _Letterbox(scale, float(left), float(top), width, height)


def _transform_for_image(image: np.ndarray) -> _Letterbox:
    height, width = image.shape[:2]
    scale = min(640.0 / width, 640.0 / height)
    resized_width = max(1, round(width * scale))
    resized_height = max(1, round(height * scale))
    pad_x = (640 - resized_width) / 2
    pad_y = (640 - resized_height) / 2
    left = int(round(pad_x - 0.1))
    top = int(round(pad_y - 0.1))
    return _Letterbox(scale, float(left), float(top), width, height)


def _postprocess(
    prediction: np.ndarray,
    transform: _Letterbox,
    *,
    confidence_threshold: float = 0.25,
    nms_threshold: float = 0.45,
) -> list[OnnxPoseDetection]:
    if prediction.shape[1] < 56:
        raise RuntimeError(f"姿态模型输出通道异常：{prediction.shape}")
    candidates = prediction[prediction[:, 4] >= confidence_threshold]
    if not len(candidates):
        return []

    boxes: list[list[float]] = []
    scores: list[float] = []
    for row in candidates:
        center_x, center_y, width, height = row[:4]
        x = (center_x - width / 2 - transform.pad_x) / transform.scale
        y = (center_y - height / 2 - transform.pad_y) / transform.scale
        boxes.append(
            [
                float(x),
                float(y),
                float(width / transform.scale),
                float(height / transform.scale),
            ]
        )
        scores.append(float(row[4]))
    selected = cv2.dnn.NMSBoxes(boxes, scores, confidence_threshold, nms_threshold)
    indices = np.asarray(selected).reshape(-1) if len(selected) else np.empty(0, dtype=int)

    detections: list[OnnxPoseDetection] = []
    for index in indices:
        row = candidates[int(index)]
        x, y, width, height = boxes[int(index)]
        x1 = float(np.clip(x, 0, transform.width - 1))
        y1 = float(np.clip(y, 0, transform.height - 1))
        x2 = float(np.clip(x + width, 0, transform.width - 1))
        y2 = float(np.clip(y + height, 0, transform.height - 1))
        keypoints = row[5:56].reshape(17, 3).astype(np.float32, copy=True)
        keypoints[:, 0] = np.clip(
            (keypoints[:, 0] - transform.pad_x) / transform.scale,
            0,
            transform.width - 1,
        )
        keypoints[:, 1] = np.clip(
            (keypoints[:, 1] - transform.pad_y) / transform.scale,
            0,
            transform.height - 1,
        )
        detections.append(
            OnnxPoseDetection(
                box=np.array([x1, y1, x2, y2], dtype=np.float32),
                keypoints=keypoints,
                confidence=float(row[4]),
            )
        )
    return detections
