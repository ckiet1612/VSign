from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.mark.parametrize("shape", [(2, 17, 4), (1, 2, 17, 4)])
@pytest.mark.parametrize("norm_before", [False, True])
def test_export_pool_slicing_preserves_outputs_and_checkpoint_tensors(shape, norm_before) -> None:
    import copy
    import torch
    from torchvision.models.video.mvit import Pool
    from ml.scripts.personal_coreml import prepare_export_model

    source = Pool(torch.nn.Conv3d(4, 4, 3, stride=1, padding=1, groups=4),
                  torch.nn.LayerNorm(4) if not norm_before else None,
                  norm_before_pool=norm_before).eval()
    export = copy.deepcopy(source)
    inputs = torch.randn(shape)
    expected, expected_thw = source(inputs, (1, 4, 4))
    prepare_export_model(export)
    actual, actual_thw = export(inputs, (1, 4, 4))
    assert actual_thw == expected_thw
    torch.testing.assert_close(actual, expected, rtol=0, atol=0)
    for key, tensor in source.state_dict().items():
        assert torch.equal(tensor, export.state_dict()[key])


@pytest.mark.parametrize("query_shape,key_shape", [((2, 2, 3), (1, 3, 2)), ((1, 4, 4), (1, 2, 2)), ((2, 2, 2), (2, 2, 2))])
def test_export_relative_position_matches_original_attention(query_shape, key_shape) -> None:
    import math
    import torch
    from torchvision.models.video.mvit import _add_rel_pos
    from ml.scripts.personal_coreml import export_add_rel_pos

    torch.manual_seed(20261010)
    batch, heads, channels = 2, 3, 4
    query = torch.randn(batch, heads, math.prod(query_shape) + 1, channels)
    attention = torch.randn(batch, heads, math.prod(query_shape) + 1, math.prod(key_shape) + 1)
    embeddings = [torch.randn(2 * size - 1, channels) for size in (query_shape[1], query_shape[2], query_shape[0])]
    expected = _add_rel_pos(attention.clone(), query, query_shape, key_shape, *embeddings)
    actual = export_add_rel_pos(attention.clone(), query, query_shape, key_shape, *embeddings)
    torch.testing.assert_close(actual, expected, rtol=1e-5, atol=1e-5)


def test_checkpoint_gate_rejects_mutated_source_and_label_order(tmp_path) -> None:
    from ml.scripts.personal_coreml import verify_source
    import hashlib
    labels = json.loads(Path("contracts/v1/sales30.labels.json").read_text()) + ["Không ký hiệu"]
    (tmp_path / "best.pt").write_bytes(b"original-checkpoint")
    summary = {"deployment_gate_passed": True, "model_version": "personal-test",
               "best_sha256": hashlib.sha256(b"original-checkpoint").hexdigest()}
    (tmp_path / "summary.json").write_text(json.dumps(summary))
    (tmp_path / "labels.json").write_text(json.dumps(labels))
    assert verify_source(tmp_path)["model_version"] == "personal-test"
    (tmp_path / "best.pt").write_bytes(b"changed-checkpoint")
    with pytest.raises(ValueError, match="checkpoint"):
        verify_source(tmp_path)
    (tmp_path / "best.pt").write_bytes(b"original-checkpoint")
    (tmp_path / "labels.json").write_text(json.dumps(list(reversed(labels))))
    with pytest.raises(ValueError, match="labels"):
        verify_source(tmp_path)


def test_package_hash_detects_nested_weight_changes(tmp_path) -> None:
    from ml.scripts.personal_coreml import package_hash
    package = tmp_path / "model.mlpackage"
    weights = package / "Data/weights"
    weights.mkdir(parents=True)
    (package / "Manifest.json").write_text("{}")
    (weights / "weight.bin").write_bytes(b"original")
    before = package_hash(package)
    assert package_hash(package) == before
    (weights / "weight.bin").write_bytes(b"modified")
    assert package_hash(package) != before


def test_package_hash_rejects_symlinks_and_empty_packages(tmp_path) -> None:
    from ml.scripts.personal_coreml import package_hash
    package = tmp_path / "model.mlpackage"
    package.mkdir()
    with pytest.raises(ValueError):
        package_hash(package)
    outside = tmp_path / "outside"
    outside.write_bytes(b"weights")
    (package / "weights").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        package_hash(package)


@pytest.mark.parametrize("candidate,expected", [
    ({"parity_passed": True, "median_ms": 500., "p95_ms": 800.}, True),
    ({"parity_passed": False, "median_ms": 500., "p95_ms": 800.}, False),
    ({"parity_passed": True, "median_ms": 790., "p95_ms": 800.}, False),
    ({"parity_passed": True, "median_ms": 500., "p95_ms": 1100.}, False),
    ({"parity_passed": True, "median_ms": float("nan"), "p95_ms": 800.}, False),
    ({"parity_passed": True, "median_ms": True, "p95_ms": True}, False),
])
def test_deployment_gate_requires_parity_meaningful_speedup_and_no_tail_regression(candidate, expected) -> None:
    from ml.scripts.personal_coreml import deployment_gate
    assert deployment_gate({"median_ms": 800., "p95_ms": 1000.}, candidate) is expected


