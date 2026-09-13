from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

import photo_fit_picker.analysis as analysis_module
from photo_fit_picker.analysis import analyze_paths
from photo_fit_picker.feature_cache import FeatureCache
from photo_fit_picker.models import CameraMetadata, PhotoRecord


def make_record(path: Path) -> PhotoRecord:
    return PhotoRecord(
        path=path,
        width=6000,
        height=4000,
        file_size=path.stat().st_size,
        captured_at=datetime(2026, 9, 13, 12, 0, 0),
        dhash=123,
        average_hash=456,
        color_signature=tuple([1 / 48] * 48),
        sharpness=0.12,
        exposure=0.5,
        metadata=CameraMetadata(
            captured_at=datetime(2026, 9, 13, 12, 0, 0),
            make="NIKON",
            model="NIKON Z 8",
            details=(("对焦模式", "AF-C"),),
        ),
        portrait_detected=True,
    )


def test_feature_cache_round_trip_and_file_invalidation() -> None:
    with TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        image = root / "photo.nef"
        image.write_bytes(b"original raw bytes")
        cache = FeatureCache(root / "cache" / "features.sqlite3")
        cache.store([make_record(image)])

        restored = cache.load([image])[image]
        assert restored.width == 6000
        assert restored.metadata.camera_label == "NIKON Z 8"
        assert restored.metadata.captured_at == datetime(2026, 9, 13, 12, 0, 0)
        assert restored.metadata.details == (("对焦模式", "AF-C"),)
        assert restored.portrait_detected is True

        image.write_bytes(b"changed raw bytes with a different size")
        assert cache.load([image]) == {}


def test_analysis_reuses_cached_features_without_decoding() -> None:
    with TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        image = root / "photo.jpg"
        image.write_bytes(b"cached image bytes")
        cache = FeatureCache(root / "features.sqlite3")
        cache.store([make_record(image)])

        with patch.object(
            analysis_module,
            "extract_feature",
            side_effect=AssertionError("cached files must not be decoded"),
        ):
            records, failures = analyze_paths([image], cache=cache)

        assert len(records) == 1
        assert failures == []


def test_analysis_adds_portrait_detection_to_older_cached_features() -> None:
    with TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        image = root / "photo.jpg"
        Image.new("RGB", (64, 48), "white").save(image)
        record = make_record(image)
        record.portrait_detected = None
        cache = FeatureCache(root / "features.sqlite3")
        cache.store([record])

        with patch.object(analysis_module, "_detect_portrait", return_value=True):
            records, failures = analyze_paths(
                [image],
                cache=cache,
                detect_portraits=True,
            )

        assert failures == []
        assert records[0].portrait_detected is True
        assert cache.load([image])[image].portrait_detected is True
