from __future__ import annotations

import json
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Optional

from .analysis import SUPPORTED_EXTENSIONS
from .models import PhotoRecord, ReviewStatus

if TYPE_CHECKING:
    from .organizer import OrganizationPlan


HISTORY_FILE = ".photo-fit-picker-history.json"


@dataclass(frozen=True)
class MoveEntry:
    source: str
    destination: str
    moved_at: str
    previous_status: str = ""


LINKED_EXTENSIONS = SUPPORTED_EXTENSIONS | {".xmp"}


def _available_destination(folder: Path, filename: str) -> Path:
    candidate = folder / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 2
    while True:
        candidate = folder / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _history_path(destination: Path) -> Path:
    return destination / HISTORY_FILE


def _send2trash(path: str) -> None:
    source = Path(path)
    if sys.platform == "darwin":
        trash = Path.home() / ".Trash"
        trash.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(_available_destination(trash, source.name)))
        return

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class FileOperation(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_ushort),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        recycle = FileOperation()
        recycle.wFunc = 3  # FO_DELETE
        recycle.pFrom = str(source) + "\0\0"
        recycle.fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(recycle))
        if result != 0 or recycle.fAnyOperationsAborted:
            raise OSError(f"Windows 回收站操作失败，错误代码：{result}")
        return

    raise OSError("当前操作系统暂不支持移到回收站")


def read_history(destination: Path) -> list[MoveEntry]:
    path = _history_path(destination)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [MoveEntry(**item) for item in data if isinstance(item, dict)]
    except (OSError, ValueError, TypeError):
        return []


def _write_history(destination: Path, entries: list[MoveEntry]) -> None:
    payload = [asdict(entry) for entry in entries]
    path = _history_path(destination)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def linked_asset_paths(path: Path) -> list[Path]:
    source = path.resolve()
    if not source.is_file():
        return []
    stem = source.stem.casefold()
    try:
        siblings = source.parent.iterdir()
    except OSError:
        return [source]
    return sorted(
        (
            sibling.resolve()
            for sibling in siblings
            if sibling.is_file()
            and sibling.stem.casefold() == stem
            and sibling.suffix.lower() in LINKED_EXTENSIONS
        ),
        key=lambda candidate: (candidate != source, candidate.suffix.lower()),
    )


def expand_linked_photo_records(
    records: Iterable[PhotoRecord],
    selected: Iterable[PhotoRecord],
) -> list[PhotoRecord]:
    all_records = list(records)
    keys = {
        (photo.path.resolve().parent, photo.path.stem.casefold())
        for photo in selected
    }
    return [
        photo
        for photo in all_records
        if (photo.path.resolve().parent, photo.path.stem.casefold()) in keys
        and photo.status not in {ReviewStatus.MOVED, ReviewStatus.TRASHED}
    ]


def _reserved_destination(
    folder: Path,
    filename: str,
    reserved: set[Path],
) -> Path:
    candidate = folder / filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 2
    while candidate.exists() or candidate.resolve() in reserved:
        candidate = folder / f"{stem}_{counter}{suffix}"
        counter += 1
    reserved.add(candidate.resolve())
    return candidate


def _plan_photo_moves(
    photos: Iterable[PhotoRecord],
    destination: Path,
    batch_time: str,
    reserved: Optional[set[Path]] = None,
    seen: Optional[set[Path]] = None,
) -> list[MoveEntry]:
    records = list(photos)
    status_by_source = {
        photo.path.resolve(): photo.status.value
        for photo in records
    }
    planned: list[MoveEntry] = []
    source_paths = seen if seen is not None else set()
    destinations = reserved if reserved is not None else set()
    for photo in records:
        for source in linked_asset_paths(photo.path):
            if source in source_paths:
                continue
            source_paths.add(source)
            target = _reserved_destination(destination, source.name, destinations)
            planned.append(
                MoveEntry(
                    source=str(source),
                    destination=str(target.resolve()),
                    moved_at=batch_time,
                    previous_status=status_by_source.get(source, ""),
                )
            )
    return planned


