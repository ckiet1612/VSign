# Sales-30 VSL-472 Training Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a reproducible MViTv2-S baseline for 30 sales-oriented labels selected entirely from the public VSL-472 Kaggle dataset.

**Architecture:** A small Kaggle catalog client audits the pinned public dataset and produces an exact 30-label inventory. KaggleHub downloads only canonical processed videos for those labels, a manifest builder preserves the source test split and carves validation groups from source train, and the existing MViTv2-S trainer consumes a new `sales30` config. Local execution verifies one batch; full training runs through the same entrypoint on Kaggle CUDA and emits versioned metrics/checkpoints.

**Tech Stack:** Python 3.9, PyTorch 2.0, torchvision MViTv2-S, PyAV, KaggleHub 0.3.13, pytest, React/TypeScript contract consumers.

**Spec:** `docs/superpowers/specs/2026-09-18-sales30-data-pipeline-design.md`

## Global Constraints

- Multi-VSL must not be used by any data or training command.
- Source is `nguyenanfms/vsl-vietnamese-sign-language-v2`, Kaggle version 8, CC BY 4.0.
- Only canonical `processed/processed/frame_splited` RGB videos are eligible; raw and augmented trees are excluded.
- Label matching is exact after Unicode NFC normalization; fuzzy matching is forbidden.
- Source test clips remain test clips and are never used for training or model selection.
- Missing signer identity marks metrics development-only, never production-ready.
- Secrets must not be written to config, manifests, reports or command output.
- Existing unrelated worktree changes and `tmp/` files must be preserved.

---

### Task 1: Replace the unsupported sales labels

**Files:**
- Modify: `contracts/v1/sales30.labels.json`
- Modify: `docs/SALES_30.md`
- Modify: `tests/test_inference_api.py`
- Modify: `apps/web/src/App.test.tsx`

**Interfaces:**
- Consumes: `_load_sales_30_labels()` from `contracts/v1/sales_vocabulary.py`.
- Produces: `SALES_30_LABELS: tuple[str, ...]` in this exact order: `Chào`, `Tôi`, `Muốn`, `Mua`, `Cho`, `Xem`, `Thử`, `Siêu thị`, `Có`, `Cần`, `Điện thoại`, `Laptop`, `Tivi`, `Tủ lạnh`, `Máy giặt`, `Nồi cơm điện`, `Gạo`, `Sữa`, `Cà phê`, `Mới`, `Cũ`, `Rẻ`, `Đắt`, `Sử dụng`, `Mua bán`, `Ngân hàng`, `Cung cấp`, `Thay đổi`, `Từ chối`, `Cảm ơn`.

- [x] **Step 1: Update the Python API expectation before the label map**

Replace the eight old labels in `tests/test_inference_api.py` with the exact replacements while preserving order.

- [x] **Step 2: Run the focused backend test and observe the expected failure**

Run: `.venv/bin/pytest tests/test_inference_api.py -q`

Expected: failure because API metadata still reads the old JSON labels.

- [x] **Step 3: Update the canonical label JSON and web expectation**

Write the exact 30-label list above to `contracts/v1/sales30.labels.json`, update the same expected list in `apps/web/src/App.test.tsx`, and revise `docs/SALES_30.md` so its 20 example intents use only the new labels plus AI-supplied Vietnamese function words.

- [x] **Step 4: Run contract and web tests**

Run: `.venv/bin/pytest tests/test_inference_api.py -q`

Run: `npm test -- --run App.test.tsx` from `apps/web`.

Expected: both pass and metadata exposes exactly 30 unique labels.

- [x] **Step 5: Commit the vocabulary increment**

```bash
git add contracts/v1/sales30.labels.json contracts/v1/sales_vocabulary.py contracts/v1/inference.py contracts/v1/inference.ts contracts/README.md services/inference/app/config.py services/inference/app/main.py tests/test_inference_api.py apps/web/src/App.tsx apps/web/src/App.test.tsx apps/web/src/components/CollectionPanel.tsx README.md docs/SALES_30.md .env.example docker-compose.yml scripts/run_onnx_local.sh
git commit -m "feat: define public sales30 vocabulary"
```

### Task 2: Add the pinned Kaggle source registry and catalog audit

**Files:**
- Create: `ml/configs/sales30_sources.json`
- Create: `ml/sales30_data.py`
- Create: `ml/scripts/audit_sales30_sources.py`
- Create: `tests/test_sales30_data.py`
- Modify: `ml/requirements.txt`

