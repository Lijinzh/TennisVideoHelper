from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
ICON_PNG = ROOT / "assets" / "icons" / "app_icon.png"
ICON_ICO = ROOT / "assets" / "icons" / "app_icon.ico"
ICON_SVG = ROOT / "assets" / "icons" / "app_icon.svg"
REQUIRED_WINDOWS_SIZES = {
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
}


def test_pixel_icon_assets_are_square_and_complete() -> None:
    with Image.open(ICON_PNG) as png:
        assert png.width == png.height
        assert png.width >= 1024

    with Image.open(ICON_ICO) as ico:
        assert ico.info["sizes"] == REQUIRED_WINDOWS_SIZES

    svg = ICON_SVG.read_text(encoding="utf-8")
    assert 'viewBox="0 0 32 32"' in svg
    assert 'shape-rendering="crispEdges"' in svg
