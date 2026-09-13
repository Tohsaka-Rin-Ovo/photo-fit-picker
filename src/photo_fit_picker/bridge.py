from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import threading
import uuid
from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from PIL import Image

from .analysis import analyze_paths, discover_images, group_similar_photos, load_display_image
from .feature_cache import FeatureCache
from .fileops import move_photo_to_trash, move_photos, undo_last_move
from .models import AnalysisOptions, PhotoGroup, PhotoRecord, ReviewStatus
from .session import ReviewSessionStore


MAX_REQUEST_BYTES = 2 * 1024 * 1024
ALLOWED_ORIGINS = {
    "http://localhost:1420",
    "http://127.0.0.1:1420",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
}


def _photo_id(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:24]


def _analysis_options(payload: object) -> AnalysisOptions:
    values = payload if isinstance(payload, dict) else {}
    defaults = AnalysisOptions()
    return AnalysisOptions(
        similarity_threshold=max(
            0.0,
            min(1.0, float(values.get("similarity_threshold", defaults.similarity_threshold))),
        ),
        time_window_seconds=max(
            1,
            min(3600, int(values.get("time_window_seconds", defaults.time_window_seconds))),
        ),
        color_weight=max(0.0, min(1.0, float(values.get("color_weight", defaults.color_weight)))),
        hash_method=(
            "average" if values.get("hash_method") == "average" else "difference"
        ),
        detect_exact_duplicates=bool(
            values.get("detect_exact_duplicates", defaults.detect_exact_duplicates)
        ),
        sharpness_weight=max(
            0.0, float(values.get("sharpness_weight", defaults.sharpness_weight))
        ),
        exposure_weight=max(
            0.0, float(values.get("exposure_weight", defaults.exposure_weight))
        ),
        resolution_weight=max(
            0.0, float(values.get("resolution_weight", defaults.resolution_weight))
        ),
        detect_portraits=bool(values.get("detect_portraits", defaults.detect_portraits)),
    )


def _metadata_payload(photo: PhotoRecord) -> dict[str, object]:
    metadata = asdict(photo.metadata)
    captured_at = metadata.get("captured_at")
    metadata["captured_at"] = captured_at.isoformat() if captured_at else None
    metadata["details"] = [list(item) for item in photo.metadata.details]
    metadata["camera_label"] = photo.metadata.camera_label
    metadata["shooting_summary"] = photo.metadata.shooting_summary
    return metadata


def _photo_payload(photo: PhotoRecord, recommended: bool) -> dict[str, object]:
    return {
        "id": _photo_id(photo.path),
        "path": str(photo.path.resolve()),
        "name": photo.display_name,
        "format": photo.format_label,
        "width": photo.width,
        "height": photo.height,
        "dimensions": photo.dimension_label,
        "file_size": photo.file_size,
        "file_size_label": photo.file_size_label,
        "captured_at": photo.captured_at.isoformat(),
        "quality_score": round(photo.quality_score, 4),
        "quality_summary": photo.quality_summary,
        "portrait_detected": photo.portrait_detected,
        "status": photo.status.value,
        "recommended": recommended,
        "metadata": _metadata_payload(photo),
    }


def _group_payload(group: PhotoGroup) -> dict[str, object]:
    recommended = group.recommended
    return {
        "id": group.id,
        "count": len(group.photos),
        "reviewed": group.reviewed,
        "kept_count": group.kept_count,
        "photos": [
            {
                **_photo_payload(photo, photo is recommended),
                "recommendation_reason": group.recommendation_reason(photo),
            }
            for photo in group.photos
        ],
    }


@dataclass
class AnalysisJob:
    id: str
    source: Path
    options: AnalysisOptions
    state: str = "queued"
    stage: str = "scan"
    current: int = 0
    total: int = 0
    detail: str = "正在读取照片文件夹"
    failures: list[tuple[Path, str]] = field(default_factory=list)
    groups: list[PhotoGroup] = field(default_factory=list)
    error: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def snapshot(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.id,
            "state": self.state,
            "stage": self.stage,
            "current": self.current,
            "total": self.total,
            "detail": self.detail,
            "source": str(self.source),
            "failure_count": len(self.failures),
        }
        if self.error:
            payload["error"] = self.error
        if self.state == "completed":
            payload["groups"] = [_group_payload(group) for group in self.groups]
            payload["failures"] = [
                {"path": str(path), "message": message}
                for path, message in self.failures
            ]
        return payload


