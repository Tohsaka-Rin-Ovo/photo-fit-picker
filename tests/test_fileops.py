import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from photo_fit_picker.fileops import (
    move_photo_to_trash,
    move_selected,
    read_history,
    undo_last_move,
)
from photo_fit_picker.models import PhotoRecord, ReviewStatus


def make_photo(path: Path, status: ReviewStatus) -> PhotoRecord:
    return PhotoRecord(
        path=path,
        width=100,
        height=100,
        file_size=4,
        captured_at=datetime.now(),
        dhash=0,
        color_signature=tuple([0.0] * 48),
        sharpness=0.1,
        exposure=0.5,
        status=status,
    )


class FileOperationTests(unittest.TestCase):
    def test_rejected_photo_is_never_deleted_or_moved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "reject.jpg"
            source.write_bytes(b"original")
            rejected = make_photo(source, ReviewStatus.REJECTED)

            moved = move_selected([rejected], root / "picked")

            self.assertEqual(moved, [])
            self.assertTrue(source.exists())
            self.assertEqual(source.read_bytes(), b"original")

    def test_manual_trash_uses_system_recycle_bin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "manual-delete.jpg"
            source.write_bytes(b"original")
            record = make_photo(source, ReviewStatus.REJECTED)

            with patch("photo_fit_picker.fileops._send2trash") as send_to_trash:
                trashed_path = move_photo_to_trash(record)

            send_to_trash.assert_called_once_with(str(source.resolve()))
            self.assertEqual(trashed_path, source.resolve())
            self.assertEqual(record.status, ReviewStatus.TRASHED)

    def test_failed_trash_does_not_change_photo_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "protected.jpg"
            source.write_bytes(b"original")
            record = make_photo(source, ReviewStatus.REJECTED)

            with patch(
                "photo_fit_picker.fileops._send2trash",
                side_effect=OSError("permission denied"),
            ):
                with self.assertRaises(OSError):
                    move_photo_to_trash(record)

            self.assertEqual(record.status, ReviewStatus.REJECTED)
            self.assertTrue(source.exists())

    def test_only_kept_photos_are_moved_and_can_be_undone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            destination = root / "picked"
            source.mkdir()
            keep_path = source / "keep.jpg"
            reject_path = source / "reject.jpg"
            keep_path.write_bytes(b"keep")
            reject_path.write_bytes(b"reject")
            kept = make_photo(keep_path, ReviewStatus.KEPT)
            rejected = make_photo(reject_path, ReviewStatus.REJECTED)

            moved = move_selected([kept, rejected], destination)

            self.assertEqual(len(moved), 1)
            self.assertFalse(keep_path.exists())
            self.assertTrue(reject_path.exists())
            self.assertTrue((destination / "keep.jpg").exists())
            self.assertEqual(len(read_history(destination)), 1)

            restored, errors = undo_last_move(destination)

            self.assertEqual(len(restored), 1)
            self.assertEqual(errors, [])
            self.assertTrue(keep_path.exists())
            self.assertFalse((destination / "keep.jpg").exists())

    def test_name_collisions_do_not_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_folder = root / "one"
            second_folder = root / "two"
            destination = root / "picked"
            first_folder.mkdir()
            second_folder.mkdir()
            first = first_folder / "same.jpg"
            second = second_folder / "same.jpg"
            first.write_bytes(b"first")
            second.write_bytes(b"second")

            move_selected(
                [make_photo(first, ReviewStatus.KEPT), make_photo(second, ReviewStatus.KEPT)],
                destination,
            )

            self.assertEqual((destination / "same.jpg").read_bytes(), b"first")
            self.assertEqual((destination / "same_2.jpg").read_bytes(), b"second")


if __name__ == "__main__":
    unittest.main()
