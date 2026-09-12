from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .models import PhotoRecord, ReviewStatus


def _distance_km(left: PhotoRecord, right: PhotoRecord) -> float:
    left_meta = left.metadata
    right_meta = right.metadata
    if not left_meta.has_location or not right_meta.has_location:
        return math.inf
    lat1 = math.radians(float(left_meta.latitude))
    lat2 = math.radians(float(right_meta.latitude))
    delta_lat = lat2 - lat1
    delta_lon = math.radians(float(right_meta.longitude) - float(left_meta.longitude))
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    value = max(0.0, min(1.0, value))
    return 6371.0 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _period_name(captured_at: datetime) -> str:
    if captured_at.hour < 6:
        return "凌晨"
    if captured_at.hour < 12:
        return "上午"
    if captured_at.hour < 18:
        return "下午"
    return "夜晚"


def safe_folder_name(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]", "-", value).strip(" .")
    cleaned = " ".join(cleaned.split())
    return (cleaned or "未命名活动")[:80]


@dataclass
class OrganizationGroup:
    id: int
    name: str
    photos: list[PhotoRecord]
    reason: str

    @property
    def date_range(self) -> str:
        ordered = sorted(photo.captured_at for photo in self.photos)
        start = ordered[0]
        end = ordered[-1]
        if start.date() == end.date():
            return f"{start:%Y-%m-%d}  {start:%H:%M}–{end:%H:%M}"
        return f"{start:%Y-%m-%d} – {end:%Y-%m-%d}"


@dataclass
class OrganizationPlan:
    groups: list[OrganizationGroup] = field(default_factory=list)

    def group(self, group_id: int) -> Optional[OrganizationGroup]:
        return next((group for group in self.groups if group.id == group_id), None)

    def rename(self, group_id: int, name: str) -> None:
        group = self.group(group_id)
        if group:
            group.name = safe_folder_name(name)

    def merge(self, group_ids: Iterable[int]) -> Optional[OrganizationGroup]:
        requested_ids = set(group_ids)
        selected = [group for group in self.groups if group.id in requested_ids]
        if len(selected) < 2:
            return None
        photos = sorted(
            (photo for group in selected for photo in group.photos),
            key=lambda photo: (photo.captured_at, photo.path.name.lower()),
        )
        merged = OrganizationGroup(
            id=min(group.id for group in selected),
            name=selected[0].name,
            photos=photos,
            reason=f"手动合并了 {len(selected)} 个整理分组",
        )
        selected_ids = {group.id for group in selected}
        self.groups = [group for group in self.groups if group.id not in selected_ids]
        self.groups.append(merged)
        self._normalize()
        return merged

    def split(
        self,
        group_id: int,
        photo_paths: Iterable[Path],
    ) -> Optional[OrganizationGroup]:
        group = self.group(group_id)
        selected_paths = {path.resolve() for path in photo_paths}
        if not group or not selected_paths:
            return None
        selected = [photo for photo in group.photos if photo.path.resolve() in selected_paths]
        if not selected or len(selected) == len(group.photos):
            return None
        group.photos = [photo for photo in group.photos if photo not in selected]
        created = OrganizationGroup(
            id=max((item.id for item in self.groups), default=0) + 1,
            name=safe_folder_name(f"{group.name} - 新分组"),
            photos=selected,
            reason="从原分组手动拆分",
        )
        self.groups.append(created)
        self._normalize()
        return created

    def _normalize(self) -> None:
        self.groups.sort(key=lambda group: min(photo.captured_at for photo in group.photos))
        for index, group in enumerate(self.groups, start=1):
            group.id = index


def _activity_groups(
    photos: list[PhotoRecord],
    gap_minutes: int,
) -> list[list[PhotoRecord]]:
    activities: list[list[PhotoRecord]] = []
    for photo in photos:
        if not activities:
            activities.append([photo])
            continue
        previous = activities[-1][-1]
        gap = (photo.captured_at - previous.captured_at).total_seconds() / 60
        if photo.captured_at.date() != previous.captured_at.date() or gap > gap_minutes:
            activities.append([photo])
        else:
            activities[-1].append(photo)
    return activities


def _location_groups(
    activity: list[PhotoRecord],
    radius_km: float,
) -> list[list[PhotoRecord]]:
    located = [photo for photo in activity if photo.metadata.has_location]
    if len(located) < 2:
        return [activity]
    clusters: list[list[PhotoRecord]] = []
    for photo in located:
        cluster = next(
            (
                candidate
                for candidate in clusters
                if min(_distance_km(photo, item) for item in candidate) <= radius_km
            ),
            None,
        )
        if cluster is None:
            clusters.append([photo])
        else:
            cluster.append(photo)
    if len(clusters) == 1:
        return [activity]

    for photo in (item for item in activity if not item.metadata.has_location):
        nearest = min(
            clusters,
            key=lambda cluster: min(
                abs((photo.captured_at - item.captured_at).total_seconds())
                for item in cluster
            ),
        )
        nearest.append(photo)
    return [sorted(cluster, key=lambda photo: photo.captured_at) for cluster in clusters]


def build_organization_plan(
    records: Iterable[PhotoRecord],
    *,
    gap_minutes: int = 180,
    gps_radius_km: float = 2.0,
) -> OrganizationPlan:
    photos = sorted(
        (
            photo
            for photo in records
            if photo.status not in {ReviewStatus.MOVED, ReviewStatus.TRASHED}
        ),
        key=lambda photo: (photo.captured_at, photo.path.name.lower()),
    )
    result: list[OrganizationGroup] = []
    for activity in _activity_groups(photos, max(1, gap_minutes)):
        location_groups = _location_groups(activity, max(0.1, gps_radius_km))
        for location_index, grouped in enumerate(location_groups, start=1):
            start = grouped[0].captured_at
            if len(location_groups) > 1:
                name = f"{start:%Y-%m-%d} 地点 {location_index}"
                reason = f"同一拍摄日，GPS 相距不超过 {gps_radius_km:g} km"
            else:
                name = f"{start:%Y-%m-%d} {_period_name(start)}"
                reason = f"同一拍摄日，照片间隔不超过 {gap_minutes} 分钟"
                cameras = sorted(
                    {photo.metadata.camera_label for photo in grouped if photo.metadata.camera_label}
                )
                if cameras:
                    reason += f"；设备：{', '.join(cameras[:2])}"
            result.append(
                OrganizationGroup(
                    id=len(result) + 1,
                    name=safe_folder_name(name),
                    photos=grouped,
                    reason=reason,
                )
            )
    return OrganizationPlan(result)
