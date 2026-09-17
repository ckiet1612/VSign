from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
import time
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Mapping, Sequence, Tuple


JsonPayload = Mapping[str, Any]
JsonFetcher = Callable[[str], JsonPayload]
DatasetDownloader = Callable[[str, str, Path], Path]
SALES30_DATASET_REF = "nguyenanfms/vsl-vietnamese-sign-language-v2"
SALES30_VERSION = 8
SALES30_LICENSE = "Attribution 4.0 International (CC BY 4.0)"
SALES30_CANONICAL_PREFIX = "processed/processed/frame_splited/"


def normalize_label(value: str) -> str:
    return unicodedata.normalize("NFC", value.strip())


@dataclass(frozen=True)
class Sales30SourceConfig:
    dataset_ref: str
    version: int
    license_name: str
    canonical_prefix: str
    minimum_total_clips: int


@dataclass(frozen=True)
class KaggleFile:
    name: str
    total_bytes: int


@dataclass(frozen=True)
class SourceInventory:
    dataset_ref: str
    version: int
    license_name: str
    files: Tuple[KaggleFile, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_ref": self.dataset_ref,
            "version": self.version,
            "license": self.license_name,
            "files": [
                {"name": item.name, "total_bytes": item.total_bytes}
                for item in self.files
            ],
        }


@dataclass(frozen=True)
class SourceAudit:
    dataset_ref: str
    version: int
    license_name: str
    coverage: Dict[str, Dict[str, int]]
    selected_files: Tuple[KaggleFile, ...]
    blockers: Tuple[str, ...]
    warnings: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_ref": self.dataset_ref,
            "version": self.version,
            "license": self.license_name,
            "coverage": self.coverage,
            "selected_files": [
                {"name": item.name, "total_bytes": item.total_bytes}
                for item in self.selected_files
            ],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "ready_for_baseline_training": not self.blockers,
            "split_strength": "development-only",
        }


@dataclass(frozen=True)
class DownloadResult:
    downloaded: int
    reused: int
    media_root: Path
    index_path: Path


@dataclass(frozen=True)
class ManifestRow:
    path: str
    label_id: int
    label: str
    split: str
    source_id: str
    source_revision: str
    source_label: str
    source_record_id: str
    license_name: str
    sha256: str
    signer_id: str
    group_id: str
    view: str
    take: str
    source_split: str
    remote_path: str
    split_strength: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "label_id": self.label_id,
            "label": self.label,
            "split": self.split,
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "source_label": self.source_label,
            "source_record_id": self.source_record_id,
            "license": self.license_name,
            "sha256": self.sha256,
            "signer_id": self.signer_id,
            "group_id": self.group_id,
            "view": self.view,
            "take": self.take,
            "source_split": self.source_split,
            "remote_path": self.remote_path,
            "split_strength": self.split_strength,
        }


@dataclass(frozen=True)
class ReadinessReport:
    counts: Dict[str, Dict[str, int]]
    blockers: Tuple[str, ...]
    warnings: Tuple[str, ...]
    split_strength: str = "development-only"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "counts": self.counts,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "split_strength": self.split_strength,
            "ready_for_baseline_training": not self.blockers,
            "production_ready": False,
        }


@dataclass(frozen=True)
class ManifestAudit:
    counts: Dict[str, Dict[str, int]]
    errors: Tuple[str, ...]
    warnings: Tuple[str, ...]
    split_strength: str = "development-only"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "counts": self.counts,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "split_strength": self.split_strength,
            "valid": not self.errors,
            "production_ready": False,
        }


def validate_sales30_source_identity(
    dataset_ref: str, version: int, license_name: str
) -> None:
    if dataset_ref != SALES30_DATASET_REF:
        raise ValueError(
            f"dataset_ref phải là nguồn VSL-472 đã duyệt: {SALES30_DATASET_REF}"
        )
    if version != SALES30_VERSION:
        raise ValueError(f"source version phải là {SALES30_VERSION}")
    if license_name != SALES30_LICENSE:
        raise ValueError(f"source license phải là {SALES30_LICENSE}")


