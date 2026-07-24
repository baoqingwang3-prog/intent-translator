#!/usr/bin/env python3
"""Local-first SQLite memory, correction, and intent-check store."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


CONFIDENCE_VALUES = {"confirmed", "observed", "inferred"}
SEVERITY_VALUES = {"low", "medium", "high", "critical"}
OUTCOME_VALUES = {"heeded", "recurred", "unknown"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def default_db_path() -> Path:
    configured = os.environ.get("INTENT_TRANSLATOR_MEMORY_DB")
    return Path(configured).expanduser() if configured else Path.home() / ".intent-translator" / "memory.db"


def ensure_columns(connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    for name, declaration in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = db_path.expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            scope TEXT NOT NULL,
            text TEXT NOT NULL,
            confidence TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(kind, scope, text)
        )
        """
    )
    ensure_columns(
        connection,
        "memories",
        {
            "stale_after_days": "INTEGER NOT NULL DEFAULT 0",
            "access_count": "INTEGER NOT NULL DEFAULT 0",
            "last_accessed_at": "TEXT NOT NULL DEFAULT ''",
        },
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            trigger_text TEXT NOT NULL,
            correction TEXT NOT NULL,
            severity TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            retrieved_count INTEGER NOT NULL DEFAULT 0,
            heeded_count INTEGER NOT NULL DEFAULT 0,
            recurred_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(scope, trigger_text, correction)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS correction_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            correction_id INTEGER NOT NULL,
            outcome TEXT NOT NULL,
            context TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(correction_id) REFERENCES corrections(id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS intent_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            goal TEXT NOT NULL,
            impact TEXT NOT NULL,
            reversible TEXT NOT NULL,
            external INTEGER NOT NULL,
            sensitive INTEGER NOT NULL,
            authorization TEXT NOT NULL,
            confirmation_required INTEGER NOT NULL,
            blocked INTEGER NOT NULL,
            correction_ids TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def memory_is_stale(record: dict[str, Any], *, at: datetime | None = None) -> bool:
    stale_after_days = int(record.get("stale_after_days", 0) or 0)
    if stale_after_days <= 0:
        return False
    at = at or datetime.now(timezone.utc)
    return parse_iso(str(record["updated_at"])) + timedelta(days=stale_after_days) < at


def decorate_memory(record: dict[str, Any], *, score: int | None = None) -> dict[str, Any]:
    result = dict(record)
    result["stale"] = memory_is_stale(result)
    if score is not None:
        result["score"] = score
    return result


def add_memory(
    connection: sqlite3.Connection,
    *,
    kind: str,
    scope: str,
    text: str,
    confidence: str,
    source: str = "",
    stale_after_days: int = 0,
) -> dict[str, Any]:
    if confidence not in CONFIDENCE_VALUES:
        raise ValueError(f"confidence must be one of {sorted(CONFIDENCE_VALUES)}")
    if not kind.strip() or not scope.strip() or not text.strip():
        raise ValueError("kind, scope, and text are required")
    if stale_after_days < 0:
        raise ValueError("stale_after_days cannot be negative")

    timestamp = now_iso()
    values = (kind.strip(), scope.strip(), text.strip())
    existing = connection.execute(
        "SELECT * FROM memories WHERE kind = ? AND scope = ? AND text = ?", values
    ).fetchone()
    if existing:
        connection.execute(
            """
            UPDATE memories
            SET confidence = ?, source = ?, stale_after_days = ?, updated_at = ?
            WHERE id = ?
            """,
            (confidence, source.strip(), stale_after_days, timestamp, existing["id"]),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM memories WHERE id = ?", (existing["id"],)).fetchone()
        result = decorate_memory(row_to_dict(row))
        result["deduplicated"] = True
        return result

    cursor = connection.execute(
        """
        INSERT INTO memories(
            kind, scope, text, confidence, source, created_at, updated_at, stale_after_days
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (*values, confidence, source.strip(), timestamp, timestamp, stale_after_days),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM memories WHERE id = ?", (cursor.lastrowid,)).fetchone()
    result = decorate_memory(row_to_dict(row))
    result["deduplicated"] = False
    return result


def search_memories(
    connection: sqlite3.Connection,
    *,
    query: str,
    scope: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    terms = [term.casefold() for term in query.split() if term.strip()]
    if not terms:
        return []
    sql = "SELECT * FROM memories"
    params: tuple[Any, ...] = ()
    if scope:
        sql += " WHERE scope IN (?, 'global')"
        params = (scope,)
    rows = connection.execute(sql, params).fetchall()

    confidence_weight = {"confirmed": 30, "observed": 20, "inferred": 10}
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for row in rows:
        record = row_to_dict(row)
        haystack = f"{record['text']} {record['source']} {record['kind']} {record['scope']}".casefold()
        matches = sum(1 for term in terms if term in haystack)
        if not matches:
            continue
        stale_penalty = 60 if memory_is_stale(record) else 0
        score = (
            matches * 100
            + confidence_weight.get(str(record["confidence"]), 0)
            + min(int(record.get("access_count", 0)), 10)
            - stale_penalty
        )
        ranked.append((score, str(record["updated_at"]), decorate_memory(record, score=score)))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    results = [item[2] for item in ranked[: max(1, limit)]]

    timestamp = now_iso()
    for result in results:
        connection.execute(
            """
            UPDATE memories
            SET access_count = access_count + 1, last_accessed_at = ?
            WHERE id = ?
            """,
            (timestamp, result["id"]),
        )
        result["access_count"] = int(result.get("access_count", 0)) + 1
        result["last_accessed_at"] = timestamp
    connection.commit()
    return results


def list_memories(
    connection: sqlite3.Connection, *, scope: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    if scope:
        rows = connection.execute(
            "SELECT * FROM memories WHERE scope = ? ORDER BY updated_at DESC LIMIT ?",
            (scope, max(1, limit)),
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (max(1, limit),)
        ).fetchall()
    return [decorate_memory(row_to_dict(row)) for row in rows]


def add_correction(
    connection: sqlite3.Connection,
    *,
    scope: str,
    trigger_text: str,
    correction: str,
    severity: str = "medium",
    evidence: str = "",
) -> dict[str, Any]:
    if severity not in SEVERITY_VALUES:
        raise ValueError(f"severity must be one of {sorted(SEVERITY_VALUES)}")
    if not scope.strip() or not trigger_text.strip() or not correction.strip():
        raise ValueError("scope, trigger_text, and correction are required")
    timestamp = now_iso()
    values = (scope.strip(), trigger_text.strip(), correction.strip())
    existing = connection.execute(
        """
        SELECT * FROM corrections
        WHERE scope = ? AND trigger_text = ? AND correction = ?
        """,
        values,
    ).fetchone()
    if existing:
        connection.execute(
            """
            UPDATE corrections
            SET severity = ?, evidence = ?, status = 'active', updated_at = ?
            WHERE id = ?
            """,
            (severity, evidence.strip(), timestamp, existing["id"]),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM corrections WHERE id = ?", (existing["id"],)).fetchone()
        result = row_to_dict(row)
        result["deduplicated"] = True
        return result

    cursor = connection.execute(
        """
        INSERT INTO corrections(
            scope, trigger_text, correction, severity, evidence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (*values, severity, evidence.strip(), timestamp, timestamp),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM corrections WHERE id = ?", (cursor.lastrowid,)).fetchone()
    result = row_to_dict(row)
    result["deduplicated"] = False
    return result


def search_corrections(
    connection: sqlite3.Connection,
    *,
    query: str,
    scope: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    terms = [term.casefold() for term in query.split() if term.strip()]
    if not terms:
        return []
    sql = "SELECT * FROM corrections WHERE status = 'active'"
    params: tuple[Any, ...] = ()
    if scope:
        sql += " AND scope IN (?, 'global')"
        params = (scope,)
    rows = connection.execute(sql, params).fetchall()
    severity_weight = {"low": 5, "medium": 10, "high": 20, "critical": 40}
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for row in rows:
        record = row_to_dict(row)
        haystack = f"{record['trigger_text']} {record['correction']} {record['evidence']}".casefold()
        matches = sum(1 for term in terms if term in haystack)
        if not matches:
            continue
        score = (
            matches * 100
            + severity_weight.get(str(record["severity"]), 0)
            + int(record["recurred_count"]) * 5
            + int(record["heeded_count"])
        )
        record["score"] = score
        ranked.append((score, str(record["updated_at"]), record))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    results = [item[2] for item in ranked[: max(1, limit)]]
    for result in results:
        connection.execute(
            "UPDATE corrections SET retrieved_count = retrieved_count + 1 WHERE id = ?",
            (result["id"],),
        )
        result["retrieved_count"] = int(result["retrieved_count"]) + 1
    connection.commit()
    return results


def record_correction_outcome(
    connection: sqlite3.Connection,
    *,
    correction_id: int,
    outcome: str,
    context: str = "",
) -> dict[str, Any]:
    if outcome not in OUTCOME_VALUES:
        raise ValueError(f"outcome must be one of {sorted(OUTCOME_VALUES)}")
    existing = connection.execute(
        "SELECT * FROM corrections WHERE id = ?", (correction_id,)
    ).fetchone()
    if not existing:
        raise ValueError(f"correction does not exist: {correction_id}")
    timestamp = now_iso()
    connection.execute(
        """
        INSERT INTO correction_events(correction_id, outcome, context, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (correction_id, outcome, context.strip(), timestamp),
    )
    if outcome in {"heeded", "recurred"}:
        column = "heeded_count" if outcome == "heeded" else "recurred_count"
        connection.execute(
            f"UPDATE corrections SET {column} = {column} + 1, updated_at = ? WHERE id = ?",
            (timestamp, correction_id),
        )
    connection.commit()
    row = connection.execute("SELECT * FROM corrections WHERE id = ?", (correction_id,)).fetchone()
    return row_to_dict(row)


def check_intent(
    connection: sqlite3.Connection,
    *,
    scope: str,
    goal: str,
    impact: str = "low",
    reversible: str = "yes",
    external: bool = False,
    sensitive: bool = False,
    authorization: str = "unknown",
    record: bool = True,
) -> dict[str, Any]:
    if impact not in {"low", "medium", "high"}:
        raise ValueError("impact must be low, medium, or high")
    if reversible not in {"yes", "no", "unknown"}:
        raise ValueError("reversible must be yes, no, or unknown")
    if authorization not in {"granted", "unknown", "denied"}:
        raise ValueError("authorization must be granted, unknown, or denied")
    corrections = search_corrections(connection, query=goal, scope=scope, limit=5)
    reasons: list[str] = []
    blocked = authorization == "denied"
    if blocked:
        reasons.append("authorization is denied")
    if authorization == "unknown" and impact == "high":
        reasons.append("high-impact action lacks explicit authorization")
    if authorization == "unknown" and reversible == "no":
        reasons.append("irreversible action lacks explicit authorization")
    if authorization == "unknown" and external:
        reasons.append("external action lacks explicit authorization")
    if authorization == "unknown" and sensitive:
        reasons.append("sensitive-data handling lacks explicit authorization")
    if reversible == "unknown" and impact != "low":
        reasons.append("reversibility is unknown")
    confirmation_required = bool(reasons) and not blocked
    result = {
        "scope": scope,
        "goal": goal,
        "impact": impact,
        "reversible": reversible,
        "external": external,
        "sensitive": sensitive,
        "authorization": authorization,
        "watch_for": corrections,
        "confirmation_required": confirmation_required,
        "blocked": blocked,
        "reasons": reasons,
    }
    if record:
        connection.execute(
            """
            INSERT INTO intent_checks(
                scope, goal, impact, reversible, external, sensitive, authorization,
                confirmation_required, blocked, correction_ids, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scope,
                goal,
                impact,
                reversible,
                int(external),
                int(sensitive),
                authorization,
                int(confirmation_required),
                int(blocked),
                json.dumps([item["id"] for item in corrections]),
                now_iso(),
            ),
        )
        connection.commit()
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=default_db_path())
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init")

    add = subparsers.add_parser("add")
    add.add_argument("--kind", required=True)
    add.add_argument("--scope", default="global")
    add.add_argument("--text", required=True)
    add.add_argument("--confidence", choices=sorted(CONFIDENCE_VALUES), default="confirmed")
    add.add_argument("--source", default="")
    add.add_argument("--stale-after-days", type=int, default=0)

    search = subparsers.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--scope")
    search.add_argument("--limit", type=int, default=10)

    listing = subparsers.add_parser("list")
    listing.add_argument("--scope")
    listing.add_argument("--limit", type=int, default=50)

    delete = subparsers.add_parser("delete")
    delete.add_argument("--id", type=int, required=True)

    correction_add = subparsers.add_parser("correction-add")
    correction_add.add_argument("--scope", default="global")
    correction_add.add_argument("--trigger", required=True)
    correction_add.add_argument("--correction", required=True)
    correction_add.add_argument("--severity", choices=sorted(SEVERITY_VALUES), default="medium")
    correction_add.add_argument("--evidence", default="")

    correction_search = subparsers.add_parser("correction-search")
    correction_search.add_argument("--query", required=True)
    correction_search.add_argument("--scope")
    correction_search.add_argument("--limit", type=int, default=10)

    correction_outcome = subparsers.add_parser("correction-outcome")
    correction_outcome.add_argument("--id", type=int, required=True)
    correction_outcome.add_argument("--outcome", choices=sorted(OUTCOME_VALUES), required=True)
    correction_outcome.add_argument("--context", default="")

    intent_check = subparsers.add_parser("intent-check")
    intent_check.add_argument("--scope", default="global")
    intent_check.add_argument("--goal", required=True)
    intent_check.add_argument("--impact", choices=("low", "medium", "high"), default="low")
    intent_check.add_argument("--reversible", choices=("yes", "no", "unknown"), default="yes")
    intent_check.add_argument("--external", action="store_true")
    intent_check.add_argument("--sensitive", action="store_true")
    intent_check.add_argument(
        "--authorization", choices=("granted", "unknown", "denied"), default="unknown"
    )
    intent_check.add_argument("--no-record", action="store_true")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    connection = connect(args.db)
    try:
        if args.command == "init":
            result: Any = {"database": str(args.db.expanduser().resolve()), "initialized": True}
        elif args.command == "add":
            result = add_memory(
                connection,
                kind=args.kind,
                scope=args.scope,
                text=args.text,
                confidence=args.confidence,
                source=args.source,
                stale_after_days=args.stale_after_days,
            )
        elif args.command == "search":
            result = search_memories(connection, query=args.query, scope=args.scope, limit=args.limit)
        elif args.command == "list":
            result = list_memories(connection, scope=args.scope, limit=args.limit)
        elif args.command == "delete":
            cursor = connection.execute("DELETE FROM memories WHERE id = ?", (args.id,))
            connection.commit()
            result = {"id": args.id, "deleted": cursor.rowcount == 1}
        elif args.command == "correction-add":
            result = add_correction(
                connection,
                scope=args.scope,
                trigger_text=args.trigger,
                correction=args.correction,
                severity=args.severity,
                evidence=args.evidence,
            )
        elif args.command == "correction-search":
            result = search_corrections(
                connection, query=args.query, scope=args.scope, limit=args.limit
            )
        elif args.command == "correction-outcome":
            result = record_correction_outcome(
                connection,
                correction_id=args.id,
                outcome=args.outcome,
                context=args.context,
            )
        else:
            result = check_intent(
                connection,
                scope=args.scope,
                goal=args.goal,
                impact=args.impact,
                reversible=args.reversible,
                external=args.external,
                sensitive=args.sensitive,
                authorization=args.authorization,
                record=not args.no_record,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
