from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple


def format_file_size(file_size: int) -> str:
    size = float(max(0, file_size))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            precision = 0 if unit == "B" else 1
            return f"{size:.{precision}f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    KEPT = "kept"
    REJECTED = "rejected"
    MOVED = "moved"
    TRASHED = "trashed"


@dataclass(frozen=True)
class AnalysisOptions:
    similarity_threshold: float = 0.84
    time_window_seconds: int = 90
    color_weight: float = 0.22
    hash_method: str = "difference"
    detect_exact_duplicates: bool = True
    sharpness_weight: float = 0.75
    exposure_weight: float = 0.25
    resolution_weight: float = 0.0
    detect_portraits: bool = False
    performance_mode: str = "balanced"


@dataclass(frozen=True)
class CameraMetadata:
    captured_at: Optional[datetime] = None
    make: str = ""
    model: str = ""
    lens: str = ""
    exposure_time: Optional[float] = None
    aperture: Optional[float] = None
    iso: Optional[int] = None
    focal_length: Optional[float] = None
    exposure_bias: Optional[float] = None
    white_balance: str = ""
    focus_mode: str = ""
    metering_mode: str = ""
    exposure_program: str = ""
    flash: str = ""
    software: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    details: Tuple[Tuple[str, str], ...] = ()

    @property
    def camera_label(self) -> str:
        parts = [part.strip() for part in (self.make, self.model) if part.strip()]
        if len(parts) == 2 and parts[1].lower().startswith(parts[0].lower()):
            parts.pop(0)
        return " ".join(parts)

    @property
    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    @property
    def shooting_summary(self) -> str:
        values: list[str] = []
        if self.exposure_time and self.exposure_time > 0:
            if self.exposure_time < 1:
                denominator = max(1, round(1 / self.exposure_time))
                values.append(f"1/{denominator} 秒")
            else:
                values.append(f"{self.exposure_time:g} 秒")
        if self.aperture:
            values.append(f"f/{self.aperture:g}")
        if self.iso:
            values.append(f"ISO {self.iso}")
        if self.focal_length:
            values.append(f"{self.focal_length:g} mm")
        return "  ·  ".join(values)


@dataclass
class PhotoRecord:
    path: Path
    width: int
    height: int
    file_size: int
    captured_at: datetime
    dhash: int
    color_signature: Tuple[float, ...]
    sharpness: float
    exposure: float
    average_hash: int = 0
    metadata: CameraMetadata = field(default_factory=CameraMetadata)
    portrait_detected: Optional[bool] = None
    status: ReviewStatus = ReviewStatus.PENDING
    group_id: int = -1
    selected: bool = False

    @property
    def display_name(self) -> str:
        return self.path.name

    @property
    def megapixels(self) -> float:
        return (self.width * self.height) / 1_000_000

    @property
    def file_size_label(self) -> str:
        return format_file_size(self.file_size)

    @property
    def format_label(self) -> str:
        return self.path.suffix.lstrip(".").upper() or "图片"

    @property
    def dimension_label(self) -> str:
        return f"{self.width} × {self.height}"

    @property
    def sharpness_label(self) -> str:
        if self.sharpness >= 0.12:
            return "清晰"
        if self.sharpness >= 0.055:
            return "清晰度尚可"
        return "可能偏软"

    @property
    def exposure_label(self) -> str:
        if self.exposure < 0.24:
            return "画面偏暗"
        if self.exposure > 0.78:
            return "画面偏亮"
        return "曝光均衡"

    @property
    def quality_summary(self) -> str:
        return f"{self.sharpness_label} · {self.exposure_label}"

    @property
    def quality_score(self) -> float:
        exposure_quality = max(0.0, 1.0 - abs(self.exposure - 0.5) * 1.8)
        sharpness_quality = min(1.0, self.sharpness / 0.12)
        return sharpness_quality * 0.75 + exposure_quality * 0.25


@dataclass
class PhotoGroup:
    id: int
    photos: list[PhotoRecord] = field(default_factory=list)
    sharpness_weight: float = 0.75
    exposure_weight: float = 0.25
    resolution_weight: float = 0.0

    def _score(self, photo: PhotoRecord, max_megapixels: float) -> float:
        sharpness_quality = min(1.0, photo.sharpness / 0.12)
        exposure_quality = max(0.0, 1.0 - abs(photo.exposure - 0.5) * 1.8)
        resolution_quality = photo.megapixels / max_megapixels if max_megapixels else 0.0
        total_weight = (
            self.sharpness_weight + self.exposure_weight + self.resolution_weight
        )
        if total_weight <= 0:
            return photo.quality_score
        return (
            sharpness_quality * self.sharpness_weight
            + exposure_quality * self.exposure_weight
            + resolution_quality * self.resolution_weight
        ) / total_weight

    def score(self, photo: PhotoRecord) -> float:
        max_megapixels = max((item.megapixels for item in self.photos), default=1.0)
        return self._score(photo, max_megapixels)

    @property
    def recommended(self) -> Optional[PhotoRecord]:
        candidates = [
            photo
            for photo in self.photos
            if photo.status not in {ReviewStatus.MOVED, ReviewStatus.TRASHED}
        ]
        if not candidates:
            return None
        max_megapixels = max((photo.megapixels for photo in candidates), default=1.0)
        return max(candidates, key=lambda photo: self._score(photo, max_megapixels))

    def recommendation_reason(self, photo: PhotoRecord) -> str:
        if photo is self.recommended:
            return "本组清晰度与曝光综合得分最高"
        return "可与本组推荐照片对比清晰度和曝光"

    @property
    def kept_count(self) -> int:
        return sum(photo.status == ReviewStatus.KEPT for photo in self.photos)

    @property
    def reviewed(self) -> bool:
        return all(photo.status != ReviewStatus.PENDING for photo in self.photos)
