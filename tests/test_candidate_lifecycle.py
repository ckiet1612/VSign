from __future__ import annotations

import csv
import hashlib
import importlib
import io
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS = ["finetune_sales30_personal", "finetune_sales30_seated_personal"]


@pytest.fixture(autouse=True)
def isolated_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'platform.db'}")
    monkeypatch.delenv("MODEL_PROTECTED_ARTIFACT_ROOTS", raising=False)


def lifecycle():
    try:
        return importlib.import_module("ml.candidate_manifest")
    except ModuleNotFoundError:
        pytest.fail("Candidate lifecycle helper is not implemented")


def registry(path, rows=()):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE registered_models (artifact_path TEXT, labels_path TEXT, "
                           "manifest_json JSON, workspace_id TEXT)")
        connection.executemany("INSERT INTO registered_models VALUES (?, ?, ?, ?)", rows)
        connection.execute("CREATE TABLE deployment_targets (active_model_id TEXT, revision INTEGER)")
        connection.execute("INSERT INTO deployment_targets VALUES ('production-untouched', 7)")


def registered_row(root, workspace="another-workspace", package=False):
    return (str(root / ("model.mlpackage" if package else "best.pt")),
            str(root / "labels.json"), '{"status":"production"}', workspace)


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("package", [False, True])
@pytest.mark.parametrize("position", ["same", "child", "ancestor", "labels"])
def test_scripts_reject_registered_outputs_before_source_reads_or_writes(
    tmp_path, script, package, position,
):
    protected = tmp_path / "immutable/model"
    row = list(registered_row(protected, package=package))
    row[1] = str(tmp_path / "immutable/labels/labels.json")
    database = tmp_path / "platform.db"
    registry(database, [row])
    before = database.read_bytes()
    output = {"same": protected, "child": protected / "new/cache",
              "ancestor": protected.parent, "labels": Path(row[1]).parent / "new"}[position]
    module = importlib.import_module(f"ml.scripts.{script}")
    with pytest.raises(ValueError, match="[Pp]rotected|registered"):
        module.main(["--root", str(tmp_path / "missing-sources"), "--output-dir", str(output)])
    assert not output.exists()
    assert database.read_bytes() == before


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("kind", ["parent", "output", "nested-file", "nested-directory", "dotdot"])
def test_scripts_reject_symlinks_in_output_before_any_write(tmp_path, script, kind):
    target = tmp_path / "real"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    output = tmp_path / "output"
    if kind == "parent":
        output = alias / "candidate"
    elif kind == "output":
        output.symlink_to(target, target_is_directory=True)
    elif kind == "dotdot":
        output = alias / ".." / "candidate"
    else:
        output.mkdir()
        (output / "features.pt").symlink_to(target if kind == "nested-directory" else target / "missing")
    module = importlib.import_module(f"ml.scripts.{script}")
    with pytest.raises(ValueError, match="symlink"):
        module.main(["--root", str(tmp_path / "missing"), "--output-dir", str(output)])
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("script", SCRIPTS)
def test_scripts_reject_hardlinked_temporary_output_files(tmp_path, script):
    protected = tmp_path / "protected/best.pt"
    protected.parent.mkdir()
    protected.write_bytes(b"immutable-checkpoint")
    output = tmp_path / "candidate"
    output.mkdir()
    os.link(protected, output / "best.tmp")
    registry(tmp_path / "platform.db", [registered_row(protected.parent)])
    module = importlib.import_module(f"ml.scripts.{script}")
    with pytest.raises(ValueError, match="hardlink"):
        module.main(["--root", str(tmp_path / "missing"), "--output-dir", str(output)])
    assert protected.read_bytes() == b"immutable-checkpoint"
    assert sorted(p.name for p in output.iterdir()) == ["best.tmp"]


@pytest.mark.parametrize("legacy", ["no-parent", "no-file", "empty-db", "old-schema"])
def test_guard_accepts_legacy_without_creating_or_mutating_database(tmp_path, monkeypatch, legacy):
    database = tmp_path / "absent/platform.db" if legacy == "no-parent" else tmp_path / "platform.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    if legacy in {"empty-db", "old-schema"}:
        with sqlite3.connect(database) as connection:
            if legacy == "old-schema":
                connection.execute("CREATE TABLE workspaces (id TEXT)")
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    lifecycle().validate_candidate_output(tmp_path / "new/candidate")
    after = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before
    assert not (tmp_path / "new").exists()
    assert database.exists() == (legacy in {"empty-db", "old-schema"})
    assert not (tmp_path / "absent").exists()