def load_source_config(path: Path) -> Sales30SourceConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Source config phải là JSON object")
    dataset_ref = str(payload.get("dataset_ref") or "").strip()
    version = payload.get("version")
    license_name = str(payload.get("license") or "").strip()
    canonical_prefix = str(payload.get("canonical_prefix") or "").strip()
    minimum_total_clips = payload.get("minimum_total_clips")
    if dataset_ref.count("/") != 1:
        raise ValueError("dataset_ref phải có dạng owner/dataset")
    if not isinstance(version, int) or version <= 0:
        raise ValueError("version phải là số nguyên dương")
    if not license_name:
        raise ValueError("license không được để trống")
    prefix_path = PurePosixPath(canonical_prefix)
    if (
        not canonical_prefix.endswith("/")
        or prefix_path.is_absolute()
        or ".." in prefix_path.parts
    ):
        raise ValueError("canonical_prefix phải là đường dẫn tương đối an toàn")
    if not isinstance(minimum_total_clips, int) or minimum_total_clips <= 0:
        raise ValueError("minimum_total_clips phải là số nguyên dương")
    validate_sales30_source_identity(dataset_ref, version, license_name)
    if canonical_prefix != SALES30_CANONICAL_PREFIX:
        raise ValueError(
            f"canonical_prefix phải là {SALES30_CANONICAL_PREFIX}"
        )
    return Sales30SourceConfig(
        dataset_ref=dataset_ref,
        version=version,
        license_name=license_name,
        canonical_prefix=canonical_prefix,
        minimum_total_clips=minimum_total_clips,
    )


