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
