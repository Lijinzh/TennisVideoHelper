"""Lightweight tennis-racket detection through ONNX Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from tennis_video_helper.detection.vision.onnx_pose import _add_torch_cuda_dll_directory

TENNIS_RACKET_CLASS = 38


@dataclass(frozen=True, slots=True)
class RacketDetection:
    box: np.ndarray
    confidence: float


@dataclass(frozen=True, slots=True)
class _Letterbox:
    scale: float
    pad_x: float
    pad_y: float
    width: int
    height: int


class OnnxRacketModel:
    """Small runtime adapter for a COCO YOLO11 object model."""

    def __init__(self, model_path: Path) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError("缺少轻量 ONNX Runtime 运行组件") from exc

        self._dll_directory = _add_torch_cuda_dll_directory()
        available = set(ort.get_available_providers())
        preferred = (
            "CUDAExecutionProvider",
            "DmlExecutionProvider",
            "CPUExecutionProvider",
        )
        providers = [name for name in preferred if name in available]
        if not providers:
            raise RuntimeError("ONNX Runtime 没有可用的执行后端")
        options = ort.SessionOptions()
        options.log_severity_level = 3
        self.session = ort.InferenceSession(
            str(model_path),
            sess_options=options,
            providers=providers,
        )
        self.input_name = self.session.get_inputs()[0].name
        self.provider = self.session.get_providers()[0]
        input_shape = self.session.get_inputs()[0].shape
        self.input_size = int(input_shape[-1]) if isinstance(input_shape[-1], int) else 640

    @property
    def supports_cuda_tensor(self) -> bool:
        return self.provider == "CUDAExecutionProvider"

    def predict(self, frames: list[np.ndarray]) -> list[list[RacketDetection]]:
        if not frames:
            return []
        tensors: list[np.ndarray] = []
        transforms: list[_Letterbox] = []
        for frame in frames:
            tensor, transform = _preprocess(frame, self.input_size)
            tensors.append(tensor)
            transforms.append(transform)
        batch = np.stack(tensors).astype(np.float32, copy=False)
        output = np.asarray(self.session.run(None, {self.input_name: batch})[0])
        if output.ndim != 3:
            raise RuntimeError(f"球拍模型输出维度异常：{output.shape}")
        if output.shape[1] < output.shape[2]:
            output = output.transpose(0, 2, 1)
        return [
            _postprocess(prediction, transform)
            for prediction, transform in zip(output, transforms, strict=True)
        ]

    def predict_cuda_tensor(
        self,
        tensor,
        original_images: list[np.ndarray],
    ) -> list[list[RacketDetection]]:
        if not self.supports_cuda_tensor:
            raise RuntimeError("当前球拍 ONNX 后端不支持 CUDA 张量直接输入")
        if not bool(getattr(tensor, "is_cuda", False)):
            raise RuntimeError("球拍 ONNX CUDA 直接输入需要 CUDA 张量")
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
        output_name = self.session.get_outputs()[0].name
        binding.bind_output(output_name, device_type="cuda", device_id=0)
        self.session.run_with_iobinding(binding)
        output = np.asarray(binding.copy_outputs_to_cpu()[0])
        if output.ndim != 3:
            raise RuntimeError(f"球拍模型输出维度异常：{output.shape}")
        if output.shape[1] < output.shape[2]:
            output = output.transpose(0, 2, 1)
        transforms = [
            _transform_for_tensor(image, tensor.shape[2], tensor.shape[3])
            for image in original_images
        ]
        return [
            _postprocess(prediction, transform)
            for prediction, transform in zip(output, transforms, strict=True)
        ]


def _preprocess(frame: np.ndarray, size: int) -> tuple[np.ndarray, _Letterbox]:
    height, width = frame.shape[:2]
    scale = min(size / width, size / height)
    resized_width = max(1, round(width * scale))
    resized_height = max(1, round(height * scale))
    resized = cv2.resize(
        frame,
        (resized_width, resized_height),
        interpolation=cv2.INTER_LINEAR,
    )
    pad_x = (size - resized_width) / 2
    pad_y = (size - resized_height) / 2
    left = int(round(pad_x - 0.1))
    top = int(round(pad_y - 0.1))
    right = size - resized_width - left
    bottom = size - resized_height - top
    padded = cv2.copyMakeBorder(
        resized,
        top,
        bottom,
        left,
        right,
        cv2.BORDER_CONSTANT,
        value=(114, 114, 114),
    )
    rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    tensor = np.transpose(rgb, (2, 0, 1)) / 255.0
    return tensor, _Letterbox(scale, float(left), float(top), width, height)


def _transform_for_tensor(
    image: np.ndarray,
    input_height: int,
    input_width: int,
) -> _Letterbox:
    height, width = image.shape[:2]
    scale = min(input_width / width, input_height / height)
    resized_width = max(1, round(width * scale))
    resized_height = max(1, round(height * scale))
    return _Letterbox(
        scale=scale,
        pad_x=float((input_width - resized_width) // 2),
        pad_y=float((input_height - resized_height) // 2),
        width=width,
        height=height,
    )


def _postprocess(
    prediction: np.ndarray,
    transform: _Letterbox,
    *,
    confidence_threshold: float = 0.10,
    nms_threshold: float = 0.45,
) -> list[RacketDetection]:
    class_column = 4 + TENNIS_RACKET_CLASS
    if prediction.shape[1] <= class_column:
        raise RuntimeError(f"球拍模型输出通道异常：{prediction.shape}")
    scores = prediction[:, class_column]
    selected_rows = np.flatnonzero(scores >= confidence_threshold)
    if not selected_rows.size:
        return []

    boxes: list[list[float]] = []
    selected_scores: list[float] = []
    for row_index in selected_rows:
        row = prediction[int(row_index)]
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
        selected_scores.append(float(scores[int(row_index)]))
    kept = cv2.dnn.NMSBoxes(
        boxes,
        selected_scores,
        confidence_threshold,
        nms_threshold,
    )
    indices = np.asarray(kept).reshape(-1) if len(kept) else np.empty(0, dtype=int)
    detections: list[RacketDetection] = []
    for index in indices:
        x, y, width, height = boxes[int(index)]
        detections.append(
            RacketDetection(
                box=np.array(
                    [
                        np.clip(x, 0, transform.width - 1),
                        np.clip(y, 0, transform.height - 1),
                        np.clip(x + width, 0, transform.width - 1),
                        np.clip(y + height, 0, transform.height - 1),
                    ],
                    dtype=np.float32,
                ),
                confidence=selected_scores[int(index)],
            )
        )
    return detections
