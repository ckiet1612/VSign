# Sales-30 data pipeline design

Date: 2026-09-18

## Goal

Build a reproducible data-ingestion pipeline for the 30 isolated sales signs in
`contracts/v1/sales30.labels.json`. The pipeline must audit source access,
license, label coverage and split safety before any video can become training
input. Multi-VSL is explicitly outside the scope.

The first deliverable is a source and coverage audit. Downloading large media,
creating the final manifest and training are allowed only when the audit passes.

## Current source status

The two Hugging Face repositories previously selected for VSL-472 and QIPEDC
cannot currently be resolved anonymously:

- `nguyenanfms/vsl-vietnamese-sign-language-v2` returns HTTP 401 and is absent
  from public Hugging Face search.
- `aresusayhi/vsl-vietnamese-sign-languages` returns HTTP 401 and is absent from
  public Hugging Face search.

Public QIPEDC scraper repositories exist on GitHub, but the repositories do not
declare a data license. Their existence is not permission to use the crawled
videos for model training.

`KhangCN/Video_VSL` is publicly accessible on Hugging Face and declares
Apache-2.0, but its visible label inventory covers only a subset of `sales-30`.
It is a candidate supplement, not an automatic replacement for the approved
vocabulary or the missing sources.

These observations are evidence captured on 2026-09-18. Every source revision
and license must be re-queried when an audit is run.

## Architecture

### Source registry

A version-controlled JSON registry describes each candidate source:

- stable source ID and repository type;
- repository identifier and pinned revision when known;
- declared license and whether training use is approved;
- label discovery strategy;
- optional local media root;
- signer and group metadata capabilities.

Credentials never appear in the registry, generated manifest or logs. Hugging
Face authentication remains in the user's standard local credential store.

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
arbitrary repository directly. It downloads only files required by approved
target mappings and records SHA256 checksums. Existing matching files are
reused; mismatches fail instead of being silently overwritten.

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

The pipeline preserves official signer-independent splits when available. When
signer metadata exists but no official split exists, it assigns whole signers
deterministically to train, validation and test. When signer metadata is absent,
it may create only a group-safe development split; that split cannot satisfy the
production release gate.

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

The default threshold is a development guard, not a production claim: at least
100 usable clips per label and at least three source groups. Production release
still requires a separately frozen webcam evaluation with unseen signers.

## Commands and outputs

The intended workflow is:

```text
python -m ml.scripts.audit_sales30_sources
python -m ml.scripts.download_sales30_sources
python -m ml.scripts.build_sales30_manifest
python -m ml.scripts.audit_sales30_manifest
```

Version-controlled inputs:

```text
ml/configs/sales30_sources.json
contracts/v1/sales30.labels.json
```

Ignored generated outputs:

```text
ml/data/raw/sales30/source_audit.json
ml/data/raw/sales30/source_audit.md
ml/data/raw/sales30/media/
ml/data/raw/sales30/manifest.csv
ml/data/raw/sales30/readiness.json
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
video. Large downloads and model training remain explicit operator actions.

## Non-goals

- Training or deploying the MViTv2-S `sales-30` model in this increment.
- Scraping QIPEDC without documented permission and license terms.
- Relabeling a source by semantic similarity without manual review.
- Treating group-safe metrics as signer-independent production evidence.
