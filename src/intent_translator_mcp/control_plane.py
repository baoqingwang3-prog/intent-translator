"""Fail-closed execution admission for one compiled intent envelope."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field


class ClaimLevel(StrEnum):
    READ_ONLY_FORM = "READ_ONLY_FORM"
    ACTION_AUTHORIZED = "ACTION_AUTHORIZED"
    ONE_SEND_AUTHORIZED = "ONE_SEND_AUTHORIZED"
    EXECUTION_AUTHORIZED = "EXECUTION_AUTHORIZED"


class ControlState(StrEnum):
    ADMITTED = "ADMITTED"
    RUNNING = "RUNNING"
    WAITING_AUTH = "WAITING_AUTH"
    FENCE_MISMATCH = "FENCE_MISMATCH"
    BINDING_ERROR = "BINDING_ERROR"
    TOOL_ERROR = "TOOL_ERROR"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class ExecutionEnvelope(BaseModel):
    """Immutable identity shared by admission, claims, and evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    goal_id: str = Field(min_length=1, max_length=200)
    task_id: str = Field(min_length=1, max_length=200)
    dedupe_key: str = Field(min_length=1, max_length=200)
    frame_id: str = Field(min_length=1, max_length=200)
    object: str = Field(min_length=1, max_length=4000)
    operation: str = Field(min_length=1, max_length=100)
    effect: str = Field(min_length=1, max_length=100)
    destination: str = Field(min_length=1, max_length=4000)
    data_class: str = Field(min_length=1, max_length=100)
    authorization_id: str = Field(min_length=1, max_length=200)
    owner_thread: str = Field(min_length=1, max_length=200)
    generation: int = Field(ge=1)
    provenance: tuple[str, ...] = Field(min_length=1, max_length=50)
    claim_level: ClaimLevel = ClaimLevel.READ_ONLY_FORM
    state: ControlState = ControlState.ADMITTED
    reason_code: str = Field(min_length=1, max_length=200)
    required_artifacts: tuple[str, ...] = Field(default_factory=tuple, max_length=50)
    cannot_prove: tuple[str, ...] = Field(default_factory=tuple, max_length=50)


