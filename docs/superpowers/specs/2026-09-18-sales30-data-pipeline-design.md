# Sales-30 data pipeline design

Date: 2026-09-18

## Goal

Build a reproducible data-ingestion pipeline for the 30 isolated sales signs in
`contracts/v1/sales30.labels.json`. The pipeline must audit source access,
license, label coverage and split safety before any video can become training
input. Multi-VSL is explicitly outside the scope.

The first deliverable is a source and coverage audit. Selective download,
manifest generation, a local smoke run and a reproducible Kaggle GPU training
job follow only when the audit passes.

## Current source status

The identifiers previously treated as Hugging Face repositories are public
Kaggle datasets. The primary source is:

- `nguyenanfms/vsl-vietnamese-sign-language-v2`, Kaggle version 8;
- title `VSL - Vietnamese Sign Language (Cropped)`;
- CC BY 4.0;
- 472 isolated glosses and 26,446 canonical processed clips;
- processed RGB videos are already cropped to 224x224 and have train/test
  directories.

The source covers 22 labels from the earlier vocabulary. To keep one consistent
source and avoid relying on the small QIPEDC classes, the eight unsupported
labels are replaced as follows:

| Previous label | VSL-472 label |
| --- | --- |
| Cửa hàng | Siêu thị |
| Có…không? | Có |
| Bao nhiêu? | Cần |
| Hóa đơn | Mua bán |
| Thẻ | Ngân hàng |
| Giao hàng | Cung cấp |
| Đổi | Thay đổi |
| Trả | Từ chối |

The resulting 30 labels all have exact directory matches in VSL-472. QIPEDC
remains a possible later supplement, not an input to this training increment.
Every source version and license must be re-queried when an audit is run.

## Architecture

### Source registry

A version-controlled JSON registry describes the pinned Kaggle source:

- stable source ID and repository type;
- repository identifier and pinned revision when known;
- declared license and whether training use is approved;
- label discovery strategy;
- optional local media root;
- signer and group metadata capabilities.

Credentials never appear in the registry, generated manifest or logs. Kaggle
authentication remains in KaggleHub's standard local credential store or the
Kaggle notebook environment. Public metadata audit works without credentials.

### Source audit

The audit command reads the registry and the canonical `sales-30` label map. It
normalizes Vietnamese labels to NFC and a conservative comparison key, then
reports:

- repository availability and resolved revision;
- declared license versus the registry expectation;
- source-label inventory;
- exact and explicitly configured label mappings;
- per-target coverage;
- whether signer IDs and source groups are available;
- blockers that prevent download, manifest generation or production use.

There is no fuzzy automatic mapping. Similar-looking labels such as `Trả`,
`Trả lại` and `Trả tiền` require an explicit reviewed mapping because they may
represent different signs.

The audit writes machine-readable JSON and a concise Markdown report. It exits
non-zero in strict mode when a source is unavailable, its revision/license has
changed, a mapping is ambiguous, or any target label has no approved source.

### Selective download

The download command consumes a passing audit artifact instead of accepting an
arbitrary repository directly. It uses KaggleHub to download only canonical
`processed/processed/frame_splited/{train,test}/{gloss}/*.mp4` files required
by the 30 exact target mappings and records SHA256 checksums. It never downloads
the 72 GB raw tree or augmented derivatives. Existing matching files are reused;
mismatches fail instead of being silently overwritten.

Archive extraction rejects absolute paths, parent traversal, symlinks and
Unicode-normalized collisions. Raw videos remain under ignored
`ml/data/raw/sales30/` and are never committed.

Sources without a confirmed training license may be catalogued but cannot be
downloaded by the training-data command. A separate metadata-only audit may
still report their label coverage.

### Canonical manifest

The generated manifest contains at least:

- `path`, `target_label_id`, `target_label`;
- `source_id`, `source_revision`, `source_label`, `source_record_id`;
- `license`, `sha256`;
- `signer_id`, `group_id`, `view`, `take`, `split`;
- `split_strength`, which is `signer-independent`, `group-safe` or
  `development-only`.

The pipeline preserves the supplied VSL-472 test split. It deterministically
carves validation groups from the supplied train split without moving any test
clip. Core VSL400 data is described as split by signer, but merged online data
does not expose complete signer identity. The generated artifact is therefore a
development evaluation unless an audit can prove signer ownership for every
included clip; it cannot by itself satisfy the production release gate.

No signer or group may cross split boundaries. Duplicate checksums across
splits are a hard failure.

### Readiness gate

The pipeline produces a readiness artifact with per-label counts, signer counts,
source counts and blockers. Full `sales-30` training is blocked unless:

- all 30 canonical labels have approved, reviewed mappings;
- every included source has an accepted license and pinned revision;
- every media file has a checksum;
- no duplicate, signer or group leakage is present;
- every target meets the configured minimum sample and diversity thresholds;
- an independent evaluation set is reserved or explicitly reported as missing.

The baseline-training gate requires every label to have non-empty train,
validation and test coverage and at least 15 canonical clips in total. Falling
below 100 usable clips or three known source groups marks the run
`development-only`; it does not prevent a baseline experiment. Production
release still requires those stronger diversity thresholds plus a separately
frozen webcam evaluation with unseen signers.

## Commands and outputs

The intended local workflow is:

```text
python -m ml.scripts.audit_sales30_sources
python -m ml.scripts.download_sales30_sources
python -m ml.scripts.build_sales30_manifest
python -m ml.scripts.audit_sales30_manifest
python -m ml.scripts.train_visignlanguage --config ml/configs/sales30_mvitv2_s.yaml --epochs 1 --max-train-batches 1 --max-val-batches 1 --no-pretrained
```

The full run uses the same config and scripts inside a Kaggle GPU notebook with
the public VSL-472 dataset attached. Training starts from Kinetics-400 weights,
uses class-weighted cross entropy and selects the checkpoint by validation macro
F1. The frozen source test split is evaluated once after model selection.

Version-controlled inputs:

```text
ml/configs/sales30_sources.json
ml/configs/sales30_mvitv2_s.yaml
contracts/v1/sales30.labels.json
```

Ignored generated outputs:

```text
ml/data/raw/sales30/source_audit.json
ml/data/raw/sales30/source_audit.md
ml/data/raw/sales30/media/
ml/data/raw/sales30/manifest.csv
ml/data/raw/sales30/readiness.json
runs/sales30_mvitv2_s/
```

## Failure behavior

- Network and authentication failures identify the source and remediation but
  never print credentials.
- Missing or unclear licenses are blockers, not warnings.
- Revision or checksum drift requires a new reviewed audit.
- Unknown signer identity downgrades the split strength and blocks a production
  readiness result.
- Partial downloads stay outside the final media directory and are safe to
  resume or remove.
- An incomplete 30-label inventory still produces a useful coverage report but
  never a train-ready manifest.

## Testing

Unit tests use small synthetic catalogs and archives; normal test runs do not
depend on the network. Tests cover Unicode normalization, explicit mappings,
license and revision drift, inaccessible sources, safe extraction, checksum
reuse, duplicate detection, deterministic signer splitting and strict readiness
failures.

One opt-in integration smoke test queries source metadata without downloading
video. The local M1 run is deliberately limited to one or a few batches and is
not reported as model quality. Full training requires a CUDA GPU notebook and
must save the checkpoint, config, labels, metrics and source version together.

## Non-goals

- Deploying the MViTv2-S `sales-30` model in this increment.
- Scraping QIPEDC without documented permission and license terms.
- Relabeling a source by semantic similarity without manual review.
- Treating group-safe metrics as signer-independent production evidence.
