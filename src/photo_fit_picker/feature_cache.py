from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from .models import CameraMetadata, PhotoRecord


CACHE_SCHEMA = 1
MAX_CACHE_ENTRIES = 20_000


class FeatureCache:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS features (
                path TEXT PRIMARY KEY,
                file_size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                schema_version INTEGER NOT NULL,
                payload TEXT NOT NULL,
                last_used INTEGER NOT NULL
            )
            """
        )
        return connection

    def load(self, paths: Sequence[Path]) -> dict[Path, PhotoRecord]:
        found: dict[Path, PhotoRecord] = {}
        touched: list[tuple[int, str]] = []
        try:
            with closing(self._connect()) as connection, connection:
                now = int(time.time())
                for path in paths:
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    key = str(path.resolve())
                    row = connection.execute(
                        """
                        SELECT payload FROM features
                        WHERE path = ? AND file_size = ? AND mtime_ns = ?
                              AND schema_version = ?
                        """,
                        (key, stat.st_size, stat.st_mtime_ns, CACHE_SCHEMA),
                    ).fetchone()
                    if not row:
                        continue
                    try:
                        found[path] = self._decode(path, stat.st_size, row[0])
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                        continue
                    touched.append((now, key))
                connection.executemany(
                    "UPDATE features SET last_used = ? WHERE path = ?",
                    touched,
                )
        except (OSError, sqlite3.Error):
            return {}
        return found

    def store(self, records: Iterable[PhotoRecord]) -> None:
        rows: list[tuple[object, ...]] = []
        now = int(time.time())
        for record in records:
            try:
                stat = record.path.stat()
                payload = self._encode(record)
            except (OSError, TypeError, ValueError):
                continue
            rows.append(
                (
                    str(record.path.resolve()),
                    stat.st_size,
                    stat.st_mtime_ns,
                    CACHE_SCHEMA,
                    payload,
                    now,
                )
            )
        if not rows:
            return
        try:
            with closing(self._connect()) as connection, connection:
                connection.executemany(
                    """
                    INSERT INTO features
                        (path, file_size, mtime_ns, schema_version, payload, last_used)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        file_size = excluded.file_size,
                        mtime_ns = excluded.mtime_ns,
                        schema_version = excluded.schema_version,
                        payload = excluded.payload,
                        last_used = excluded.last_used
                    """,
                    rows,
                )
                connection.execute(
                    """
                    DELETE FROM features WHERE path IN (
                        SELECT path FROM features
                        ORDER BY last_used DESC, path
                        LIMIT -1 OFFSET ?
                    )
                    """,
                    (MAX_CACHE_ENTRIES,),
                )
        except (OSError, sqlite3.Error):
            return

    @staticmethod
    def _encode(record: PhotoRecord) -> str:
        metadata = asdict(record.metadata)
        metadata_capture_time = metadata.get("captured_at")
        if isinstance(metadata_capture_time, datetime):
            metadata["captured_at"] = metadata_capture_time.isoformat()
        return json.dumps(
            {
                "width": record.width,
                "height": record.height,
                "captured_at": record.captured_at.isoformat(),
                "dhash": record.dhash,
                "average_hash": record.average_hash,
                "color_signature": record.color_signature,
                "sharpness": record.sharpness,
                "exposure": record.exposure,
                "portrait_detected": record.portrait_detected,
                "metadata": metadata,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _decode(path: Path, file_size: int, payload: str) -> PhotoRecord:
        data = json.loads(payload)
        metadata_data = dict(data["metadata"])
        if metadata_data.get("captured_at"):
            metadata_data["captured_at"] = datetime.fromisoformat(
                str(metadata_data["captured_at"])
            )
        metadata_data["details"] = tuple(
            tuple(item) for item in metadata_data.get("details", ())
        )
        return PhotoRecord(
            path=path,
            width=int(data["width"]),
            height=int(data["height"]),
            file_size=file_size,
            captured_at=datetime.fromisoformat(str(data["captured_at"])),
            dhash=int(data["dhash"]),
            average_hash=int(data["average_hash"]),
            color_signature=tuple(float(value) for value in data["color_signature"]),
            sharpness=float(data["sharpness"]),
            exposure=float(data["exposure"]),
            portrait_detected=data.get("portrait_detected"),
            metadata=CameraMetadata(**metadata_data),
        )
