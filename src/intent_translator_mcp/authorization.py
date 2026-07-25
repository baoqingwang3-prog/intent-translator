"""Process-local, action-bound confirmation receipts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Any


_RECEIPT_SECRET = secrets.token_bytes(32)
_DEFAULT_TTL_SECONDS = 300
_CONSUMED_NONCES: set[str] = set()
_CONSUMED_LOCK = threading.Lock()


def action_digest(action: str, scope: str) -> str:
    canonical = " ".join(action.casefold().split())
    return hashlib.sha256(f"{scope}\n{canonical}".encode("utf-8")).hexdigest()


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_confirmation_receipt(
    action: str,
    scope: str,
    *,
    grants: list[str],
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    now = int(time.time())
    payload = {
        "v": 1,
        "action": action_digest(action, scope),
        "scope": scope,
        "grants": sorted(set(grants)),
        "iat": now,
        "exp": now + max(30, min(ttl_seconds, 900)),
        "nonce": secrets.token_urlsafe(12),
    }
    encoded = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _encode(hmac.new(_RECEIPT_SECRET, encoded.encode("ascii"), hashlib.sha256).digest())
    return {
        "receipt": f"{encoded}.{signature}",
        "action_digest": payload["action"],
        "scope": scope,
        "grants": payload["grants"],
        "expires_at_unix": payload["exp"],
    }


def verify_confirmation_receipt(
    receipt: str,
    action: str,
    scope: str,
    *,
    required_grants: list[str],
    consume: bool = False,
) -> dict[str, Any]:
    if not receipt:
        return {"verified": False, "reason": "missing receipt"}
    try:
        encoded, supplied_signature = receipt.split(".", 1)
        expected_signature = _encode(
            hmac.new(_RECEIPT_SECRET, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return {"verified": False, "reason": "invalid signature"}
        payload = json.loads(_decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError):
        return {"verified": False, "reason": "malformed receipt"}

    if int(payload.get("exp", 0)) < int(time.time()):
        return {"verified": False, "reason": "expired receipt"}
    if payload.get("scope") != scope:
        return {"verified": False, "reason": "scope mismatch"}
    if payload.get("action") != action_digest(action, scope):
        return {"verified": False, "reason": "action mismatch"}
    grants = set(payload.get("grants", []))
    if not set(required_grants).issubset(grants):
        return {"verified": False, "reason": "grant mismatch"}
    nonce = str(payload.get("nonce", ""))
    if not nonce:
        return {"verified": False, "reason": "missing nonce"}
    with _CONSUMED_LOCK:
        if nonce in _CONSUMED_NONCES:
            return {"verified": False, "reason": "receipt already consumed"}
        if consume:
            _CONSUMED_NONCES.add(nonce)
    return {
        "verified": True,
        "reason": "action-bound confirmation receipt verified",
        "grants": sorted(grants),
        "expires_at_unix": int(payload["exp"]),
        "single_use": True,
    }
