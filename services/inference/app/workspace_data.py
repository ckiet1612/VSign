from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from app.collection import label_slug, save_collection_sample
from app.platform_db import AuditEvent, Workspace, utc_now
from app.validation import close_frames, decode_frames
from app.workspace_data_db import DataSample, DataSession, DatasetSnapshot, DatasetVersion, LabelVersion

logger = logging.getLogger("vsign.data")


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def fingerprint(payload) -> str:
    return hashlib.sha256(canonical(payload.model_dump(mode="json"))).hexdigest()


def file_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise HTTPException(409, "Dữ liệu thiếu hoặc không còn nguyên vẹn")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sync_file(path: Path):
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def sync_directory(path: Path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class WorkspaceData:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings

    @contextmanager
    def write(self, actor):
        with self.database.session() as session:
            # SQLite writer lock / PostgreSQL workspace row lock spans media commit.
            if self.database.engine.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            else:
                session.execute(select(Workspace).where(Workspace.id == actor.workspace.id).with_for_update())
            yield session
            session.commit()

    def get(self, session, table, actor, identity):
        row = session.scalar(select(table).where(table.workspace_id == actor.workspace.id, table.id == str(identity)))
        if row is None:
            raise HTTPException(404, "Không tìm thấy dữ liệu trong workspace")
        return row

    def existing(self, session, table, actor, identity, request_hash):
        row = session.get(table, str(identity))
        if row is None:
            return False
        if row.workspace_id != actor.workspace.id or row.request_hash != request_hash:
            raise HTTPException(409, "Mã yêu cầu đã được dùng cho nội dung khác")
        return True

    def audit(self, session, actor, event_type, resource_id, metadata=None):
        session.add(AuditEvent(id=str(uuid4()), workspace_id=actor.workspace.id,
            event_type=event_type, actor_type="user", actor_id=actor.user.id, outcome="success",
            resource_type="dataset" if event_type.startswith("data.") else "collection",
            resource_id=str(resource_id), metadata_json=metadata or {}))

    def directory(self, actor, *parts):
        root = self.settings.collection_dir.resolve()
        path = root / "workspaces" / actor.workspace.id
        for part in ("workspaces", actor.workspace.id, *parts):
            root = root / part
            if root.is_symlink():
                raise HTTPException(409, "Vùng lưu dữ liệu không hợp lệ")
        if not root.is_relative_to(path):
            raise HTTPException(409, "Vùng lưu dữ liệu không hợp lệ")
        return root

    def media(self, root, relative_path):
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise HTTPException(409, "Đường dẫn dữ liệu không hợp lệ")
        path = root
        for part in relative.parts:
            path = path / part
            if path.is_symlink():
                raise HTTPException(409, "Dữ liệu không còn nguyên vẹn")
        return path

    def samples(self, session, actor, dataset_id):
        return session.scalars(select(DataSample).where(DataSample.workspace_id == actor.workspace.id,
            DataSample.dataset_version_id == dataset_id).order_by(DataSample.id)).all()

    def counts(self, session, actor, dataset):
        labels = self.get(session, LabelVersion, actor, dataset.label_version_id)
        result = {entry["name"]: {"right": 0, "left": 0} for entry in labels.entries_json}
        groups = session.execute(select(DataSample.expected_label, DataSample.hand, func.count()).where(
            DataSample.workspace_id == actor.workspace.id, DataSample.dataset_version_id == dataset.id
        ).group_by(DataSample.expected_label, DataSample.hand)).all()
        for name, hand, count in groups:
            result[name][hand] = count
        return result

    def overview(self, actor):
        from app.workspace_settings import collection_policy
        scope = actor.workspace.id
        with self.database.session() as session:
            policy = collection_policy(session, self.settings)
            def rows(table):
                return session.scalars(select(table).where(table.workspace_id == scope)
                    .order_by(table.created_at.desc(), table.id)).all()
            session_counts = dict(session.execute(select(DataSample.collection_session_id, func.count()).where(
                DataSample.workspace_id == scope).group_by(DataSample.collection_session_id)).all())
            datasets = []
            for row in rows(DatasetVersion):
                counts = self.counts(session, actor, row)
                datasets.append(dict(id=row.id, name=row.name, label_version_id=row.label_version_id,
                    quota_per_label=row.quota_per_label, status=row.status, created_at=row.created_at,
                    counts=counts, sample_count=sum(sum(value.values()) for value in counts.values())))
            return dict(api_version="1", workspace_id=scope, collection_enabled=policy['enabled'], collection_policy=policy,
                default_labels=list(dict.fromkeys([*self.settings.collection_labels, "Không ký hiệu"])),
                permissions={"manage": actor.can("data:manage"), "collect": actor.can("data:use")},
                labels=[dict(id=row.id, name=row.name, parent_id=row.parent_id, entries=row.entries_json,
                    created_at=row.created_at) for row in rows(LabelVersion)], datasets=datasets,
                sessions=[dict(id=row.id, dataset_version_id=row.dataset_version_id, state=row.state,
                    created_by=row.created_by, created_at=row.created_at, updated_at=row.updated_at,
                    sample_count=session_counts.get(row.id, 0)) for row in rows(DataSession)],
                snapshots=[dict(id=row.id, dataset_version_id=row.dataset_version_id, label_version_id=row.label_version_id,
                    sample_count=row.sample_count, sha256=row.sha256, created_at=row.created_at) for row in rows(DatasetSnapshot)])

    def labels(self, actor, payload):
        entries = [entry.model_dump(mode="json") for entry in payload.entries]
        slugs = [label_slug(entry["name"]) for entry in entries]
        if len(set(slugs)) != len(slugs):
            raise HTTPException(422, "Tên ký hiệu trùng khi chuẩn hóa")
        with self.write(actor) as session:
            if self.existing(session, LabelVersion, actor, payload.request_id, fingerprint(payload)):
                return
            old = {}
            if payload.parent_id:
                parent = self.get(session, LabelVersion, actor, payload.parent_id)
                old = {entry["id"]: entry for entry in parent.entries_json}
                for entry in entries:
                    if entry["id"] in old and entry["kind"] != old[entry["id"]]["kind"]:
                        raise HTTPException(409, "Không đổi loại ký hiệu đã có; hãy tạo ký hiệu mới")
            known = {entry["id"] for version in session.scalars(select(LabelVersion).where(
                LabelVersion.workspace_id == actor.workspace.id)).all() for entry in version.entries_json}
            if any(entry["id"] in known and entry["id"] not in old for entry in entries):
                raise HTTPException(409, "Ký hiệu đã tồn tại; hãy tạo phiên bản dựa trên danh mục gốc")
            session.add(LabelVersion(id=str(payload.request_id), workspace_id=actor.workspace.id,
                name=payload.name.strip(), parent_id=str(payload.parent_id) if payload.parent_id else None,
                entries_json=entries, created_by=actor.user.id, request_hash=fingerprint(payload)))
            self.audit(session, actor, "data.labels_created", payload.request_id)

    def dataset(self, actor, payload):
        from app.workspace_settings import collection_policy
        with self.write(actor) as session:
            inherited = 'quota_per_label' not in payload.model_fields_set
            request_hash = hashlib.sha256(canonical({**payload.model_dump(mode='json'), '_default_quota': inherited})).hexdigest()
            previous = session.get(DatasetVersion, str(payload.request_id))
            # Pre-settings receipts did not distinguish omitted quota from explicit 100.
            if previous is not None and previous.request_hash == fingerprint(payload):
                request_hash = previous.request_hash
            if self.existing(session, DatasetVersion, actor, payload.request_id, request_hash):
                return
            self.get(session, LabelVersion, actor, payload.label_version_id)
            quota = collection_policy(session, self.settings)['default_quota_per_label'] if inherited else payload.quota_per_label
            session.add(DatasetVersion(id=str(payload.request_id), workspace_id=actor.workspace.id,
                name=payload.name.strip(), label_version_id=str(payload.label_version_id),
                quota_per_label=quota, request_hash=request_hash, created_by=actor.user.id))
            self.audit(session, actor, "data.dataset_created", payload.request_id)

    def quota(self, actor, identity, payload):
        with self.write(actor) as session:
            dataset = self.get(session, DatasetVersion, actor, identity)
            if dataset.status != "draft":
                raise HTTPException(409, "Phiên bản đã chốt không thể thay đổi")
            if any(sum(count.values()) > payload.quota_per_label for count in self.counts(session, actor, dataset).values()):
                raise HTTPException(409, "Hạn mức không thể thấp hơn số mẫu đã lưu")
            if dataset.quota_per_label != payload.quota_per_label:
                dataset.quota_per_label = payload.quota_per_label
                self.audit(session, actor, "data.quota_changed", identity, {"target": payload.quota_per_label})

    def start(self, actor, payload):
        from app.workspace_settings import check_collection_policy
        with self.write(actor) as session:
            request_hash = hashlib.sha256(canonical(payload.model_dump(mode='json', exclude={'consent'} if not payload.consent else set()))).hexdigest()
            if self.existing(session, DataSession, actor, payload.request_id, request_hash):
                row = self.get(session, DataSession, actor, payload.request_id)
                if row.created_by != actor.user.id:
                    raise HTTPException(403, "Phiên thu thuộc người dùng khác")
                return
            policy = check_collection_policy(session, self.settings, payload.consent)
            dataset = self.get(session, DatasetVersion, actor, payload.dataset_version_id)
            if dataset.status != "draft":
                raise HTTPException(409, "Phiên bản đã chốt không thể thu thêm")
            session.add(DataSession(id=str(payload.request_id), workspace_id=actor.workspace.id,
                dataset_version_id=dataset.id, created_by=actor.user.id, request_hash=request_hash,
                consented_at=utc_now() if payload.consent else None, policy_revision=policy['revision']))
            self.audit(session, actor, "collection.started", payload.request_id, {"dataset_version_id": dataset.id})

    def session_owner(self, actor, row):
        if row.created_by != actor.user.id and not actor.can("data:manage"):
            raise HTTPException(403, "Bạn không quản lý phiên thu này")

    def transition(self, actor, identity, payload):
        from app.workspace_settings import check_collection_policy
        with self.write(actor) as session:
            row = self.get(session, DataSession, actor, identity)
            self.session_owner(actor, row)
            if payload.state == 'running':
                check_collection_policy(session, self.settings, row.consented_at is not None)
            if row.state == payload.state:
                return
            if row.state in {"stopped", "completed"}:
                raise HTTPException(409, "Phiên đã kết thúc; hãy bắt đầu phiên mới")
            row.state, row.updated_at = payload.state, utc_now()
            event = {"running": "resumed", "paused": "paused", "stopped": "stopped", "completed": "completed"}[payload.state]
            self.audit(session, actor, "collection." + event, identity)

    def save(self, actor, identity, payload):
        from app.workspace_settings import check_collection_policy
        request_hash = fingerprint(payload)
        decoded = []
        try:
            with self.write(actor) as session:
                collection = self.get(session, DataSession, actor, identity)
                self.session_owner(actor, collection)
                dataset = self.get(session, DatasetVersion, actor, collection.dataset_version_id)
                root = self.directory(actor, "datasets", dataset.id)
                existing = session.get(DataSample, str(payload.sample_key))
                if existing is not None:
                    if existing.workspace_id != actor.workspace.id or existing.collection_session_id != collection.id or existing.request_hash != request_hash:
                        raise HTTPException(409, "Mã lượt thu đã được dùng cho mẫu khác")
                    self.verify_sample(root, existing)
                    counts = self.counts(session, actor, dataset)[existing.expected_label]
                    return dict(status="saved", sample_id=existing.id, expected_label=existing.expected_label,
                        hand=existing.hand, relative_video_path=existing.relative_path,
                        label_hand_count=counts[existing.hand], label_count=sum(counts.values()))
                check_collection_policy(session, self.settings, collection.consented_at is not None)
                if collection.state != "running" or dataset.status != "draft":
                    raise HTTPException(409, "Phiên thu không hoạt động hoặc dữ liệu đã chốt")
                labels = self.get(session, LabelVersion, actor, dataset.label_version_id)
                label_key = unicodedata.normalize("NFC", payload.expected_label).strip().casefold()
                label = next((entry for entry in labels.entries_json if entry["name"].casefold() == label_key), None)
                if label is None:
                    raise HTTPException(422, "Ký hiệu không thuộc phiên bản danh mục đang thu")
                counts = self.counts(session, actor, dataset)[label["name"]]
                if sum(counts.values()) >= dataset.quota_per_label:
                    raise HTTPException(409, "Ký hiệu đã đủ hạn mức mẫu")
                decoded = decode_frames(payload.frames, self.settings.max_frame_bytes)
                directory = f"{label_slug(label['name'])}/{payload.hand.value}"
                for filename in (f"{payload.sample_key}.mp4", f"{payload.sample_key}.json",
                    f".{payload.sample_key}.video.tmp", f".{payload.sample_key}.metadata.tmp"):
                    self.media(root, f"{directory}/{filename}")
                orphan_video = self.media(root, f"{directory}/{payload.sample_key}.mp4")
                orphan_metadata = orphan_video.with_suffix(".json")
                if orphan_metadata.is_file():
                    residue = json.loads(orphan_metadata.read_bytes())
                    if residue.get("request_fingerprint") != request_hash:
                        raise HTTPException(409, "Mã lượt thu đã được dùng cho mẫu khác")
                    # No DB sample owns these bytes; regenerate from the retried capture.
                    orphan_metadata.unlink()
                    orphan_video.unlink(missing_ok=True)
                _, relative, _ = save_collection_sample(root, frames=decoded, session_id=payload.session_id,
                    captured_at=payload.captured_at, duration_ms=payload.duration_ms,
                    expected_label=label["name"], hand=payload.hand, predicted_label=payload.predicted_label,
                    predicted_confidence=payload.predicted_confidence, distance=payload.distance, lighting=payload.lighting,
                    negative_action=payload.negative_action, model_version="dataset-collection",
                    sample_key=payload.sample_key, request_fingerprint=request_hash)
                video = self.media(root, relative)
                sync_file(video)
                sync_file(video.with_suffix(".json"))
                sync_directory(video.parent)
                sample = DataSample(id=str(payload.sample_key), workspace_id=actor.workspace.id,
                    dataset_version_id=dataset.id, collection_session_id=collection.id, label_id=label["id"],
                    expected_label=label["name"], hand=payload.hand.value, relative_path=relative,
                    video_sha256=file_hash(video), metadata_sha256=file_hash(video.with_suffix(".json")), request_hash=request_hash)
                session.add(sample)
                collection.updated_at = utc_now()
                self.audit(session, actor, "collection.sample_saved", collection.id,
                    {"sample_id": sample.id, "dataset_version_id": dataset.id})
                counts[payload.hand.value] += 1
                result = dict(status="saved", sample_id=sample.id, expected_label=sample.expected_label, hand=sample.hand,
                    relative_video_path=relative, label_hand_count=counts[sample.hand], label_count=sum(counts.values()))
            return result
        finally:
            close_frames(decoded)

    def verify_sample(self, root, sample):
        video = self.media(root, sample.relative_path)
        if file_hash(video) != sample.video_sha256 or file_hash(video.with_suffix(".json")) != sample.metadata_sha256:
            raise HTTPException(409, "Mẫu dữ liệu không còn nguyên vẹn")

    def seal(self, actor, identity, payload):
        with self.write(actor) as session:
            dataset = self.get(session, DatasetVersion, actor, identity)
            existing = session.get(DatasetSnapshot, str(payload.request_id))
            if existing is not None:
                if existing.workspace_id != actor.workspace.id or existing.dataset_version_id != dataset.id:
                    raise HTTPException(409, "Mã snapshot đã được sử dụng")
                self.read_manifest(actor, existing)
                return
            if dataset.status != "draft":
                raise HTTPException(409, "Phiên bản đã được chốt")
            active = session.scalar(select(DataSession.id).where(DataSession.workspace_id == actor.workspace.id,
                DataSession.dataset_version_id == dataset.id, DataSession.state.in_(["running", "paused"])).limit(1))
            samples = self.samples(session, actor, dataset.id)
            if active or not samples:
                raise HTTPException(409, "Cần có mẫu đã lưu và kết thúc mọi phiên thu trước khi chốt")
            labels = self.get(session, LabelVersion, actor, dataset.label_version_id)
            source = self.directory(actor, "datasets", dataset.id)
            target = self.directory(actor, "snapshots", str(payload.request_id))
            target.parent.mkdir(parents=True, exist_ok=True)
            stage = target.parent / f".{payload.request_id}-{uuid4()}.tmp"
            stage.mkdir()
            try:
                manifest = dict(schema_version="1", workspace_id=actor.workspace.id, snapshot_id=str(payload.request_id),
                    dataset_version_id=dataset.id, label_version_id=labels.id, labels=labels.entries_json,
                    quota_per_label=dataset.quota_per_label, samples=[])
                for sample in samples:
                    self.verify_sample(source, sample)
                    relative = f"samples/{sample.id}.mp4"
                    destination = stage / relative
                    destination.parent.mkdir(exist_ok=True)
                    video = self.media(source, sample.relative_path)
                    shutil.copyfile(video, destination)
                    shutil.copyfile(video.with_suffix(".json"), destination.with_suffix(".json"))
                    if file_hash(destination) != sample.video_sha256 or file_hash(destination.with_suffix(".json")) != sample.metadata_sha256:
                        raise HTTPException(409, "Mẫu thay đổi trong lúc chốt dữ liệu")
                    sync_file(destination)
                    sync_file(destination.with_suffix(".json"))
                    manifest["samples"].append(dict(id=sample.id, collection_session_id=sample.collection_session_id,
                        label_id=sample.label_id, expected_label=sample.expected_label, hand=sample.hand,
                        video=relative, video_sha256=sample.video_sha256, metadata_sha256=sample.metadata_sha256))
                encoded = canonical(manifest)
                (stage / "manifest.json").write_bytes(encoded)
                sync_file(stage / "manifest.json")
                sync_directory(stage / "samples")
                sync_directory(stage)
                digest = hashlib.sha256(encoded).hexdigest()
                # Residue from an uncommitted publication may only be reused byte-for-byte.
                if target.exists():
                    if file_hash(target / "manifest.json") != digest:
                        raise HTTPException(409, "Snapshot chưa hoàn tất cần được kiểm tra")
                    self.verify_manifest_files(target, manifest)
                else:
                    stage.rename(target)
                    sync_directory(target.parent)
                session.add(DatasetSnapshot(id=str(payload.request_id), workspace_id=actor.workspace.id,
                    dataset_version_id=dataset.id, label_version_id=labels.id, sample_count=len(samples),
                    sha256=digest, created_by=actor.user.id))
                dataset.status = "sealed"
                self.audit(session, actor, "data.snapshot_created", dataset.id, {"snapshot_id": str(payload.request_id), "sample_count": len(samples)})
            finally:
                shutil.rmtree(stage, ignore_errors=True)

    def verify_manifest_files(self, root, manifest):
        for sample in manifest["samples"]:
            video = self.media(root, sample["video"])
            if file_hash(video) != sample["video_sha256"] or file_hash(video.with_suffix(".json")) != sample["metadata_sha256"]:
                raise HTTPException(409, "Snapshot không còn nguyên vẹn; không được dùng để huấn luyện")

    def read_manifest(self, actor, snapshot):
        root = self.directory(actor, "snapshots", snapshot.id)
        path = root / "manifest.json"
        if file_hash(path) != snapshot.sha256:
            raise HTTPException(409, "Snapshot không còn nguyên vẹn")
        manifest = json.loads(path.read_bytes())
        if (manifest["workspace_id"] != actor.workspace.id or manifest["snapshot_id"] != snapshot.id or
            manifest["dataset_version_id"] != snapshot.dataset_version_id or
            manifest["label_version_id"] != snapshot.label_version_id or len(manifest["samples"]) != snapshot.sample_count):
            raise HTTPException(409, "Snapshot không khớp phiên bản dữ liệu")
        self.verify_manifest_files(root, manifest)
        return manifest

    def manifest(self, actor, identity):
        with self.database.session() as session:
            return self.read_manifest(actor, self.get(session, DatasetSnapshot, actor, identity))