class EngineState:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.feature_cache = FeatureCache(data_root / "analysis-cache.sqlite3")
        self.session_store = ReviewSessionStore(data_root / "review-sessions")
        self.thumbnail_root = data_root / "thumbnails"
        self.jobs: dict[str, AnalysisJob] = {}
        self.records: dict[str, PhotoRecord] = {}
        self.source: Optional[Path] = None
        self.lock = threading.RLock()

    def start_analysis(self, source: Path, options_payload: object) -> AnalysisJob:
        source = source.expanduser().resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"找不到照片文件夹：{source}")
        options = _analysis_options(options_payload)
        job = AnalysisJob(uuid.uuid4().hex, source, options)
        with self.lock:
            self.jobs[job.id] = job
        threading.Thread(
            target=self._run_analysis,
            args=(job,),
            name=f"analysis-{job.id[:8]}",
            daemon=True,
        ).start()
        return job

    def _run_analysis(self, job: AnalysisJob) -> None:
        try:
            job.state = "running"
            paths = discover_images(job.source)
            job.total = len(paths)
            job.detail = f"找到 {len(paths)} 张照片"
            if not paths:
                raise ValueError("该文件夹中没有找到支持的照片")

            job.stage = "features"

            def feature_progress(current: int, total: int, detail: str) -> None:
                job.current = current
                job.total = total
                job.detail = detail

            records, failures = analyze_paths(
                paths,
                progress=feature_progress,
                cancelled=job.cancel_event.is_set,
                cache=self.feature_cache,
                detect_portraits=job.options.detect_portraits,
            )
            if job.cancel_event.is_set():
                job.state = "cancelled"
                job.detail = "已取消分析"
                return

            job.stage = "grouping"
            job.current = 0
            job.total = max(1, len(records))

            def group_progress(current: int, total: int) -> None:
                job.current = current
                job.total = total
                job.detail = "正在整理相似照片"

            groups = group_similar_photos(
                records,
                job.options,
                progress=group_progress,
                cancelled=job.cancel_event.is_set,
            )
            if job.cancel_event.is_set():
                job.state = "cancelled"
                job.detail = "已取消分析"
                return

            self.session_store.restore(job.source, records)
            with self.lock:
                self.source = job.source
                self.records = {_photo_id(record.path): record for record in records}
                job.groups = groups
                job.failures = failures
                job.current = job.total
                job.stage = "complete"
                job.state = "completed"
                job.detail = f"完成分析，共 {len(records)} 张照片"
        except Exception as exc:
            job.state = "failed"
            job.error = str(exc)
            job.detail = "分析失败"

    def job_snapshot(self, job_id: str) -> dict[str, object]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise KeyError("找不到分析任务")
            return job.snapshot()

    def cancel_job(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise KeyError("找不到分析任务")
            job.cancel_event.set()
            if job.state == "queued":
                job.state = "cancelled"

    def update_review(self, updates: object) -> dict[str, int]:
        if not isinstance(updates, list):
            raise ValueError("审核状态必须是列表")
        changed = 0
        with self.lock:
            for update in updates:
                if not isinstance(update, dict):
                    continue
                photo = self.records.get(str(update.get("id", "")))
                try:
                    status = ReviewStatus(str(update.get("status", "")))
                except ValueError:
                    continue
                if photo is None or status not in {
                    ReviewStatus.PENDING,
                    ReviewStatus.KEPT,
                    ReviewStatus.REJECTED,
                }:
                    continue
                photo.status = status
                photo.selected = False
                changed += 1
            if self.source:
                self.session_store.save(self.source, self.records.values())
        return {"changed": changed}

    def move(self, photo_ids: object, destination: Path) -> dict[str, object]:
        photos = self._selected_records(photo_ids)
        if not photos:
            raise ValueError("没有选择照片")
        moved = move_photos(photos, destination.expanduser().resolve())
        return {
            "moved_files": len(moved),
            "entries": [asdict(entry) for entry in moved],
        }

    def trash(self, photo_ids: object, confirmed: bool) -> dict[str, object]:
        if not confirmed:
            raise PermissionError("移到回收站必须由用户再次确认")
        photos = self._selected_records(photo_ids)
        if not photos:
            raise ValueError("没有选择照片")
        trashed: list[str] = []
        for photo in photos:
            trashed.append(str(move_photo_to_trash(photo)))
        return {"trashed_files": len(trashed), "paths": trashed}

    def undo(self, destination: Path) -> dict[str, object]:
        restored, errors = undo_last_move(destination.expanduser().resolve())
        return {
            "restored_files": len(restored),
            "errors": errors,
        }

    def _selected_records(self, photo_ids: object) -> list[PhotoRecord]:
        if not isinstance(photo_ids, list):
            raise ValueError("照片 ID 必须是列表")
        with self.lock:
            return [
                self.records[photo_id]
                for photo_id in dict.fromkeys(str(item) for item in photo_ids)
                if photo_id in self.records
                and self.records[photo_id].status
                not in {ReviewStatus.MOVED, ReviewStatus.TRASHED}
            ]

    def thumbnail(self, photo_id: str, maximum: int = 720) -> Path:
        maximum = max(160, min(1600, maximum))
        with self.lock:
            photo = self.records.get(photo_id)
        if photo is None:
            raise KeyError("找不到照片")
        stat = photo.path.stat()
        cache_key = hashlib.sha256(
            f"{photo.path.resolve()}\0{stat.st_size}\0{stat.st_mtime_ns}\0{maximum}".encode(
                "utf-8"
            )
        ).hexdigest()[:32]
        destination = self.thumbnail_root / f"{cache_key}.jpg"
        if destination.is_file():
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(f".{threading.get_ident()}.tmp")
        with load_display_image(photo.path) as source:
            image = source.convert("RGB")
            image.thumbnail((maximum, maximum), Image.Resampling.LANCZOS)
            image.save(temporary, "JPEG", quality=86, optimize=True)
        temporary.replace(destination)
        return destination


class EngineRequestHandler(BaseHTTPRequestHandler):
    server_version = "PhotoFitPickerEngine/0.8"

    @property
    def engine(self) -> EngineState:
        return self.server.engine  # type: ignore[attr-defined,no-any-return]

    @property
    def token(self) -> str:
        return self.server.token  # type: ignore[attr-defined,no-any-return]

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _origin(self) -> Optional[str]:
        origin = self.headers.get("Origin")
        return origin if origin in ALLOWED_ORIGINS else None

    def _cors_headers(self) -> None:
        origin = self._origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _authorized(self) -> bool:
        return secrets.compare_digest(
            self.headers.get("Authorization", ""),
            f"Bearer {self.token}",
        )

    def _json_body(self) -> dict[str, object]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("无效的请求长度") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("无效的请求内容")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("请求内容必须是对象")
        return payload

    def _send_json(self, status: int, payload: object) -> None:
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": message})

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send_error(HTTPStatus.UNAUTHORIZED, "未授权")
            return
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                self._send_json(HTTPStatus.OK, {"status": "ok"})
                return
            if parsed.path.startswith("/api/jobs/"):
                job_id = parsed.path.removeprefix("/api/jobs/")
                self._send_json(HTTPStatus.OK, self.engine.job_snapshot(job_id))
                return
            if parsed.path.startswith("/api/thumbnails/"):
                photo_id = parsed.path.removeprefix("/api/thumbnails/")
                thumbnail = self.engine.thumbnail(photo_id)
                content = thumbnail.read_bytes()
                self.send_response(HTTPStatus.OK)
                self._cors_headers()
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "private, max-age=31536000, immutable")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            self._send_error(HTTPStatus.NOT_FOUND, "接口不存在")
        except KeyError as exc:
            self._send_error(HTTPStatus.NOT_FOUND, str(exc))
        except (OSError, ValueError) as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send_error(HTTPStatus.UNAUTHORIZED, "未授权")
            return
        try:
            payload = self._json_body()
            if self.path == "/api/analyze":
                job = self.engine.start_analysis(
                    Path(str(payload.get("source", ""))),
                    payload.get("options"),
                )
                self._send_json(HTTPStatus.ACCEPTED, {"job_id": job.id})
                return
            if self.path == "/api/cancel":
                self.engine.cancel_job(str(payload.get("job_id", "")))
                self._send_json(HTTPStatus.OK, {"cancelled": True})
                return
            if self.path == "/api/review":
                self._send_json(
                    HTTPStatus.OK,
                    self.engine.update_review(payload.get("updates")),
                )
                return
            if self.path == "/api/move":
                result = self.engine.move(
                    payload.get("photo_ids"),
                    Path(str(payload.get("destination", ""))),
                )
                self._send_json(HTTPStatus.OK, result)
                return
            if self.path == "/api/trash":
                result = self.engine.trash(
                    payload.get("photo_ids"),
                    payload.get("confirmed") is True,
                )
                self._send_json(HTTPStatus.OK, result)
                return
            if self.path == "/api/undo":
                result = self.engine.undo(Path(str(payload.get("destination", ""))))
                self._send_json(HTTPStatus.OK, result)
                return
            self._send_error(HTTPStatus.NOT_FOUND, "接口不存在")
        except PermissionError as exc:
            self._send_error(HTTPStatus.FORBIDDEN, str(exc))
        except KeyError as exc:
            self._send_error(HTTPStatus.NOT_FOUND, str(exc))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))


class EngineServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        token: str,
        data_root: Path,
    ) -> None:
        self.token = token
        self.engine = EngineState(data_root)
        super().__init__(address, EngineRequestHandler)


def create_server(port: int, token: str, data_root: Path) -> EngineServer:
    if not token:
        raise ValueError("必须提供引擎访问令牌")
    return EngineServer(("127.0.0.1", port), token, data_root.expanduser().resolve())


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="拾影无界面图片处理引擎")
    parser.add_argument("serve", nargs="?")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", default="")
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args(argv)
    token = args.token or secrets.token_urlsafe(32)
    server = create_server(args.port, token, args.data_root)
    print(
        json.dumps(
            {
                "type": "ready",
                "host": "127.0.0.1",
                "port": server.server_address[1],
                "token": token,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
