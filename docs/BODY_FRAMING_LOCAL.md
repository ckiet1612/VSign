# Body framing (`trim-bodycrop-v1`)

## What changed

Before this change, three different crops reached the Sales30 model:

- **Training** used 16 frames spread over the whole clip, with the full frame stretched to 224×224.
- **Live automatic capture** used a center square of the camera image. It also sent the 650 ms of resting hands before the sign and about 660 ms of quiet after it.
- **Live manual capture** used a center square over the whole time the button was held.

Signer size also varied widely between sources. Nhu's seated clips are landscape video letterboxed inside a portrait frame, so the signer is small. HA's clips are medium shots, and the personal clips are close-ups.

`trim-bodycrop-v1` applies the same rules in training and in the browser:

1. **Signing span.** A frame is active when a hand is detected above the rest line, which is `shoulder midpoint y + 1.1 × shoulder width`, or when a visible pose wrist is above that line. With no shoulders, any detected hand counts as active.
   - The clip keeps the frames from the first active frame to the last, plus 100 ms on each side.
   - 16 frames are then sampled uniformly from that span.
   - If fewer than two frames are active, the whole clip is kept.
2. **Body box.** The crop is one square per clip.
   - The side is `2.6 × median shoulder width`.
   - The horizontal center is the shoulder midpoint. The vertical center is `0.15 × shoulder width` above the shoulder line.
   - Any part of the box outside the image is filled black, so the signer stays the same size across sources.
   - Without a stable pose (fewer than 3 frames with both shoulders visible), the crop falls back to the center square.

The thresholds come from MediaPipe statistics over all 4,920 training clips. During signing, 99% of hand points fall within ±1.1 shoulder widths horizontally and within −1.13…+0.78 shoulder widths vertically of the shoulder midpoint. Standing signers rest their hands about 1.6 shoulder widths below the shoulders.

Code:

| Role | Location |
|---|---|
| Python reference | `ml/body_framing.py` |
| Browser port | `apps/web/src/lib/bodyFraming.ts` |
| Shared golden vectors | `contracts/v1/framing_golden.json` |
| Golden vector tests | `tests/test_body_framing.py`, `apps/web/src/lib/bodyFraming.test.ts` |

Change both implementations together and regenerate the golden file.

The browser applies body framing only when `/metadata` reports `input_framing: "trim-bodycrop-v1"`. Older models still get the center square.

- **Automatic capture** uses the median pose over the last 1.5 s as a live approximation of the per-clip median. It cuts the 224 px crop at snapshot time, then sends only the snapshots inside the signing span.
- **Manual capture** locks the box when capture starts. It uses the median pose over the 1.5 s before the press, while the signer is still at rest.
- **Data collection** is unchanged. The offline pipeline frames the stored clips itself.

Both recognition modes encode frames while the user is still signing, through one persistent worker (`createStreamingEncoder` in `apps/web/src/lib/frameEncoder.ts`). Automatic capture keeps resting snapshots raw. From the first moving frame onward it hands every snapshot to the worker, and the trimmed-away frames are discarded. Manual capture encodes each 224 px frame as soon as it is captured; full-resolution frames are no longer held until the end.

In Chromium on the M1, 30 frames at 75 ms intervals took a median of 14.4 ms per frame (max 69 ms). The wait after the sign ends dropped from 82–121 ms for a 16-frame batch to 0 ms. The `Encode ảnh` readout in the automatic panel now shows only that remaining wait.

## Model

`sales30-mvitv2s-personal-v2-bodycrop-head-epoch38` was trained in `ml/artifacts/sales30_personal_v2_bodycrop/`. It uses the same frozen MViTv2-S backbone, manifest, 31 labels and recipe as personal-v1; only the preprocessing differs. Its Core ML FP32 package is in `ml/artifacts/sales30_personal_v2_bodycrop_coreml_fp32/`.

The benchmark compared it against PyTorch runs before and after (`benchmark_r2/`):

| Runtime | Median | P95 |
|---|---:|---:|
| Core ML `CPU_AND_GPU` | 363.27 ms | 377.27 ms |
| PyTorch | 644.07 ms | 659.00 ms |

Parity passed against PyTorch.

> **Update, same day:** personal-v3 replaced v2 as the default. It is v2 plus the owner's curation: Mua uses only the Personal variant, and Nhu's Nồi cơm điện clips are dropped. See [reports/2026-10-19-curation-v3](reports/2026-10-19-curation-v3/README.md).

## Evidence: 2026-10-19

The report is in [reports/2026-10-19-bodycrop-ab](reports/2026-10-19-bodycrop-ab/).

**Runtime replay.** Port 8000 ran Core ML. Each clip was framed in Python and sent as JPEG 90.

| Group | personal-v1 (2026-10-10), ok / wrong / uncertain | v2 body framing, ok / wrong / uncertain |
|---|---|---|
| Seated validation (Nhu, 600) | 390 / 84 / 126 | **445 / 68 / 87** |
| Standing validation (144) | 138 / 4 / 2 | 139 / 2 / 3 |
| Standing test (351) | 336 / 6 / 9 | 336 / 4 / 11 |

Results per word are mixed. On seated validation, the number of correctly accepted clips (out of 20) changed as follows:

- **Large gains:** Muốn 0→18, Thử 0→15, Điện thoại 6→20, Gạo 3→17, Cho 10→18.
- **Small regressions:** Tủ lạnh 16→11, Mới 20→16, Đắt 20→17, Cung cấp 9→6.
- **New wrong accepts:** Chào and Nồi cơm điện are still never correct, but they now produce wrong accepts (Chào 0→8, Nồi cơm điện 4→16) where v1 mostly answered uncertain.
- **Still wrong:** Mua and Rẻ.

Limits:

- Nhu's seated validation selected the checkpoint for both models, so it is a development set, not an independent test. Standing test is the only held-out split.
- No new signer, new session, live camera or sentence was evaluated.
- The live browser path has unit tests, golden parity and a canvas plan check. It has not been measured end to end with a camera.

## Rebuild

```bash
.venv/bin/python -m ml.scripts.build_sales30_framing --workers 7       # MediaPipe observations
PYTHONPATH=. .venv/bin/python -m ml.scripts.finetune_sales30_personal \
  --output-dir ml/artifacts/<new_dir> --framing-dir ml/artifacts/sales30_framing_v1 --threads 8
PYTHONPATH=. .venv/bin/python -m ml.scripts.compare_sales30_framing \
  --candidate ml/artifacts/<new_dir> --output <report>/comparison.json
```

Notes:

- Clips offloaded to iCloud must be downloaded first, including the `personal-100` JSON sidecars. Reads of offloaded files block silently.
- For the Core ML benchmark, pass `--candidates CPU_AND_GPU` to `benchmark_personal_coreml`. This skips Neural Engine configurations, whose compile did not finish for this model.

## Rollback

Stop the port-8000 launcher, then start personal-v1. Its summary has no `input_framing`, so the web client returns to the center square. Keep the wrapper used for port 8000 so the local system admin settings survive:

```bash
PERSONAL_MODEL_DIR="$PWD/ml/artifacts/sales30_personal_v1" \
COREML_MODEL_DIR="$PWD/ml/artifacts/sales30_personal_coreml_fp32_r4" \
  bash scripts/run_system_admin_local.sh
```
