import unittest
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import numpy
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

import photo_fit_picker.analysis as analysis_module
from photo_fit_picker.analysis import (
    RAW_EXTENSIONS,
    _gps_coordinate,
    discover_images,
    extract_feature,
    extract_metadata,
    group_similar_photos,
    hamming_distance,
    visual_similarity,
)
from photo_fit_picker.models import PhotoRecord


def make_photo(name: str, hash_value: int, seconds: int, color: tuple[float, ...]) -> PhotoRecord:
    return PhotoRecord(
        path=Path(name),
        width=4000,
        height=3000,
        file_size=1_000_000,
        captured_at=datetime(2026, 1, 1, 12, 0, 0) + timedelta(seconds=seconds),
        dhash=hash_value,
        color_signature=color,
        sharpness=0.1,
        exposure=0.5,
    )


class AnalysisTests(unittest.TestCase):
    def test_extracts_camera_and_shooting_metadata_from_jpeg(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "nikon.jpg"
            exif = Image.Exif()
            exif[271] = "NIKON CORPORATION"
            exif[272] = "NIKON Z 8"
            exif[36867] = "2026:09:12 14:35:06"
            exif[33434] = IFDRational(1, 250)
            exif[33437] = IFDRational(28, 10)
            exif[34855] = 640
            exif[37386] = IFDRational(85, 1)
            exif[42036] = "NIKKOR Z 85mm f/1.8 S"
            Image.new("RGB", (640, 480), (80, 120, 160)).save(path, exif=exif)

            record = extract_feature(path)

        self.assertEqual(record.captured_at, datetime(2026, 9, 12, 14, 35, 6))
        self.assertEqual(record.metadata.make, "NIKON CORPORATION")
        self.assertEqual(record.metadata.model, "NIKON Z 8")
        self.assertEqual(record.metadata.lens, "NIKKOR Z 85mm f/1.8 S")
        self.assertAlmostEqual(record.metadata.exposure_time or 0, 1 / 250)
        self.assertAlmostEqual(record.metadata.aperture or 0, 2.8)
        self.assertEqual(record.metadata.iso, 640)
        self.assertEqual(record.metadata.focal_length, 85)
        self.assertIn("1/250 秒", record.metadata.shooting_summary)

    def test_gps_dms_coordinates_are_converted(self) -> None:
        value = SimpleNamespace(
            values=[IFDRational(31, 1), IFDRational(13, 1), IFDRational(48, 1)]
        )

        self.assertAlmostEqual(_gps_coordinate(value, "N") or 0, 31.23)
        self.assertAlmostEqual(_gps_coordinate(value, "W") or 0, -31.23)

    def test_missing_or_damaged_metadata_falls_back_safely(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "plain.jpg"
            Image.new("RGB", (32, 24), "white").save(path)
            self.assertEqual(extract_metadata(path).camera_label, "")

            with patch.object(
                analysis_module.exifread,
                "process_file",
                side_effect=RuntimeError("damaged maker note"),
            ):
                metadata = extract_metadata(path)

        self.assertEqual(metadata.shooting_summary, "")
        self.assertFalse(metadata.has_location)

    def test_common_camera_raw_extensions_are_discovered(self) -> None:
        expected = {".cr2", ".cr3", ".nef", ".arw", ".raf", ".dng", ".rw2"}
        self.assertTrue(expected.issubset(RAW_EXTENSIONS))
        with TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            for name in ("canon.CR3", "nikon.nef", "notes.txt"):
                (folder / name).write_bytes(b"test")

            discovered = {path.name for path in discover_images(folder)}

            self.assertEqual(discovered, {"canon.CR3", "nikon.nef"})

    def test_raw_embedded_preview_is_used_for_analysis(self) -> None:
        buffer = BytesIO()
        Image.new("RGB", (800, 600), (80, 140, 190)).save(buffer, format="JPEG")

        class FakeRawFile:
            sizes = SimpleNamespace(width=6000, height=4000)

            def __enter__(self):  # type: ignore[no-untyped-def]
                return self

            def __exit__(self, *args) -> None:  # type: ignore[no-untyped-def]
                return None

            def extract_thumb(self):  # type: ignore[no-untyped-def]
                return SimpleNamespace(format="jpeg", data=buffer.getvalue())

        fake_rawpy = SimpleNamespace(
            ThumbFormat=SimpleNamespace(JPEG="jpeg"),
            imread=lambda _: FakeRawFile(),
        )

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "sample.cr3"
            path.write_bytes(b"fake raw container")
            with patch.object(analysis_module, "rawpy", fake_rawpy):
                record = extract_feature(path)

        self.assertEqual((record.width, record.height), (6000, 4000))
        self.assertEqual(len(record.color_signature), 48)
        self.assertGreater(record.exposure, 0.4)

    def test_raw_without_preview_uses_half_size_postprocess(self) -> None:
        class FakeRawFile:
            sizes = SimpleNamespace(width=5000, height=3300)
            postprocess_called = False

            def __enter__(self):  # type: ignore[no-untyped-def]
                return self

            def __exit__(self, *args) -> None:  # type: ignore[no-untyped-def]
                return None

            def extract_thumb(self):  # type: ignore[no-untyped-def]
                raise RuntimeError("no embedded preview")

            def postprocess(self, **kwargs):  # type: ignore[no-untyped-def]
                self.postprocess_called = True
                self.postprocess_options = kwargs
                return numpy.full((120, 180, 3), 128, dtype=numpy.uint8)

        fake_raw = FakeRawFile()
        fake_rawpy = SimpleNamespace(
            ThumbFormat=SimpleNamespace(JPEG="jpeg"),
            imread=lambda _: fake_raw,
        )

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "sample.nef"
            path.write_bytes(b"fake raw container")
            with patch.object(analysis_module, "rawpy", fake_rawpy):
                record = extract_feature(path)

        self.assertTrue(fake_raw.postprocess_called)
        self.assertTrue(fake_raw.postprocess_options["half_size"])
        self.assertEqual((record.width, record.height), (5000, 3300))

    def test_extract_feature_reads_real_image(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "sample.jpg"
            Image.new("RGB", (640, 480), (128, 160, 192)).save(path)

            record = extract_feature(path)

            self.assertEqual((record.width, record.height), (640, 480))
            self.assertGreater(record.file_size, 0)
            self.assertGreater(record.exposure, 0.5)
            self.assertEqual(len(record.color_signature), 48)

    def test_hamming_distance(self) -> None:
        self.assertEqual(hamming_distance(0b1010, 0b0011), 2)

    def test_similar_burst_photos_are_grouped(self) -> None:
        neutral = tuple([1 / 48] * 48)
        photos = [
            make_photo("a.jpg", 0xAAAAAAAAAAAAAAAA, 0, neutral),
            make_photo("b.jpg", 0xAAAAAAAAAAAAAAAB, 2, neutral),
            make_photo("c.jpg", 0x1111111111111111, 4, tuple([0.0] * 48)),
        ]

        groups = group_similar_photos(photos, similarity_threshold=0.84, time_window_seconds=10)

        self.assertEqual(sorted(len(group.photos) for group in groups), [1, 2])

    def test_distant_photos_stay_separate(self) -> None:
        neutral = tuple([1 / 48] * 48)
        left = make_photo("a.jpg", 0xAAAAAAAAAAAAAAAA, 0, neutral)
        right = make_photo("b.jpg", 0x5555555555555555, 1, neutral)

        self.assertLess(visual_similarity(left, right), 0.84)
        self.assertEqual(len(group_similar_photos([left, right])), 2)


if __name__ == "__main__":
    unittest.main()