def fetch_json_url(url: str) -> JsonPayload:
    request = urllib.request.Request(url, headers={"User-Agent": "VSign-data-audit/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError(f"Kaggle API không trả JSON object: {url}")
    return payload


def list_kaggle_files(
    config: Sales30SourceConfig,
    *,
    fetch_json: JsonFetcher = fetch_json_url,
) -> SourceInventory:
    encoded_ref = urllib.parse.quote(config.dataset_ref, safe="/")
    metadata_url = (
        f"https://www.kaggle.com/api/v1/datasets/view/{encoded_ref}"
        "?includeMetadata=true"
    )
    metadata = fetch_json(metadata_url)
    version = int(metadata.get("currentVersionNumber") or 0)
    license_name = str(metadata.get("licenseName") or "")

    files = []
    page_token = ""
    seen_tokens = set()
    saw_canonical_prefix = False
    while True:
        parameters = {"pageSize": "200"}
        if page_token:
            parameters["pageToken"] = page_token
        query = urllib.parse.urlencode(parameters)
        page = fetch_json(
            f"https://www.kaggle.com/api/v1/datasets/list/{encoded_ref}?{query}"
        )
        raw_files = page.get("datasetFiles") or []
        if not isinstance(raw_files, list):
            raise ValueError("Kaggle datasetFiles không phải danh sách")
        passed_canonical_prefix = False
        for raw in raw_files:
            if not isinstance(raw, dict):
                continue
            name = normalize_label(str(raw.get("name") or ""))
            if not name.startswith(config.canonical_prefix):
                if saw_canonical_prefix and name > config.canonical_prefix:
                    passed_canonical_prefix = True
                continue
            saw_canonical_prefix = True
            if not name.endswith(".mp4"):
                continue
            relative = name[len(config.canonical_prefix) :]
            parts = PurePosixPath(relative).parts
            if len(parts) < 3 or parts[0] not in {"train", "test"}:
                continue
            files.append(KaggleFile(name=name, total_bytes=int(raw.get("totalBytes") or 0)))
        if passed_canonical_prefix:
            break
        next_token = str(page.get("nextPageToken") or "")
        if not next_token:
            break
        if next_token in seen_tokens:
            raise RuntimeError("Kaggle pagination lặp token")
        seen_tokens.add(next_token)
        page_token = next_token

    return SourceInventory(
        dataset_ref=str(metadata.get("ref") or config.dataset_ref),
        version=version,
        license_name=license_name,
        files=tuple(sorted(files, key=lambda item: item.name)),
    )


def _source_split_and_label(
    config: Sales30SourceConfig, item: KaggleFile
) -> tuple[str, str] | None:
    if not item.name.startswith(config.canonical_prefix):
        return None
    relative = item.name[len(config.canonical_prefix) :]
    parts = PurePosixPath(relative).parts
    if len(parts) < 3 or parts[0] not in {"train", "test"}:
        return None
    return parts[0], normalize_label(parts[1])


def audit_source(
    config: Sales30SourceConfig,
    labels: Sequence[str],
    inventory: SourceInventory,
) -> SourceAudit:
    normalized_labels = tuple(normalize_label(label) for label in labels)
    if len(normalized_labels) != len(set(normalized_labels)):
        raise ValueError("Label map trùng sau Unicode NFC")
    coverage = {
        label: {"train": 0, "test": 0} for label in normalized_labels
    }
    target_set = set(normalized_labels)
    selected = []
    for item in inventory.files:
        parsed = _source_split_and_label(config, item)
        if parsed is None:
            continue
        split, label = parsed
        if label not in target_set:
            continue
        coverage[label][split] += 1
        selected.append(item)

    blockers = []
    if inventory.dataset_ref != config.dataset_ref:
        blockers.append(
            f"Source dataset drift: expected {config.dataset_ref}, got {inventory.dataset_ref}"
        )
    if inventory.version != config.version:
        blockers.append(
            f"Source version drift: expected {config.version}, got {inventory.version}"
        )
    if inventory.license_name != config.license_name:
        blockers.append("Source license drift")
    for label in normalized_labels:
        total = sum(coverage[label].values())
        if total == 0:
            blockers.append(f"Thiếu label nguồn: {label}")
            continue
        if total < config.minimum_total_clips:
            blockers.append(
                f"Label {label} chỉ có {total} clip, cần tối thiểu {config.minimum_total_clips}"
            )
            continue
        for split in ("train", "test"):
            if coverage[label][split] == 0:
                blockers.append(f"Label {label} thiếu source split {split}")

    return SourceAudit(
        dataset_ref=inventory.dataset_ref,
        version=inventory.version,
        license_name=inventory.license_name,
        coverage=coverage,
        selected_files=tuple(sorted(selected, key=lambda item: item.name)),
        blockers=tuple(blockers),
        warnings=(
            "Nguồn gộp online clip không có signer ID đầy đủ; metrics chỉ development-only",
        ),
    )


MANIFEST_FIELDS = (
    "path",
    "label_id",
    "label",
    "split",
    "source_id",
    "source_revision",
    "source_label",
    "source_record_id",
    "license",
    "sha256",
    "signer_id",
    "group_id",
    "view",
    "take",
    "source_split",
    "remote_path",
    "split_strength",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _safe_relative_path(value: str, *, field: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"{field} không an toàn: {value}")
    return path


def _parse_remote_path(remote_path: str) -> tuple[str, str, str]:
    path = _safe_relative_path(remote_path, field="Remote path")
    prefix = PurePosixPath(SALES30_CANONICAL_PREFIX).parts
    if path.parts[: len(prefix)] != prefix:
        raise ValueError(f"Remote path không an toàn hoặc ngoài canonical tree: {remote_path}")
    relative = path.parts[len(prefix) :]
    if len(relative) != 3 or relative[0] not in {"train", "test"}:
        raise ValueError(f"Remote path không an toàn hoặc sai schema: {remote_path}")
    source_split, label, filename = relative
    if not label or not filename.lower().endswith(".mp4"):
        raise ValueError(f"Remote path không an toàn hoặc không phải MP4: {remote_path}")
    return source_split, normalize_label(label), filename


def _load_download_index(
    path: Path,
    *,
    dataset_ref: str | None = None,
    version: int | None = None,
    license_name: str | None = None,
) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        raise ValueError(f"Download index không hợp lệ: {path}")
    identity_errors = []
    if dataset_ref is not None and payload.get("dataset_ref") != dataset_ref:
        identity_errors.append("dataset_ref")
    if version is not None and payload.get("version") != version:
        identity_errors.append("version")
    if license_name is not None and payload.get("license") != license_name:
        identity_errors.append("license")
    if identity_errors:
        raise ValueError(
            "Download index source drift: " + ", ".join(identity_errors)
        )
    entries: dict[str, dict[str, Any]] = {}
    for raw in payload["files"]:
        if not isinstance(raw, dict) or not raw.get("remote_path"):
            raise ValueError(f"Download index có entry không hợp lệ: {path}")
        remote_path = str(raw["remote_path"])
        if remote_path in entries:
            raise ValueError(f"Download index trùng remote path: {remote_path}")
        entries[remote_path] = dict(raw)
    return entries


def _write_download_index(
    path: Path,
    audit: SourceAudit,
    completed: Mapping[str, Mapping[str, Any]],
) -> None:
    _write_json_atomic(
        path,
        {
            "dataset_ref": audit.dataset_ref,
            "version": audit.version,
            "license": audit.license_name,
            "files": [dict(completed[key]) for key in sorted(completed)],
        },
    )


def _default_kaggle_downloader(
    dataset_handle: str, remote_path: str, _output_dir: Path
) -> Path:
    try:
        import kagglehub
    except ImportError as error:  # pragma: no cover - actionable runtime message
        raise RuntimeError(
            "Thiếu kagglehub. Chạy: .venv/bin/pip install -r ml/requirements.txt"
        ) from error
    for attempt in range(3):
        try:
            return Path(
                kagglehub.dataset_download(
                    dataset_handle,
                    path=remote_path,
                )
            )
        except Exception as error:
            response = getattr(error, "response", None)
            status_code = getattr(response, "status_code", None)
            retryable = status_code in {404, 429} or (
                isinstance(status_code, int) and status_code >= 500
            )
            if not retryable or attempt == 2:
                raise RuntimeError(
                    f"KaggleHub không tải được {remote_path}: {error}"
                ) from error
            time.sleep(0.5 * (2**attempt))
    raise AssertionError("unreachable")


def _find_downloaded_file(
    returned_path: Path, staging_root: Path, remote_path: str
) -> Path:
    _, _, filename = _parse_remote_path(remote_path)
    candidates = (
        returned_path / filename,
        returned_path / remote_path,
        staging_root / remote_path,
        staging_root / filename,
    )
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    roots = [path for path in (returned_path, staging_root) if path.is_dir()]
    matches = {
        match.resolve()
        for root in roots
        for match in root.rglob(filename)
        if match.is_file() and not match.is_symlink()
    }
    if len(matches) != 1:
        raise FileNotFoundError(
            f"Không tìm thấy duy nhất file {remote_path} sau khi KaggleHub tải"
        )
    return next(iter(matches))


def download_inventory(
    audit: SourceAudit,
    output_root: Path,
    *,
    downloader: DatasetDownloader = _default_kaggle_downloader,
) -> DownloadResult:
    validate_sales30_source_identity(
        audit.dataset_ref, audit.version, audit.license_name
    )
    if audit.blockers:
        raise ValueError("Source audit còn blocker; từ chối tải dữ liệu train")
    output_root = output_root.resolve()
    media_root = output_root / "media"
    index_path = output_root / "download_index.json"
    staging_parent = output_root / ".download-staging"
    media_root.mkdir(parents=True, exist_ok=True)
    staging_parent.mkdir(parents=True, exist_ok=True)

    existing_index = _load_download_index(
        index_path,
        dataset_ref=audit.dataset_ref,
        version=audit.version,
        license_name=audit.license_name,
    )
    grouped: dict[str, list[tuple[KaggleFile, str, str, str]]] = {}
    for item in sorted(audit.selected_files, key=lambda value: value.name):
        source_split, label, filename = _parse_remote_path(item.name)
        remote_dir = PurePosixPath(item.name).parent.as_posix()
        grouped.setdefault(remote_dir, []).append(
            (item, source_split, label, filename)
        )

    downloaded = 0
    reused = 0
    completed: dict[str, dict[str, Any]] = {}
    pending_groups: dict[str, list[tuple[KaggleFile, str, str, str]]] = {}
    for remote_dir, items in grouped.items():
        pending = []
        for item, source_split, label, filename in items:
            local_relative = PurePosixPath(source_split, label, filename).as_posix()
            destination = media_root / Path(local_relative)
            indexed = existing_index.get(item.name)
            if not destination.exists():
                pending.append((item, source_split, label, filename))
                continue
            if destination.is_symlink() or not destination.is_file():
                raise ValueError(f"Media path không an toàn: {destination}")
            if indexed is None:
                raise ValueError(
                    f"File đã tồn tại nhưng không có checksum trong index: {destination}"
                )
            actual_digest = sha256_file(destination)
            if (
                indexed.get("sha256") != actual_digest
                or int(indexed.get("total_bytes") or -1) != item.total_bytes
                or destination.stat().st_size != item.total_bytes
                or indexed.get("local_path") != local_relative
            ):
                raise ValueError(f"File hiện có sai checksum hoặc metadata: {destination}")
            completed[item.name] = {
                "remote_path": item.name,
                "local_path": local_relative,
                "total_bytes": item.total_bytes,
                "sha256": actual_digest,
            }
            reused += 1
        if pending:
            pending_groups[remote_dir] = pending

    dataset_handle = f"{audit.dataset_ref}/versions/{audit.version}"
    for remote_dir, items in pending_groups.items():
        staging_root = Path(
            tempfile.mkdtemp(prefix="group-", dir=staging_parent)
        )
        try:
            if downloader is _default_kaggle_downloader:
                def download_one(
                    record: tuple[KaggleFile, str, str, str]
                ) -> tuple[str, Path]:
                    item = record[0]
                    return item.name, Path(
                        downloader(dataset_handle, item.name, staging_root)
                    )

                downloaded_sources = dict(download_one(record) for record in items)
            else:
                returned_path = Path(
                    downloader(dataset_handle, remote_dir, staging_root)
                )
                downloaded_sources = {
                    item.name: _find_downloaded_file(
                        returned_path, staging_root, item.name
                    )
                    for item, _, _, _ in items
                }
            for item, source_split, label, filename in items:
                source = downloaded_sources[item.name]
                actual_size = source.stat().st_size
                if actual_size != item.total_bytes:
                    raise ValueError(
                        f"Sai kích thước {item.name}: expected {item.total_bytes}, got {actual_size}"
                    )
                digest = sha256_file(source)
                local_relative = PurePosixPath(
                    source_split, label, filename
                ).as_posix()
                destination = media_root / Path(local_relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    raise ValueError(f"Từ chối ghi đè media hiện có: {destination}")
                temporary = destination.with_name(f".{destination.name}.partial")
                shutil.copy2(source, temporary)
                if sha256_file(temporary) != digest:
                    temporary.unlink(missing_ok=True)
                    raise ValueError(f"Checksum thay đổi khi ghi {destination}")
                completed[item.name] = {
                    "remote_path": item.name,
                    "local_path": local_relative,
                    "total_bytes": item.total_bytes,
                    "sha256": digest,
                }
                _write_download_index(index_path, audit, completed)
                temporary.replace(destination)
                downloaded += 1
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

    _write_download_index(index_path, audit, completed)
    if staging_parent.exists() and not any(staging_parent.iterdir()):
        staging_parent.rmdir()
    return DownloadResult(
        downloaded=downloaded,
        reused=reused,
        media_root=media_root,
        index_path=index_path,
    )


def _stable_split_key(seed: int, label: str, remote_path: str) -> str:
    value = f"{seed}\0{label}\0{remote_path}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def build_sales30_manifest(
    output_root: Path,
    labels: Sequence[str],
    source_inventory: SourceInventory,
    *,
    seed: int,
    minimum_total_clips: int = 15,
) -> tuple[list[ManifestRow], ReadinessReport]:
    normalized_labels = tuple(normalize_label(label) for label in labels)
    if len(normalized_labels) != len(set(normalized_labels)):
        raise ValueError("Label map trùng sau Unicode NFC")
    if minimum_total_clips <= 0:
        raise ValueError("minimum_total_clips phải lớn hơn 0")
    label_ids = {label: index for index, label in enumerate(normalized_labels)}
    index_path = output_root / "download_index.json"
    validate_sales30_source_identity(
        source_inventory.dataset_ref,
        source_inventory.version,
        source_inventory.license_name,
    )
    indexed = _load_download_index(
        index_path,
        dataset_ref=source_inventory.dataset_ref,
        version=source_inventory.version,
        license_name=source_inventory.license_name,
    )
    media_root = output_root / "media"
    records: dict[str, list[tuple[KaggleFile, dict[str, Any], str]]] = {
        label: [] for label in normalized_labels
    }
    blockers = []

    for item in sorted(source_inventory.files, key=lambda value: value.name):
        try:
            source_split, label, _ = _parse_remote_path(item.name)
        except ValueError as error:
            blockers.append(str(error))
            continue
        if label not in label_ids:
            continue
        entry = indexed.get(item.name)
        if entry is None:
            blockers.append(f"Thiếu download index cho {item.name}")
            continue
        local_path = _safe_relative_path(
            str(entry.get("local_path") or ""), field="Local path"
        )
        media_path = media_root / Path(local_path.as_posix())
        if not media_path.is_file() or media_path.is_symlink():
            blockers.append(f"Thiếu media: {local_path.as_posix()}")
            continue
        actual_digest = sha256_file(media_path)
        if entry.get("sha256") != actual_digest:
            blockers.append(f"Sai checksum: {local_path.as_posix()}")
            continue
        if media_path.stat().st_size != item.total_bytes:
            blockers.append(f"Sai kích thước: {local_path.as_posix()}")
            continue
        records[label].append((item, entry, source_split))

    rows: list[ManifestRow] = []
    counts = {
        label: {"train": 0, "validation": 0, "test": 0}
        for label in normalized_labels
    }
    for label in normalized_labels:
        label_records = records[label]
        train_records = sorted(
            (record for record in label_records if record[2] == "train"),
            key=lambda record: _stable_split_key(seed, label, record[0].name),
        )
        test_records = sorted(
            (record for record in label_records if record[2] == "test"),
            key=lambda record: record[0].name,
        )
        validation_count = max(1, round(len(train_records) * 0.1)) if train_records else 0
        validation_paths = {
            record[0].name for record in train_records[:validation_count]
        }
        for item, entry, source_split in train_records + test_records:
            if source_split == "test":
                split = "test"
            elif item.name in validation_paths:
                split = "validation"
            else:
                split = "train"
            rows.append(
                ManifestRow(
                    path=str(entry["local_path"]),
                    label_id=label_ids[label],
                    label=label,
                    split=split,
                    source_id=source_inventory.dataset_ref,
                    source_revision=str(source_inventory.version),
                    source_label=label,
                    source_record_id=item.name,
                    license_name=source_inventory.license_name,
                    sha256=str(entry["sha256"]),
                    signer_id="unknown",
                    group_id="unknown",
                    view="unknown",
                    take="unknown",
                    source_split=source_split,
                    remote_path=item.name,
                    split_strength="development-only",
                )
            )
            counts[label][split] += 1

        total = sum(counts[label].values())
        if total < minimum_total_clips:
            blockers.append(
                f"Label {label} chỉ có {total} clip, cần tối thiểu {minimum_total_clips}"
            )
        for split in ("train", "validation", "test"):
            if counts[label][split] == 0:
                blockers.append(f"Label {label} thiếu split {split}")

    checksum_splits: dict[str, set[str]] = {}
    for row in rows:
        checksum_splits.setdefault(row.sha256, set()).add(row.split)
    for digest, splits in sorted(checksum_splits.items()):
        if len(splits) > 1:
            blockers.append(
                f"checksum xuất hiện ở nhiều split: {digest} ({', '.join(sorted(splits))})"
            )

    split_order = {"train": 0, "validation": 1, "test": 2}
    rows.sort(
        key=lambda row: (
            row.label_id,
            split_order[row.split],
            row.remote_path,
        )
    )
    readiness = ReadinessReport(
        counts=counts,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=(
            "Không có signer ID đầy đủ; manifest và metrics chỉ development-only",
        ),
    )
    return rows, readiness


def audit_sales30_manifest(
    path: Path,
    data_root: Path,
    labels: Sequence[str],
    *,
    minimum_total_clips: int = 15,
) -> ManifestAudit:
    normalized_labels = tuple(normalize_label(label) for label in labels)
    label_ids = {label: index for index, label in enumerate(normalized_labels)}
    counts = {
        label: {"train": 0, "validation": 0, "test": 0}
        for label in normalized_labels
    }
    errors = []
    seen_paths: set[str] = set()
    seen_records: set[str] = set()
    checksum_splits: dict[str, set[str]] = {}
    signer_splits: dict[str, set[str]] = {}
    group_splits: dict[str, set[str]] = {}

    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(MANIFEST_FIELDS) - set(reader.fieldnames or ())
        if missing:
            return ManifestAudit(
                counts=counts,
                errors=(f"Manifest thiếu cột: {', '.join(sorted(missing))}",),
                warnings=(),
            )
        for line_number, row in enumerate(reader, start=2):
            label = normalize_label(row["label"])
            split = row["split"]
            source_split = row["source_split"]
            relative_value = row["path"]
            remote_path = row["remote_path"]
            if label not in label_ids:
                errors.append(f"Dòng {line_number}: label ngoài label map: {label}")
                continue
            try:
                label_id = int(row["label_id"])
            except ValueError:
                errors.append(f"Dòng {line_number}: label_id không phải số nguyên")
                continue
            if label_id != label_ids[label]:
                errors.append(f"Dòng {line_number}: label không khớp label map")
            if split not in {"train", "validation", "test"}:
                errors.append(f"Dòng {line_number}: split không hợp lệ: {split}")
                continue
            try:
                remote_split, remote_label, remote_filename = _parse_remote_path(
                    remote_path
                )
            except ValueError as error:
                errors.append(f"Dòng {line_number}: {error}")
                continue
            if remote_split != source_split:
                errors.append(
                    f"Dòng {line_number}: source_split không khớp remote_path"
                )
            if remote_label != label:
                errors.append(f"Dòng {line_number}: label không khớp remote_path")
            if remote_split == "test" and split != "test":
                errors.append(
                    f"Dòng {line_number}: remote_path thuộc source test nhưng bị gán sang {split}"
                )
            if remote_split == "train" and split == "test":
                errors.append(
                    f"Dòng {line_number}: remote_path thuộc source train nhưng bị gán sang test"
                )
            expected_local = PurePosixPath(
                remote_split, remote_label, remote_filename
            ).as_posix()
            if relative_value != expected_local:
                errors.append(
                    f"Dòng {line_number}: local path không khớp remote_path"
                )
            if row["source_id"] != SALES30_DATASET_REF:
                errors.append(f"Dòng {line_number}: source_id không hợp lệ")
            if row["source_revision"] != str(SALES30_VERSION):
                errors.append(f"Dòng {line_number}: source_revision không hợp lệ")
            if row["source_label"] != label:
                errors.append(f"Dòng {line_number}: source_label không khớp")
            if row["source_record_id"] != remote_path:
                errors.append(f"Dòng {line_number}: source_record_id không khớp")
            if row["license"] != SALES30_LICENSE:
                errors.append(f"Dòng {line_number}: license không hợp lệ")
            if row["split_strength"] != "development-only":
                errors.append(f"Dòng {line_number}: split_strength không hợp lệ")
            if remote_path in seen_records:
                errors.append(f"Dòng {line_number}: source record trùng: {remote_path}")
            seen_records.add(remote_path)
            if relative_value in seen_paths:
                errors.append(f"Dòng {line_number}: path trùng: {relative_value}")
            seen_paths.add(relative_value)
            try:
                relative = _safe_relative_path(relative_value, field="Manifest path")
            except ValueError as error:
                errors.append(f"Dòng {line_number}: {error}")
                continue
            media_path = data_root / Path(relative.as_posix())
            if not media_path.is_file() or media_path.is_symlink():
                errors.append(f"Dòng {line_number}: thiếu media {relative_value}")
                continue
            actual_digest = sha256_file(media_path)
            if row["sha256"] != actual_digest:
                errors.append(f"Dòng {line_number}: checksum không khớp")
            checksum_splits.setdefault(actual_digest, set()).add(split)
            if row["signer_id"] != "unknown":
                signer_splits.setdefault(row["signer_id"], set()).add(split)
            if row["group_id"] != "unknown":
                group_splits.setdefault(row["group_id"], set()).add(split)
            counts[label][split] += 1

    for digest, splits in sorted(checksum_splits.items()):
        if len(splits) > 1:
            errors.append(
                f"checksum xuất hiện ở nhiều split: {digest} ({', '.join(sorted(splits))})"
            )
    for signer_id, splits in sorted(signer_splits.items()):
        if len(splits) > 1:
            errors.append(
                f"signer_id {signer_id} xuất hiện ở nhiều split: {', '.join(sorted(splits))}"
            )
    for group_id, splits in sorted(group_splits.items()):
        if len(splits) > 1:
            errors.append(
                f"group_id {group_id} xuất hiện ở nhiều split: {', '.join(sorted(splits))}"
            )
    for label in normalized_labels:
        total = sum(counts[label].values())
        if total < minimum_total_clips:
            errors.append(
                f"Label {label} chỉ có {total} clip, cần tối thiểu {minimum_total_clips}"
            )
        for split in ("train", "validation", "test"):
            if counts[label][split] == 0:
                errors.append(f"Label {label} thiếu split {split}")

    return ManifestAudit(
        counts=counts,
        errors=tuple(dict.fromkeys(errors)),
        warnings=(
            "Không có signer ID đầy đủ; manifest và metrics chỉ development-only",
        ),
    )
