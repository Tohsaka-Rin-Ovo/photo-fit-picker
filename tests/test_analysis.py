import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from photo_fit_picker.analysis import (
    extract_feature,
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
