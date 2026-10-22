"""Short-lived signed tokens for runtimes that cannot read the platform database.

The Mac runtime issues a token to a signed-in user; a GPU runtime elsewhere (Modal)
verifies it with the shared secret alone, without a database lookup.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Optional

INFERENCE_TOKEN_AUDIENCE = "inference"
INFERENCE_TOKEN_TTL_SECONDS = 10 * 60


@dataclass(frozen=True)
class InferenceTokenClaims:
    workspace_id: str
    user_id: str
    expires_at: int

    def expired(self, now: Optional[float] = None) -> bool:
        return (time.time() if now is None else now) >= self.expires_at


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(secret: str, body: str) -> str:
    return _encode(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())


def issue_inference_token(secret: str, workspace_id: str, user_id: str,
                          ttl_seconds: int = INFERENCE_TOKEN_TTL_SECONDS,
                          now: Optional[float] = None) -> tuple[str, int]:
    expires_at = int(time.time() if now is None else now) + ttl_seconds
    payload = {"aud": INFERENCE_TOKEN_AUDIENCE, "ws": workspace_id, "uid": user_id, "exp": expires_at}
    body = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{body}.{_sign(secret, body)}", expires_at


def verify_inference_token(secret: str, token: Optional[str], workspace_id: str,
                           now: Optional[float] = None) -> Optional[InferenceTokenClaims]:
    """Claims for a valid, unexpired token of this workspace; None for anything else."""
    if not secret or not token or len(token) > 1024 or token.count(".") != 1:
        return None
    body, signature = token.split(".")
    try:
        if not hmac.compare_digest(_sign(secret, body), signature):
            return None
        payload = json.loads(_decode(body))
        claims = InferenceTokenClaims(
            workspace_id=payload["ws"], user_id=payload["uid"], expires_at=int(payload["exp"]),
        )
        audience = payload["aud"]
    except (ValueError, KeyError, TypeError, UnicodeError):
        return None
    if audience != INFERENCE_TOKEN_AUDIENCE or claims.workspace_id != workspace_id or claims.expired(now):
        return None
    return claims