**Interfaces:**
- Produces: `normalize_label(value: str) -> str`.
- Produces: `load_source_config(path: Path) -> Sales30SourceConfig`.
- Produces: `list_kaggle_files(config: Sales30SourceConfig, fetch_json: JsonFetcher = fetch_json_url) -> SourceInventory`.
- Produces: `audit_source(config: Sales30SourceConfig, labels: Sequence[str], inventory: SourceInventory) -> SourceAudit`.
- Produces CLI: `python -m ml.scripts.audit_sales30_sources --config ... --labels ... --output-dir ...`.

- [ ] **Step 1: Write failing tests for config validation and exact coverage**

Add tests with an injected two-page fake Kaggle response:

```python
def test_source_audit_requires_exact_nfc_label_coverage(tmp_path: Path) -> None:
    config = source_config(tmp_path, expected_version=8)
    inventory = SourceInventory(
        dataset_ref=config.dataset_ref,
        version=8,
        license_name="Attribution 4.0 International (CC BY 4.0)",
        files=(
            KaggleFile("processed/processed/frame_splited/train/Ca\u0300 phe/1.mp4", 10),
            KaggleFile("processed/processed/frame_splited/test/Cà phê/2.mp4", 10),
        ),
    )
    audit = audit_source(config, ["Cà phê", "Laptop"], inventory)
    assert audit.coverage["Cà phê"] == {"train": 1, "test": 1}
    assert audit.blockers == ("Thiếu label nguồn: Laptop",)
```

Also test version drift, license drift, exclusion of `raw/` and `processed_augmented/`, and pagination token forwarding.

- [ ] **Step 2: Run the focused test and verify import failure**

Run: `.venv/bin/pytest tests/test_sales30_data.py -q`

Expected: FAIL because `ml.sales30_data` does not exist.

- [ ] **Step 3: Implement immutable config, file and audit dataclasses**

Use frozen dataclasses `Sales30SourceConfig`, `KaggleFile`, `SourceInventory`, and `SourceAudit`. Validate dataset ref, version `8`, accepted license, canonical prefix and minimum total clips `15` at config load time.

- [ ] **Step 4: Implement the anonymous Kaggle metadata client**

Use `urllib.request` against:

```text
https://www.kaggle.com/api/v1/datasets/view/{dataset_ref}?includeMetadata=true
https://www.kaggle.com/api/v1/datasets/list/{dataset_ref}?pageSize=200&pageToken={token}
```

Stop pagination only when `nextPageToken` is empty. Keep only `.mp4` paths under the configured canonical prefix. Do not log response headers or environment variables.

- [ ] **Step 5: Add the CLI report writer**

Write `source_audit.json` and `source_audit.md` atomically. Return exit code `1` when blockers exist and `0` only when all 30 labels meet the baseline gate.

- [ ] **Step 6: Add KaggleHub dependency and run tests**

Add `kagglehub==0.3.13` to `ml/requirements.txt`.

Run: `.venv/bin/pytest tests/test_sales30_data.py -q`

Expected: PASS.

- [ ] **Step 7: Run the live metadata audit**

Run:

```bash
.venv/bin/python -m ml.scripts.audit_sales30_sources \
  --config ml/configs/sales30_sources.json \
  --labels contracts/v1/sales30.labels.json \
  --output-dir ml/data/raw/sales30
```

Expected: version 8, CC BY 4.0, 30/30 exact labels, no source blocker, and development-only split warning.

- [ ] **Step 8: Commit the source-audit increment**

```bash
git add ml/configs/sales30_sources.json ml/sales30_data.py ml/scripts/audit_sales30_sources.py ml/requirements.txt tests/test_sales30_data.py
git commit -m "feat: audit public VSL472 source"
```

### Task 3: Download canonical clips and build a leakage-safe manifest

**Files:**
- Create: `ml/scripts/download_sales30_sources.py`
- Create: `ml/scripts/build_sales30_manifest.py`
- Create: `ml/scripts/audit_sales30_manifest.py`
- Modify: `ml/sales30_data.py`
- Modify: `tests/test_sales30_data.py`
- Modify: `ml/data/README.md`

**Interfaces:**
- Produces: `download_inventory(audit: SourceAudit, output_root: Path, downloader: DatasetDownloader) -> DownloadResult`.
- Produces: `build_sales30_manifest(media_root: Path, labels: Sequence[str], source_inventory: SourceInventory, seed: int) -> tuple[list[ManifestRow], ReadinessReport]`.
- Produces: `audit_sales30_manifest(path: Path, data_root: Path) -> ManifestAudit`.

- [ ] **Step 1: Write failing safe-download and split tests**

Cover download-path traversal rejection, reuse of an existing matching checksum, checksum mismatch failure, deterministic validation selection, preservation of source test, duplicate checksum across split failure, and non-empty train/validation/test for every label.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `.venv/bin/pytest tests/test_sales30_data.py -q`

