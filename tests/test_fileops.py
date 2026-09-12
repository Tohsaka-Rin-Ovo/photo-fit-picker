import tempfile
import unittest
import shutil
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from photo_fit_picker.fileops import (
    execute_organization_plan,
    move_photo_to_trash,
    move_photos,
    move_selected,
    read_history,
    undo_last_move,
)
from photo_fit_picker.models import PhotoRecord, ReviewStatus
from photo_fit_picker.organizer import OrganizationGroup, OrganizationPlan


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
    def test_explicit_batch_move_does_not_include_other_kept_photos(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            destination = root / "picked"
            source.mkdir()
            selected_path = source / "selected.jpg"
            other_path = source / "other-kept.jpg"
            selected_path.write_bytes(b"selected")
            other_path.write_bytes(b"other")
            selected = make_photo(selected_path, ReviewStatus.PENDING)
            selected.selected = True
            other_kept = make_photo(other_path, ReviewStatus.KEPT)

            moved = move_photos([selected], destination)

            self.assertEqual(len(moved), 1)
            self.assertTrue((destination / "selected.jpg").exists())
            self.assertFalse(selected_path.exists())
            self.assertFalse(selected.selected)
            self.assertTrue(other_path.exists())
            self.assertEqual(other_kept.status, ReviewStatus.KEPT)

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

    def test_symbolic_link_is_never_moved_or_trashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "target.jpg"
            target.write_bytes(b"original")
            link = root / "linked.jpg"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symbolic links are not available")
            record = make_photo(link, ReviewStatus.KEPT)

            with self.assertRaisesRegex(OSError, "符号链接"):
                move_selected([record], root / "picked")
            with self.assertRaisesRegex(OSError, "符号链接"):
                move_photo_to_trash(record)

            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_bytes(), b"original")

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

    def test_move_to_current_folder_is_rejected_without_renaming_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory)
            path = source / "keep.jpg"
            path.write_bytes(b"original")

            with self.assertRaisesRegex(OSError, "当前所在文件夹相同"):
                move_selected([make_photo(path, ReviewStatus.KEPT)], source)

            self.assertEqual(path.read_bytes(), b"original")
            self.assertFalse((source / "keep_2.jpg").exists())
            self.assertEqual(read_history(source), [])

    def test_raw_jpeg_and_xmp_are_moved_and_undone_together(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            destination = root / "picked"
            source.mkdir()
            raw_path = source / "DSC_0042.NEF"
            jpeg_path = source / "DSC_0042.jpg"
            xmp_path = source / "DSC_0042.xmp"
            raw_path.write_bytes(b"raw")
            jpeg_path.write_bytes(b"jpeg")
            xmp_path.write_bytes(b"rating=5")
            raw = make_photo(raw_path, ReviewStatus.KEPT)
            jpeg = make_photo(jpeg_path, ReviewStatus.REJECTED)

            moved = move_selected([raw, jpeg], destination)

            self.assertEqual(len(moved), 3)
            self.assertTrue((destination / "DSC_0042.NEF").exists())
            self.assertTrue((destination / "DSC_0042.jpg").exists())
            self.assertTrue((destination / "DSC_0042.xmp").exists())
            self.assertEqual(raw.status, ReviewStatus.MOVED)
            self.assertEqual(jpeg.status, ReviewStatus.MOVED)

            restored, errors = undo_last_move(destination)
            self.assertEqual(len(restored), 3)
            self.assertEqual(errors, [])
            self.assertTrue(raw_path.exists())
            self.assertTrue(jpeg_path.exists())
            self.assertTrue(xmp_path.exists())
            statuses = {
                Path(entry.source).suffix.lower(): entry.previous_status
                for entry in restored
            }
            self.assertEqual(statuses[".nef"], ReviewStatus.KEPT.value)
            self.assertEqual(statuses[".jpg"], ReviewStatus.REJECTED.value)

    def test_failed_batch_move_rolls_back_without_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            destination = root / "picked"
            source.mkdir()
            first_path = source / "first.jpg"
            second_path = source / "second.jpg"
            first_path.write_bytes(b"first")
            second_path.write_bytes(b"second")
            first = make_photo(first_path, ReviewStatus.KEPT)
            second = make_photo(second_path, ReviewStatus.KEPT)
            real_move = shutil.move

            def fail_second(source_name: str, destination_name: str):  # type: ignore[no-untyped-def]
                if Path(source_name).name == "second.jpg":
                    raise OSError("simulated disk error")
                return real_move(source_name, destination_name)

            with patch("photo_fit_picker.fileops.shutil.move", side_effect=fail_second):
                with self.assertRaisesRegex(OSError, "已回滚"):
                    move_selected([first, second], destination)

            self.assertTrue(first_path.exists())
            self.assertTrue(second_path.exists())
            self.assertEqual(first.status, ReviewStatus.KEPT)
            self.assertEqual(second.status, ReviewStatus.KEPT)
            self.assertEqual(read_history(destination), [])

    def test_organization_uses_distinct_folders_and_keeps_history_at_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            destination = root / "organized"
            source.mkdir()
            first_path = source / "first.jpg"
            second_path = source / "second.jpg"
            first_path.write_bytes(b"first")
            second_path.write_bytes(b"second")
            first = make_photo(first_path, ReviewStatus.PENDING)
            second = make_photo(second_path, ReviewStatus.REJECTED)
            plan = OrganizationPlan(
                [
                    OrganizationGroup(1, "旅行", [first], "test"),
                    OrganizationGroup(2, "旅行", [second], "test"),
                ]
            )

            moved = execute_organization_plan(plan, destination)

            self.assertEqual(len(moved), 2)
            self.assertTrue((destination / "旅行" / "first.jpg").exists())
            self.assertTrue((destination / "旅行 (2)" / "second.jpg").exists())
            self.assertEqual(len(read_history(destination)), 2)
            self.assertEqual(first.status, ReviewStatus.MOVED)
            self.assertEqual(second.status, ReviewStatus.MOVED)


if __name__ == "__main__":
    unittest.main()