def test_guard_default_database_is_read_from_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL")
    (tmp_path / "data").mkdir()
    root = tmp_path / "immutable"
    registry(tmp_path / "data/vsign-platform.db", [registered_row(root)])
    with pytest.raises(ValueError, match="[Pp]rotected|registered"):
        lifecycle().validate_candidate_output(root / "new")


@pytest.mark.parametrize("package", [False, True])
def test_registered_existing_artifact_and_separate_labels_reserve_containing_directories(tmp_path, package):
    root = tmp_path / "immutable"
    row = list(registered_row(root / "model", package=package))
    artifact = Path(row[0])
    artifact.parent.mkdir(parents=True)
    if package:
        artifact.mkdir()
        (artifact / "weights.bin").write_bytes(b"immutable-weights")
    else:
        artifact.write_bytes(b"immutable-weights")
    labels = root / "labels/labels.json"
    labels.parent.mkdir()
    labels.write_text('["a","b"]')
    row[1] = str(labels)
    registry(tmp_path / "platform.db", [row])
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    for output in [artifact.parent / "sibling", artifact / "child", labels.parent / "candidate", root]:
        with pytest.raises(ValueError, match="[Pp]rotected|registered|directory|inspect"):
            lifecycle().validate_candidate_output(output)
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("bad", ["corrupt", "columns", "manifest", "null", "relative", "workspace", "symlink"])
def test_existing_registry_fails_closed_on_unreadable_or_malformed_data(tmp_path, bad):
    database = tmp_path / "platform.db"
    if bad == "corrupt":
        database.write_bytes(b"not a database")
    elif bad == "columns":
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE registered_models (artifact_path TEXT)")
    else:
        row = list(registered_row(tmp_path / "protected"))
        if bad == "manifest":
            row[2] = "[]"
        elif bad == "null":
            row[1] = None
        elif bad == "relative":
            row[0] = "relative/best.pt"
        elif bad == "workspace":
            row[3] = ""
        else:
            (tmp_path / "protected").symlink_to(tmp_path / "missing", target_is_directory=True)
        registry(database, [row])
    before = database.read_bytes()
    with pytest.raises(ValueError, match="registry|[Rr]egistered"):
        lifecycle().validate_candidate_output(tmp_path / "safe")
    assert database.read_bytes() == before
    assert not (tmp_path / "safe").exists()


def test_registry_table_names_cannot_bypass_guard_by_changing_case(tmp_path):
    database = tmp_path / "platform.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE REGISTERED_MODELS (artifact_path TEXT, labels_path TEXT, manifest_json JSON, workspace_id TEXT)")
        connection.execute("INSERT INTO REGISTERED_MODELS VALUES (?, ?, ?, ?)", registered_row(tmp_path / "protected"))
    with pytest.raises(ValueError, match="[Pp]rotected|registered"):
        lifecycle().validate_candidate_output(tmp_path / "protected/new")


def test_explicit_roots_do_not_override_a_broken_existing_registry(tmp_path, monkeypatch):
    (tmp_path / "platform.db").write_bytes(b"corrupt registry")
    monkeypatch.setenv("MODEL_PROTECTED_ARTIFACT_ROOTS", str(tmp_path / "protected"))
    with pytest.raises(ValueError, match="registry"):
        lifecycle().validate_candidate_output(tmp_path / "candidate")


def test_database_path_symlinks_fail_closed_even_when_target_is_missing(tmp_path):
    (tmp_path / "platform.db").symlink_to(tmp_path / "missing.db")
    with pytest.raises(ValueError, match="registry"):
        lifecycle().validate_candidate_output(tmp_path / "candidate")
    assert not (tmp_path / "missing.db").exists()