Expected: FAIL because downloader/manifest functions are undefined.

- [ ] **Step 3: Implement selective KaggleHub download**

Import KaggleHub lazily and call:

```python
kagglehub.dataset_download(
    "nguyenanfms/vsl-vietnamese-sign-language-v2/versions/8",
    path=remote_path,
    output_dir=str(staging_root),
)
```

Move a fully downloaded file into `media/{source_split}/{label}/{filename}` only after SHA256 succeeds. Maintain `download_index.json` with remote path, bytes and digest. Do not silently retry permanent 401/403 errors.

- [ ] **Step 4: Implement deterministic manifest generation**

For every label, sort source-train paths by `sha256(f"{seed}\0{label}\0{path}")`. Reserve `max(1, round(train_count * 0.1))` paths for validation and assign the rest to train. Preserve every source-test path as test. Write the existing trainer columns first: `path,label_id,label,split`, followed by provenance columns.

- [ ] **Step 5: Implement readiness and manifest audit**

Fail on missing files, duplicate paths, duplicate checksums across splits, label-map mismatch, empty split, source-test reassignment, or fewer than 15 clips total for a label. Report unknown signers as `development-only` rather than fabricating signer IDs.

- [ ] **Step 6: Run focused and existing data tests**

Run: `.venv/bin/pytest tests/test_sales30_data.py tests/test_data_tools.py tests/test_prepare_visignlanguage_video.py -q`

Expected: PASS.

- [ ] **Step 7: Attempt the selective download**

Run:

```bash
.venv/bin/python -m ml.scripts.download_sales30_sources \
  --audit ml/data/raw/sales30/source_audit.json \
  --output-root ml/data/raw/sales30
```

If KaggleHub requires login, preserve the audit and stop with the exact command `python -m kagglehub.login`; never fall back to downloading all 82 GB.

- [ ] **Step 8: Build and audit the real manifest when download succeeds**

Run:

```bash
.venv/bin/python -m ml.scripts.build_sales30_manifest --output-root ml/data/raw/sales30
.venv/bin/python -m ml.scripts.audit_sales30_manifest ml/data/raw/sales30/manifest.csv --data-root ml/data/raw/sales30/media
```

Expected: 30 labels, three non-empty splits per label, zero duplicate leakage, `development-only` readiness.

- [ ] **Step 9: Commit the data-preparation increment**

```bash
git add ml/sales30_data.py ml/scripts/download_sales30_sources.py ml/scripts/build_sales30_manifest.py ml/scripts/audit_sales30_manifest.py tests/test_sales30_data.py ml/data/README.md
git commit -m "feat: prepare selective sales30 dataset"
```

### Task 4: Configure and harden MViTv2-S training

**Files:**
- Create: `ml/configs/sales30_mvitv2_s.yaml`
- Modify: `ml/scripts/train_visignlanguage.py`
- Modify: `ml/scripts/evaluate_visignlanguage.py`
- Create: `tests/test_sales30_training.py`

**Interfaces:**
- Extends: `resolve_device(requested: str) -> torch.device` with `mps` rejection that explains MViTv2-S must use CPU smoke or CUDA full training.
- Produces: `validate_training_config(config: dict[str, Any], labels: Sequence[str]) -> None`.
- Produces: checkpoint metadata keys `source`, `source_version`, `split_strength`, `git_commit`, and `development_only`.

- [ ] **Step 1: Write failing config and checkpoint metadata tests**

Test that class count must equal 30, source version must be 8, the labels path must be `contracts/v1/sales30.labels.json`, and a development-only split is stored in checkpoints.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `.venv/bin/pytest tests/test_sales30_training.py -q`

Expected: FAIL because config validation and metadata helpers are missing.

- [ ] **Step 3: Add the sales30 training config**

Configure 16 RGB frames at 224x224, Kinetics-400 initialization, 30 classes, batch size 2, gradient accumulation 4, 12 epochs, AdamW learning rate `1e-4`, cosine minimum `1e-6`, weight decay `0.05`, no horizontal flip and early selection by macro F1.

- [ ] **Step 4: Add validation and provenance metadata**

Validate config before constructing datasets. Store the exact source ref/version, config, labels, git commit and split strength in every checkpoint and summary. Rename user-facing descriptions from Common-20 to generic VSign training/evaluation.

- [ ] **Step 5: Run training unit tests**

Run: `.venv/bin/pytest tests/test_sales30_training.py tests/test_visignlanguage_training.py -q`

Expected: PASS.

