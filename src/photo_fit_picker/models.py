from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple


class ReviewStatus(str, Enum):
    PENDING = "pending"
    KEPT = "kept"
    REJECTED = "rejected"
    MOVED = "moved"
    TRASHED = "trashed"


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
    metadata: CameraMetadata = field(default_factory=CameraMetadata)
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
        size = float(self.file_size)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                precision = 0 if unit == "B" else 1
                return f"{size:.{precision}f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"

    @property
    def format_label(self) -> str:
        return self.path.suffix.lstrip(".").upper() or "图片"

    @property
    def dimension_label(self) -> str:
        return f"{self.width} × {self.height}"

    @property
    def quality_score(self) -> float:
        exposure_quality = max(0.0, 1.0 - abs(self.exposure - 0.5) * 1.8)
        sharpness_quality = min(1.0, self.sharpness / 0.12)
        return sharpness_quality * 0.75 + exposure_quality * 0.25


@dataclass
class PhotoGroup:
    id: int
    photos: list[PhotoRecord] = field(default_factory=list)

    @property
    def recommended(self) -> Optional[PhotoRecord]:
        candidates = [
            photo
            for photo in self.photos
            if photo.status not in {ReviewStatus.MOVED, ReviewStatus.TRASHED}
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda photo: photo.quality_score)

    @property
    def kept_count(self) -> int:
        return sum(photo.status == ReviewStatus.KEPT for photo in self.photos)

    @property
    def reviewed(self) -> bool:
        return all(photo.status != ReviewStatus.PENDING for photo in self.photos)