def test_registry_read_failure_fails_closed_without_leaking_details(tmp_path, monkeypatch):
    database = tmp_path / "platform.db"
    registry(database)
    helper = lifecycle()

    def denied(*args, **kwargs):
        raise sqlite3.OperationalError("secret-database-password")

    monkeypatch.setattr(helper.sqlite3, "connect", denied)
    with pytest.raises(ValueError) as caught:
        helper.validate_candidate_output(tmp_path / "safe")
    assert "secret-database-password" not in str(caught.value)
    assert caught.value.__suppress_context__


def test_registry_connection_uses_read_only_sqlite_uri(tmp_path, monkeypatch):
    database = tmp_path / "platform.db"
    registry(database)
    helper = lifecycle()
    connect = sqlite3.connect
    connections = []

    def readonly(database_uri, **kwargs):
        assert database_uri == database.as_uri() + "?mode=ro"
        assert kwargs["uri"] is True
        connection = connect(database_uri, **kwargs)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("UPDATE deployment_targets SET revision=8")
        connections.append(connection)
        return connection

    monkeypatch.setattr(helper.sqlite3, "connect", readonly)
    helper.validate_candidate_output(tmp_path / "safe")
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")


@pytest.mark.parametrize("url", ["postgresql://user:db-secret@host/platform", "sqlite:///:memory:"])
def test_non_file_database_requires_explicit_protection_without_exposing_url(tmp_path, monkeypatch, url):
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ValueError, match="MODEL_PROTECTED_ARTIFACT_ROOTS") as caught:
        lifecycle().validate_candidate_output(tmp_path / "candidate")
    assert "db-secret" not in str(caught.value)
    assert url not in str(caught.value)
    protected = tmp_path / "production"
    monkeypatch.setenv("MODEL_PROTECTED_ARTIFACT_ROOTS", str(protected))
    lifecycle().validate_candidate_output(tmp_path / "candidate")
    with pytest.raises(ValueError, match="[Pp]rotected"):
        lifecycle().validate_candidate_output(protected / "candidate")


def test_configured_roots_are_additive_to_all_workspace_registry_roots(tmp_path, monkeypatch):
    roots = [tmp_path / name for name in ["first-workspace", "second-workspace", "configured", "configured2"]]
    registry(tmp_path / "platform.db", [registered_row(roots[0], "first"), registered_row(roots[1], "second")])
    monkeypatch.setenv("MODEL_PROTECTED_ARTIFACT_ROOTS", os.pathsep.join(map(str, roots[2:])))
    for root in roots:
        with pytest.raises(ValueError, match="[Pp]rotected|registered"):
            lifecycle().validate_candidate_output(root / "candidate")
    lifecycle().validate_candidate_output(tmp_path / "first-workspace-copy")


@pytest.mark.parametrize("value", ["relative/root", ":", " ", "/safe::/other"])
def test_malformed_explicit_protection_is_not_silently_ignored(tmp_path, monkeypatch, value):
    monkeypatch.setenv("MODEL_PROTECTED_ARTIFACT_ROOTS", value)
    with pytest.raises(ValueError, match="MODEL_PROTECTED_ARTIFACT_ROOTS"):
        lifecycle().validate_candidate_output(tmp_path / "candidate")


@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_explicit_roots_must_be_directories_without_symlinks(tmp_path, monkeypatch, kind):
    protected = tmp_path / "protected"
    if kind == "file":
        protected.write_bytes(b"not a directory")
    else:
        protected.symlink_to(tmp_path / "missing", target_is_directory=True)
    monkeypatch.setenv("MODEL_PROTECTED_ARTIFACT_ROOTS", str(protected))
    with pytest.raises(ValueError, match="MODEL_PROTECTED_ARTIFACT_ROOTS"):
        lifecycle().validate_candidate_output(tmp_path / "candidate")


@pytest.mark.parametrize("script", SCRIPTS)
def test_non_sqlite_scripts_fail_before_source_read_or_output_creation(tmp_path, monkeypatch, script):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:db-secret@host/platform")
    module = importlib.import_module(f"ml.scripts.{script}")
    output = tmp_path / "new/candidate"
    with pytest.raises(ValueError, match="MODEL_PROTECTED_ARTIFACT_ROOTS"):
        module.main(["--root", str(tmp_path / "missing"), "--output-dir", str(output)])
    assert not output.parent.exists()


