from tennis_video_helper.nvdec import _decode_request_size, _progress_frame_total


def test_decode_request_size_stops_at_final_frame() -> None:
    assert _decode_request_size(27296, 27309, 32) == 13
    assert _decode_request_size(27309, 27309, 32) == 0


def test_progress_frame_total_respects_preview_limit() -> None:
    assert _progress_frame_total(27309, 30.0, 5.0) == 150
    assert _progress_frame_total(27309, 30.0, None) == 27309