- [ ] **Step 6: Run a local one-batch smoke train when media exists**

Run:

```bash
.venv/bin/python -m ml.scripts.train_visignlanguage \
  --config ml/configs/sales30_mvitv2_s.yaml \
  --output-dir runs/sales30_smoke \
  --device cpu --epochs 1 --batch-size 1 --num-workers 0 \
  --max-train-batches 1 --max-val-batches 1 --no-pretrained
```

Expected: `last.pt`, `best.pt`, `labels.json` and `summary.json`; this run is labeled smoke/development-only.

- [ ] **Step 7: Commit the trainer increment**

```bash
git add ml/configs/sales30_mvitv2_s.yaml ml/scripts/train_visignlanguage.py ml/scripts/evaluate_visignlanguage.py tests/test_sales30_training.py
git commit -m "feat: configure sales30 MViTv2 training"
```

### Task 5: Add a reproducible Kaggle GPU entrypoint

**Files:**
- Create: `ml/scripts/run_sales30_kaggle.py`
- Create: `ml/notebooks/SALES30_KAGGLE.md`
- Create: `tests/test_sales30_kaggle_runner.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `find_attached_vsl472_root(input_root: Path) -> Path`.
- Produces CLI that builds the manifest from the attached dataset, trains, evaluates test once and exports ONNX into `/kaggle/working/vsign-sales30-artifacts`.

- [ ] **Step 1: Write failing attached-dataset discovery tests**

Use synthetic directories to assert one valid canonical root is accepted, zero roots gives an actionable error, and multiple roots requires `--dataset-root`.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `.venv/bin/pytest tests/test_sales30_kaggle_runner.py -q`

Expected: FAIL because the runner does not exist.

- [ ] **Step 3: Implement the Kaggle runner**

The runner accepts `--dataset-root`, `--output-dir`, `--epochs`, `--batch-size` and `--num-workers`. It invokes Python functions directly, not shell strings, and refuses to start full training when CUDA is unavailable. It evaluates `best.pt` on test exactly once and exports `model.onnx`, `labels.json`, `test_metrics.json` and `artifact_manifest.json`.

- [ ] **Step 4: Document the free Kaggle run**

Document: create a GPU notebook, attach dataset version 8, upload/clone this repository, run `pip install -r ml/requirements.txt`, execute the runner, and download the output artifact. State that the attached dataset is read-only and no Kaggle token is required inside the notebook.

- [ ] **Step 5: Run the runner tests and CLI help**

Run: `.venv/bin/pytest tests/test_sales30_kaggle_runner.py -q`

Run: `.venv/bin/python -m ml.scripts.run_sales30_kaggle --help`

Expected: tests pass and help lists all explicit paths/overrides.

- [ ] **Step 6: Commit the Kaggle execution increment**

```bash
git add ml/scripts/run_sales30_kaggle.py ml/notebooks/SALES30_KAGGLE.md tests/test_sales30_kaggle_runner.py README.md
git commit -m "feat: add Kaggle sales30 training job"
```

### Task 6: Verify the complete implementation and launch training

**Files:**
- Modify only when verification exposes a scoped defect.

**Interfaces:**
- Consumes all commands and artifacts from Tasks 1-5.
- Produces a verified local pipeline and, when a logged-in Kaggle session is available, a running/completed CUDA training job.

- [ ] **Step 1: Run all Python tests**

Run: `.venv/bin/pytest -q`

Expected: all tests pass.

- [ ] **Step 2: Run all web checks**

Run from `apps/web`:

```bash
npm test -- --run
npm run lint
npm run build
```

Expected: tests, lint and production build pass.

- [ ] **Step 3: Run source audit and manifest audit**

Expected: source version/license/coverage pass; manifest passes when media is present. Report authentication as a blocker when selective download could not start.

- [ ] **Step 4: Run the local smoke train**

Expected: one optimizer step and one validation batch complete without NaN; artifacts contain 30 labels and development-only provenance.

- [ ] **Step 5: Launch the Kaggle CUDA run**

Use an existing authenticated Kaggle browser session or Kaggle API credentials. Attach dataset version 8 and run:

```bash
python -m ml.scripts.run_sales30_kaggle --epochs 12 --batch-size 2 --num-workers 2
```

Do not claim completion until `best.pt`, test metrics and ONNX export are retrieved and checksummed. If authentication is unavailable, stop at the actionable login boundary and report that no full model was trained.

- [ ] **Step 6: Final verification report**

Record source version, clip counts by split/class, best validation macro F1, frozen test accuracy/macro F1/top-3, elapsed time, device and artifact checksums. Explicitly label the result development-only until independent webcam evaluation passes.
