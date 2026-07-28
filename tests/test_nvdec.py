from pathlib import Path
from types import SimpleNamespace

from tennis_video_helper.nvdec import (
    _create_decoder,
    _decode_request_size,
    _progress_frame_total,
    nvdec_unsupported_reason,
)


def test_decode_request_size_stops_at_final_frame() -> None:
    assert _decode_request_size(27296, 27309, 32) == 13
    assert _decode_request_size(27309, 27309, 32) == 0


def test_progress_frame_total_respects_preview_limit() -> None:
    assert _progress_frame_total(27309, 30.0, 5.0) == 150
    assert _progress_frame_total(27309, 30.0, None) == 27309


def test_create_decoder_prefers_threaded_prefetch() -> None:
    calls = []

    class Threaded:
        def __init__(self, path, **kwargs):
            calls.append((path, kwargs))

    class OutputColorType:
        RGBP = "rgbp"

    nvc = SimpleNamespace(ThreadedDecoder=Threaded, OutputColorType=OutputColorType)

    decoder = _create_decoder(nvc, Path("match.mov"), batch_size=16)

    assert isinstance(decoder, Threaded)
    assert calls[0][1]["buffer_size"] == 64
    assert calls[0][1]["use_device_memory"] is True


def test_prores_is_skipped_before_attempting_nvdec() -> None:
    reason = nvdec_unsupported_reason("prores")

    assert reason is not None
    assert "Apple ProRes" in reason
    assert "CPU/OpenCV" in reason
    assert "CUDA 姿态推理" in reason


def test_hevc_remains_eligible_for_nvdec() -> None:
    assert nvdec_unsupported_reason("hevc") is None
