from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from PIL import Image, ImageFilter, ImageOps, ImageStat

from .models import CameraMetadata, PhotoGroup, PhotoRecord

try:
    import exifread
except ImportError:
    exifread = None

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


def _first_tag(tags: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = tags.get(name)
        if value is not None:
            return value
    return None


def _tag_text(tags: Mapping[str, Any], *names: str) -> str:
    value = _first_tag(tags, *names)
    if value is None:
        return ""
    return " ".join(str(value).replace("\x00", "").split())


def _numeric_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    values = getattr(value, "values", value)
    if isinstance(values, (list, tuple)):
        if not values:
            return None
        values = values[0]
    numerator = getattr(values, "num", None)
    denominator = getattr(values, "den", None)
    if numerator is not None and denominator:
        return float(numerator) / float(denominator)
    try:
        return float(values)
    except (TypeError, ValueError, OverflowError):
        return None


def _gps_coordinate(value: Any, reference: str) -> Optional[float]:
    values = getattr(value, "values", value)
    if not isinstance(values, (list, tuple)) or len(values) < 3:
        return None
    parts = [_numeric_value(part) for part in values[:3]]
    if any(part is None for part in parts):
        return None
    degrees, minutes, seconds = (float(part) for part in parts if part is not None)
    coordinate = degrees + minutes / 60 + seconds / 3600
    if reference.upper().startswith(("S", "W")):
        coordinate *= -1
    return coordinate


def _metadata_capture_time(tags: Mapping[str, Any]) -> Optional[datetime]:
    raw = _tag_text(
        tags,
        "EXIF DateTimeOriginal",
        "EXIF DateTimeDigitized",
        "Image DateTimeOriginal",
        "Image DateTimeDigitized",
        "Image DateTime",
    )
    if not raw:
        return None
    for pattern in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw[:19], pattern)
        except ValueError:
            continue
    return None


def _maker_note_details(tags: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    selected = (
        ("focusmode", "对焦模式"),
        ("shootingmode", "拍摄模式"),
        ("vrinfo", "防抖"),
        ("picturecontrol", "优化校准"),
        ("lensdata", "镜头数据"),
        ("colorspace", "色彩空间"),
    )
    details: list[tuple[str, str]] = []
    for key, value in tags.items():
        normalized = key.lower().replace(" ", "")
        if "makernote" not in normalized:
            continue
        label = next((label for needle, label in selected if needle in normalized), "")
        text = " ".join(str(value).replace("\x00", "").split())
        if label and text and len(text) <= 120 and (label, text) not in details:
            details.append((label, text))
        if len(details) >= 8:
            break
    return tuple(details)


def extract_metadata(path: Path) -> CameraMetadata:
    if exifread is None:
        return CameraMetadata()
    try:
        with path.open("rb") as stream:
            tags = exifread.process_file(stream, details=True, strict=False)
    except Exception:
        return CameraMetadata()

    exposure_time = _numeric_value(
        _first_tag(tags, "EXIF ExposureTime", "Image ExposureTime")
    )
    aperture = _numeric_value(_first_tag(tags, "EXIF FNumber", "Image FNumber"))
    iso_value = _numeric_value(
        _first_tag(
            tags,
            "EXIF ISOSpeedRatings",
            "EXIF PhotographicSensitivity",
            "Image ISOSpeedRatings",
            "Image PhotographicSensitivity",
            "MakerNote ISOSetting",
        )
    )
    latitude = _gps_coordinate(
        _first_tag(tags, "GPS GPSLatitude"),
        _tag_text(tags, "GPS GPSLatitudeRef"),
    )
    longitude = _gps_coordinate(
        _first_tag(tags, "GPS GPSLongitude"),
        _tag_text(tags, "GPS GPSLongitudeRef"),
    )
    return CameraMetadata(
        captured_at=_metadata_capture_time(tags),
        make=_tag_text(tags, "Image Make"),
        model=_tag_text(tags, "Image Model"),
        lens=_tag_text(tags, "EXIF LensModel", "Image LensModel", "MakerNote Lens"),
        exposure_time=exposure_time,
        aperture=aperture,
        iso=round(iso_value) if iso_value is not None else None,
        focal_length=_numeric_value(
            _first_tag(tags, "EXIF FocalLength", "Image FocalLength")
        ),
        exposure_bias=_numeric_value(
            _first_tag(tags, "EXIF ExposureBiasValue", "Image ExposureBiasValue")
        ),
        white_balance=_tag_text(tags, "MakerNote WhiteBalance", "EXIF WhiteBalance"),
        focus_mode=_tag_text(tags, "MakerNote FocusMode"),
        metering_mode=_tag_text(tags, "EXIF MeteringMode"),
        exposure_program=_tag_text(tags, "EXIF ExposureProgram"),
        flash=_tag_text(tags, "EXIF Flash"),
        software=_tag_text(tags, "Image Software"),
        latitude=latitude,
        longitude=longitude,
        details=_maker_note_details(tags),
    )


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
    metadata = extract_metadata(path)
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
        captured_at=metadata.captured_at or captured_at,
        dhash=dhash,
        color_signature=signature,
        sharpness=sharpness,
        exposure=exposure,
        metadata=metadata,
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
