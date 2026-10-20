# Seated + Personal Local Candidate

Approved on 2026-10-11: fine-tune using seated recordings plus personal-100,
keep the current model unchanged, and allow local UI selection and rollback.

## Dataset And Training

| Partition | Source | Samples |
| --- | --- | ---: |
| Train | Seated HA + Nhi | 1,160 |
| Train | Personal-100, one session | 1,400 |
| Validation | Seated Nhu | 600 |
| Evaluation only | Existing standing test | 351 |

The validation signer is `Như` in the original manifests. All 30 words have
training and validation coverage. Nhi lacks Cung cap and Thay doi, but HA
provides both. Personal adds 13 words at 100 clips each and 100 idle clips.
The original 30 label indices and the idle output index 30 are unchanged.

No standing clip enters optimization. Initialization is still seated-v3,
which previously learned standing data: this is seated/personal-only
fine-tuning, not a model trained from scratch without standing knowledge.
Only `head.1.weight` and `head.1.bias` change. Features come from the sealed
personal-v1 cache after manifest, baseline hash, tensor integrity, row identity,
completion and unchanged-backbone checks. Original data, caches, checkpoints
and the backend on port 8000 are not replaced.

Cross-entropy weights give each class equal total mass, then divide that mass
equally among available seated/personal sources within that class. Seated
teacher distillation and classifier regularization retain the old vocabulary.
The fixed schedule is 40 epochs, AdamW learning rate 0.0005, seed 20261011.

Select the highest seated-validation macro-F1 among epochs whose accuracy,
macro-F1 and correct runtime acceptance fall by no more than 0.02 absolute
versus personal-v1, and whose personal-training idle recognition is at least
90/100 with at most 2/100 wrong word accepts. Negative fit is training evidence,
not independent validation. Standing test is evaluated only after selection.
It must also pass the 0.02 regression tolerance before the candidate launcher
accepts the artifact. Passing a tolerance gate does not mean improvement or
production acceptance.

## Local Run

The first run is preserved in `ml/artifacts/sales30_seated_personal_v1/`.
Its float32 rate comparison incorrectly excluded exactly 90/100 idle fits.
A tested boundary fix uses confusion-matrix recall and integer false-accept
counts. The same schedule was rerun into a new directory, without tuning on
standing-test results:

```bash
.venv/bin/python -u -m ml.scripts.finetune_sales30_seated_personal \
  --output-dir ml/artifacts/sales30_seated_personal_v1_r2
```

This path already contains the completed run. Reruns must use a fresh output
directory; the script refuses any existing directory. Epoch 33 was selected:
`sales30-mvitv2s-seated-personal-v1-head-epoch33`.

Checkpoint SHA256:
`83d9897405ceb2d3f264f9d2845c233a9daa099659aa3586ef32dafc463f6b65`.

| Measure | Current personal-v1 | Candidate |
| --- | ---: | ---: |
| Seated validation top-1 accuracy | 69.67% | 69.83% |
| Seated validation macro-F1 | 0.64432 | 0.64315 |
| Seated validation correct accepted word | 65.00% | 65.17% |
| Standing test top-1 accuracy | 96.58% | 96.58% |
| Standing test correct accepted word | 95.73% | 95.44% |
| Personal training idle top-1 recognition | 92/100 | 90/100 |
| Personal training wrong word accepts on idle | 1/100 | 2/100 |

The candidate is not a clear quality win. The old model remains the default.
`comparison.json` contains every word's top-1 confusion, accepted-correct,
accepted-wrong and uncertain counts/rates separately. Each seated-validation
word has only 20 examples, so one changed clip moves that word by 5 percentage
points. The candidate does not fix zero correct accepts for Thu, Noi com dien
or Su dung in this development set.
See the generated [per-word table](reports/2026-10-11-seated-personal/per-word-validation.md).

## Run And Switch

Keep the existing default backend running on 8000. In another terminal:

