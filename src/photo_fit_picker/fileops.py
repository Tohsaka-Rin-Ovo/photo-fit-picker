from __future__ import annotations

import json
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .models import PhotoRecord, ReviewStatus


HISTORY_FILE = ".photo-fit-picker-history.json"


@dataclass(frozen=True)
class MoveEntry:
    source: str
    destination: str
    moved_at: str


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
    _history_path(destination).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _move_photos(photos: Iterable[PhotoRecord], destination: Path) -> list[MoveEntry]:
    destination.mkdir(parents=True, exist_ok=True)
    history = read_history(destination)
    moved: list[MoveEntry] = []
    batch_time = datetime.now().isoformat(timespec="microseconds")
    try:
        for photo in photos:
            if photo.status in {ReviewStatus.MOVED, ReviewStatus.TRASHED}:
                continue
            if not photo.path.is_file():
                continue
            target = _available_destination(destination, photo.path.name)
            source = photo.path.resolve()
            shutil.move(str(source), str(target))
            entry = MoveEntry(
                source=str(source),
                destination=str(target.resolve()),
                moved_at=batch_time,
            )
            moved.append(entry)
            history.append(entry)
            photo.path = target
            photo.status = ReviewStatus.MOVED
            photo.selected = False
    finally:
        if moved:
            _write_history(destination, history)
    return moved


def move_selected(photos: Iterable[PhotoRecord], destination: Path) -> list[MoveEntry]:
    kept = (photo for photo in photos if photo.status == ReviewStatus.KEPT)
    return _move_photos(kept, destination)


def move_photos(photos: Iterable[PhotoRecord], destination: Path) -> list[MoveEntry]:
    """Move only the photo records explicitly supplied by the caller."""
    return _move_photos(photos, destination)


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
