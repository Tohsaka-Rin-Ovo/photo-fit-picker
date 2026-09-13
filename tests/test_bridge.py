import json
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from PIL import Image

from photo_fit_picker.bridge import EngineState, create_server


def _wait_for_job(engine: EngineState, job_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        snapshot = engine.job_snapshot(job_id)
        if snapshot["state"] in {"completed", "failed", "cancelled"}:
            return snapshot
        time.sleep(0.02)
    raise AssertionError("analysis job did not finish")


def test_engine_analyzes_and_serves_thumbnail(tmp_path: Path) -> None:
    source = tmp_path / "photos"
    source.mkdir()
    for index, color in enumerate(((50, 120, 180), (52, 122, 182))):
        Image.new("RGB", (320, 240), color).save(source / f"photo-{index}.jpg")

    engine = EngineState(tmp_path / "state")
    job = engine.start_analysis(source, {"similarity_threshold": 0.7})
    snapshot = _wait_for_job(engine, job.id)

    assert snapshot["state"] == "completed"
    groups = snapshot["groups"]
    assert isinstance(groups, list)
    assert sum(group["count"] for group in groups) == 2
    photo_id = groups[0]["photos"][0]["id"]
    thumbnail = engine.thumbnail(photo_id)
    assert thumbnail.is_file()
    assert thumbnail.read_bytes().startswith(b"\xff\xd8")

    compact_thumbnail = engine.thumbnail(photo_id, maximum=160)
    with Image.open(compact_thumbnail) as preview:
        assert max(preview.size) == 160


def test_engine_persists_review_and_requires_trash_confirmation(tmp_path: Path) -> None:
    source = tmp_path / "photos"
    source.mkdir()
    image_path = source / "photo.jpg"
    Image.new("RGB", (160, 120), (80, 90, 100)).save(image_path)
    engine = EngineState(tmp_path / "state")
    snapshot = _wait_for_job(engine, engine.start_analysis(source, {}).id)
    photo_id = snapshot["groups"][0]["photos"][0]["id"]

    assert engine.update_review([{"id": photo_id, "status": "kept"}]) == {
        "changed": 1
    }
    assert engine.records[photo_id].status.value == "kept"

    try:
        engine.trash([photo_id], confirmed=False)
    except PermissionError as exc:
        assert "再次确认" in str(exc)
    else:
        raise AssertionError("trash must require explicit confirmation")
    assert image_path.is_file()


def test_engine_undo_restores_record_path_and_status(tmp_path: Path) -> None:
    source = tmp_path / "photos"
    destination = tmp_path / "selected"
    source.mkdir()
    image_path = source / "photo.jpg"
    Image.new("RGB", (160, 120), (80, 90, 100)).save(image_path)
    engine = EngineState(tmp_path / "state")
    snapshot = _wait_for_job(engine, engine.start_analysis(source, {}).id)
    photo_id = snapshot["groups"][0]["photos"][0]["id"]

    engine.update_review([{"id": photo_id, "status": "kept"}])
    assert engine.move([photo_id], destination)["moved_files"] == 1
    assert engine.records[photo_id].status.value == "moved"
    assert engine.records[photo_id].path.parent == destination.resolve()

    assert engine.undo(destination)["restored_files"] == 1
    assert engine.records[photo_id].status.value == "kept"
    assert engine.records[photo_id].path == image_path.resolve()
    assert image_path.is_file()


def test_http_engine_rejects_missing_token(tmp_path: Path) -> None:
    try:
        server = create_server(0, "test-token", tmp_path / "state")
    except PermissionError:
        pytest.skip("sandbox does not permit binding a loopback socket")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/api/health"
    try:
        with urlopen(url, timeout=2):
            raise AssertionError("request without token should fail")
    except HTTPError as exc:
        assert exc.code == 401

    request = Request(url, headers={"Authorization": "Bearer test-token"})
    with urlopen(request, timeout=2) as response:
        assert json.loads(response.read()) == {"status": "ok"}
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
