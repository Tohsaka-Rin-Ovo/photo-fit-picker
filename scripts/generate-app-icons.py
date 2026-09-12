from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SCALE = 4
SIZE = 1024


def scaled_box(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    return tuple(value * SCALE for value in box)


def main() -> None:
    canvas = Image.new("RGBA", (SIZE * SCALE, SIZE * SCALE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    draw.rounded_rectangle(
        scaled_box((32, 32, 992, 992)),
        radius=218 * SCALE,
        fill=(31, 36, 39, 255),
    )

    draw.rounded_rectangle(
        scaled_box((154, 174, 750, 726)),
        radius=64 * SCALE,
        fill=(224, 107, 82, 255),
    )
    draw.rounded_rectangle(
        scaled_box((226, 236, 862, 824)),
        radius=72 * SCALE,
        fill=(246, 246, 241, 255),
    )
    draw.rounded_rectangle(
        scaled_box((270, 280, 818, 780)),
        radius=42 * SCALE,
        fill=(119, 186, 188, 255),
    )
    draw.ellipse(scaled_box((642, 352, 738, 448)), fill=(244, 193, 88, 255))
    draw.polygon(
        [
            (270 * SCALE, 666 * SCALE),
            (432 * SCALE, 484 * SCALE),
            (548 * SCALE, 604 * SCALE),
            (648 * SCALE, 514 * SCALE),
            (818 * SCALE, 694 * SCALE),
            (818 * SCALE, 780 * SCALE),
            (270 * SCALE, 780 * SCALE),
        ],
        fill=(43, 101, 82, 255),
    )

    draw.ellipse(scaled_box((680, 660, 920, 900)), fill=(246, 246, 241, 255))
    draw.line(
        [
            (741 * SCALE, 780 * SCALE),
            (790 * SCALE, 829 * SCALE),
            (866 * SCALE, 735 * SCALE),
        ],
        fill=(31, 36, 39, 255),
        width=35 * SCALE,
        joint="curve",
    )

    icon = canvas.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    ASSETS.mkdir(parents=True, exist_ok=True)
    icon.save(ASSETS / "app-icon.png", optimize=True)
    icon.save(ASSETS / "app.icns", format="ICNS")
    icon.save(
        ASSETS / "app.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Generated app icons in {ASSETS}")


if __name__ == "__main__":
    main()