def test_conversion_finalization_keeps_original_error_when_source_verification_fails(tmp_path) -> None:
    from ml.scripts.personal_coreml import finalize_conversion
    report = {"passed": True, "source": {}, "error": {"message": "original conversion failure"}}
    finalize_conversion(report, tmp_path)
    assert report["passed"] is False
    assert report["source_unchanged"] is False
    assert report["error"]["message"] == "original conversion failure"
    assert report["preservation_error"]["type"] == "FileNotFoundError"


def test_benchmark_selects_only_faster_parity_passing_candidates_and_brackets_baseline() -> None:
    from ml.scripts.benchmark_personal_coreml import select_candidate
    baseline = [
        {"median_ms": 800., "p95_ms": 1000.},
        {"median_ms": 700., "p95_ms": 900.},
    ]
    candidates = [
        {"compute_units": "CPU_ONLY", "median_ms": 400., "p95_ms": 600., "parity_passed": False},
        {"compute_units": "ALL", "median_ms": 500., "p95_ms": 800., "parity_passed": True},
        {"compute_units": "CPU_AND_GPU", "median_ms": 680., "p95_ms": 950., "parity_passed": True},
    ]
    selected, gate_baseline = select_candidate(baseline, candidates)
    assert selected["compute_units"] == "ALL"
    assert gate_baseline == {"median_ms": 700., "p95_ms": 900.}
    selected, _ = select_candidate(baseline, [candidates[0], candidates[2]])
    assert selected is None


def test_coreml_preflight_rechecks_speed_gate_package_and_original_checkpoint(tmp_path) -> None:
    import hashlib
    from ml.scripts.personal_coreml import package_hash, verify_deployment, verify_source

    original = tmp_path / "original"
    candidate = tmp_path / "candidate"
    original.mkdir()
    candidate.mkdir()
    labels = json.loads(Path("contracts/v1/sales30.labels.json").read_text()) + ["Không ký hiệu"]
    (original / "best.pt").write_bytes(b"source-checkpoint")
    (original / "labels.json").write_text(json.dumps(labels))
    (original / "summary.json").write_text(json.dumps({"deployment_gate_passed": True,
        "model_version": "source-model", "best_sha256": hashlib.sha256(b"source-checkpoint").hexdigest()}))
    source = verify_source(original)
    package = candidate / "model.mlpackage"
    package.mkdir()
    (package / "weights").write_bytes(b"converted-weights")
    digest = package_hash(package)
    (candidate / "labels.json").write_text(json.dumps(labels))
    (candidate / "conversion.json").write_text(json.dumps({"passed": True,
        "source_unchanged": True, "source": source, "package_sha256": digest}))
    benchmark_path = candidate / "benchmark.json"
    report = {"deployment_gate_passed": True, "source_unchanged": True,
              "source": source, "package_sha256": digest, "selected_compute_units": "ALL",
              "fixture_sha256": "a" * 64,
              "baseline_for_gate": {"median_ms": 800., "p95_ms": 1000.},
              "selected_timing": {"median_ms": 400., "p95_ms": 600.},
              "results": [{"backend": "coreml", "compute_units": "ALL", "parity_passed": True,
                           "median_ms": 400., "p95_ms": 600., "source": source, "fixture_sha256": "a" * 64},
                          {"backend": "pytorch", "parity_passed": True, "median_ms": 800., "p95_ms": 1000., "source": source, "fixture_sha256": "a" * 64},
                          {"backend": "pytorch", "parity_passed": True, "median_ms": 850., "p95_ms": 1100., "source": source, "fixture_sha256": "a" * 64}]}
    benchmark_path.write_text(json.dumps(report))
    assert verify_deployment(original, candidate, benchmark_path) == ("source-model", "ALL")
    valid_results = json.loads(json.dumps(report["results"]))
    for corrupt in ["missing", "failed", "wrong_source", "wrong_baseline", "nonfinite_baseline", "infinite_baseline", "boolean_baseline"]:
        report["results"] = json.loads(json.dumps(valid_results))
        if corrupt == "missing":
            report["results"].pop()
        elif corrupt == "failed":
            report["results"][-1]["parity_passed"] = False
        elif corrupt == "wrong_source":
            report["results"][-1]["source"]["checkpoint_sha256"] = "0" * 64
        elif corrupt == "wrong_baseline":
            report["results"][-1]["median_ms"] = 500.
        elif corrupt == "nonfinite_baseline":
            report["results"][-1]["median_ms"] = float("nan")
        elif corrupt == "infinite_baseline":
            report["results"][-1]["p95_ms"] = float("inf")
        else:
            report["results"][-1]["median_ms"] = True
        benchmark_path.write_text(json.dumps(report))
        with pytest.raises(ValueError, match="benchmark"):
            verify_deployment(original, candidate, benchmark_path)
    for index in range(3):
        for bad_fixture in [None, "b" * 64]:
            report["results"] = json.loads(json.dumps(valid_results))
            report["results"][index]["fixture_sha256"] = bad_fixture
            benchmark_path.write_text(json.dumps(report))
            with pytest.raises(ValueError, match="fixture"):
                verify_deployment(original, candidate, benchmark_path)
    report["results"] = valid_results
    report["selected_timing"]["median_ms"] = 900.
    benchmark_path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="benchmark"):
        verify_deployment(original, candidate, benchmark_path)
    report["selected_timing"]["median_ms"] = 400.
    benchmark_path.write_text(json.dumps(report))
    (package / "weights").write_bytes(b"tampered-weights")
    with pytest.raises(ValueError, match="artifact"):
        verify_deployment(original, candidate, benchmark_path)
