# Expanded Local Sentence Rules

Approved scope: recognized Sales30 labels to Vietnamese draft text. This is
not a certified VSL grammar or continuous VSL translator. No new model,
question/negation detector, API key, checkpoint or acceptance threshold is
introduced. Existing capture/FIFO/sentence timing stays unchanged.

## Supported Families

Optional components appear only if recognized, never as inferred intent:

| Family | Example |
| --- | --- |
| Greeting / thanks | Chào. / Tôi chào. / Tôi cảm ơn. |
| Desire / need | Tôi muốn laptop mới. / Tôi cần tủ lạnh rẻ. |
| Buy / view / try / use | Tôi muốn mua sữa. / Tôi cần xem máy giặt. |
| Recipient requests | Cho tôi xem tivi mới. / Cho tôi cà phê. |
| Giving | Tôi cho điện thoại. (not Cho tôi điện thoại.) |
| Has | Siêu thị có gạo. (question/statement remains unverified) |
| Product description | Tủ lạnh mới rẻ. |
| Trade / supply | Tôi muốn mua bán điện thoại. / Siêu thị cung cấp sữa. |
| Change | Tôi muốn thay đổi ngân hàng. |
| Explicit refusal | Tôi từ chối laptop. / Tôi từ chối mua tivi. |
| Product lists | Tôi muốn mua gạo, sữa. |
| Attached qualifiers | Tôi muốn mua laptop mới, điện thoại cũ. |
| Multiple actions | Tôi muốn xem tủ lạnh, thử điện thoại. |
| Greeting/content/thanks | Chào. Tôi muốn mua sữa. Cảm ơn. |

Bare recognized fragments remain drafts (Mua. / Tủ lạnh.). The code uses
only punctuation and case normalization; it does not introduce conjunctions,
subjects, products, quantities, prices, qualifiers, question particles or
negation. Every recognized label phrase and its lexical counts are preserved.

## Ordering And Review

Single-object statements with at most one action, one desire and an optional
Tôi may be reordered. Both `Tôi Muốn Mua Tủ lạnh Rẻ` and
`Tôi Tủ lạnh Rẻ Muốn Mua` produce `Tôi muốn mua tủ lạnh rẻ.`.
Institutions may be reordered as a change target only with an explicit Tôi
at the start of the phrase.
`Ngân hàng Muốn Thay đổi` must not become `Muốn thay đổi ngân hàng.`.

Cho/recipient constructions are never freely reordered. Multi-product and
multi-action phrases require intact object/action groups in their original
order. Product-specific qualifiers cannot move across groups. A trailing
qualifier following bare product names has uncertain scope and stays raw.
Conflicting qualifiers, repeated labels, unsupported structures and unclear
roles keep their input order and return review warnings. Duplicate words are
never silently removed. The API continues to reject Không ký hiệu as content;
the direct local helper defensively filters it with a warning.

`Có Tủ lạnh` is not expanded into a question. A lexical composer cannot
detect facial grammar, negation or silently missed signs. Known recognition
gaps stay visible independently of grammar warnings. A grammar warning is
recomputed after edits/continuation; it never clears a capture-gap warning.
Review does not block later sentences or trigger repeated HTTP composition.
Composition errors/timeouts are stored separately too; retrying successfully
must not erase an earlier capture-gap warning.

## API And UI

`POST /sentence/compose` keeps sentence/provider/model and adds `warnings`
as a list (empty for an unflagged draft). TypeScript accepts responses from
older servers without that field, but rejects malformed warning payloads.
Automatic and manual displays/copy include review warnings. The existing
30-label input and 300-character output limits remain; oversized output is
rejected with 422, not truncated or turned into a server error.

## Rollback

Default: `SENTENCE_RULES=expanded`. To revert, stop the backend you launched
with Ctrl+C and run from the project root:

```bash
SENTENCE_RULES=legacy bash scripts/run_coreml_local.sh
```

Legacy preserves the pre-change case/punctuation and single sales-template
behavior, with no new composition warnings. The personal PyTorch launcher
also accepts the same variable. No frontend rebuild or model rollback is
needed. Remove this override or set `SENTENCE_RULES=expanded` and restart to
return to the expanded composer. No dotenv loader was added; setting an
example file alone does not change the running process.

## Verification

```bash
.venv/bin/python -m pytest
cd apps/web
npm test
npm run lint
npm run build
```

Reproduce the benchmark from the root with the archived pre-change source:

```bash
.venv/bin/python scripts/benchmark_sentence_rules.py \
  --before tmp/sentence-rules-20261010/sentence_before.py \
  --output tmp/sentence-rules-20261010/benchmark.json
```

The benchmark measures computation and the in-process sentence endpoint,
not camera recognition or real-network latency. Browser fixtures exercise
capture, encoding, FIFO, automatic drafts, review recovery, and 320/390/768/1365
pixel layouts against the real sentence endpoint. They do not establish live
webcam recognition accuracy, VSL grammar correctness or CUDA performance.

### Observed Local Results (2026-10-10)

- Backend: 385 tests passed; frontend: 295 passed, lint/build passed.
- Browser: 18 encoded captures, continued recognition after grammar review,
  no reported page errors or text overflow at the four tested widths.
- Full composer computation, pooled across 20 fixtures (20,000 calls each):
  median 0.00300 ms before / 0.00654 ms expanded;
  P95 0.00367 ms before / 0.00833 ms expanded.
- TestClient endpoint (400 calls per mode): median 0.78794 ms legacy /
  0.78954 ms expanded. These small differences are not a recognition-speed
  result or a stable network-latency estimate.
- Legacy output matches the archived pre-change source on 1,020 inputs.
- Checkpoint, labels, Core ML weights, segmenter, capture hook and FIFO hook
  hashes match the values recorded before editing.
- Evidence: `tmp/sentence-rules-20261010/verification.json`, `benchmark.json`,
  `backend-tests.xml`, `frontend-tests.json`, and `browser/report.json`.