def _execute_move_entries(entries: list[MoveEntry], history_root: Path) -> list[MoveEntry]:
    if not entries:
        return []
    history_root.mkdir(parents=True, exist_ok=True)
    history = read_history(history_root)
    completed: list[MoveEntry] = []
    try:
        for entry in entries:
            source = Path(entry.source)
            destination = Path(entry.destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            completed.append(entry)
        _write_history(history_root, history + completed)
    except Exception as exc:
        rollback_errors: list[str] = []
        unrestored: list[MoveEntry] = []
        for entry in reversed(completed):
            source = Path(entry.source)
            destination = Path(entry.destination)
            try:
                if destination.exists() and not source.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(destination), str(source))
                elif destination.exists():
                    unrestored.append(entry)
            except OSError as rollback_error:
                unrestored.append(entry)
                rollback_errors.append(f"{destination.name}: {rollback_error}")
        history_error = ""
        if unrestored:
            try:
                _write_history(history_root, history + list(reversed(unrestored)))
            except OSError as write_error:
                history_error = f"；移动历史也无法写入：{write_error}"
        if unrestored:
            detail = f"移动失败，且有 {len(unrestored)} 个文件未能回滚：{exc}"
        else:
            detail = f"移动失败，已回滚本批操作：{exc}"
        if rollback_errors:
            detail += "\n回滚错误：" + "；".join(rollback_errors)
        detail += history_error
        raise OSError(detail) from exc
    return completed


def _update_moved_records(
    records: Iterable[PhotoRecord],
    entries: Iterable[MoveEntry],
) -> None:
    destinations = {
        Path(entry.source).resolve(): Path(entry.destination).resolve()
        for entry in entries
    }
    for photo in records:
        target = destinations.get(photo.path.resolve())
        if target:
            photo.path = target
            photo.status = ReviewStatus.MOVED
            photo.selected = False


def _move_photos(photos: Iterable[PhotoRecord], destination: Path) -> list[MoveEntry]:
    records = [
        photo
        for photo in photos
        if photo.status not in {ReviewStatus.MOVED, ReviewStatus.TRASHED}
    ]
    batch_time = datetime.now().isoformat(timespec="microseconds")
    planned = _plan_photo_moves(records, destination, batch_time)
    moved = _execute_move_entries(planned, destination)
    _update_moved_records(records, moved)
    return moved


def move_selected(photos: Iterable[PhotoRecord], destination: Path) -> list[MoveEntry]:
    records = list(photos)
    kept = [photo for photo in records if photo.status == ReviewStatus.KEPT]
    return _move_photos(expand_linked_photo_records(records, kept), destination)


def move_photos(photos: Iterable[PhotoRecord], destination: Path) -> list[MoveEntry]:
    """Move only the photo records explicitly supplied by the caller."""
    return _move_photos(photos, destination)


def plan_organization_moves(
    plan: "OrganizationPlan",
    destination_root: Path,
) -> list[MoveEntry]:
    batch_time = datetime.now().isoformat(timespec="microseconds")
    reserved: set[Path] = set()
    planned: list[MoveEntry] = []
    used_names: dict[str, int] = {}
    seen: set[Path] = set()
    for group in plan.groups:
        count = used_names.get(group.name.casefold(), 0) + 1
        used_names[group.name.casefold()] = count
        folder_name = group.name if count == 1 else f"{group.name} ({count})"
        planned.extend(
            _plan_photo_moves(
                group.photos,
                destination_root / folder_name,
                batch_time,
                reserved,
                seen,
            )
        )
    return planned


def execute_organization_plan(
    plan: "OrganizationPlan",
    destination_root: Path,
) -> list[MoveEntry]:
    records = [photo for group in plan.groups for photo in group.photos]
    planned = plan_organization_moves(plan, destination_root)
    moved = _execute_move_entries(planned, destination_root)
    _update_moved_records(records, moved)
    return moved


def move_photo_to_trash(photo: PhotoRecord) -> Path:
    """Move one explicitly selected photo to the operating system trash."""
    source = photo.path.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"找不到照片：{source}")
    _send2trash(str(source))
    photo.status = ReviewStatus.TRASHED
    photo.selected = False
    return source


def undo_last_move(destination: Path) -> tuple[list[MoveEntry], list[str]]:
    history = read_history(destination)
    if not history:
        return [], []

    latest_time = history[-1].moved_at
    batch_start = len(history) - 1
    while batch_start > 0 and history[batch_start - 1].moved_at == latest_time:
        batch_start -= 1
    batch = history[batch_start:]

    restored: list[MoveEntry] = []
    errors: list[str] = []
    for entry in reversed(batch):
        source = Path(entry.source)
        current = Path(entry.destination)
        if not current.exists():
            errors.append(f"找不到已移动文件：{current}")
            continue
        if source.exists():
            errors.append(f"原位置已有同名文件：{source}")
            continue
        try:
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(current), str(source))
            restored.append(entry)
        except OSError as exc:
            errors.append(f"无法恢复 {current.name}：{exc}")

    restored_set = {(entry.source, entry.destination, entry.moved_at) for entry in restored}
    remaining = [
        entry
        for entry in history
        if (entry.source, entry.destination, entry.moved_at) not in restored_set
    ]
    _write_history(destination, remaining)
    return restored, errors
