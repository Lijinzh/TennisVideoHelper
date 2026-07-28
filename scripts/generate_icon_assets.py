"""Convert the finalized transparent PNG into a multi-resolution Windows ICO."""

from pathlib import Path

from PIL import Image
ROOT = Path(__file__).resolve().parents[1]
PNG_TARGET = ROOT / "assets" / "app_icon.png"
ICO_TARGET = ROOT / "assets" / "app_icon.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> None:
    if not PNG_TARGET.is_file():
        raise RuntimeError(f"找不到透明 PNG 图标：{PNG_TARGET}")
    image = Image.open(PNG_TARGET).convert("RGBA")
    image.save(
        ICO_TARGET,
        format="ICO",
        sizes=[(size, size) for size in SIZES],
    )
    print(ICO_TARGET)


if __name__ == "__main__":
    main()
