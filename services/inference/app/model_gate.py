from __future__ import annotations

import math
import re

from app.registry_artifacts import RegistryManifest

POLICY_VERSION = "workspace-heldout-v2"


def evaluate_gate(report: dict, candidate: RegistryManifest, baseline: RegistryManifest, labels: list[str]) -> dict:
    checks = []

    def check(name: str, passed: bool, detail: str):
        checks.append(dict(name=name, passed=bool(passed), detail=detail))

    identity = {
        "schema_version": "1", "candidate_artifact_sha256": candidate.artifact_sha256,
        "baseline_artifact_sha256": baseline.artifact_sha256,
        "labels_sha256": candidate.labels_sha256, "source_run_id": candidate.source_run_id,
        "preprocessing_version": candidate.preprocessing_version, "protocol_version": candidate.protocol_version,
        "confidence_threshold": candidate.confidence_threshold, "margin_threshold": candidate.margin_threshold,
        "baseline_confidence_threshold": baseline.confidence_threshold, "baseline_margin_threshold": baseline.margin_threshold,
    }
    check("identity", all(type(report.get(k)) is type(v) and report.get(k) == v for k, v in identity.items())
          and candidate.labels_sha256 == baseline.labels_sha256
          and candidate.backend == baseline.backend,
          "Báo cáo phải khớp chính xác artifact, baseline, backend, nhãn và cấu hình suy luận.")
    digest = report.get("dataset_snapshot_sha256")
    check("dataset_snapshot", isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest) is not None,
          "Cần SHA256 snapshot dữ liệu đánh giá.")
    count = report.get("positive_count")
    check("held_out", report.get("held_out") is True and type(count) is int and count > 0,
          "Cần mẫu dương held-out, không dùng kết quả fit trên tập huấn luyện.")
    count = report.get("negative_count")
    check("independent_negatives", report.get("independent_negatives") is True and type(count) is int and count > 0,
          "Cần tập âm độc lập có mẫu thực tế.")

    def number(value, low=0., high=1.):
        return type(value) in (int, float) and math.isfinite(value) and low <= value <= high

    before, after = report.get("baseline"), report.get("candidate")
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    valid_f1 = all(number(v.get("macro_f1")) for v in (before, after))
    check("macro_f1", valid_f1 and after["macro_f1"] >= before["macro_f1"] - .02,
          "Macro F1 không giảm quá 0,02 so với baseline.")
    valid_far = all(number(v.get("false_accept_rate")) for v in (before, after))
    check("false_accept_rate", valid_far and after["false_accept_rate"] <= .05
          and after["false_accept_rate"] <= before["false_accept_rate"] + .01,
          "Tỷ lệ nhận nhầm <=5% và tăng không quá 1 điểm phần trăm.")
    valid_latency = all(number(v.get("latency_p95_ms"), .001, 1e9) for v in (before, after))
    check("latency_p95", valid_latency and after["latency_p95_ms"] <= 2000
          and after["latency_p95_ms"] <= before["latency_p95_ms"] * 1.2,
          "P95 <=2.000 ms và không vượt 120% baseline trên cùng runtime.")

    def classes(value):
        rows = value.get("per_class")
        if not isinstance(rows, list) or len(rows) != len(labels):
            return None
        if any(not isinstance(row, dict) or not isinstance(row.get("label"), str) for row in rows):
            return None
        result = {row["label"]: row for row in rows}
        if set(result) != set(labels) or len(result) != len(rows):
            return None
        if any(type(row.get("support")) is not int or row["support"] <= 0 or not number(row.get("recall")) for row in rows):
            return None
        return result

    old, new = classes(before), classes(after)
    check("per_class_recall", old is not None and new is not None and all(
        old[label]["support"] == new[label]["support"] and new[label]["recall"] >= old[label]["recall"] - .1 for label in labels),
        "Mọi nhãn có cùng support dương; recall không giảm quá 0,10.")
    return dict(passed=all(item["passed"] for item in checks), checks=checks)


def evaluate_workspace_gate(report, candidate, baseline, labels, trusted):
    result = evaluate_gate(report,candidate,baseline,[label for label in labels if label != 'Không ký hiệu'])
    result['checks'].append(dict(name='trusted_provenance',passed=bool(trusted),
        detail='Cần bằng chứng nguồn dữ liệu độc lập, tách video và nhóm người/phiên thu khỏi huấn luyện của cả hai model.'))
    result['passed'] = all(check['passed'] for check in result['checks'])
    return result
