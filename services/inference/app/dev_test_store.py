"""Durable local test evidence with immutable predictions and append-only reviews."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class TrialStore:
    def __init__(self, root: Path, protected: list[Path]):
        for path in (root, *root.parents):
            if path.is_symlink():
                raise ValueError("Test storage must not use symlinks")
        resolved = root.resolve()
        if any(resolved.is_relative_to(path.resolve()) or path.resolve().is_relative_to(resolved) for path in protected):
            raise ValueError("Test storage overlaps protected training/model data")
        self.root, self.lock = root, Lock()
        root.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS trials (
                    trial_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY, trial_id TEXT NOT NULL REFERENCES trials(trial_id),
                    data TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(str(self.root / "trials.sqlite3"), timeout=30)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def find(self, trial_id: str):
        with self.connect() as connection:
            row = connection.execute("SELECT fingerprint, data FROM trials WHERE trial_id=?", (trial_id,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def save(self, fingerprint: str, trial: dict):
        with self.connect() as connection:
            connection.execute("INSERT INTO trials VALUES(?,?,?)", (trial["trial_id"], fingerprint, canonical(trial)))

    def rows(self, session_id: str | None = None):
        with self.connect() as connection:
            rows = [json.loads(row[0]) for row in connection.execute("SELECT data FROM trials ORDER BY rowid DESC")]
            histories = defaultdict(list)
            for trial_id, data in connection.execute("SELECT trial_id,data FROM reviews ORDER BY id"):
                histories[trial_id].append(json.loads(data))
        for row in rows:
            history = histories[row["trial_id"]]
            row["review_history"] = history
            row["review"] = history[-1] if history else {"valid": True, "notes": "", "reviewer": None}
        return [row for row in rows if session_id is None or row["session_id"] == session_id]

    def review(self, trial_id: str, review: dict):
        if self.find(trial_id) is None:
            raise KeyError(trial_id)
        with self.connect() as connection:
            connection.execute("INSERT INTO reviews(trial_id,data) VALUES(?,?)", (trial_id, canonical({**review, "reviewed_at": now()})))


def outcome(expected: str, prediction: dict | None) -> str:
    if prediction is None or prediction["status"] not in {"ok", "uncertain"}:
        return "technical_error"
    if expected == "Không ký hiệu":
        return "correct_rejection" if prediction["status"] == "uncertain" else "false_accept"
    if prediction["status"] == "uncertain":
        return "uncertain"
    return "correct" if prediction["label"] == expected else "wrong"


def summarize(rows: list[dict]) -> dict:
    def counts(items):
        valid = [row for row in items if row["review"]["valid"]]
        evaluated = [row for row in valid if row["outcome"] != "technical_error"]
        tally = Counter(row["outcome"] for row in evaluated)
        total = len(evaluated)
        result = {"recorded": len(items), "excluded": len(items) - len(valid), "evaluated": total,
                  "technical_error": sum(row["outcome"] == "technical_error" for row in valid)}
        for key in ("correct", "wrong", "uncertain", "correct_rejection", "false_accept"):
            result[key] = tally[key]
            result[key + "_pct"] = round(tally[key] * 100 / total, 2) if total else None
        result["wrong_labels"] = dict(Counter(row["prediction"]["label"] for row in evaluated
                                             if row["outcome"] in {"wrong", "false_accept"}))
        return result
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["runtime_key"], row["session_id"])].append(row)
    groups = []
    for (runtime_key, session), items in grouped.items():
        labels = items[0]["labels"]
        groups.append({"runtime_key": runtime_key, "session_id": session, "model_version": items[0]["model_version"],
                       "confidence_threshold": items[0]["confidence_threshold"], "margin_threshold": items[0]["margin_threshold"],
                       "positive": counts([row for row in items if row["expected_label"] != "Không ký hiệu"]),
                       "negative": counts([row for row in items if row["expected_label"] == "Không ký hiệu"]),
                       "per_word": [{"label": label, **counts([row for row in items if row["expected_label"] == label])} for label in labels]})
    return {"groups": groups, "recorded": len(rows), "independent_evaluation": False}


def export_csv(rows: list[dict]) -> str:
    def cell(value):
        if isinstance(value, str) and (value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))):
            return "'" + value
        return value

    fields = ["trial_id", "session_id", "signer_id", "expected_label", "outcome", "predicted_label", "confidence",
              "model_version", "runtime_key", "confidence_threshold", "margin_threshold", "captured_at", "duration_ms",
              "inference_ms", "hand", "distance", "lighting", "negative_action", "error_stage", "valid", "notes", "reviewer"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        prediction = row["prediction"] or {}
        values = {**row, **row["review"], "predicted_label": prediction.get("label"), "confidence": prediction.get("confidence")}
        writer.writerow({key: cell(value) for key, value in values.items()})
    return "\ufeff" + buffer.getvalue()
