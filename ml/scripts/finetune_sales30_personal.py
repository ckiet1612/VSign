from __future__ import annotations

import argparse
import copy
import csv
import io
import json
import time
from pathlib import Path

import torch
from PIL import ImageOps
from torch import nn
from torch.nn import functional as F

from ml.body_framing import PREPROCESSING_VERSION, frame_clip, load_observations, observations_digest
from ml.candidate_manifest import candidate_training_guard, publish_candidate_manifest
from ml.personal_finetune import (
    IDLE_LABEL, MANIFEST_FIELDS, apply_curation, decode_uniform_frames, evaluate_features, expand_head,
    load_feature_cache,
    prepare_rows, regression_gate, save_cache, sha256_file, validate_output, verify_baseline_manifest,
)
from ml.visignlanguage import build_model, decode_video, frames_to_tensor, load_labels


def write_json(path: Path, payload: dict | list) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def decode_clip(path, record, flip=False):
    if record is None:
        frames = decode_uniform_frames(path)
    else:
        images = decode_video(path)
        try:
            frames = frame_clip(images, record)
        finally:
            for image in images:
                image.close()
    if not flip:
        return frames
    # The body box is centred on the shoulders, so mirroring the framed clip equals
    # framing the mirrored video: a signer using the other hand.
    mirrored = [ImageOps.mirror(frame) for frame in frames]
    for frame in frames:
        frame.close()
    return mirrored


