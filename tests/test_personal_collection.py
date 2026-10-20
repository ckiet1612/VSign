from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.test_inference_api import image_data_url


def sample_payload(**overrides: object) -> dict:
    return {
        "session_id": "123e4567-e89b-12d3-a456-426614174000",
        "sample_key": "123e4567-e89b-12d3-a456-426614174001",
        "batch": "personal-100",
        "captured_at": 1788980000000,
        "duration_ms": 2100,
        "expected_label": "Cho",
        "hand": "right",
        "frames": [image_data_url()] * 28,
        **overrides,
    }


def test_new_batch_is_separate_and_resumes_saved_progress(tmp_path: Path) -> None:
    old = tmp_path / "cho" / "right"
    old.mkdir(parents=True)
    (old / "old.mp4").write_bytes(b"preserve-old-data")
    settings = Settings(collection_enabled=True, collection_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        initial = client.get("/collection/summary?batch=personal-100").json()
        assert initial["counts"]["Cho"] == {"right": 0, "left": 0}
        assert initial["target_per_label"] == 100
        saved = client.post("/collection/samples", json=sample_payload())
        assert saved.status_code == 200, saved.text
        assert saved.json()["label_count"] == 1
        assert saved.json()["relative_video_path"].startswith("batches/personal-100/")
        assert client.get("/collection/summary").json()["counts"]["Cho"]["right"] == 1
    with TestClient(create_app(settings)) as client:
        assert client.get("/collection/summary?batch=personal-100").json()["counts"]["Cho"]["right"] == 1
    assert (old / "old.mp4").read_bytes() == b"preserve-old-data"


def test_same_capture_is_saved_once_and_different_payload_cannot_reuse_key(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(collection_enabled=True, collection_dir=tmp_path))) as client:
        payload = sample_payload()
        first = client.post("/collection/samples", json=payload)
        assert first.status_code == 200, first.text
        repeat = client.post("/collection/samples", json=payload)
        assert repeat.status_code == 200
        assert repeat.json() == first.json()
        changed = client.post("/collection/samples", json={**payload, "duration_ms": 2200})
        assert changed.status_code == 409
    assert len(list(tmp_path.rglob("*.mp4"))) == 1


def test_quota_is_total_not_per_hand_and_retries_at_quota_work(tmp_path: Path) -> None:
    batch = tmp_path / "batches" / "personal-100" / "cho"
    for hand, count in [("right", 80), ("left", 19)]:
        directory = batch / hand
        directory.mkdir(parents=True)
        for index in range(count):
            (directory / f"old-{index}.mp4").write_bytes(b"existing")
            (directory / f"old-{index}.json").write_text("{}", encoding="utf-8")
    with TestClient(create_app(Settings(collection_enabled=True, collection_dir=tmp_path))) as client:
        payload = sample_payload()
        saved = client.post("/collection/samples", json=payload)
        assert saved.status_code == 200, saved.text
        assert saved.json()["label_count"] == 100
        assert client.post("/collection/samples", json=payload).status_code == 200
        extra = client.post("/collection/samples", json=sample_payload(
            sample_key="123e4567-e89b-12d3-a456-426614174002", hand="left",
        ))
        assert extra.status_code == 409
    assert len(list(batch.rglob("*.mp4"))) == 100


def test_batch_paths_and_missing_capture_key_are_rejected(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(collection_enabled=True, collection_dir=tmp_path))) as client:
        assert client.get("/collection/summary?batch=../old").status_code == 422
        assert client.post("/collection/samples", json=sample_payload(batch="../old")).status_code == 422
        assert client.post("/collection/samples", json=sample_payload(sample_key=None)).status_code == 422


def test_concurrent_last_two_captures_cannot_exceed_quota(tmp_path: Path) -> None:
    directory = tmp_path / "batches" / "personal-100" / "cho" / "right"
    directory.mkdir(parents=True)
    for index in range(99):
        (directory / f"old-{index}.mp4").write_bytes(b"existing")
        (directory / f"old-{index}.json").write_text("{}", encoding="utf-8")
    with TestClient(create_app(Settings(collection_enabled=True, collection_dir=tmp_path))) as client:
        def submit(index: int) -> int:
            return client.post("/collection/samples", json=sample_payload(
                sample_key=f"123e4567-e89b-12d3-a456-42661417400{index}",
            )).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(submit, [1, 2])) == [200, 409]
    assert len(list(directory.glob("*.mp4"))) == 100


def test_encoding_failure_leaves_no_counted_or_partial_sample(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.collection as collection

    def fail_encoding(path: Path, *args: object) -> None:
        path.write_bytes(b"partial")
        raise RuntimeError("encoding failed")

    monkeypatch.setattr(collection, "_encode_video", fail_encoding)
    with TestClient(create_app(Settings(collection_enabled=True, collection_dir=tmp_path))) as client:
        assert client.post("/collection/samples", json=sample_payload()).status_code == 500
        assert client.get("/collection/summary?batch=personal-100").json()["counts"]["Cho"] == {"right": 0, "left": 0}
    assert not list(tmp_path.rglob("*.mp4"))
    assert not list(tmp_path.rglob("*.tmp"))


def test_uncommitted_video_is_not_counted_and_same_capture_can_be_recovered(tmp_path: Path) -> None:
    directory = tmp_path / "batches" / "personal-100" / "cho" / "right"
    directory.mkdir(parents=True)
    key = sample_payload()["sample_key"]
    (directory / f"{key}.mp4").write_bytes(b"video-committed-before-metadata")
    with TestClient(create_app(Settings(collection_enabled=True, collection_dir=tmp_path))) as client:
        initial = client.get("/collection/summary?batch=personal-100").json()
        assert initial["counts"]["Cho"]["right"] == 0
        saved = client.post("/collection/samples", json=sample_payload())
        assert saved.status_code == 200, saved.text
        assert saved.json()["label_count"] == 1
    assert len(list(directory.glob("*.mp4"))) == 1
    assert (directory / f"{key}.json").is_file()
