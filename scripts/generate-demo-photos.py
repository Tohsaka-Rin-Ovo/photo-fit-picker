from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter


WIDTH = 1200
HEIGHT = 800
OUTPUT = Path(__file__).resolve().parents[1] / "demo-photos"


def gradient(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        ratio = y / (HEIGHT - 1)
        color = tuple(round(a + (b - a) * ratio) for a, b in zip(top, bottom))
        draw.line((0, y, WIDTH, y), fill=color)
    return image


def lake_scene() -> Image.Image:
    image = gradient((91, 166, 218), (239, 192, 126))
    draw = ImageDraw.Draw(image)
    draw.polygon([(0, 410), (230, 205), (420, 405)], fill=(66, 91, 91))
    draw.polygon([(250, 410), (585, 150), (835, 410)], fill=(53, 77, 78))
    draw.polygon([(630, 410), (930, 225), (1200, 420)], fill=(73, 91, 87))
    draw.polygon([(505, 210), (585, 150), (655, 225)], fill=(227, 231, 218))
    draw.rectangle((0, 405, WIDTH, HEIGHT), fill=(55, 124, 151))
    for y in range(430, HEIGHT, 22):
        draw.line((80, y, 1100, y), fill=(106, 165, 178), width=3)
    draw.ellipse((930, 95, 1010, 175), fill=(252, 208, 104))
    return image


def street_scene() -> Image.Image:
    image = gradient((178, 205, 216), (242, 226, 190))
    draw = ImageDraw.Draw(image)
    draw.polygon([(0, 210), (420, 285), (510, HEIGHT), (0, HEIGHT)], fill=(177, 80, 65))
    draw.polygon([(WIDTH, 180), (760, 280), (675, HEIGHT), (WIDTH, HEIGHT)], fill=(219, 174, 94))
    for x in (90, 230, 345, 870, 1010, 1110):
        draw.rectangle((x, 300, x + 58, 445), fill=(54, 67, 65))
        draw.rectangle((x + 7, 308, x + 51, 435), fill=(116, 175, 183))
    draw.polygon([(420, 285), (760, 280), (900, HEIGHT), (300, HEIGHT)], fill=(94, 103, 100))
    draw.polygon([(500, 320), (690, 320), (745, HEIGHT), (430, HEIGHT)], fill=(201, 196, 170))
    draw.ellipse((568, 430, 615, 477), fill=(52, 44, 38))
    draw.rectangle((575, 474, 608, 610), fill=(42, 86, 111))
    return image


def coast_scene() -> Image.Image:
    image = gradient((82, 153, 199), (232, 228, 202))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 420, WIDTH, HEIGHT), fill=(39, 117, 151))
    draw.polygon([(0, 600), (260, 420), (430, 470), (610, HEIGHT), (0, HEIGHT)], fill=(83, 88, 78))
    draw.rectangle((800, 250, 865, 545), fill=(229, 225, 208))
    draw.polygon([(780, 250), (832, 185), (885, 250)], fill=(156, 55, 48))
    draw.rectangle((815, 320, 850, 365), fill=(62, 93, 104))
    for y in range(450, HEIGHT, 28):
        draw.arc((540, y - 20, 1220, y + 30), 190, 345, fill=(158, 202, 211), width=3)
    return image


def forest_scene() -> Image.Image:
    image = gradient((119, 160, 125), (226, 205, 145))
    draw = ImageDraw.Draw(image)
    for x, width, height in ((80, 80, 600), (260, 55, 520), (920, 85, 620), (1080, 60, 540)):
        draw.rectangle((x, HEIGHT - height, x + width, HEIGHT), fill=(67, 72, 55))
        draw.ellipse((x - 100, HEIGHT - height - 120, x + width + 100, HEIGHT - height + 90), fill=(54, 104, 68))
    draw.polygon([(510, HEIGHT), (690, HEIGHT), (635, 350), (565, 350)], fill=(188, 166, 116))
    return image


def shifted(image: Image.Image, x: int, y: int) -> Image.Image:
    return image.transform(
        image.size,
        Image.Transform.AFFINE,
        (1, 0, x, 0, 1, y),
        resample=Image.Resampling.BICUBIC,
    )


def save(image: Image.Image, filename: str, captured_at: datetime) -> None:
    exif = Image.Exif()
    timestamp = captured_at.strftime("%Y:%m:%d %H:%M:%S")
    exif[36867] = timestamp
    exif[306] = timestamp
    image.save(OUTPUT / filename, quality=91, optimize=True, exif=exif)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    start = datetime(2026, 5, 18, 9, 30, 0)

    lake = lake_scene()
    save(lake, "01_lake_clear.jpg", start)
    save(ImageEnhance.Brightness(shifted(lake, 5, 1)).enhance(1.04), "02_lake_bright.jpg", start + timedelta(seconds=2))
    save(shifted(lake, -4, 2).filter(ImageFilter.GaussianBlur(1.5)), "03_lake_soft.jpg", start + timedelta(seconds=4))

    street = street_scene()
    street_time = start + timedelta(minutes=8)
    save(street, "04_street_clear.jpg", street_time)
    save(shifted(street, 6, 0), "05_street_step.jpg", street_time + timedelta(seconds=2))
    save(ImageEnhance.Brightness(street).enhance(0.82), "06_street_dark.jpg", street_time + timedelta(seconds=5))

    coast = coast_scene()
    coast_time = start + timedelta(minutes=18)
    save(coast, "07_coast_clear.jpg", coast_time)
    save(shifted(coast, 3, -2), "08_coast_shift.jpg", coast_time + timedelta(seconds=3))
    save(coast.filter(ImageFilter.GaussianBlur(1.8)), "09_coast_soft.jpg", coast_time + timedelta(seconds=6))

    save(forest_scene(), "10_forest.jpg", start + timedelta(minutes=35))
    save(ImageEnhance.Color(lake.rotate(90, expand=False)).enhance(0.45), "11_abstract.jpg", start + timedelta(minutes=48))

    print(f"Generated 11 demo photos in {OUTPUT}")


if __name__ == "__main__":
    main()