class OwnerLease(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dedupe_key: str = Field(min_length=1)
    owner_thread: str = Field(min_length=1)
    generation: int = Field(ge=1)
    lease_epoch: int = Field(ge=1)
    fence_token: str = Field(min_length=16)
    last_heartbeat: datetime
    expires_at: datetime


class ExecutionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command: str = ""
    session: str = ""
    pid: int | None = Field(default=None, ge=1)
    artifact: str = ""
    artifact_sha256: str = Field(default="", pattern=r"^[a-fA-F0-9]{64}$|^$")
    true_exit: int | None = None
    cannot_prove: tuple[str, ...] = Field(default_factory=tuple, max_length=50)


class ControlSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    envelope: ExecutionEnvelope
    state: ControlState
    lease: OwnerLease | None = None
    reason_code: str
    next_action: str


class AdmissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    envelope: ExecutionEnvelope
    state: ControlState
    admitted: bool
    execute: bool
    reason_code: str
    next_action: str
    lease: OwnerLease | None = None
    claim_level: ClaimLevel = ClaimLevel.READ_ONLY_FORM
    evidence: ExecutionEvidence | None = None
    completed: bool = False

    def snapshot(self) -> ControlSnapshot:
        return ControlSnapshot(
            envelope=self.envelope,
            state=self.state,
            lease=self.lease,
            reason_code=self.reason_code,
            next_action=self.next_action,
        )


@dataclass
class _Record:
    generation: int
    lease_epoch: int
    lease: OwnerLease | None
    state: ControlState


_CLAIM_ORDER = {
    ClaimLevel.READ_ONLY_FORM: 0,
    ClaimLevel.ACTION_AUTHORIZED: 1,
    ClaimLevel.ONE_SEND_AUTHORIZED: 2,
    ClaimLevel.EXECUTION_AUTHORIZED: 3,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _envelope_digest(envelope: ExecutionEnvelope) -> str:
    identity = {
        key: value
        for key, value in envelope.model_dump(mode="json").items()
        if key not in {"claim_level", "state", "reason_code"}
    }
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _frame_digest(envelope: ExecutionEnvelope) -> str:
    identity = {
        key: value
        for key, value in envelope.model_dump(mode="json").items()
        if key not in {"authorization_id", "claim_level", "provenance", "state", "reason_code"}
    }
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ControlPlane:
    """Single-writer admission and evidence validation behind one small interface."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _utcnow,
        secret: bytes | None = None,
        state_path: Path | str | None = None,
    ) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._state_path = Path(state_path).resolve() if state_path is not None else None
        self._memory_connection: sqlite3.Connection | None = None
        if self._state_path is None:
            self._memory_connection = self._open_connection(":memory:")
        else:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._secret = self._initialize_store(secret)

    def close(self) -> None:
        with self._lock:
            connection = self._memory_connection
            self._memory_connection = None
            if connection is not None:
                connection.close()

    def __enter__(self) -> ControlPlane:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def admit(
        self,
        envelope: ExecutionEnvelope,
        *,
        lease: OwnerLease | None = None,
        claim: str = "",
        lease_ttl_seconds: int = 60,
    ) -> AdmissionDecision:
        now = self._clock()
        with self._transaction() as connection:
            record = self._load_record(connection, envelope.dedupe_key)
            if record is None:
                if lease is not None:
                    return self._rejected(envelope, "FENCE_MISMATCH", ControlState.FENCE_MISMATCH)
                acquired = self._new_lease(envelope, lease_epoch=1, now=now, ttl=lease_ttl_seconds)
                self._save_record(connection, envelope.dedupe_key, _Record(
                    generation=envelope.generation,
                    lease_epoch=1,
                    lease=acquired,
                    state=ControlState.RUNNING,
                ))
                return self._accepted(envelope, acquired, reason_code="LEASE_ACQUIRED")

            if record.state in {ControlState.COMPLETED, ControlState.FAILED}:
                return self._rejected(
                    envelope,
                    "TERMINAL_STATE",
                    record.state,
                    next_action="create a new generation for any follow-up action",
                    lease=record.lease,
                )
            if record.state == ControlState.EXPIRED:
                return self._rejected(
                    envelope,
                    "LEASE_EXPIRED_REVIEW_REQUIRED",
                    ControlState.EXPIRED,
                    next_action="review the expired owner before recovery",
                )
            if record.lease and now >= record.lease.expires_at:
                record.state = ControlState.EXPIRED
                self._save_record(connection, envelope.dedupe_key, record)
                return self._rejected(
                    envelope,
                    "LEASE_EXPIRED_REVIEW_REQUIRED",
                    ControlState.EXPIRED,
                    next_action="review the expired owner before recovery",
                )
            if envelope.generation != record.generation:
                return self._rejected(envelope, "FENCE_MISMATCH", ControlState.FENCE_MISMATCH)

            if record.lease is None:
                if record.state != ControlState.VERIFYING:
                    return self._rejected(envelope, "FENCE_MISMATCH", ControlState.FENCE_MISMATCH)
                acquired = self._new_lease(
                    envelope,
                    lease_epoch=record.lease_epoch + 1,
                    now=now,
                    ttl=lease_ttl_seconds,
                )
                record.lease_epoch = acquired.lease_epoch
                record.lease = acquired
                record.state = ControlState.RUNNING
                self._save_record(connection, envelope.dedupe_key, record)
                return self._accepted(envelope, acquired, reason_code="RECOVERY_LEASE_ACQUIRED")

            if envelope.owner_thread != record.lease.owner_thread:
                return self._rejected(
                    envelope,
                    "OWNER_CONFLICT",
                    ControlState.WAITING_AUTH,
                    next_action="wait for the active owner or invalidate it after review",
                    lease=record.lease,
                )
            if lease is None or not self._lease_matches(lease, record.lease):
                return self._rejected(envelope, "FENCE_MISMATCH", ControlState.FENCE_MISMATCH)
            if not claim:
                renewed = record.lease.model_copy(
                    update={
                        "last_heartbeat": now,
                        "expires_at": now
                        + timedelta(seconds=max(1, min(lease_ttl_seconds, 3600))),
                    }
                )
                record.lease = renewed
                record.state = ControlState.RUNNING
                self._save_record(connection, envelope.dedupe_key, record)
                return self._accepted(envelope, renewed, reason_code="LEASE_CONFIRMED")

            verified = self._verify_claim(connection, claim, envelope, record.lease, now)
            if verified["reason_code"] != "CLAIM_ACCEPTED":
                state = (
                    ControlState.FENCE_MISMATCH
                    if verified["reason_code"] == "FENCE_MISMATCH"
                    else ControlState.BINDING_ERROR
                )
                return self._rejected(envelope, verified["reason_code"], state)
            level = ClaimLevel(verified["claim_level"])
            record.state = ControlState.RUNNING
            self._save_record(connection, envelope.dedupe_key, record)
            updated = envelope.model_copy(
                update={
                    "claim_level": level,
                    "state": ControlState.RUNNING,
                    "reason_code": "CLAIM_ACCEPTED",
                }
            )
            return AdmissionDecision(
                envelope=updated,
                state=ControlState.RUNNING,
                admitted=True,
                execute=_CLAIM_ORDER[level] >= _CLAIM_ORDER[ClaimLevel.ACTION_AUTHORIZED],
                reason_code="CLAIM_ACCEPTED",
                next_action="execute only the bound frame and record evidence",
                lease=record.lease,
                claim_level=level,
            )

    def issue_claim(
        self,
        decision: AdmissionDecision,
        claim_level: ClaimLevel,
        *,
        ttl_seconds: int = 300,
    ) -> str:
        if not decision.admitted or decision.lease is None:
            raise ValueError("an active admitted lease is required")
        if claim_level == ClaimLevel.READ_ONLY_FORM:
            raise ValueError("read-only form does not require an authorization claim")
        with self._transaction() as connection:
            record = self._load_record(connection, decision.envelope.dedupe_key)
            if (
                record is None
                or record.state != ControlState.RUNNING
                or record.lease is None
                or record.generation != decision.envelope.generation
                or not self._lease_matches(decision.lease, record.lease)
            ):
                raise ValueError("the admission decision is stale")
            existing = connection.execute(
                "SELECT 1 FROM issued_claims WHERE dedupe_key = ? AND generation = ? AND claim_level = ?",
                (
                    decision.envelope.dedupe_key,
                    decision.envelope.generation,
                    claim_level.value,
                ),
            ).fetchone()
            if existing:
                raise ValueError("that claim level was already issued for this generation")
            now = int(self._clock().timestamp())
            payload = {
                "v": 1,
                "envelope": _envelope_digest(decision.envelope),
                "dedupe_key": decision.envelope.dedupe_key,
                "generation": decision.envelope.generation,
                "lease_epoch": decision.lease.lease_epoch,
                "fence_token": decision.lease.fence_token,
                "claim_level": claim_level.value,
                "iat": now,
                "exp": now + max(30, min(ttl_seconds, 900)),
                "nonce": secrets.token_urlsafe(12),
            }
            encoded = _encode(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )
            signature = _encode(
                hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest()
            )
            connection.execute(
                "INSERT INTO issued_claims(dedupe_key, generation, claim_level) VALUES (?, ?, ?)",
                (
                    decision.envelope.dedupe_key,
                    decision.envelope.generation,
                    claim_level.value,
                ),
            )
            return f"{encoded}.{signature}"

    def authorize(
        self,
        envelope: ExecutionEnvelope,
        claim_level: ClaimLevel,
        *,
        continuation_receipt: str = "",
        lease_ttl_seconds: int = 300,
    ) -> AdmissionDecision:
        """Admit one envelope and consume only a server-selected claim level."""
        if continuation_receipt:
            previous = self.open_admission_receipt(continuation_receipt)
            if previous.lease is None or _frame_digest(previous.envelope) != _frame_digest(envelope):
                return self._rejected(
                    envelope,
                    "CONTINUATION_BINDING_MISMATCH",
                    ControlState.BINDING_ERROR,
                )
            admitted = self.admit(
                envelope,
                lease=previous.lease,
                lease_ttl_seconds=lease_ttl_seconds,
            )
        else:
            admitted = self.admit(envelope, lease_ttl_seconds=lease_ttl_seconds)
        if not admitted.admitted or claim_level == ClaimLevel.READ_ONLY_FORM:
            return admitted
        claim = self.issue_claim(admitted, claim_level)
        return self.admit(
            envelope,
            lease=admitted.lease,
            claim=claim,
            lease_ttl_seconds=lease_ttl_seconds,
        )

    def wait_for_authorization(self, decision: AdmissionDecision) -> AdmissionDecision:
        """Keep the fenced owner visible while refusing execution pending confirmation."""
        if not decision.admitted or decision.lease is None:
            return decision
        with self._transaction() as connection:
            record = self._load_record(connection, decision.envelope.dedupe_key)
            if (
                record is None
                or record.lease is None
                or record.generation != decision.envelope.generation
                or not self._lease_matches(decision.lease, record.lease)
            ):
                return self._rejected(
                    decision.envelope,
                    "FENCE_MISMATCH",
                    ControlState.FENCE_MISMATCH,
                )
            record.state = ControlState.WAITING_AUTH
            self._save_record(connection, decision.envelope.dedupe_key, record)
        updated = decision.envelope.model_copy(
            update={
                "state": ControlState.WAITING_AUTH,
                "reason_code": "WAITING_ACTION_CONFIRMATION",
            }
        )
        return AdmissionDecision(
            envelope=updated,
            state=ControlState.WAITING_AUTH,
            admitted=True,
            execute=False,
            reason_code="WAITING_ACTION_CONFIRMATION",
            next_action="obtain an action-bound confirmation receipt",
            lease=decision.lease,
            claim_level=ClaimLevel.READ_ONLY_FORM,
        )

    def seal_admission_receipt(
        self,
        decision: AdmissionDecision,
        *,
        ttl_seconds: int = 3600,
    ) -> str:
        return self._seal_receipt(
            "admission",
            decision.model_dump(mode="json"),
            ttl_seconds=ttl_seconds,
        )

    def open_admission_receipt(self, receipt: str) -> AdmissionDecision:
        return AdmissionDecision.model_validate(self._open_receipt(receipt, "admission"))

    def seal_resume_receipt(
        self,
        decision: AdmissionDecision,
        *,
        ttl_seconds: int = 86400,
    ) -> str:
        return self._seal_receipt(
            "resume",
            decision.snapshot().model_dump(mode="json"),
            ttl_seconds=ttl_seconds,
        )

    def record_receipt(
        self,
        admission_receipt: str,
        evidence: ExecutionEvidence,
    ) -> AdmissionDecision:
        return self.record(self.open_admission_receipt(admission_receipt), evidence)

    def resume_receipt(self, resume_receipt: str) -> AdmissionDecision:
        snapshot = ControlSnapshot.model_validate(self._open_receipt(resume_receipt, "resume"))
        return self.resume(snapshot)

    def invalidate(
        self,
        decision: AdmissionDecision,
        *,
        reason_code: str,
        next_action: str,
    ) -> AdmissionDecision:
        with self._transaction() as connection:
            record = self._load_record(connection, decision.envelope.dedupe_key)
            stale = bool(
                record is None
                or record.generation != decision.envelope.generation
                or (
                    record.lease is not None
                    and (
                        decision.lease is None
                        or not self._lease_matches(decision.lease, record.lease)
                    )
                )
                or (record.lease is None and decision.lease is not None)
            )
            if stale:
                current_generation = record.generation if record else decision.envelope.generation
                current = decision.envelope.model_copy(
                    update={"generation": current_generation}
                )
                return self._rejected(
                    current,
                    "STALE_INVALIDATION",
                    ControlState.FENCE_MISMATCH,
                    next_action="use only the current generation decision",
                )
            generation = max(decision.envelope.generation, record.generation if record else 0) + 1
            lease_epoch = record.lease_epoch if record else 0
            self._save_record(connection, decision.envelope.dedupe_key, _Record(
                generation=generation,
                lease_epoch=lease_epoch,
                lease=None,
                state=ControlState.VERIFYING,
            ))
            updated = decision.envelope.model_copy(
                update={
                    "generation": generation,
                    "claim_level": ClaimLevel.READ_ONLY_FORM,
                    "state": ControlState.VERIFYING,
                    "reason_code": reason_code,
                }
            )
            return AdmissionDecision(
                envelope=updated,
                state=ControlState.VERIFYING,
                admitted=False,
                execute=False,
                reason_code=reason_code,
                next_action=next_action,
                claim_level=ClaimLevel.READ_ONLY_FORM,
            )

    def resume(self, snapshot: ControlSnapshot) -> AdmissionDecision:
        with self._transaction() as connection:
            current = self._load_record(connection, snapshot.envelope.dedupe_key)
            if current and snapshot.envelope.generation != current.generation:
                stale = snapshot.envelope.model_copy(update={"generation": current.generation})
                return self._rejected(
                    stale,
                    "STALE_SNAPSHOT",
                    ControlState.FENCE_MISMATCH,
                    next_action="use only the current generation snapshot",
                )
            generation = max(
                snapshot.envelope.generation,
                current.generation if current else 0,
            ) + 1
            lease_epoch = max(
                snapshot.lease.lease_epoch if snapshot.lease else 0,
                current.lease_epoch if current else 0,
            )
            updated = snapshot.envelope.model_copy(
                update={
                    "generation": generation,
                    "claim_level": ClaimLevel.READ_ONLY_FORM,
                    "state": ControlState.VERIFYING,
                    "reason_code": "RECOVERY_REVIEW_REQUIRED",
                }
            )
            self._save_record(connection, updated.dedupe_key, _Record(
                generation=generation,
                lease_epoch=lease_epoch,
                lease=None,
                state=ControlState.VERIFYING,
            ))
            return AdmissionDecision(
                envelope=updated,
                state=ControlState.VERIFYING,
                admitted=False,
                execute=False,
                reason_code="RECOVERY_REVIEW_REQUIRED",
                next_action="review the snapshot and acquire a new fenced lease",
                claim_level=ClaimLevel.READ_ONLY_FORM,
            )

    def record(
        self,
        decision: AdmissionDecision,
        evidence: ExecutionEvidence,
    ) -> AdmissionDecision:
        with self._transaction() as connection:
            record = self._load_record(connection, decision.envelope.dedupe_key)
            current = bool(
                record
                and record.state == ControlState.RUNNING
                and record.lease
                and decision.lease
                and record.generation == decision.envelope.generation
                and self._lease_matches(decision.lease, record.lease)
            )
            if not current:
                state, reason_code, completed = (
                    ControlState.FENCE_MISMATCH,
                    "LATE_EVIDENCE_REJECTED",
                    False,
                )
            elif not decision.execute:
                state, reason_code, completed = (
                    ControlState.EVIDENCE_MISSING,
                    "EXECUTION_NOT_AUTHORIZED",
                    False,
                )
            elif decision.envelope.cannot_prove or evidence.cannot_prove:
                state, reason_code, completed = (
                    ControlState.EVIDENCE_MISSING,
                    "CANNOT_PROVE_PRESENT",
                    False,
                )
            elif not all(
                (
                    evidence.command,
                    evidence.session,
                    evidence.pid,
                    evidence.artifact,
                    evidence.artifact_sha256,
                )
            ) or evidence.true_exit is None:
                state, reason_code, completed = (
                    ControlState.EVIDENCE_MISSING,
                    "EVIDENCE_FIELDS_MISSING",
                    False,
                )
            elif evidence.true_exit != 0:
                state, reason_code, completed = (
                    ControlState.FAILED,
                    "EXECUTION_FAILED",
                    False,
                )
            else:
                state, reason_code, completed = (
                    ControlState.COMPLETED,
                    "EVIDENCE_VERIFIED",
                    True,
                )
            if current and record:
                record.state = state
                self._save_record(connection, decision.envelope.dedupe_key, record)
            return self._evidence_decision(
                decision,
                evidence,
                state=state,
                reason_code=reason_code,
                completed=completed,
            )

    @staticmethod
    def _open_connection(target: str) -> sqlite3.Connection:
        connection = sqlite3.connect(
            target,
            timeout=5,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _connect(self) -> tuple[sqlite3.Connection, bool]:
        if self._memory_connection is not None:
            return self._memory_connection, False
        if self._state_path is None:
            raise RuntimeError("control plane is closed")
        return self._open_connection(str(self._state_path)), True

    def _initialize_store(self, secret: bytes | None) -> bytes:
        connection, close_after = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS control_records (
                    dedupe_key TEXT PRIMARY KEY,
                    generation INTEGER NOT NULL,
                    lease_epoch INTEGER NOT NULL,
                    lease_json TEXT,
                    state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS consumed_claims (
                    nonce TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS issued_claims (
                    dedupe_key TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    claim_level TEXT NOT NULL,
                    PRIMARY KEY (dedupe_key, generation, claim_level)
                );
                CREATE TABLE IF NOT EXISTS control_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO control_meta(key, value) VALUES ('schema_version', '1')"
            )
            row = connection.execute(
                "SELECT value FROM control_meta WHERE key = 'claim_secret'"
            ).fetchone()
            if row:
                stored = bytes.fromhex(str(row[0]))
                if secret is not None and not hmac.compare_digest(stored, secret):
                    raise ValueError("state store already has a different claim secret")
                result = stored
            else:
                result = secret or secrets.token_bytes(32)
                connection.execute(
                    "INSERT INTO control_meta(key, value) VALUES ('claim_secret', ?)",
                    (result.hex(),),
                )
            connection.commit()
            return result
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            if close_after:
                connection.close()

    def _seal_receipt(
        self,
        kind: str,
        value: dict[str, object],
        *,
        ttl_seconds: int,
    ) -> str:
        now = int(self._clock().timestamp())
        payload = {
            "v": 1,
            "kind": kind,
            "iat": now,
            "exp": now + max(1, min(ttl_seconds, 86400)),
            "value": value,
        }
        encoded = _encode(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        signature = _encode(
            hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        return f"{encoded}.{signature}"

    def _open_receipt(self, receipt: str, expected_kind: str) -> dict[str, object]:
        try:
            encoded, supplied_signature = receipt.split(".", 1)
            expected_signature = _encode(
                hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(supplied_signature, expected_signature):
                raise ValueError("control receipt signature is invalid")
            payload = json.loads(_decode(encoded).decode("utf-8"))
        except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("control receipt is invalid") from exc
        if payload.get("kind") != expected_kind:
            raise ValueError("control receipt kind is invalid")
        if int(payload.get("exp", 0)) < int(self._clock().timestamp()):
            raise ValueError("control receipt has expired")
        value = payload.get("value")
        if not isinstance(value, dict):
            raise ValueError("control receipt payload is invalid")
        return value

    @contextmanager
    def _transaction(self):
        with self._lock:
            connection, close_after = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
            finally:
                if close_after:
                    connection.close()

    @staticmethod
    def _load_record(connection: sqlite3.Connection, dedupe_key: str) -> _Record | None:
        row = connection.execute(
            "SELECT generation, lease_epoch, lease_json, state FROM control_records WHERE dedupe_key = ?",
            (dedupe_key,),
        ).fetchone()
        if row is None:
            return None
        return _Record(
            generation=int(row[0]),
            lease_epoch=int(row[1]),
            lease=OwnerLease.model_validate_json(row[2]) if row[2] else None,
            state=ControlState(row[3]),
        )

    @staticmethod
    def _save_record(
        connection: sqlite3.Connection,
        dedupe_key: str,
        record: _Record,
    ) -> None:
        connection.execute(
            """
            INSERT INTO control_records(dedupe_key, generation, lease_epoch, lease_json, state)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(dedupe_key) DO UPDATE SET
                generation = excluded.generation,
                lease_epoch = excluded.lease_epoch,
                lease_json = excluded.lease_json,
                state = excluded.state
            """,
            (
                dedupe_key,
                record.generation,
                record.lease_epoch,
                record.lease.model_dump_json() if record.lease else None,
                record.state.value,
            ),
        )

    def _new_lease(
        self,
        envelope: ExecutionEnvelope,
        *,
        lease_epoch: int,
        now: datetime,
        ttl: int,
    ) -> OwnerLease:
        return OwnerLease(
            dedupe_key=envelope.dedupe_key,
            owner_thread=envelope.owner_thread,
            generation=envelope.generation,
            lease_epoch=lease_epoch,
            fence_token=secrets.token_urlsafe(18),
            last_heartbeat=now,
            expires_at=now + timedelta(seconds=max(1, min(ttl, 3600))),
        )

    @staticmethod
    def _lease_matches(supplied: OwnerLease, expected: OwnerLease) -> bool:
        return hmac.compare_digest(
            supplied.model_dump_json(),
            expected.model_dump_json(),
        )

    def _verify_claim(
        self,
        connection: sqlite3.Connection,
        token: str,
        envelope: ExecutionEnvelope,
        lease: OwnerLease,
        now: datetime,
    ) -> dict[str, str]:
        try:
            encoded, supplied_signature = token.split(".", 1)
            expected_signature = _encode(
                hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(supplied_signature, expected_signature):
                return {"reason_code": "CLAIM_INVALID", "claim_level": ""}
            payload = json.loads(_decode(encoded).decode("utf-8"))
        except (ValueError, UnicodeError, json.JSONDecodeError):
            return {"reason_code": "CLAIM_INVALID", "claim_level": ""}
        nonce = str(payload.get("nonce", ""))
        if not nonce:
            return {"reason_code": "CLAIM_INVALID", "claim_level": ""}
        if connection.execute(
            "SELECT 1 FROM consumed_claims WHERE nonce = ?", (nonce,)
        ).fetchone():
            return {"reason_code": "CLAIM_REPLAYED", "claim_level": ""}
        if int(payload.get("exp", 0)) < int(now.timestamp()):
            return {"reason_code": "CLAIM_EXPIRED", "claim_level": ""}
        if payload.get("generation") != lease.generation or payload.get("lease_epoch") != lease.lease_epoch:
            return {"reason_code": "FENCE_MISMATCH", "claim_level": ""}
        if payload.get("fence_token") != lease.fence_token:
            return {"reason_code": "FENCE_MISMATCH", "claim_level": ""}
        if payload.get("envelope") != _envelope_digest(envelope):
            return {"reason_code": "CLAIM_BINDING_MISMATCH", "claim_level": ""}
        try:
            level = ClaimLevel(str(payload.get("claim_level", "")))
        except ValueError:
            return {"reason_code": "CLAIM_INVALID", "claim_level": ""}
        connection.execute("INSERT INTO consumed_claims(nonce) VALUES (?)", (nonce,))
        return {"reason_code": "CLAIM_ACCEPTED", "claim_level": level.value}

    @staticmethod
    def _accepted(
        envelope: ExecutionEnvelope,
        lease: OwnerLease,
        *,
        reason_code: str,
    ) -> AdmissionDecision:
        updated = envelope.model_copy(
            update={"state": ControlState.RUNNING, "reason_code": reason_code}
        )
        return AdmissionDecision(
            envelope=updated,
            state=ControlState.RUNNING,
            admitted=True,
            execute=False,
            reason_code=reason_code,
            next_action="obtain a bound claim before execution",
            lease=lease,
            claim_level=ClaimLevel.READ_ONLY_FORM,
        )

    @staticmethod
    def _rejected(
        envelope: ExecutionEnvelope,
        reason_code: str,
        state: ControlState,
        *,
        next_action: str = "review the control-plane decision",
        lease: OwnerLease | None = None,
    ) -> AdmissionDecision:
        updated = envelope.model_copy(update={"state": state, "reason_code": reason_code})
        return AdmissionDecision(
            envelope=updated,
            state=state,
            admitted=False,
            execute=False,
            reason_code=reason_code,
            next_action=next_action,
            lease=lease,
            claim_level=ClaimLevel.READ_ONLY_FORM,
        )

    @staticmethod
    def _evidence_decision(
        decision: AdmissionDecision,
        evidence: ExecutionEvidence,
        *,
        state: ControlState,
        reason_code: str,
        completed: bool = False,
    ) -> AdmissionDecision:
        updated = decision.envelope.model_copy(
            update={"state": state, "reason_code": reason_code}
        )
        return AdmissionDecision(
            envelope=updated,
            state=state,
            admitted=decision.admitted,
            execute=False,
            reason_code=reason_code,
            next_action="none" if completed else "review evidence and retry only with a new generation",
            lease=decision.lease,
            claim_level=decision.claim_level,
            evidence=evidence,
            completed=completed,
        )


__all__ = [
    "AdmissionDecision",
    "ClaimLevel",
    "ControlPlane",
    "ControlSnapshot",
    "ControlState",
    "ExecutionEnvelope",
    "ExecutionEvidence",
    "OwnerLease",
]
