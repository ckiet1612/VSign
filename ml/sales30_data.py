from __future__ import annotations

import json
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Mapping, Sequence, Tuple


JsonPayload = Mapping[str, Any]
JsonFetcher = Callable[[str], JsonPayload]


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