def reuse_features(cache, rows, source_dir, identity, observations):
    """Copy already-extracted features for identical clips from a sealed run with the same preprocessing."""
    source_identity = json.loads((source_dir / "run_identity.json").read_text(encoding="utf-8"))
    if any(source_identity.get(key) != identity.get(key)
           for key in ("baseline_sha256", "labels", "preprocessing", "training")):
        raise ValueError("Feature source used a different baseline, labels or preprocessing")
    with (source_dir / "manifest.csv").open(encoding="utf-8", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    if observations is not None:
        if any(row["path"] not in observations for row in source_rows) or observations_digest(
                {row["path"]: observations[row["path"]] for row in source_rows}) != source_identity.get("framing_sha256"):
            raise ValueError("Feature source was framed from different observations")
    elif "framing_sha256" in source_identity:
        raise ValueError("Feature source is body-framed but this run is not")
    source = load_feature_cache(source_dir / "features.pt", source_identity, len(source_rows), cache["features"].shape[1])
    lookup = {(row["path"], row["sha256"]): index for index, row in enumerate(source_rows)}
    reused = 0
    for index, row in enumerate(rows):
        match = lookup.get((row["path"], row["sha256"]))
        if match is not None and source["completed"][match] and not cache["completed"][index]:
            cache["features"][index].copy_(source["features"][match])
            cache["completed"][index] = True
            reused += 1
    return reused


def extract_features(root, rows, model, cache, cache_path, observations=None, flip=False):
    started = time.monotonic()
    initial = int(cache["completed"].sum())
    try:
        for index, row in enumerate(rows):
            if cache["completed"][index]:
                continue
            path = root / row["path"]
            if sha256_file(path) != row["sha256"]:
                raise ValueError(f"Source changed during extraction: {path}")
            frames = decode_clip(path, None if observations is None else observations[row["path"]], flip)
            clip = frames_to_tensor(frames, frame_count=16, height=224, width=224, training=False).unsqueeze(0)
            for frame in frames:
                frame.close()
            del frames
            with torch.inference_mode():
                features = model(clip)[0]
            if not torch.isfinite(features).all():
                raise ValueError(f"Non-finite features: {path}")
            cache["features"][index].copy_(features)
            cache["completed"][index] = True
            completed = int(cache["completed"].sum())
            if completed % 25 == 0 or completed == len(rows):
                seconds = time.monotonic() - started
                print(json.dumps({"event": "features", "completed": completed, "total": len(rows),
                                  "source": row["source"], "split": row["split"],
                                  "elapsed_seconds": round(seconds, 1),
                                  "seconds_per_new_sample": round(seconds / (completed - initial), 3)}), flush=True)
            if completed % 100 == 0:
                save_cache(cache_path, cache)
    finally:
        save_cache(cache_path, cache)
    return cache["features"]


def head_epochs(features, targets, train_ids, old_train, baseline_head, class_count, epochs, learning_rate):
    """Yield (epoch, head, mean loss) for the reversible head recipe: weighted CE on all
    training clips, KL replay of the accepted head on old clips, and L2 toward its weights."""
    head = expand_head(baseline_head)
    teacher = copy.deepcopy(baseline_head).requires_grad_(False)
    with torch.inference_mode():
        teacher_probabilities = teacher(features[train_ids]).softmax(dim=1)
    counts = torch.bincount(targets[train_ids], minlength=class_count).float()
    if (counts == 0).any():
        raise ValueError("Every class must have training examples")
    weights = counts.rsqrt()
    weights /= weights.mean()
    optimizer = torch.optim.AdamW(head.parameters(), lr=learning_rate, weight_decay=.01)
    for epoch in range(1, epochs + 1):
        head.train()
        order = torch.randperm(len(train_ids))
        loss_sum = 0.
        for offset in range(0, len(order), 128):
            local = order[offset:offset + 128]
            ids = train_ids[local]
            logits = head(features[ids])
            loss = F.cross_entropy(logits, targets[ids], weight=weights)
            replay = old_train[local]
            if replay.any():
                loss = loss + .5 * F.kl_div(
                    logits[replay, :30].log_softmax(dim=1), teacher_probabilities[local][replay], reduction="batchmean",
                )
            loss = loss + .01 * ((head.weight[:30] - teacher.weight).square().mean() + (head.bias[:30] - teacher.bias).square().mean())
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(head.parameters(), 5.)
            optimizer.step()
            loss_sum += float(loss.detach()) * len(ids)
        head.eval()
        yield epoch, head, loss_sum / len(train_ids)


def train_head(features, rows, baseline_head, labels, epochs, learning_rate, output):
    targets = torch.tensor([int(row["label_id"]) for row in rows])
    train_ids = torch.tensor([i for i, row in enumerate(rows) if row["split"] == "train"])
    validation_ids = torch.tensor([i for i, row in enumerate(rows) if row["split"] == "validation"])
    test_ids = torch.tensor([i for i, row in enumerate(rows) if row["split"] == "test"])
    personal_ids = torch.tensor([i for i, row in enumerate(rows) if row["source"] == "personal"])
    old_train = torch.tensor([row["source"] != "personal" for row in rows])[train_ids]
    teacher = copy.deepcopy(baseline_head).requires_grad_(False)
    baseline_validation = evaluate_features(teacher, features[validation_ids], targets[validation_ids], labels[:30])
    write_json(output / "baseline_validation.json", baseline_validation)
    history, best_score, best_state, best_epoch = [], float("-inf"), None, None
    for epoch, head, mean_loss in head_epochs(features, targets, train_ids, old_train, baseline_head,
                                              len(labels), epochs, learning_rate):
        validation = evaluate_features(head, features[validation_ids], targets[validation_ids], labels, positive_class_count=30)
        personal = evaluate_features(head, features[personal_ids], targets[personal_ids], labels)
        entry = {"epoch": epoch, "loss": mean_loss, "validation": validation,
                 "personal_training_diagnostics": personal}
        history.append(entry)
        # Negative fit is training evidence, not an independent validation metric.
        eligible = regression_gate(baseline_validation, validation) and personal["negative_recognition_rate"] >= .9
        score = validation["macro_f1"]
        if eligible and score > best_score:
            best_score, best_epoch = score, epoch
            best_state = copy.deepcopy(head.state_dict())
        print(json.dumps({"event": "epoch", "epoch": epoch, "loss": round(entry["loss"], 5),
                          "validation_accuracy": validation["accuracy"], "validation_macro_f1": score,
                          "personal_training_accuracy": personal["accuracy"],
                          "negative_training_recognition": personal["negative_recognition_rate"],
                          "negative_training_false_accept": personal["negative_false_accept_rate"],
                          "eligible": eligible}), flush=True)
    write_json(output / "history.json", history)
    if best_state is None:
        write_json(output / "summary.json", {"event": "deployment_gate_failed", "reason": "No eligible validation checkpoint", "history": history})
        raise RuntimeError("No candidate satisfies validation regression and negative training-fit gates; v3 stays active")
    head.load_state_dict(best_state)
    head.eval()
    baseline_test = evaluate_features(teacher, features[test_ids], targets[test_ids], labels[:30])
    candidate_test = evaluate_features(head, features[test_ids], targets[test_ids], labels, positive_class_count=30)
    validation = evaluate_features(head, features[validation_ids], targets[validation_ids], labels, positive_class_count=30)
    personal = evaluate_features(head, features[personal_ids], targets[personal_ids], labels)
    with torch.no_grad():
        baseline_personal_logits = teacher(features[personal_ids])
    positive = targets[personal_ids] < 30
    baseline_personal = evaluate_features(teacher, features[personal_ids][positive], targets[personal_ids][positive], labels[:30])
    negative_logits = baseline_personal_logits[~positive].softmax(dim=1).topk(2, dim=1).values
    baseline_negative_false_accept = float(((negative_logits[:, 0] >= .7) & (negative_logits[:, 0] - negative_logits[:, 1] >= .15)).float().mean())
    gate_passed = regression_gate(baseline_test, candidate_test)
    comparison = {"validation": {"baseline": baseline_validation, "candidate": validation},
                  "standing_test": {"baseline": baseline_test, "candidate": candidate_test},
                  "personal_training_only": {"baseline_positive": baseline_personal,
                                             "baseline_negative_false_accept_rate": baseline_negative_false_accept,
                                             "candidate": personal},
                  "regression_tolerance_absolute": .02, "deployment_gate_passed": gate_passed,
                  "independent_negative_evaluation": False, "development_only": True}
    write_json(output / "comparison.json", comparison)
    return head, best_epoch, history, comparison


@candidate_training_guard
def main(argv=None):
    parser = argparse.ArgumentParser(description="Real, reversible head fine-tuning from accepted Sales30 v3")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=Path("ml/artifacts/sales30_personal_v1"))
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--learning-rate", type=float, default=5e-4)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--features-only", action="store_true")
    parser.add_argument("--curation", type=Path, help="Owner decisions that drop clips from every split")
    parser.add_argument("--features-from", type=Path,
                        help="Sealed run with identical preprocessing whose cached features may be reused")
    parser.add_argument("--model-name", help="Model version stem, e.g. personal-v3-bodycrop-curated")
    parser.add_argument("--augment-hflip", action="store_true",
                        help="Also train on horizontally mirrored clips (signers using the other hand)")
    parser.add_argument("--framing-dir", type=Path,
                        help="Observations from build_sales30_framing; enables trim-bodycrop-v1 preprocessing")
    args = parser.parse_args(argv)
    if args.epochs < 1 or args.learning_rate <= 0 or args.threads < 1:
        parser.error("epochs, learning-rate, and threads must be positive")
    root = args.root.resolve()
    output = args.output_dir.absolute()
    baseline = root / "ml/artifacts/sales30_seated_v3/training/best.pt"
    batch = root / "ml/data/collected/sales30/batches/personal-100"
    validate_output(output, baseline, batch)
    if (output / "best.pt").exists():
        raise FileExistsError("Existing trained candidate; use a new output directory")
    labels = load_labels(root / "contracts/v1/sales30.labels.json")
    baseline_digest = sha256_file(baseline)
    checkpoint = torch.load(baseline, map_location="cpu", weights_only=True)
    if checkpoint.get("labels") != labels or checkpoint.get("input_shape") != [1, 3, 16, 224, 224]:
        raise ValueError("Baseline labels/input shape mismatch")
    baseline_manifest = root / "ml/data/combined/sales30_seated_v3/manifest.csv"
    verify_baseline_manifest(baseline_manifest, checkpoint)
    rows, audit = prepare_rows(root, baseline_manifest, batch, labels)
    if args.curation:
        rows, audit["curation"] = apply_curation(rows, json.loads((root / args.curation).read_text(encoding="utf-8")))
        audit["curated_total"] = len(rows)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=MANIFEST_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    manifest_content = buffer.getvalue().encode("utf-8")
    import hashlib
    identity = {"baseline_sha256": baseline_digest, "manifest_sha256": hashlib.sha256(manifest_content).hexdigest(),
                "labels": labels + [IDLE_LABEL], "preprocessing": "uniform16-224-imagenet-eval-v1", "training": "frozen-backbone-linear-head-v1"}
    observations = None
    if args.framing_dir:
        observations = load_observations(root / args.framing_dir)
        missing = [row["path"] for row in rows if row["path"] not in observations]
        if missing or any(observations[row["path"]]["sha256"] != row["sha256"] for row in rows):
            raise ValueError(f"Framing observations missing or stale for {len(missing)} clips")
        identity["preprocessing"] = f"{PREPROCESSING_VERSION}-uniform16-224-imagenet-eval"
        identity["framing_sha256"] = observations_digest({row["path"]: observations[row["path"]] for row in rows})
    if args.curation:
        identity["curation_sha256"] = sha256_file(root / args.curation)
    if args.augment_hflip:
        identity["augmentation"] = "hflip"
    model_name = args.model_name or ("personal-v2-bodycrop" if observations is not None else "personal-v1")
    output.mkdir(parents=True, exist_ok=True)
    identity_path = output / "run_identity.json"
    if identity_path.exists() and json.loads(identity_path.read_text(encoding="utf-8")) != identity:
        raise ValueError("Output belongs to a different run identity")
    write_json(identity_path, identity)
    manifest_path = output / "manifest.csv"
    if manifest_path.exists() and manifest_path.read_bytes() != manifest_content:
        raise ValueError("Refusing to overwrite a different manifest")
    manifest_path.write_bytes(manifest_content)
    write_json(output / "audit.json", audit)
    write_json(output / "labels.json", identity["labels"])
    torch.set_num_threads(args.threads)
    torch.manual_seed(20261009)
    model = build_model(30, pretrained=False)
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    baseline_head = copy.deepcopy(model.head[-1])
    baseline_state = {key: value for key, value in checkpoint["state_dict"].items()}
    del checkpoint
    model.head[-1] = nn.Identity()
    model.eval().requires_grad_(False)
    cache_path = output / "features.pt"
    cache = load_feature_cache(cache_path, identity, len(rows), baseline_head.in_features)
    if args.features_from:
        reused = reuse_features(cache, rows, root / args.features_from, identity, observations)
        audit["features_reused_from"] = {"run": str(args.features_from), "clips": reused}
        write_json(output / "audit.json", audit)
        save_cache(cache_path, cache)
    print(json.dumps({"event": "dataset_ready", "audit": audit, "cached_features": int(cache["completed"].sum()), "threads": args.threads}), flush=True)
    features = extract_features(root, rows, model, cache, cache_path, observations)
    flip_features = None
    if args.augment_hflip:
        flip_identity = {**identity, "view": "hflip"}
        flip_path = output / "features_hflip.pt"
        flip_cache = load_feature_cache(flip_path, flip_identity, len(rows), baseline_head.in_features)
        print(json.dumps({"event": "hflip_features", "cached": int(flip_cache["completed"].sum())}), flush=True)
        flip_features = extract_features(root, rows, model, flip_cache, flip_path, observations, flip=True)
    del model
    if args.features_only:
        return 0
    started = time.monotonic()
    training_rows, training_features = rows, features
    if flip_features is not None:
        # Mirrored copies join training only; validation, test and checkpoint selection stay on originals.
        train_index = [index for index, row in enumerate(rows) if row["split"] == "train"]
        training_rows = rows + [{**rows[index], "path": rows[index]["path"] + "#hflip"} for index in train_index]
        training_features = torch.cat([features, flip_features[torch.tensor(train_index)]])
    head, best_epoch, history, comparison = train_head(training_features, training_rows, baseline_head, identity["labels"], args.epochs, args.learning_rate, output)
    state_dict = dict(baseline_state)
    state_dict["head.1.weight"] = head.weight.detach().clone()
    state_dict["head.1.bias"] = head.bias.detach().clone()
    model = build_model(31, pretrained=False).eval()
    model.load_state_dict(state_dict, strict=True)
    changed = [key for key in baseline_state if state_dict[key].shape != baseline_state[key].shape or not torch.equal(state_dict[key], baseline_state[key])]
    if sorted(changed) != ["head.1.bias", "head.1.weight"]:
        raise RuntimeError(f"Unexpected backbone changes: {changed}")
    payload = {"architecture": "mvit_v2_s", "state_dict": state_dict, "labels": identity["labels"],
               "input_shape": [1, 3, 16, 224, 224], "epoch": best_epoch,
               "model_version": f"sales30-mvitv2s-{model_name}-head-epoch{best_epoch}",
               "input_framing": PREPROCESSING_VERSION if observations is not None else "center-square",
               "augmentation": identity.get("augmentation"),
               "fine_tuned_from_sha256": identity["baseline_sha256"], "run_identity": identity,
               "development_only": True, "training_scope": "linear_head_only"}
    temporary = output / "best.tmp"
    torch.save(payload, temporary)
    temporary.replace(output / "best.pt")
    summary = {"event": "training_complete", "model_version": payload["model_version"], "best_epoch": best_epoch,
               "epochs": args.epochs, "learning_rate": args.learning_rate,
               "training_seconds": time.monotonic() - started, "changed_tensors": changed,
               "backbone_unchanged": True, "deployment_gate_passed": comparison["deployment_gate_passed"],
               "independent_negative_evaluation": False, "best_sha256": sha256_file(output / "best.pt"),
               "input_framing": payload["input_framing"],
               "validation": comparison["validation"]["candidate"], "test": comparison["standing_test"]["candidate"]}
    write_json(output / "summary.json", summary)
    publish_candidate_manifest(output, labels=payload["labels"], model_version=payload["model_version"],
                               source_run_id=sha256_file(output / "run_identity.json"))
    print(json.dumps({key: summary[key] for key in ("event", "model_version", "best_epoch", "deployment_gate_passed", "backbone_unchanged")}), flush=True)
    return 0 if comparison["deployment_gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
