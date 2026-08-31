"""Action-bound confirmation receipts that survive restarts and extra processes.

A receipt authorizes exactly one action: it is signed over the scope, the normalized
action text, and the granted capabilities, expires quickly, and can be consumed once.

Signing keys and the consumed-receipt ledger are shared through the local data
directory so that a receipt issued by one process is still verifiable by another and
after a restart. The signing key is not a confidentiality boundary against a local
user who can already execute this package; it prevents a caller that only sees the
API surface, such as a model returning an invented string, from forging one.

When no shared location is usable the module degrades to a process-local key and
ledger. That keeps single-process installs working, but a receipt then dies with the
process, so deployments running more than one worker must provide a shared secret or
a writable data directory. `receipt_backend_status()` reports which mode is active.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Protocol


_DEFAULT_TTL_SECONDS = 300
_MAX_TTL_SECONDS = 900
_MIN_TTL_SECONDS = 30
_MINIMUM_SECRET_BYTES = 32

_STATE_LOCK = threading.Lock()
_PROCESS_SECRET = secrets.token_bytes(_MINIMUM_SECRET_BYTES)
_CACHE: dict[str, Any] = {}


def action_digest(action: str, scope: str) -> str:
    canonical = " ".join(action.casefold().split())
    return hashlib.sha256(f"{scope}\n{canonical}".encode("utf-8")).hexdigest()


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _key_id(secret: bytes) -> str:
    return hashlib.sha256(b"intent-translator-receipt-key\x00" + secret).hexdigest()[:16]


def _data_dir(env: Mapping[str, str]) -> Path:
    configured = str(env.get("INTENT_TRANSLATOR_DATA_DIR", "")).strip()
    if configured:
        return Path(configured).expanduser()
    return Path(env.get("INTENT_TRANSLATOR_HOME", "") or Path.home()).expanduser() / ".intent-translator"


def _decode_configured_secret(raw: str) -> bytes | None:
    candidate = raw.strip()
    if not candidate:
        return None
    for decoder in (bytes.fromhex, _decode):
        try:
            material = decoder(candidate)
        except (ValueError, binascii.Error):
            continue
        if len(material) >= _MINIMUM_SECRET_BYTES:
            return material
    encoded = candidate.encode("utf-8")
    return encoded if len(encoded) >= _MINIMUM_SECRET_BYTES else None


def _load_or_create_key_file(path: Path) -> bytes | None:
    try:
        if path.is_file():
            material = _decode_configured_secret(path.read_text(encoding="utf-8"))
            if material:
                return material
        path.parent.mkdir(parents=True, exist_ok=True)
        material = secrets.token_bytes(_MINIMUM_SECRET_BYTES)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, material.hex().encode("ascii"))
        finally:
            os.close(descriptor)
        return material
    except FileExistsError:
        try:
            return _decode_configured_secret(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            return None
    except (OSError, UnicodeError):
        return None


class ReceiptLedger(Protocol):
    """Records single-use receipt identifiers."""

    shared: bool

    def consume(self, nonce: str, expires_at: int) -> bool:
        """Claim `nonce` and return False when it was already claimed."""

    def seen(self, nonce: str) -> bool:
        """Report whether `nonce` was already claimed."""


class MemoryReceiptLedger:
    """Process-local ledger. A receipt cannot outlive the issuing process."""

    shared = False

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._consumed: dict[str, int] = {}

    def _expire(self, now: int) -> None:
        for nonce, expires_at in list(self._consumed.items()):
            if expires_at < now:
                del self._consumed[nonce]

    def consume(self, nonce: str, expires_at: int) -> bool:
        now = int(time.time())
        with self._lock:
            self._expire(now)
            if nonce in self._consumed:
                return False
            self._consumed[nonce] = expires_at
            return True

    def seen(self, nonce: str) -> bool:
        with self._lock:
            self._expire(int(time.time()))
            return nonce in self._consumed


class SqliteReceiptLedger:
    """Ledger shared by every process using the same data directory."""

    shared = True

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._prepare()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _prepare(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS consumed_receipts (
                    nonce TEXT PRIMARY KEY,
                    expires_at INTEGER NOT NULL
                )
                """
            )
        finally:
            connection.close()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def consume(self, nonce: str, expires_at: int) -> bool:
        now = int(time.time())
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("DELETE FROM consumed_receipts WHERE expires_at < ?", (now,))
                try:
                    connection.execute(
                        "INSERT INTO consumed_receipts(nonce, expires_at) VALUES (?, ?)",
                        (nonce, expires_at),
                    )
                except sqlite3.IntegrityError:
                    return False
                return True
            finally:
                connection.close()

    def seen(self, nonce: str) -> bool:
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT 1 FROM consumed_receipts WHERE nonce = ? AND expires_at >= ?",
                    (nonce, int(time.time())),
                ).fetchone()
                return row is not None
            finally:
                connection.close()


def _build_state(env: Mapping[str, str]) -> dict[str, Any]:
    configured = _decode_configured_secret(env.get("INTENT_TRANSLATOR_RECEIPT_SECRET", ""))
    previous = _decode_configured_secret(env.get("INTENT_TRANSLATOR_RECEIPT_SECRET_PREVIOUS", ""))
    data_dir = _data_dir(env)
    source = "configured-secret"
    active = configured
    if active is None:
        active = _load_or_create_key_file(data_dir / "receipt-key")
        source = "shared-key-file"
    if active is None:
        active = _PROCESS_SECRET
        source = "process-local"

    ledger: ReceiptLedger
    if source == "process-local":
        ledger = MemoryReceiptLedger()
    else:
        try:
            ledger = SqliteReceiptLedger(data_dir / "receipts.db")
        except sqlite3.Error:
            ledger = MemoryReceiptLedger()

    keys = {_key_id(active): active}
    if previous is not None:
        keys.setdefault(_key_id(previous), previous)
    return {
        "active_secret": active,
        "active_kid": _key_id(active),
        "keys": keys,
        "source": source,
        "ledger": ledger,
        "data_dir": data_dir,
        "rotation_ready": previous is not None,
    }


