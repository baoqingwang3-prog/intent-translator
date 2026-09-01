"""Local operational records for preflight decisions.

The deterministic rules in this package can only be tuned against evidence about
what they actually decided, which requires records that outlive one session. This
module writes them locally and never over a network.

No request text is recorded. A record carries the decision, the typed classification,
the rule reasons, timing, and lengths. The utterance is represented only by a salted
digest so that repeated wording can be counted without storing what was said, and the
salt lives with the local data so digests are not comparable between installs.

Set `INTENT_TRANSLATOR_TELEMETRY=off` to disable recording entirely.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

_MAX_LOG_BYTES = 8 * 1024 * 1024
_KEPT_GENERATIONS = 3
_LOCK = threading.Lock()
_COUNTERS: Counter[str] = Counter()
_STATE: dict[str, Any] = {}


def _data_dir(env: Mapping[str, str]) -> Path:
    configured = str(env.get("INTENT_TRANSLATOR_DATA_DIR", "")).strip()
    if configured:
        return Path(configured).expanduser()
    return Path(env.get("INTENT_TRANSLATOR_HOME", "") or Path.home()).expanduser() / ".intent-translator"


def _resolve_state() -> dict[str, Any]:
    env = dict(os.environ)
    fingerprint = (
        env.get("INTENT_TRANSLATOR_TELEMETRY", ""),
        env.get("INTENT_TRANSLATOR_DATA_DIR", ""),
        env.get("INTENT_TRANSLATOR_HOME", ""),
        str(Path.home()),
    )
    if _STATE.get("fingerprint") == fingerprint:
        return _STATE
    _STATE.clear()
    _STATE["fingerprint"] = fingerprint
    _STATE["enabled"] = env.get("INTENT_TRANSLATOR_TELEMETRY", "on").strip().casefold() not in {
        "off",
        "0",
        "false",
        "no",
    }
    directory = _data_dir(env)
    _STATE["path"] = directory / "decisions.jsonl"
    _STATE["salt"] = _load_or_create_salt(directory / "digest-salt")
    return _STATE


def _load_or_create_salt(path: Path) -> bytes:
    try:
        if path.is_file():
            material = bytes.fromhex(path.read_text(encoding="utf-8").strip())
            if len(material) >= 16:
                return material
        path.parent.mkdir(parents=True, exist_ok=True)
        material = secrets.token_bytes(16)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, material.hex().encode("ascii"))
        finally:
            os.close(descriptor)
        return material
    except FileExistsError:
        try:
            return bytes.fromhex(path.read_text(encoding="utf-8").strip())
        except (OSError, UnicodeError, ValueError):
            return b""
    except (OSError, UnicodeError, ValueError):
        return b""


def utterance_digest(text: str, salt: bytes) -> str:
    if not salt:
        return ""
    normalized = " ".join(text.casefold().split()).encode("utf-8")
    return hashlib.sha256(salt + b"\x00" + normalized).hexdigest()[:16]


def _rotate(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size >= _MAX_LOG_BYTES:
            for generation in range(_KEPT_GENERATIONS - 1, 0, -1):
                older = path.with_suffix(path.suffix + f".{generation}")
                newer = path.with_suffix(path.suffix + f".{generation + 1}")
                if older.exists():
                    os.replace(older, newer)
            os.replace(path, path.with_suffix(path.suffix + ".1"))
    except OSError:
        pass


def decision_record(
    envelope: Mapping[str, Any],
    *,
    utterance: str,
    scope: str,
    duration_ms: float,
    salt: bytes,
    entrypoint: str = "",
) -> dict[str, Any]:
    """Build one record. Contains no request text, only a salted digest of it."""
    contract = envelope.get("intent_contract") or {}
    risk = envelope.get("risk") or {}
    gateway = envelope.get("tool_gateway") or {}
    routing = envelope.get("routing") or {}
    semantic = envelope.get("semantic") or {}
    usage = envelope.get("input_usage") or {}
    return {
        "schema_version": 1,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
        "entrypoint": entrypoint,
        "scope": scope,
        "utterance_digest": utterance_digest(utterance, salt),
        "decision": gateway.get("decision"),
        "decision_reasons": list(gateway.get("reasons") or []),
        "required_slots": list(contract.get("required_slots") or []),
        "mode": envelope.get("mode"),
        "operation": contract.get("operation"),
        "effect": contract.get("effect"),
        "data_egress": contract.get("data_egress"),
        "destination_kind": (contract.get("destination") or {}).get("kind"),
        "risk_impact": risk.get("impact"),
        "risk_reasons": list(risk.get("reasons") or []),
        "confirmation_required": bool(risk.get("confirmation_required")),
        "receipt_verified": bool(risk.get("receipt_verified")),
        "blocked": bool(risk.get("blocked")),
        "clarification_required": bool(envelope.get("clarification_required")),
        "gate_required": bool((envelope.get("interpretation_gate") or {}).get("required")),
        "primary_skill": routing.get("primary_skill"),
        "routing_abstained": bool(routing.get("abstained")),
        "prohibition_count": len(contract.get("prohibitions") or []),
        "semantic_status": semantic.get("status"),
        "confidence": envelope.get("confidence"),
        "duration_ms": round(duration_ms, 2),
        "utterance_chars": usage.get("utterance_chars"),
        "context_chars": usage.get("context_chars"),
    }


def _bump(record: Mapping[str, Any]) -> None:
    _COUNTERS["compiles_total"] += 1
    _COUNTERS[f"decision.{record.get('decision')}"] += 1
    if record.get("clarification_required"):
        _COUNTERS["clarification_required"] += 1
    if record.get("confirmation_required"):
        _COUNTERS["confirmation_required"] += 1
    if record.get("blocked"):
        _COUNTERS["blocked"] += 1
    if record.get("receipt_verified"):
        _COUNTERS["receipt_verified"] += 1
    if record.get("routing_abstained"):
        _COUNTERS["routing_abstained"] += 1
    operation = record.get("operation")
    if operation:
        _COUNTERS[f"operation.{operation}"] += 1
    for reason in record.get("risk_reasons") or []:
        _COUNTERS[f"risk_reason.{reason}"] += 1
    for slot in record.get("required_slots") or []:
        _COUNTERS[f"required_slot.{slot}"] += 1


def record_decision(
    envelope: Mapping[str, Any],
    *,
    utterance: str,
    scope: str = "global",
    duration_ms: float = 0.0,
    entrypoint: str = "",
) -> dict[str, Any] | None:
    """Append one decision record locally. Never raises into the caller."""
    try:
        state = _resolve_state()
        if not state.get("enabled"):
            return None
        record = decision_record(
            envelope,
            utterance=utterance,
            scope=scope,
            duration_ms=duration_ms,
            salt=state["salt"],
            entrypoint=entrypoint,
        )
        path: Path = state["path"]
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)
        with _LOCK:
            _bump(record)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                _rotate(path)
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(line + "\n")
            except OSError:
                pass
        return record
    except Exception:
        # Recording must never change a safety decision or fail a request.
        return None


def counters() -> dict[str, int]:
    with _LOCK:
        return dict(_COUNTERS)


def reset_counters() -> None:
    with _LOCK:
        _COUNTERS.clear()


def reset_observability_state() -> None:
    """Drop cached configuration. Intended for tests."""
    with _LOCK:
        _STATE.clear()
        _COUNTERS.clear()


def summarize(path: Path | None = None, *, limit: int = 10) -> dict[str, Any]:
    """Aggregate recorded decisions so rules can be tuned against real usage."""
    state = _resolve_state()
    target = Path(path) if path is not None else state["path"]
    records: list[dict[str, Any]] = []
    for candidate in (target, *(target.with_suffix(target.suffix + f".{n}") for n in (1, 2, 3))):
        if not candidate.is_file():
            continue
        try:
            for line in candidate.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    records.append(json.loads(line))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
    if not records:
        return {"record_count": 0, "path": str(target), "enabled": bool(state.get("enabled"))}

    decisions = Counter(str(item.get("decision")) for item in records)
    reasons = Counter(
        reason for item in records for reason in (item.get("risk_reasons") or [])
    )
    slots = Counter(slot for item in records for slot in (item.get("required_slots") or []))
    operations = Counter(str(item.get("operation")) for item in records)
    durations = sorted(float(item.get("duration_ms") or 0.0) for item in records)
    reviewed = decisions.get("human_review", 0) + decisions.get("deny", 0)
    return {
        "record_count": len(records),
        "path": str(target),
        "enabled": bool(state.get("enabled")),
        "decisions": dict(decisions),
        "review_rate": round(reviewed / len(records), 4),
        "top_risk_reasons": reasons.most_common(limit),
        "top_required_slots": slots.most_common(limit),
        "operations": dict(operations),
        "duration_ms": {
            "p50": durations[len(durations) // 2],
            "p95": durations[min(len(durations) - 1, int(0.95 * len(durations)))],
            "max": durations[-1],
        },
        "distinct_utterance_digests": len(
            {item.get("utterance_digest") for item in records if item.get("utterance_digest")}
        ),
        "contains_request_text": False,
    }
