from __future__ import annotations

import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

import numpy
from PIL import Image, ImageFilter, ImageOps, ImageStat

from .feature_cache import FeatureCache
from .models import AnalysisOptions, CameraMetadata, PhotoGroup, PhotoRecord

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

try:
    import cv2
except ImportError:
    cv2 = None


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
MEMORY_HEAVY_EXTENSIONS = RAW_EXTENSIONS | {".heic", ".heif", ".tif", ".tiff"}
ANALYSIS_IMAGE_MAX_SIZE = 1024
DUPLICATE_SAMPLE_SIZE = 64 * 1024
PORTRAIT_IMAGE_MAX_SIZE = 768
_portrait_detector_state = threading.local()


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
        if path.is_file()
        and not path.is_symlink()
        and path.suffix.lower() in SUPPORTED_EXTENSIONS
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


def _decoded_image(
    path: Path,
    known_capture_time: Optional[datetime] = None,
) -> tuple[Image.Image, int, int, datetime]:
    if path.suffix.lower() in RAW_EXTENSIONS:
        image, width, height = _raw_image(path)
        return image, width, height, known_capture_time or _capture_time(image, path)

    with Image.open(path) as source:
        captured_at = known_capture_time or _capture_time(source, path)
        width, height = source.size
        try:
            orientation = int(source.getexif().get(274, 1))
        except (AttributeError, TypeError, ValueError):
            orientation = 1
        if orientation in {5, 6, 7, 8}:
            width, height = height, width
        try:
            source.draft("RGB", (ANALYSIS_IMAGE_MAX_SIZE, ANALYSIS_IMAGE_MAX_SIZE))
        except (AttributeError, OSError):
            pass
        oriented = ImageOps.exif_transpose(source)
        oriented.thumbnail(
            (ANALYSIS_IMAGE_MAX_SIZE, ANALYSIS_IMAGE_MAX_SIZE),
            Image.Resampling.LANCZOS,
        )
        oriented.load()
        image = oriented.copy()
    return image, width, height, captured_at


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


def _average_hash(image: Image.Image) -> int:
    pixels = image.convert("L").resize((8, 8), Image.Resampling.LANCZOS).tobytes()
    average = sum(pixels) / len(pixels)
    value = 0
    for pixel in pixels:
        value <<= 1
        value |= pixel >= average
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


def _portrait_detector():  # type: ignore[no-untyped-def]
    if cv2 is None:
        raise RuntimeError("人像检测组件不可用，请重新安装应用")
    detector = getattr(_portrait_detector_state, "detector", None)
    if detector is None:
        model_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        detector = cv2.CascadeClassifier(str(model_path))
        if detector.empty():
            raise RuntimeError("无法载入本地人像检测模型")
        _portrait_detector_state.detector = detector
    return detector


def _detect_portrait(image: Image.Image) -> bool:
    if cv2 is None:
        raise RuntimeError("人像检测组件不可用，请重新安装应用")
    working = image.convert("RGB")
    try:
        working.thumbnail(
            (PORTRAIT_IMAGE_MAX_SIZE, PORTRAIT_IMAGE_MAX_SIZE),
            Image.Resampling.LANCZOS,
        )
        gray = cv2.cvtColor(numpy.asarray(working), cv2.COLOR_RGB2GRAY)
        minimum_face = max(24, min(gray.shape[:2]) // 18)
        faces = _portrait_detector().detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(minimum_face, minimum_face),
        )
        return len(faces) > 0
    finally:
        working.close()


def _detect_portrait_for_record(record: PhotoRecord) -> PhotoRecord:
    image, _, _, _ = _decoded_image(record.path, record.captured_at)
    try:
        record.portrait_detected = _detect_portrait(image)
    finally:
        image.close()
    return record


def extract_feature(path: Path, detect_portraits: bool = False) -> PhotoRecord:
    metadata = extract_metadata(path)
    image, width, height, captured_at = _decoded_image(path, metadata.captured_at)
    try:
        dhash = _difference_hash(image)
        average_hash = _average_hash(image)
        signature = _color_signature(image)
        sharpness, exposure = _quality_metrics(image)
        portrait_detected = _detect_portrait(image) if detect_portraits else None
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
        average_hash=average_hash,
        metadata=metadata,
        portrait_detected=portrait_detected,
    )


