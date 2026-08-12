#!/usr/bin/env python3
"""Governed capture, promotion, reinforcement, and tier maintenance for intent memory."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_store import add_memory, connect, decorate_memory, memory_is_stale, now_iso


SIGNAL_TYPES = {"correction", "failure", "preference", "success", "reflection"}
SIGNAL_STATUSES = {"candidate", "promoted", "dismissed"}
REINFORCEMENT_OUTCOMES = {"helpful", "unhelpful"}


def _fingerprint(scope: str, signal_type: str, summary: str) -> str:
    normalized = " ".join(summary.casefold().split())
    return hashlib.sha256(f"{scope.strip()}\0{signal_type}\0{normalized}".encode("utf-8")).hexdigest()


def _signal_dict(row: Any) -> dict[str, Any]:
    result = {key: row[key] for key in row.keys()}
    try:
        result["evidence"] = json.loads(str(result.pop("evidence_json", "[]") or "[]"))
    except json.JSONDecodeError:
        result["evidence"] = []
    result["requires_user_confirmation_to_promote"] = result["status"] == "candidate"
    result["source_fix_candidate"] = (
        result.get("signal_type") == "failure"
        and int(result.get("occurrence_count", 0) or 0) >= 2
        and result.get("status") == "candidate"
    )
    if result["source_fix_candidate"]:
        result["recommended_action"] = "diagnose-source-and-add-regression-before-archiving"
    result["local_only"] = True
    return result


def capture_signal(
    connection: Any,
    *,
    scope: str,
    signal_type: str,
    summary: str,
    evidence: str = "",
    source_type: str = "agent_inferred",
) -> dict[str, Any]:
    if signal_type not in SIGNAL_TYPES:
        raise ValueError(f"signal_type must be one of {sorted(SIGNAL_TYPES)}")
    if not scope.strip() or not summary.strip():
        raise ValueError("scope and summary are required")
    if len(summary) > 1000 or len(evidence) > 2000:
        raise ValueError("learning signal exceeds the bounded storage limit")
    fingerprint = _fingerprint(scope, signal_type, summary)
    existing = connection.execute(
        "SELECT * FROM learning_signals WHERE fingerprint = ?", (fingerprint,)
    ).fetchone()
    timestamp = now_iso()
    if existing:
        items = json.loads(str(existing["evidence_json"] or "[]"))
        if evidence.strip() and evidence.strip() not in items:
            items = (items + [evidence.strip()])[-10:]
        connection.execute(
            """
            UPDATE learning_signals
            SET evidence_json = ?, occurrence_count = occurrence_count + 1, updated_at = ?
            WHERE id = ?
            """,
            (json.dumps(items, ensure_ascii=False), timestamp, existing["id"]),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM learning_signals WHERE id = ?", (existing["id"],)
        ).fetchone()
        result = _signal_dict(row)
        result["deduplicated"] = True
        return result
    items = [evidence.strip()] if evidence.strip() else []
    cursor = connection.execute(
        """
        INSERT INTO learning_signals(
            fingerprint, scope, signal_type, summary, evidence_json, source_type,
            occurrence_count, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 1, 'candidate', ?, ?)
        """,
        (
            fingerprint,
            scope.strip(),
            signal_type,
            summary.strip(),
            json.dumps(items, ensure_ascii=False),
            source_type.strip() or "agent_inferred",
            timestamp,
            timestamp,
        ),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM learning_signals WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    result = _signal_dict(row)
    result["deduplicated"] = False
    return result


def list_signals(
    connection: Any, *, scope: str | None = None, status: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    if status and status not in SIGNAL_STATUSES:
        raise ValueError(f"status must be one of {sorted(SIGNAL_STATUSES)}")
    where: list[str] = []
    params: list[Any] = []
    if scope:
        where.append("scope = ?")
        params.append(scope)
    if status:
        where.append("status = ?")
        params.append(status)
    sql = "SELECT * FROM learning_signals"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(max(1, min(limit, 200)))
    return [_signal_dict(row) for row in connection.execute(sql, tuple(params)).fetchall()]


def promote_signal(
    connection: Any,
    *,
    signal_id: int,
    kind: str,
    confirmation: str,
    text: str = "",
    conflict_key: str = "",
    conflict_resolution: str = "flag",
    stale_after_days: int = 0,
) -> dict[str, Any]:
    if confirmation != f"PROMOTE:{signal_id}":
        raise ValueError(f"promotion requires --confirm PROMOTE:{signal_id}")
    signal = connection.execute(
        "SELECT * FROM learning_signals WHERE id = ?", (signal_id,)
    ).fetchone()
    if not signal:
        raise ValueError(f"learning signal does not exist: {signal_id}")
    if signal["status"] != "candidate":
        raise ValueError(f"learning signal is already {signal['status']}")
    memory = add_memory(
        connection,
        kind=kind,
        scope=str(signal["scope"]),
        text=text.strip() or str(signal["summary"]),
        confidence="confirmed",
        source=f"learning-signal:{signal_id}",
        source_type="user_confirmed",
        stale_after_days=stale_after_days,
        conflict_key=conflict_key,
        conflict_resolution=conflict_resolution,
    )
    connection.execute(
        "UPDATE memories SET tier = 'hot', last_reinforced_at = ? WHERE id = ?",
        (now_iso(), memory["id"]),
    )
    connection.execute(
        "UPDATE learning_signals SET status = 'promoted', memory_id = ?, updated_at = ? WHERE id = ?",
        (memory["id"], now_iso(), signal_id),
    )
    connection.commit()
    promoted = connection.execute(
        "SELECT * FROM learning_signals WHERE id = ?", (signal_id,)
    ).fetchone()
    stored = connection.execute("SELECT * FROM memories WHERE id = ?", (memory["id"],)).fetchone()
    return {"signal": _signal_dict(promoted), "memory": decorate_memory(dict(stored))}


def dismiss_signal(connection: Any, *, signal_id: int, confirmation: str) -> dict[str, Any]:
    if confirmation != f"DISMISS:{signal_id}":
        raise ValueError(f"dismissal requires --confirm DISMISS:{signal_id}")
    cursor = connection.execute(
        "UPDATE learning_signals SET status = 'dismissed', updated_at = ? WHERE id = ? AND status = 'candidate'",
        (now_iso(), signal_id),
    )
    connection.commit()
    return {"id": signal_id, "status": "dismissed", "updated": cursor.rowcount == 1}


def reinforce_memory(connection: Any, *, memory_id: int, outcome: str) -> dict[str, Any]:
    if outcome not in REINFORCEMENT_OUTCOMES:
        raise ValueError(f"outcome must be one of {sorted(REINFORCEMENT_OUTCOMES)}")
    row = connection.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if not row:
        raise ValueError(f"memory does not exist: {memory_id}")
    helpful = int(row["reinforcement_count"] or 0) + int(outcome == "helpful")
    negative = int(row["negative_count"] or 0) + int(outcome == "unhelpful")
    tier = (
        "cold"
        if negative >= 2
        else "hot"
        if helpful >= 2 or (str(row["tier"]) == "hot" and outcome == "helpful")
        else "warm"
    )
    connection.execute(
        """
        UPDATE memories
        SET reinforcement_count = ?, negative_count = ?, tier = ?,
            last_reinforced_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (helpful, negative, tier, now_iso(), now_iso(), memory_id),
    )
    connection.commit()
    updated = connection.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    result = decorate_memory(dict(updated))
    result["authority_unchanged"] = True
    return result


