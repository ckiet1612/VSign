"""Per-word calibrated, sentence-context-aware acceptance for one recognized sign.

The policy runs on the model's full probability vector:

1. Calibration: ``softmax((log p + bias) / temperature)``, fitted per word offline
   by ``ml/scripts/calibrate_sales30_decisions.py``.
2. Context: a top-3 candidate that cannot continue the words already in the
   sentence (per ``sentence_rules``) is down-weighted by ``context_penalty``.
3. Confusers: a winner with a known look-alike (e.g. Có vs Rẻ) is refused while that
   look-alike keeps more than its fitted probability, unless context rules it out.
4. Acceptance: the winner needs its own word threshold and the global margin.
   When context leaves it as the only grammatical candidate in the top 3, a lower
   ``context_floor`` is enough, so a low-confidence sign that fits the sentence
   can still be accepted.

Without a policy file the runtime keeps its original fixed thresholds.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Optional, Sequence

import numpy as np

from app.backends.base import BackendCandidate, BackendPrediction
from app.models import PredictionStatus
from app.sentence_rules import REPEATED, UNCLEAR, expanded_sentence

IDLE_LABEL = "Không ký hiệu"
MAX_CONTEXT_WORDS = 8
CONTINUATION_DEPTH = 2


def _key(word: str) -> str:
    return unicodedata.normalize("NFC", word.strip()).lower()


def labels_digest(labels: Sequence[str]) -> str:
    return hashlib.sha256(json.dumps(list(labels), ensure_ascii=False).encode("utf-8")).hexdigest()


@lru_cache(maxsize=65536)
def _complete(words: tuple[str, ...]) -> bool:
    try:
        _, warnings = expanded_sentence(words)
    except ValueError:
        return False
    return UNCLEAR not in warnings and REPEATED not in warnings


@lru_cache(maxsize=8192)
def can_continue(prefix: tuple[str, ...], vocabulary: tuple[str, ...], depth: int = CONTINUATION_DEPTH) -> bool:
    """True when ``prefix`` is, or can become within ``depth`` more words, a rule-valid sentence."""
    if _complete(prefix):
        return True
    if depth == 0:
        return False
    return any(can_continue(prefix + (word,), vocabulary, depth - 1) for word in vocabulary)


@dataclass(frozen=True)
class DecisionPolicy:
    labels: tuple[str, ...]
    temperature: float = 1.0
    bias: Mapping[str, float] = field(default_factory=dict)
    thresholds: Mapping[str, float] = field(default_factory=dict)
    default_threshold: float = 0.70
    margin_threshold: float = 0.15
    context_penalty: float = 1.0
    context_floor: Optional[float] = None
    confusers: Mapping[str, Mapping[str, float]] = field(default_factory=dict)

    @classmethod
    def baseline(cls, labels: Sequence[str], confidence: float, margin: float) -> "DecisionPolicy":
        return cls(labels=tuple(labels), default_threshold=confidence, margin_threshold=margin)

    @classmethod
    def load(cls, path: Path, labels: Sequence[str], model_version: str) -> "DecisionPolicy":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("model_version") != model_version or payload.get("labels_sha256") != labels_digest(labels):
            raise ValueError("Decision policy belongs to a different model or label order")
        confusers = payload.get("confusers", {})
        unknown = (set(payload.get("bias", {})) | set(payload.get("thresholds", {})) | set(confusers)
                   | {other for pairs in confusers.values() for other in pairs}) - set(labels)
        if unknown:
            raise ValueError(f"Decision policy names unknown labels: {sorted(unknown)}")
        policy = cls(
            labels=tuple(labels), temperature=float(payload["temperature"]),
            bias={key: float(value) for key, value in payload.get("bias", {}).items()},
            thresholds={key: float(value) for key, value in payload.get("thresholds", {}).items()},
            default_threshold=float(payload["default_threshold"]),
            margin_threshold=float(payload["margin_threshold"]),
            context_penalty=float(payload["context_penalty"]),
            context_floor=None if payload.get("context_floor") is None else float(payload["context_floor"]),
            confusers={word: {other: float(limit) for other, limit in pairs.items()} for word, pairs in confusers.items()},
        )
        if (not 0.25 <= policy.temperature <= 4 or not 0 < policy.context_penalty <= 1
                or any(not 0.3 <= value <= 0.99 for value in policy.thresholds.values())
                or (policy.context_floor is not None and not 0.2 <= policy.context_floor <= policy.default_threshold)
                or any(not 0 < limit < 1 for pairs in policy.confusers.values() for limit in pairs.values())):
            raise ValueError("Decision policy parameters are out of range")
        return policy

    def calibrate(self, probabilities: np.ndarray) -> np.ndarray:
        logits = np.log(np.clip(np.asarray(probabilities, dtype=np.float64), 1e-12, 1.0))
        logits = logits + np.array([self.bias.get(label, 0.0) for label in self.labels])
        logits = logits / self.temperature
        exponentials = np.exp(logits - logits.max())
        return exponentials / exponentials.sum()

    def context_fit(self, context_words: Sequence[str], candidates: Sequence[str]) -> Optional[dict[str, bool]]:
        """Which candidates can continue the sentence; None when context says nothing."""
        known = {_key(label) for label in self.labels if label != IDLE_LABEL}
        prefix = tuple(word for word in (_key(item) for item in context_words) if word in known)[-MAX_CONTEXT_WORDS:]
        if not prefix:
            return None
        vocabulary = tuple(sorted(known))
        # An already-broken sentence cannot rank the next word.
        if not can_continue(prefix, vocabulary):
            return None
        return {label: can_continue(prefix + (_key(label),), vocabulary, CONTINUATION_DEPTH)
                for label in candidates}

    def decide(self, probabilities: Sequence[float], context_words: Sequence[str] = ()) -> tuple[BackendPrediction, tuple[str, ...]]:
        raw = np.asarray(probabilities, dtype=np.float64)
        if raw.shape != (len(self.labels),) or not np.isfinite(raw).all():
            raise ValueError("Probability vector does not match the policy labels")
        adjusted: list[str] = []
        calibrated = bool(self.bias) or not math.isclose(self.temperature, 1.0)
        values = self.calibrate(raw) if calibrated else raw / raw.sum()
        if calibrated:
            adjusted.append("calibrated")
        order = [int(index) for index in np.argsort(values)[::-1]]
        words = [self.labels[index] for index in order if self.labels[index] != IDLE_LABEL][:3]
        fit = self.context_fit(context_words, words) if context_words else None
        if fit is not None and any(fit.values()) and not all(fit.values()):
            penalty = np.ones_like(values)
            for word, ok in fit.items():
                if not ok:
                    penalty[self.labels.index(word)] = self.context_penalty
            if self.context_penalty < 1:
                values = values * penalty
                values = values / values.sum()
                order = [int(index) for index in np.argsort(values)[::-1]]
            adjusted.append("context")
        top_k = [BackendCandidate(self.labels[index], float(values[index]))
                 for index in order if self.labels[index] != IDLE_LABEL][:3]
        winner = self.labels[order[0]]
        confidence = float(values[order[0]])
        margin = confidence - float(values[order[1]]) if len(order) > 1 else confidence
        threshold = self.thresholds.get(winner, self.default_threshold)
        accepted = winner != IDLE_LABEL and confidence >= threshold and margin >= self.margin_threshold
        vetoed = any(values[self.labels.index(other)] >= limit and not (fit is not None and fit.get(other) is False)
                     for other, limit in self.confusers.get(winner, {}).items())
        if vetoed:
            accepted = False
        if not accepted and not vetoed and winner != IDLE_LABEL and fit is not None and self.context_floor is not None:
            # Context vouches for a weak winner only when it is the sole grammatical top-3 word.
            grammatical = [word for word, ok in fit.items() if ok]
            accepted = grammatical == [winner] and confidence >= self.context_floor
            if accepted and "context" not in adjusted:
                adjusted.append("context")
        if not accepted:
            return BackendPrediction(PredictionStatus.UNCERTAIN, None, None, top_k), tuple(adjusted)
        return BackendPrediction(PredictionStatus.OK, top_k[0].label, top_k[0].confidence, top_k), tuple(adjusted)
