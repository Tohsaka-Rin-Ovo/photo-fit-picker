from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .models import PhotoRecord, ReviewStatus


SESSION_SCHEMA = 1
RESTORABLE_STATUSES = {ReviewStatus.KEPT, ReviewStatus.REJECTED}


@dataclass(frozen=True)
class ReviewSessionSummary:
    source: Path
    saved_at: str
    reviewed_count: int
    total_count: int


class ReviewSessionStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _session_path(self, source: Path) -> Path:
        key = hashlib.sha256(str(source.resolve()).encode("utf-8")).hexdigest()[:24]
        return self.root / f"{key}.json"

    def _write_json(self, path: Path, payload: object) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def save(
        self,
        source: Path,
        records: Iterable[PhotoRecord],
    ) -> ReviewSessionSummary:
        source = source.resolve()
        photos = list(records)
        decisions: list[dict[str, object]] = []
        for photo in photos:
            if photo.status not in RESTORABLE_STATUSES:
                continue
            path = photo.path.resolve()
            try:
                relative_path = path.relative_to(source).as_posix()
                stat = path.stat()
            except (OSError, ValueError):
                continue
            decisions.append(
                {
                    "path": relative_path,
                    "status": photo.status.value,
                    "file_size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )

        summary = ReviewSessionSummary(
            source=source,
            saved_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            reviewed_count=sum(photo.status != ReviewStatus.PENDING for photo in photos),
            total_count=len(photos),
        )
        self._write_json(
            self._session_path(source),
            {
                "schema": SESSION_SCHEMA,
                "source": str(source),
                "saved_at": summary.saved_at,
                "reviewed_count": summary.reviewed_count,
                "total_count": summary.total_count,
                "decisions": decisions,
            },
        )
        latest = asdict(summary)
        latest["source"] = str(source)
        self._write_json(self.root / "latest.json", latest)
        return summary

    def latest(self) -> Optional[ReviewSessionSummary]:
        payload = self._read_json(self.root / "latest.json")
        if not isinstance(payload, dict):
            return None
        try:
            source = Path(str(payload["source"]))
            summary = ReviewSessionSummary(
                source=source,
                saved_at=str(payload["saved_at"]),
                reviewed_count=max(0, int(payload["reviewed_count"])),
                total_count=max(0, int(payload["total_count"])),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if not summary.source.is_dir() or not self._session_path(source).is_file():
            return None
        return summary

    def restore(self, source: Path, records: Iterable[PhotoRecord]) -> int:
        source = source.resolve()
        payload = self._read_json(self._session_path(source))
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != SESSION_SCHEMA
            or payload.get("source") != str(source)
            or not isinstance(payload.get("decisions"), list)
        ):
            return 0

        decisions: dict[str, dict[str, object]] = {}
        for item in payload["decisions"]:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                decisions[str(item["path"])] = item

        restored = 0
        for photo in records:
            path = photo.path.resolve()
            try:
                key = path.relative_to(source).as_posix()
                stat = path.stat()
            except (OSError, ValueError):
                continue
            decision = decisions.get(key)
            if not decision:
                continue
            try:
                status = ReviewStatus(str(decision["status"]))
                file_size = int(decision["file_size"])
                mtime_ns = int(decision["mtime_ns"])
            except (KeyError, TypeError, ValueError):
                continue
            if (
                status not in RESTORABLE_STATUSES
                or file_size != photo.file_size
                or mtime_ns != stat.st_mtime_ns
            ):
                continue
            photo.status = status
            photo.selected = False
            restored += 1
        return restored

    @staticmethod
    def _read_json(path: Path) -> object:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