def maintain_tiers(connection: Any, *, scope: str | None = None, apply: bool = False) -> dict[str, Any]:
    sql = "SELECT * FROM memories WHERE status = 'active' AND trust_level != 'quarantined'"
    params: list[Any] = []
    if scope:
        sql += " AND scope = ?"
        params.append(scope)
    changes: list[dict[str, Any]] = []
    for row in connection.execute(sql, tuple(params)).fetchall():
        record = dict(row)
        promoted_memory = str(record.get("source", "")).startswith("learning-signal:")
        desired = (
            "cold"
            if memory_is_stale(record) or int(record.get("negative_count", 0) or 0) >= 2
            else "hot"
            if promoted_memory or int(record.get("reinforcement_count", 0) or 0) >= 2
            else "warm"
        )
        if desired != str(record.get("tier", "warm")):
            changes.append({"id": record["id"], "from": record.get("tier", "warm"), "to": desired})
            if apply:
                connection.execute(
                    "UPDATE memories SET tier = ? WHERE id = ?",
                    (desired, record["id"]),
                )
    if apply:
        connection.commit()
    return {"scope": scope or "all", "apply": apply, "changed": len(changes), "changes": changes}


def lifecycle_stats(connection: Any, *, scope: str | None = None) -> dict[str, Any]:
    memory_where = "WHERE 1 = 1"
    signal_where = "WHERE 1 = 1"
    params: tuple[Any, ...] = ()
    if scope:
        memory_where += " AND scope = ?"
        signal_where += " AND scope = ?"
        params = (scope,)
    tiers = {name: 0 for name in ("hot", "warm", "cold")}
    for row in connection.execute(
        f"SELECT tier, COUNT(*) AS total FROM memories {memory_where} GROUP BY tier", params
    ):
        tiers[str(row["tier"])] = int(row["total"])
    signals = {name: 0 for name in sorted(SIGNAL_STATUSES)}
    for row in connection.execute(
        f"SELECT status, COUNT(*) AS total FROM learning_signals {signal_where} GROUP BY status", params
    ):
        signals[str(row["status"])] = int(row["total"])
    return {"scope": scope or "all", "memories_by_tier": tiers, "signals_by_status": signals}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser("capture")
    capture.add_argument("--scope", default="global")
    capture.add_argument("--type", choices=sorted(SIGNAL_TYPES), required=True)
    capture.add_argument("--summary", required=True)
    capture.add_argument("--evidence", default="")
    signals = subparsers.add_parser("signals")
    signals.add_argument("--scope")
    signals.add_argument("--status", choices=sorted(SIGNAL_STATUSES))
    signals.add_argument("--limit", type=int, default=50)
    promote = subparsers.add_parser("promote")
    promote.add_argument("--id", type=int, required=True)
    promote.add_argument("--kind", required=True)
    promote.add_argument("--text", default="")
    promote.add_argument("--conflict-key", default="")
    promote.add_argument("--on-conflict", choices=("flag", "replace", "reject"), default="flag")
    promote.add_argument("--stale-after-days", type=int, default=0)
    promote.add_argument("--confirm", required=True)
    dismiss = subparsers.add_parser("dismiss")
    dismiss.add_argument("--id", type=int, required=True)
    dismiss.add_argument("--confirm", required=True)
    reinforce = subparsers.add_parser("reinforce")
    reinforce.add_argument("--id", type=int, required=True)
    reinforce.add_argument("--outcome", choices=sorted(REINFORCEMENT_OUTCOMES), required=True)
    maintain = subparsers.add_parser("maintain")
    maintain.add_argument("--scope")
    maintain.add_argument("--apply", action="store_true")
    stats = subparsers.add_parser("stats")
    stats.add_argument("--scope")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    connection = connect(args.db) if args.db else connect(Path.home() / ".intent-translator" / "memory.db")
    try:
        if args.command == "capture":
            result = capture_signal(
                connection, scope=args.scope, signal_type=args.type, summary=args.summary, evidence=args.evidence
            )
        elif args.command == "signals":
            result = list_signals(connection, scope=args.scope, status=args.status, limit=args.limit)
        elif args.command == "promote":
            result = promote_signal(
                connection,
                signal_id=args.id,
                kind=args.kind,
                text=args.text,
                conflict_key=args.conflict_key,
                conflict_resolution=args.on_conflict,
                stale_after_days=args.stale_after_days,
                confirmation=args.confirm,
            )
        elif args.command == "dismiss":
            result = dismiss_signal(connection, signal_id=args.id, confirmation=args.confirm)
        elif args.command == "reinforce":
            result = reinforce_memory(connection, memory_id=args.id, outcome=args.outcome)
        elif args.command == "maintain":
            result = maintain_tiers(connection, scope=args.scope, apply=args.apply)
        else:
            result = lifecycle_stats(connection, scope=args.scope)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
