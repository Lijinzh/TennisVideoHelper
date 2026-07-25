from tennis_video_helper.nvdec import _decode_request_size


def test_decode_request_size_stops_at_final_frame() -> None:
    assert _decode_request_size(27296, 27309, 32) == 13
    assert _decode_request_size(27309, 27309, 32) == 0
