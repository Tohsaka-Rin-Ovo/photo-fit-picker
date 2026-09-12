from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from photo_fit_picker.models import CameraMetadata, PhotoRecord
from photo_fit_picker.organizer import build_organization_plan, safe_folder_name


def photo(
    name: str,
    captured_at: datetime,
    *,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> PhotoRecord:
    return PhotoRecord(
        path=Path(name),
        width=4000,
        height=3000,
        file_size=1_000_000,
        captured_at=captured_at,
        dhash=0,
        color_signature=tuple([0.0] * 48),
        sharpness=0.1,
        exposure=0.5,
        metadata=CameraMetadata(latitude=latitude, longitude=longitude),
    )


def test_plan_splits_dates_and_long_time_gaps() -> None:
    start = datetime(2026, 5, 1, 9)
    plan = build_organization_plan(
        [
            photo("a.jpg", start),
            photo("b.jpg", start + timedelta(minutes=20)),
            photo("c.jpg", start + timedelta(hours=5)),
            photo("d.jpg", start + timedelta(days=1)),
        ],
        gap_minutes=120,
    )

    assert [len(group.photos) for group in plan.groups] == [2, 1, 1]


def test_plan_splits_distant_gps_locations_and_assigns_unlocated_photo() -> None:
    start = datetime(2026, 5, 1, 9)
    plan = build_organization_plan(
        [
            photo("west.jpg", start, latitude=31.2304, longitude=121.4737),
            photo("nearby.jpg", start + timedelta(minutes=3)),
            photo(
                "east.jpg",
                start + timedelta(minutes=10),
                latitude=31.0304,
                longitude=121.8737,
            ),
        ],
        gps_radius_km=2,
    )

    assert len(plan.groups) == 2
    assert "nearby.jpg" in {item.path.name for item in plan.groups[0].photos}
    assert all("GPS" in group.reason for group in plan.groups)


def test_plan_can_rename_merge_and_split_without_touching_files() -> None:
    start = datetime(2026, 5, 1, 9)
    records = [
        photo("a.jpg", start),
        photo("b.jpg", start + timedelta(minutes=1)),
        photo("c.jpg", start + timedelta(hours=5)),
    ]
    plan = build_organization_plan(records, gap_minutes=60)
    plan.rename(1, " 西湖/清晨 ")
    assert plan.groups[0].name == "西湖-清晨"

    merged = plan.merge([1, 2])
    assert merged is not None
    assert len(plan.groups) == 1
    created = plan.split(1, [Path("c.jpg")])
    assert created is not None
    assert sorted(len(group.photos) for group in plan.groups) == [1, 2]
    assert all(not item.path.exists() for item in records)


def test_safe_folder_name_handles_invalid_or_empty_names() -> None:
    assert safe_folder_name('A/B:C*D?"E<F>G|') == "A-B-C-D--E-F-G-"
    assert safe_folder_name(" ... ") == "未命名活动"
