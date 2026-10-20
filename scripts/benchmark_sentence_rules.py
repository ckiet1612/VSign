"""Compare rule computation and the sentence endpoint, not recognition latency."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import statistics
import sys
from pathlib import Path
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services/inference"))

from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.sentence import LocalSentenceComposer
from contracts.v1.sales_vocabulary import SALES_30_LABELS


CASES = [
    ["Tôi", "Muốn", "Mua", "Tủ lạnh", "Rẻ"],
    ["Tôi", "Tủ lạnh", "Rẻ", "Muốn", "Mua"],
    ["Tôi", "Laptop", "Mới", "Muốn"],
    ["Tôi", "Tủ lạnh", "Rẻ", "Cần"],
    ["Tôi", "Điện thoại", "Muốn", "Mua bán"],
    ["Tôi", "Ngân hàng", "Muốn", "Thay đổi"],
    ["Cho", "Tôi", "Xem", "Tivi", "Mới"],
    ["Tôi", "Cho", "Xem", "Điện thoại"],
    ["Tôi", "Muốn", "Mua", "Gạo", "Sữa"],
    ["Tôi", "Muốn", "Mua", "Laptop", "Mới", "Điện thoại", "Cũ"],
    ["Tôi", "Muốn", "Xem", "Tủ lạnh", "Thử", "Điện thoại"],
    ["Chào", "Tôi", "Muốn", "Mua", "Sữa"],
    ["Tôi", "Muốn", "Xem", "Laptop", "Cảm ơn"],
    ["Laptop", "Mới", "Cũ"],
    ["Tôi", "Tôi", "Muốn", "Mua", "Sữa"],
    ["Ngân hàng", "Thay đổi", "Cung cấp"],
    ["Tôi", "Từ chối", "Mua", "Tivi"],
    ["Siêu thị", "Cung cấp", "Gạo"],
    ["Mua"], ["Tủ lạnh"],
]


def measure(call, count):
    for _ in range(20):
        call()
    samples = []
    for _ in range(count):
        start = perf_counter_ns()
        call()
        samples.append((perf_counter_ns() - start) / 1_000_000)
    return samples


def stats(samples):
    ordered = sorted(samples)
    return {"samples": len(samples), "median_ms": round(statistics.median(ordered), 5),
            "p95_ms": round(ordered[int((len(ordered) - 1) * .95)], 5)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("sentence_before", args.before)
    before = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = before
    spec.loader.exec_module(before)
    original = before.LocalSentenceComposer()
    expanded = LocalSentenceComposer()
    legacy = LocalSentenceComposer(rules="legacy")
    rng = random.Random(20261010)
    rollback_cases = CASES + [rng.choices(SALES_30_LABELS, k=rng.randint(1, 30)) for _ in range(1000)]
    assert all(before.local_sentence(words) == legacy.compose(words).sentence for words in rollback_cases)
    rows = []
    compute = {"before": [], "expanded": []}
    for words in CASES:
        old_samples = measure(lambda: original.compose(words), 1000)
        new_samples = measure(lambda: expanded.compose(words), 1000)
        compute["before"].extend(old_samples)
        compute["expanded"].extend(new_samples)
        result = expanded.compose(words)
        rows.append({"words": words, "before": before.local_sentence(words), "after": result.sentence,
                     "warnings": result.warnings, "compute_before": stats(old_samples), "compute_after": stats(new_samples)})
    endpoint = {}
    for mode in ("legacy", "expanded"):
        samples = []
        with TestClient(create_app(Settings(sentence_rules=mode))) as client:
            for words in CASES:
                def call():
                    response = client.post("/sentence/compose", json={"words": words})
                    assert response.status_code == 200
                samples.extend(measure(call, 20))
        endpoint[mode] = stats(samples)
    protected_paths = [
        "ml/artifacts/sales30_personal_v1/best.pt",
        "ml/artifacts/sales30_personal_v1/labels.json",
        "ml/artifacts/sales30_personal_coreml_fp32_r4/model.mlpackage/Data/com.apple.CoreML/weights/weight.bin",
        "apps/web/src/lib/autoSegmentation.ts",
        "apps/web/src/hooks/useAutomaticSignCapture.ts",
        "apps/web/src/hooks/useAutomaticInferenceQueue.ts",
    ]
    hashes = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in protected_paths}
    report = {"compute": {key: stats(value) for key, value in compute.items()}, "endpoint_testclient": endpoint,
              "rollback_exact_match_cases": len(rollback_cases), "cases": rows, "protected_sha256": hashes,
              "limits": "Single Mac process, short recognized-word fixtures. TestClient includes API validation/threadpool, not real network, webcam recognition, VSL grammar validation or CUDA."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("compute", "endpoint_testclient", "rollback_exact_match_cases")}, indent=2))


if __name__ == "__main__":
    main()