def _state() -> dict[str, Any]:
    env = dict(os.environ)
    fingerprint = (
        env.get("INTENT_TRANSLATOR_RECEIPT_SECRET", ""),
        env.get("INTENT_TRANSLATOR_RECEIPT_SECRET_PREVIOUS", ""),
        env.get("INTENT_TRANSLATOR_DATA_DIR", ""),
        env.get("INTENT_TRANSLATOR_HOME", ""),
        str(Path.home()),
    )
    with _STATE_LOCK:
        if _CACHE.get("fingerprint") != fingerprint:
            _CACHE.clear()
            _CACHE["fingerprint"] = fingerprint
            _CACHE["state"] = _build_state(env)
        return _CACHE["state"]


def reset_receipt_state() -> None:
    """Drop cached keys and ledger. Intended for tests and after key rotation."""
    with _STATE_LOCK:
        _CACHE.clear()


def receipt_backend_status() -> dict[str, Any]:
    """Report whether receipts survive restarts and additional processes."""
    state = _state()
    ledger = state["ledger"]
    shared = state["source"] != "process-local" and bool(getattr(ledger, "shared", False))
    return {
        "key_source": state["source"],
        "key_id": state["active_kid"],
        "ledger": type(ledger).__name__,
        "shared_across_processes": shared,
        "survives_restart": shared,
        "rotation_ready": bool(state["rotation_ready"]),
        "verifiable_key_count": len(state["keys"]),
        "warning": (
            ""
            if shared
            else "receipts are process-local; a restart or a second worker invalidates them"
        ),
    }


def issue_confirmation_receipt(
    action: str,
    scope: str,
    *,
    grants: list[str],
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    actor: str = "",
) -> dict[str, Any]:
    state = _state()
    now = int(time.time())
    payload = {
        "v": 2,
        "kid": state["active_kid"],
        "action": action_digest(action, scope),
        "scope": scope,
        "grants": sorted(set(grants)),
        "sub": " ".join(actor.split()),
        "iat": now,
        "exp": now + max(_MIN_TTL_SECONDS, min(ttl_seconds, _MAX_TTL_SECONDS)),
        "nonce": secrets.token_urlsafe(12),
    }
    encoded = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _encode(
        hmac.new(state["active_secret"], encoded.encode("ascii"), hashlib.sha256).digest()
    )
    return {
        "receipt": f"{encoded}.{signature}",
        "action_digest": payload["action"],
        "scope": scope,
        "grants": payload["grants"],
        "actor": payload["sub"],
        "key_id": payload["kid"],
        "expires_at_unix": payload["exp"],
        "single_use": True,
        "shared_across_processes": receipt_backend_status()["shared_across_processes"],
    }


def verify_confirmation_receipt(
    receipt: str,
    action: str,
    scope: str,
    *,
    required_grants: list[str],
    consume: bool = False,
    actor: str = "",
) -> dict[str, Any]:
    if not receipt:
        return {"verified": False, "reason": "missing receipt"}
    state = _state()
    try:
        encoded, supplied_signature = receipt.split(".", 1)
        payload = json.loads(_decode(encoded).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("receipt payload must be an object")
    except (ValueError, UnicodeError, binascii.Error, json.JSONDecodeError):
        return {"verified": False, "reason": "malformed receipt"}

    candidates = state["keys"]
    key_id = str(payload.get("kid", ""))
    secrets_to_try = [candidates[key_id]] if key_id in candidates else list(candidates.values())
    if not any(
        hmac.compare_digest(
            supplied_signature,
            _encode(hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest()),
        )
        for secret in secrets_to_try
    ):
        return {"verified": False, "reason": "invalid signature"}

    if int(payload.get("exp", 0)) < int(time.time()):
        return {"verified": False, "reason": "expired receipt"}
    if payload.get("scope") != scope:
        return {"verified": False, "reason": "scope mismatch"}
    if payload.get("action") != action_digest(action, scope):
        return {"verified": False, "reason": "action mismatch"}
    grants = set(payload.get("grants", []))
    if not set(required_grants).issubset(grants):
        return {"verified": False, "reason": "grant mismatch"}
    subject = str(payload.get("sub", ""))
    if subject and subject != " ".join(actor.split()):
        return {"verified": False, "reason": "actor mismatch"}
    nonce = str(payload.get("nonce", ""))
    if not nonce:
        return {"verified": False, "reason": "missing nonce"}

    ledger: ReceiptLedger = state["ledger"]
    if consume:
        if not ledger.consume(nonce, int(payload["exp"])):
            return {"verified": False, "reason": "receipt already consumed"}
    elif ledger.seen(nonce):
        return {"verified": False, "reason": "receipt already consumed"}

    return {
        "verified": True,
        "reason": "action-bound confirmation receipt verified",
        "grants": sorted(grants),
        "actor": subject,
        "actor_bound": bool(subject),
        "expires_at_unix": int(payload["exp"]),
        "single_use": True,
    }