```bash
bash scripts/run_seated_personal_local.sh
```

The separate candidate binds 127.0.0.1:8003, checks the artifact hash/label order,
preservation flag and regression gate, and disables collection. It enables
the development manual-test APIs with the same local store as the old test
backend. It refuses the existing default ports 8000 and 8002, and an occupied
candidate port. The port check permits TIME_WAIT reuse, as Uvicorn does.

The launcher uses the separate FP32 Core ML package only after its conversion
and serial parity/latency benchmark pass. Otherwise it uses this candidate's
verified PyTorch checkpoint, not an arbitrary old checkpoint. If the source
candidate fails verification, it exits without changing either old backend.
PyTorch keeps the model portable for later CUDA deployment; CUDA performance
has not been tested here.

The existing local Vite pages at 5173 and 5174 receive the selector through
hot reload. Normal recognition uses `Model máy chủ`: `Hiện tại` or
`Seated + Personal`. Manual testing at 5174/dev-test offers the same selector.
Both pages start on `Hiện tại` after reload. A failed preflight leaves the old
selection unchanged. Returning to `Hiện tại` restores the old endpoint;
it does not edit or retrain a checkpoint. Normal recognition clears its word
draft after a successful switch. Captures, encoding, inference, queued work,
composition and pending collection saves block switching. Manual pending
trials and clip reviews also block it. A disconnected explicitly selected
candidate cannot silently use the browser landmark fallback model.

For a new frontend terminal, use a free port:

```bash
cd apps/web
npm run dev -- --host 127.0.0.1 --port 5175 --strictPort
```

The candidate defaults to port 8003. Override both
`VITE_SEATED_INFERENCE_HTTP_URL` and `VITE_SEATED_INFERENCE_WS_URL` if using a
different candidate port. The selector is local development UI only and is
hidden from production/public builds; it is an operator/testing control, not
a required customer interaction.

## Runtime Comparison

The separate Core ML conversion passes parity on the fixed 20-clip training
replay at probability tolerance 1e-5. Its serial worker benchmark selects
`ALL`: median 365.28 ms / P95 385.58 ms versus the faster PyTorch bracket
709.27 ms / P95 985.04 ms. This compares implementations of the same candidate,
not candidate quality or speed against the already-accelerated old model.

The actual endpoint comparison uses byte-identical encoded frames, two warmups,
40 sequential requests per bracket, old -> candidate -> old, with no capture
or collection. All three brackets return 24/26 correct positive accepts and
0/14 wrong accepts on idle training replays.

| Actual Core ML endpoint | Median | P95 |
| --- | ---: | ---: |
| Old personal-v1 before | 377.76 ms | 400.14 ms |
| Seated + personal | 417.92 ms | 731.66 ms |
| Old personal-v1 after | 440.75 ms | 585.28 ms |

There is no demonstrated speed gain over the old Core ML model. Candidate P95
is higher in this run, and the old brackets also show drift. Neither result
establishes camera-to-result realtime or load performance. Evidence and UI
screenshots are in [the run report](reports/2026-10-11-seated-personal/README.md).

## Evidence Limits

- Personal metadata does not record posture. Inclusion was approved, but
  seated posture for all personal clips is not independently verified.
- Personal contains one signer/session. Semantic labels were not manually
  reviewed by this training run. Do not randomly split that session to claim
  independent accuracy.
- Nhu was already used in v3 development. Seated validation is not an unseen
  signer or new-session test; there is no independent seated/negative test.
- Cached evaluation retains the existing uniform-16 preprocessing. It is not
  a new real-camera segmentation/crop test.
- Recorded-clip WebSocket, Core ML parity, screenshots and unit tests do not
  establish realtime, customer accuracy, load or production readiness.

Before promoting the candidate, compare new seated camera sessions in Dev/Test,
including ordinary movements and each of the 30 words. Keep immutable
predictions and reject incomplete/incorrectly labeled clips during review.