def test_guard_module_does_not_import_torch_or_backend():
    result = subprocess.run([sys.executable, "-c", "import sys; import ml.candidate_manifest; "
        "assert not any(n == 'torch' or n.startswith(('torch.', 'services.', 'app.')) for n in sys.modules)"],
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_candidate_publisher_refuses_different_label_order(tmp_path):
    (tmp_path / "best.pt").write_bytes(b"checkpoint")
    (tmp_path / "labels.json").write_text('["b", "a"]')
    with pytest.raises(ValueError, match="label order"):
        lifecycle().publish_candidate_manifest(tmp_path, labels=["a", "b"], model_version="candidate-v1", source_run_id="run1")
    assert not (tmp_path / "model_manifest.json").exists()


def test_candidate_hashes_are_streamed_not_loaded_with_read_bytes(tmp_path, monkeypatch):
    (tmp_path / "best.pt").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    (tmp_path / "labels.json").write_text('["a", "b"]')

    def no_read_bytes(self):
        pytest.fail("Artifact hashing must not load entire files")

    monkeypatch.setattr(Path, "read_bytes", no_read_bytes)
    path = lifecycle().publish_candidate_manifest(tmp_path, labels=["a", "b"], model_version="candidate-v1", source_run_id="run1")
    manifest = json.loads(path.read_text())
    assert manifest["artifact_sha256"] == hashlib.sha256(b"x" * (2 * 1024 * 1024 + 1)).hexdigest()
    assert manifest["status"] == "candidate"


class TinyModel:
    @staticmethod
    def build(count, pretrained=False):
        import torch

        model = torch.nn.Module()
        model.head = torch.nn.Sequential(torch.nn.Dropout(), torch.nn.Linear(2, count))
        return model


def training_fixture(tmp_path, monkeypatch, script, *, gate=True, fail=False):
    import torch
    from ml import personal_finetune as personal
    module = importlib.import_module(f"ml.scripts.{script}")
    root = tmp_path / "project"
    labels = [f"word-{i}" for i in range(30)]
    all_labels = labels + [personal.IDLE_LABEL]
    labels_path = root / "contracts/v1/sales30.labels.json"
    labels_path.parent.mkdir(parents=True)
    labels_path.write_text(json.dumps(labels))
    baseline = root / "ml/artifacts/sales30_seated_v3/training/best.pt"
    baseline.parent.mkdir(parents=True)
    state = TinyModel.build(30).state_dict()
    torch.save({"state_dict": state, "labels": labels, "input_shape": [1, 3, 16, 224, 224]}, baseline)
    rows = []
    for split, count in [("train", 2560), ("validation", 600), ("test", 351)]:
        for index in range(count):
            label_id = index % (31 if split == "train" else 30)
            rows.append({"path": f"{split}/{index}.mp4", "label_id": str(label_id), "label": all_labels[label_id],
                         "split": split, "source": {"train": "personal", "validation": "seated", "test": "standing"}[split],
                         "person": "Nh\u01b0" if split == "validation" else "unknown",
                         "group_id": split, "sha256": f"{split}-{index}"})
    audit = {"personal_sessions": {}, "personal_labels": {}}
    monkeypatch.setattr(module, "verify_baseline_manifest", lambda *args: None)
    monkeypatch.setattr(module, "prepare_rows", lambda *args: (rows, audit))
    comparison = {"deployment_gate_passed": gate, "validation": {"candidate": {}}, "standing_test": {"candidate": {}}}

    def trained(*args):
        if fail:
            raise RuntimeError("training failed")
        head = personal.expand_head(torch.nn.Linear(2, 30))
        return (head, 3, [], comparison) if script == SCRIPTS[0] else (head, 3, comparison)

    monkeypatch.setattr(module, "train_head", trained)
    features = torch.zeros(len(rows), 2)
    if script == SCRIPTS[0]:
        monkeypatch.setattr(module, "build_model", TinyModel.build)
        monkeypatch.setattr(module, "extract_features", lambda *args: features)
    else:
        current = root / "ml/artifacts/sales30_personal_v1"
        current.mkdir(parents=True)
        current_state = dict(state)
        head = personal.expand_head(torch.nn.Linear(2, 30))
        current_state.update({"head.1.weight": head.weight, "head.1.bias": head.bias})
        torch.save({"state_dict": current_state, "labels": all_labels, "input_shape": [1, 3, 16, 224, 224]}, current / "best.pt")
        (current / "labels.json").write_text(json.dumps(all_labels))
        (current / "summary.json").write_text(json.dumps({"best_sha256": personal.sha256_file(current / "best.pt"), "deployment_gate_passed": True}))
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=personal.MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        identity = {"baseline_sha256": personal.sha256_file(baseline), "manifest_sha256": hashlib.sha256(buffer.getvalue().encode()).hexdigest(),
                    "labels": all_labels, "preprocessing": "uniform16-224-imagenet-eval-v1"}
        (current / "run_identity.json").write_text(json.dumps(identity))
        (current / "features.pt").write_bytes(b"cache-fixture")
        manifest = root / "ml/data/combined/sales30_seated_v3/manifest.csv"
        manifest.parent.mkdir(parents=True)
        manifest.write_bytes(b"baseline-manifest-fixture")
        monkeypatch.setattr(module, "reuse_features", lambda *args: features)
    registry(tmp_path / "platform.db", [registered_row(baseline.parent)])
    return module, root, all_labels


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("gate", [False, True])
def test_successful_training_only_publishes_candidate_and_preserves_sources(tmp_path, monkeypatch, script, gate):
    import torch

    module, root, labels = training_fixture(tmp_path, monkeypatch, script, gate=gate)
    output = root / "ml/artifacts/new-candidate"
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert module.main(["--root", str(root), "--output-dir", str(output), "--epochs", "1"]) == (0 if gate else 2)
    manifest = json.loads((output / "model_manifest.json").read_text())
    assert manifest["status"] == "candidate"
    assert manifest["development_only"] is True
    assert manifest["artifact_sha256"] == hashlib.sha256((output / "best.pt").read_bytes()).hexdigest()
    assert manifest["labels_sha256"] == hashlib.sha256(json.dumps(labels, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    assert manifest["labels_file_sha256"] == hashlib.sha256((output / "labels.json").read_bytes()).hexdigest()
    assert manifest["source_run_id"] == hashlib.sha256((output / "run_identity.json").read_bytes()).hexdigest()
    assert manifest["model_version"] == torch.load(output / "best.pt", weights_only=True)["model_version"]
    assert {key: manifest[key] for key in ["backend", "protocol_version", "frame_count", "frame_size", "preprocessing_version", "confidence_threshold", "margin_threshold"]} == {
        "backend": "pytorch", "protocol_version": "1.0", "frame_count": 16, "frame_size": 224,
        "preprocessing_version": "rgb16-224-imagenet-v1", "confidence_threshold": .70, "margin_threshold": .15}
    assert torch.load(output / "best.pt", weights_only=True)["development_only"] is True
    for path, content in before.items():
        assert path.read_bytes() == content


@pytest.mark.parametrize("script", SCRIPTS)
def test_training_failure_does_not_publish_candidate_manifest(tmp_path, monkeypatch, script):
    from contracts.model_lifecycle_lock import lifecycle_lock

    module, root, _ = training_fixture(tmp_path, monkeypatch, script, fail=True)
    output = root / "ml/artifacts/new-candidate"
    with pytest.raises(RuntimeError, match="training failed"):
        module.main(["--root", str(root), "--output-dir", str(output)])
    assert not (output / "model_manifest.json").exists()
    with lifecycle_lock(os.environ["DATABASE_URL"]):
        assert not (output / "model_manifest.json").exists()


def test_features_only_does_not_publish_candidate_manifest(tmp_path, monkeypatch):
    from contracts.model_lifecycle_lock import lifecycle_lock

    module, root, _ = training_fixture(tmp_path, monkeypatch, SCRIPTS[0], fail=True)
    output = root / "ml/artifacts/new-candidate"
    assert module.main(["--root", str(root), "--output-dir", str(output), "--features-only"]) == 0
    assert not (output / "model_manifest.json").exists()
    with lifecycle_lock(os.environ["DATABASE_URL"]):
        assert not (output / "best.pt").exists()


@pytest.mark.parametrize("script", SCRIPTS)
def test_script_training_lock_held_before_preflight_through_publication(tmp_path, monkeypatch, script):
    try:
        from contracts.model_lifecycle_lock import LifecycleBusy, lifecycle_lock
    except ModuleNotFoundError:
        pytest.fail("Shared model lifecycle lock is not implemented")
    module, root, _ = training_fixture(tmp_path, monkeypatch, script)
    output = root / "ml/artifacts/new-candidate"
    url = os.environ["DATABASE_URL"]
    phases = []

    def registration_denied(phase):
        with pytest.raises(LifecycleBusy):
            with lifecycle_lock(url):
                pytest.fail("Registration overlapped training")
        phases.append(phase)

    preflight = module.validate_output
    write_json = module.write_json
    publish = module.publish_candidate_manifest

    def checked_preflight(*args):
        assert not output.exists()
        registration_denied("preflight")
        return preflight(*args)

    def checked_write(*args):
        registration_denied("write")
        return write_json(*args)

    def checked_publish(*args, **kwargs):
        registration_denied("publication-before")
        result = publish(*args, **kwargs)
        registration_denied("publication-after")
        return result

    monkeypatch.setattr(module, "validate_output", checked_preflight)
    monkeypatch.setattr(module, "write_json", checked_write)
    monkeypatch.setattr(module, "publish_candidate_manifest", checked_publish)
    assert module.main(["--root", str(root), "--output-dir", str(output), "--epochs", "1"]) == 0
    assert phases[0] == "preflight"
    assert "write" in phases
    assert phases[-1] == "publication-after"
    with lifecycle_lock(url):
        assert (output / "model_manifest.json").is_file()


@pytest.mark.parametrize("script", SCRIPTS)
def test_script_releases_training_lock_after_preflight_failure(tmp_path, monkeypatch, script):
    try:
        from contracts.model_lifecycle_lock import LifecycleBusy, lifecycle_lock
    except ModuleNotFoundError:
        pytest.fail("Shared model lifecycle lock is not implemented")
    module = importlib.import_module(f"ml.scripts.{script}")
    url = os.environ["DATABASE_URL"]

    def failed_preflight(*args):
        with pytest.raises(LifecycleBusy):
            with lifecycle_lock(url):
                pytest.fail("Registration overlapped preflight")
        raise ValueError("preflight failed")

    monkeypatch.setattr(module, "validate_output", failed_preflight)
    with pytest.raises(ValueError, match="preflight failed"):
        module.main(["--root", str(tmp_path), "--output-dir", str(tmp_path / "candidate")])
    with lifecycle_lock(url):
        assert not (tmp_path / "candidate").exists()
    assert not (tmp_path / "platform.db").exists()


@pytest.mark.parametrize("script", SCRIPTS)
def test_registration_lock_rejects_script_before_preflight(tmp_path, monkeypatch, script):
    from contracts.model_lifecycle_lock import LifecycleBusy, lifecycle_lock

    module = importlib.import_module(f"ml.scripts.{script}")

    def forbidden_preflight(*args):
        pytest.fail("Training reached preflight while registration held its exclusive lock")

    monkeypatch.setattr(module, "validate_output", forbidden_preflight)
    with lifecycle_lock(os.environ["DATABASE_URL"]):
        with pytest.raises(LifecycleBusy):
            module.main(["--root", str(tmp_path), "--output-dir", str(tmp_path / "candidate")])
    assert not (tmp_path / "candidate").exists()
    assert not (tmp_path / "platform.db").exists()


def test_training_decorator_uses_default_database_and_preserves_function_metadata(tmp_path, monkeypatch):
    try:
        from contracts.model_lifecycle_lock import LifecycleBusy, lifecycle_lock
    except ModuleNotFoundError:
        pytest.fail("Shared model lifecycle lock is not implemented")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL")

    @lifecycle().candidate_training_guard
    def sample(value):
        """Training entry point documentation."""
        with pytest.raises(LifecycleBusy):
            with lifecycle_lock(f"sqlite:///{tmp_path / 'data/vsign-platform.db'}"):
                pytest.fail("Default database was not protected")
        return value

    assert sample(7) == 7
    assert sample.__name__ == "sample"
    assert sample.__doc__ == "Training entry point documentation."
    assert sample.__wrapped__ is not sample
    assert not (tmp_path / "data").exists()
