from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from PIL import Image, ImageFilter, ImageOps, ImageStat

from .models import PhotoGroup, PhotoRecord

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

try:
    import rawpy
except ImportError:
    rawpy = None


STANDARD_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
}

RAW_EXTENSIONS = {
    ".3fr",
    ".arw",
    ".bay",
    ".bmq",
    ".cap",
    ".cr2",
    ".cr3",
    ".crw",
    ".dcr",
    ".dcs",
    ".dng",
    ".drf",
    ".eip",
    ".erf",
    ".fff",
    ".gpr",
    ".iiq",
    ".k25",
    ".kdc",
    ".mdc",
    ".mef",
    ".mos",
    ".mrw",
    ".nef",
    ".nrw",
    ".orf",
    ".ori",
    ".pef",
    ".ptx",
    ".pxn",
    ".r3d",
    ".raf",
    ".raw",
    ".rw2",
    ".rwl",
    ".rwz",
    ".sr2",
    ".srf",
    ".srw",
    ".x3f",
}

SUPPORTED_EXTENSIONS = STANDARD_EXTENSIONS | RAW_EXTENSIONS


def discover_images(folder: Path, recursive: bool = True) -> list[Path]:
    iterator = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(
        path
        for path in iterator
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def _capture_time(image: Image.Image, path: Path) -> datetime:
    try:
        exif = image.getexif()
        for key in (36867, 36868, 306):
            raw = exif.get(key)
            if raw:
                return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
    except (AttributeError, TypeError, ValueError, OverflowError):
        pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def _raw_image(path: Path) -> tuple[Image.Image, int, int]:
    if rawpy is None:
        raise RuntimeError("读取 RAW 照片需要安装 rawpy")

    with rawpy.imread(str(path)) as raw:
        width = int(raw.sizes.width)
        height = int(raw.sizes.height)
        try:
            thumbnail = raw.extract_thumb()
            if thumbnail.format == rawpy.ThumbFormat.JPEG:
                with Image.open(BytesIO(thumbnail.data)) as embedded:
                    image = ImageOps.exif_transpose(embedded).convert("RGB")
            else:
                image = Image.fromarray(thumbnail.data).convert("RGB")
        except Exception:
            rgb = raw.postprocess(
                use_camera_wb=True,
                half_size=True,
                no_auto_bright=False,
                output_bps=8,
            )
            image = Image.fromarray(rgb).convert("RGB")
    return image, width, height


def _decoded_image(path: Path) -> tuple[Image.Image, int, int, datetime]:
    if path.suffix.lower() in RAW_EXTENSIONS:
        image, width, height = _raw_image(path)
        return image, width, height, _capture_time(image, path)

    with Image.open(path) as source:
        captured_at = _capture_time(source, path)
        oriented = ImageOps.exif_transpose(source)
        oriented.load()
        image = oriented.copy()
    return image, image.width, image.height, captured_at


def load_display_image(path: Path) -> Image.Image:
    image, _, _, _ = _decoded_image(path)
    return image


def _difference_hash(image: Image.Image) -> int:
    pixels = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS).tobytes()
    value = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            value <<= 1
            value |= pixels[offset + column] > pixels[offset + column + 1]
    return value


def _color_signature(image: Image.Image) -> tuple[float, ...]:
    rgb = image.convert("RGB").resize((96, 96), Image.Resampling.BILINEAR)
    histogram = rgb.histogram()
    bins = [
        sum(histogram[channel * 256 + start : channel * 256 + start + 16])
        for channel in range(3)
        for start in range(0, 256, 16)
    ]
    scale = float(rgb.width * rgb.height * 3)
    return tuple(value / scale for value in bins)


def _quality_metrics(image: Image.Image) -> tuple[float, float]:
    gray = image.convert("L")
    gray.thumbnail((320, 320), Image.Resampling.LANCZOS)
    width, height = gray.size
    if width < 3 or height < 3:
        return 0.0, 0.5

    exposure = ImageStat.Stat(gray).mean[0] / 255.0
    interior = gray.crop((1, 1, width - 1, height - 1))
    edges = interior.filter(ImageFilter.FIND_EDGES)
    sharpness = ImageStat.Stat(edges).stddev[0] / 255.0
    return sharpness, exposure


def extract_feature(path: Path) -> PhotoRecord:
    image, width, height, captured_at = _decoded_image(path)
    try:
        dhash = _difference_hash(image)
        signature = _color_signature(image)
        sharpness, exposure = _quality_metrics(image)
    finally:
        image.close()
    return PhotoRecord(
        path=path,
        width=width,
        height=height,
        file_size=path.stat().st_size,
        captured_at=captured_at,
        dhash=dhash,
        color_signature=signature,
        sharpness=sharpness,
        exposure=exposure,
    )


def analyze_paths(
    paths: Sequence[Path],
    progress: Optional[Callable[[int, int, str], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
) -> tuple[list[PhotoRecord], list[tuple[Path, str]]]:
    records: list[PhotoRecord] = []
    failures: list[tuple[Path, str]] = []
    total = len(paths)
    for index, path in enumerate(paths, start=1):
        if cancelled and cancelled():
            break
        try:
            records.append(extract_feature(path))
        except Exception as exc:  # Pillow raises format-specific exceptions.
            failures.append((path, str(exc)))
        if progress:
            progress(index, total, path.name)
    return records, failures


def hamming_distance(left: int, right: int) -> int:
    bits = left ^ right
    if hasattr(bits, "bit_count"):
        return bits.bit_count()
    return bin(bits).count("1")


def histogram_intersection(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(min(a, b) for a, b in zip(left, right))


def visual_similarity(left: PhotoRecord, right: PhotoRecord) -> float:
    hash_similarity = 1.0 - hamming_distance(left.dhash, right.dhash) / 64.0
    color_similarity = histogram_intersection(left.color_signature, right.color_signature)
    return max(0.0, min(1.0, hash_similarity * 0.78 + color_similarity * 0.22))


class _DisjointSet:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1


def group_similar_photos(
    records: Iterable[PhotoRecord],
    similarity_threshold: float = 0.84,
    time_window_seconds: int = 90,
) -> list[PhotoGroup]:
    ordered = sorted(records, key=lambda photo: (photo.captured_at, photo.path.name.lower()))
    disjoint = _DisjointSet(len(ordered))
    for left_index, left in enumerate(ordered):
        for right_index in range(left_index + 1, len(ordered)):
            right = ordered[right_index]
            time_gap = (right.captured_at - left.captured_at).total_seconds()
            hash_distance = hamming_distance(left.dhash, right.dhash)
            if time_gap > time_window_seconds and hash_distance > 6:
                if time_gap > max(time_window_seconds * 4, 600):
                    break
                continue
            if visual_similarity(left, right) >= similarity_threshold:
                disjoint.union(left_index, right_index)

    buckets: dict[int, list[PhotoRecord]] = {}
    for index, photo in enumerate(ordered):
        buckets.setdefault(disjoint.find(index), []).append(photo)

    grouped_photos = sorted(
        buckets.values(),
        key=lambda photos: (-len(photos), photos[0].captured_at, photos[0].path.name.lower()),
    )
    groups: list[PhotoGroup] = []
    for group_id, photos in enumerate(grouped_photos, start=1):
        for photo in photos:
            photo.group_id = group_id
        groups.append(PhotoGroup(id=group_id, photos=photos))
    return groups
