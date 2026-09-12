import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from photo_fit_picker.models import PhotoRecord, ReviewStatus
from photo_fit_picker.session import ReviewSessionStore


def make_photo(path: Path, status: ReviewStatus = ReviewStatus.PENDING) -> PhotoRecord:
    return PhotoRecord(
        path=path,
        width=100,
        height=100,
        file_size=path.stat().st_size,
        captured_at=datetime.now(),
        dhash=0,
        color_signature=tuple([0.0] * 48),
        sharpness=0.1,
        exposure=0.5,
        status=status,
    )


class ReviewSessionStoreTests(unittest.TestCase):
    def test_review_decisions_are_restored_without_batch_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "photos"
            source.mkdir()
            keep_path = source / "keep.jpg"
            reject_path = source / "reject.jpg"
            keep_path.write_bytes(b"keep")
            reject_path.write_bytes(b"reject")
            keep = make_photo(keep_path, ReviewStatus.KEPT)
            keep.selected = True
            reject = make_photo(reject_path, ReviewStatus.REJECTED)
            store = ReviewSessionStore(root / "state")

            summary = store.save(source, [keep, reject])
            restored_keep = make_photo(keep_path)
            restored_reject = make_photo(reject_path)
            restored_keep.selected = True
            restored = store.restore(source, [restored_keep, restored_reject])

            self.assertEqual(restored, 2)
            self.assertEqual(summary.reviewed_count, 2)
            self.assertEqual(restored_keep.status, ReviewStatus.KEPT)
            self.assertEqual(restored_reject.status, ReviewStatus.REJECTED)
            self.assertFalse(restored_keep.selected)
            self.assertEqual(store.latest(), summary)

    def test_replaced_file_does_not_inherit_an_old_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "photos"
            source.mkdir()
            path = source / "same-name.jpg"
            path.write_bytes(b"old")
            store = ReviewSessionStore(root / "state")
            store.save(source, [make_photo(path, ReviewStatus.KEPT)])

            path.write_bytes(b"new and different")
            replacement = make_photo(path)

            self.assertEqual(store.restore(source, [replacement]), 0)
            self.assertEqual(replacement.status, ReviewStatus.PENDING)

    def test_corrupt_session_files_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "photos"
            source.mkdir()
            path = source / "photo.jpg"
            path.write_bytes(b"photo")
            store = ReviewSessionStore(root / "state")
            store.save(source, [make_photo(path, ReviewStatus.KEPT)])
            store._session_path(source).write_text("not json", encoding="utf-8")

            restored = make_photo(path)
            self.assertEqual(store.restore(source, [restored]), 0)
            self.assertEqual(restored.status, ReviewStatus.PENDING)

            (store.root / "latest.json").write_text(
                json.dumps({"source": str(source)}),
                encoding="utf-8",
            )
            self.assertIsNone(store.latest())


if __name__ == "__main__":
    unittest.main()