def analysis_worker_count(
    pending_count: int,
    memory_heavy: bool,
    detect_portraits: bool,
    performance_mode: str = "balanced",
    cpu_count: Optional[int] = None,
) -> int:
    if cpu_count is None:
        cpu_count = os.cpu_count() or 2
    if performance_mode == "high":
        worker_limit = max(2, cpu_count)
    else:
        worker_limit = 2 if memory_heavy or detect_portraits else 4
        worker_limit = max(2, min(worker_limit, cpu_count // 2))
    return max(2, min(max(1, pending_count), worker_limit))


def analyze_paths(
    paths: Sequence[Path],
    progress: Optional[Callable[[int, int, str], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
    cache: Optional[FeatureCache] = None,
    detect_portraits: bool = False,
    performance_mode: str = "balanced",
) -> tuple[list[PhotoRecord], list[tuple[Path, str]]]:
    if not paths:
        return [], []
    records: list[Optional[PhotoRecord]] = [None] * len(paths)
    failures: list[tuple[Path, str]] = []
    total = len(paths)
    cached = cache.load(paths) if cache else {}
    pending: list[tuple[int, Path, Optional[PhotoRecord]]] = []
    for index, path in enumerate(paths):
        record = cached.get(path)
        if record is None:
            pending.append((index, path, None))
        else:
            records[index] = record
            if detect_portraits and record.portrait_detected is None:
                pending.append((index, path, record))
    completed = total - len(pending)
    if progress and completed:
        progress(completed, total, f"已复用 {completed} 张照片的分析结果")
    if not pending:
        return [record for record in records if record is not None], []

    memory_heavy = any(
        path.suffix.lower() in MEMORY_HEAVY_EXTENSIONS
        for _, path, _ in pending
    )
    worker_count = analysis_worker_count(
        len(pending),
        memory_heavy,
        detect_portraits,
        performance_mode,
    )
    executor = ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="photo-analysis",
    )
    futures = {}
    for index, path, cached_record in pending:
        future = (
            executor.submit(extract_feature, path, detect_portraits)
            if cached_record is None
            else executor.submit(_detect_portrait_for_record, cached_record)
        )
        futures[future] = (index, path)
    new_records: list[PhotoRecord] = []
    try:
        for future in as_completed(futures):
            if cancelled and cancelled():
                for pending in futures:
                    pending.cancel()
                break
            index, path = futures[future]
            try:
                record = future.result()
                records[index] = record
                new_records.append(record)
            except Exception as exc:  # Pillow raises format-specific exceptions.
                failures.append((path, str(exc)))
            completed += 1
            if progress:
                progress(completed, total, path.name)
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    if cache:
        cache.store(new_records)
    return [record for record in records if record is not None], failures


def hamming_distance(left: int, right: int) -> int:
    bits = left ^ right
    if hasattr(bits, "bit_count"):
        return bits.bit_count()
    return bin(bits).count("1")


def histogram_intersection(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(min(a, b) for a, b in zip(left, right))


def visual_similarity(
    left: PhotoRecord,
    right: PhotoRecord,
    *,
    color_weight: float = 0.22,
    hash_method: str = "difference",
) -> float:
    left_hash = left.average_hash if hash_method == "average" else left.dhash
    right_hash = right.average_hash if hash_method == "average" else right.dhash
    hash_similarity = 1.0 - hamming_distance(left_hash, right_hash) / 64.0
    color_similarity = histogram_intersection(left.color_signature, right.color_signature)
    color_weight = max(0.0, min(1.0, color_weight))
    return max(
        0.0,
        min(1.0, hash_similarity * (1.0 - color_weight) + color_similarity * color_weight),
    )


def _maximum_viable_hash_distance(threshold: float, color_weight: float) -> int:
    color_weight = max(0.0, min(1.0, color_weight))
    if color_weight >= 1.0 or threshold <= color_weight:
        return 64
    required_hash_similarity = (threshold - color_weight) / (1.0 - color_weight)
    return max(0, min(64, int((1.0 - required_hash_similarity) * 64)))


def _sample_digest(path: Path, file_size: int) -> tuple[str, bool]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        if file_size <= DUPLICATE_SAMPLE_SIZE * 2:
            digest.update(stream.read())
            return digest.hexdigest(), True
        digest.update(stream.read(DUPLICATE_SAMPLE_SIZE))
        stream.seek(-DUPLICATE_SAMPLE_SIZE, 2)
        digest.update(stream.read(DUPLICATE_SAMPLE_SIZE))
    return digest.hexdigest(), False


def _content_digest(
    path: Path,
    cancelled: Optional[Callable[[], bool]] = None,
) -> Optional[str]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            if cancelled and cancelled():
                return None
            digest.update(chunk)
    return digest.hexdigest()


def _union_exact_duplicates(
    records: Sequence[PhotoRecord],
    disjoint: "_DisjointSet",
    progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
) -> bool:
    total = len(records)
    candidates: dict[int, list[int]] = {}
    for index, photo in enumerate(records):
        if cancelled and cancelled():
            return False
        candidates.setdefault(photo.file_size, []).append(index)

    sampled: dict[tuple[int, str], list[tuple[int, bool]]] = {}
    for index, photo in enumerate(records):
        if cancelled and cancelled():
            return False
        same_size = candidates.get(photo.file_size, ())
        if len(same_size) >= 2:
            try:
                digest, is_complete = _sample_digest(photo.path, photo.file_size)
            except OSError:
                pass
            else:
                sampled.setdefault((photo.file_size, digest), []).append(
                    (index, is_complete)
                )
        if progress:
            progress(index + 1, max(1, total * 2))

    needs_full_digest: list[list[int]] = []
    for entries in sampled.values():
        if len(entries) < 2:
            continue
        indices = [index for index, _ in entries]
        if all(is_complete for _, is_complete in entries):
            first = indices[0]
            for index in indices[1:]:
                disjoint.union(first, index)
        else:
            needs_full_digest.append(indices)

    processed = 0
    for indices in needs_full_digest:
        digests: dict[str, int] = {}
        for index in indices:
            if cancelled and cancelled():
                return False
            try:
                digest = _content_digest(records[index].path, cancelled)
            except OSError:
                digest = None
            if digest is None:
                if cancelled and cancelled():
                    return False
            else:
                first = digests.setdefault(digest, index)
                if first != index:
                    disjoint.union(first, index)
            processed += 1
            if progress:
                progress(min(total * 2, total + processed), max(1, total * 2))
    if progress:
        progress(total * 2, max(1, total * 2))
    return True


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
    options: Optional[AnalysisOptions] = None,
    *,
    similarity_threshold: Optional[float] = None,
    time_window_seconds: Optional[int] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
) -> list[PhotoGroup]:
    options = options or AnalysisOptions()
    threshold = max(0.0, min(1.0, (
        similarity_threshold
        if similarity_threshold is not None
        else options.similarity_threshold
    )))
    time_window = (
        time_window_seconds
        if time_window_seconds is not None
        else options.time_window_seconds
    )
    ordered = sorted(records, key=lambda photo: (photo.captured_at, photo.path.name.lower()))
    disjoint = _DisjointSet(len(ordered))
    maximum_hash_distance = _maximum_viable_hash_distance(
        threshold,
        options.color_weight,
    )
    duplicate_steps = len(ordered) * 2 if options.detect_exact_duplicates else 0
    total_steps = max(1, duplicate_steps + len(ordered))
    if options.detect_exact_duplicates:
        completed = _union_exact_duplicates(
            ordered,
            disjoint,
            progress=(
                (lambda current, _total: progress(current, total_steps))
                if progress
                else None
            ),
            cancelled=cancelled,
        )
        if not completed:
            return []
    for left_index, left in enumerate(ordered):
        if cancelled and cancelled():
            return []
        for right_index in range(left_index + 1, len(ordered)):
            right = ordered[right_index]
            time_gap = (right.captured_at - left.captured_at).total_seconds()
            if time_gap > max(time_window * 4, 600):
                break
            if disjoint.find(left_index) == disjoint.find(right_index):
                continue
            left_hash = left.average_hash if options.hash_method == "average" else left.dhash
            right_hash = right.average_hash if options.hash_method == "average" else right.dhash
            hash_distance = hamming_distance(left_hash, right_hash)
            if time_gap > time_window and hash_distance > 6:
                continue
            if hash_distance > maximum_hash_distance:
                continue
            if visual_similarity(
                left,
                right,
                color_weight=options.color_weight,
                hash_method=options.hash_method,
            ) >= threshold:
                disjoint.union(left_index, right_index)
        if progress and (left_index % 16 == 0 or left_index + 1 == len(ordered)):
            progress(duplicate_steps + left_index + 1, total_steps)

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
        groups.append(
            PhotoGroup(
                id=group_id,
                photos=photos,
                sharpness_weight=options.sharpness_weight,
                exposure_weight=options.exposure_weight,
                resolution_weight=options.resolution_weight,
            )
        )
    return groups
