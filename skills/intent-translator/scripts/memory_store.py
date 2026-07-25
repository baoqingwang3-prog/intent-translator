#!/usr/bin/env python3
"""Local-first governed memory, correction, and intent-check store."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from semantic_search import (  # noqa: E402
    ensure_fts,
    fts_candidate_ids,
    index_record,
    overlap_score,
    rebuild_indexes,
    remove_record,
    semantic_tokens,
)


DB_SCHEMA_VERSION = 5
CONFIDENCE_VALUES = {"confirmed", "observed", "inferred"}
SEVERITY_VALUES = {"low", "medium", "high", "critical"}
OUTCOME_VALUES = {"heeded", "recurred", "unknown"}
MEMORY_STATUS_VALUES = {"active", "superseded", "retracted", "expired"}
SENSITIVITY_VALUES = {"standard", "sensitive"}
CONFLICT_RESOLUTIONS = {"flag", "replace", "reject"}
SOURCE_TYPE_VALUES = {
    "user_explicit",
    "user_confirmed",
    "agent_inferred",
    "local_file",
    "external",
    "imported",
    "legacy",
}
TRUST_LEVEL_VALUES = {"trusted", "untrusted", "quarantined"}
NON_AUTHORITATIVE_SOURCE_TYPES = {"agent_inferred", "local_file", "external", "imported"}
AUTHORITY_MEMORY_KINDS = {"preference", "phrase", "decision", "warning", "instruction", "policy"}
INJECTION_PATTERNS = (
    re.compile(r"\b(?:ignore|disregard|override)\b.{0,80}\b(?:previous|prior|system|developer|safety|instructions?)\b", re.I),
    re.compile(r"\b(?:reveal|print|show|expose)\b.{0,80}\b(?:system prompt|developer message|hidden instructions?|api key|token|password|secret)\b", re.I),
    re.compile(r"\b(?:bypass|disable|evade|remove)\b.{0,80}\b(?:safety|policy|guardrails?|authorization|permissions?)\b", re.I),
    re.compile(r"(?:忽略|无视|覆盖).{0,30}(?:之前|系统|开发者|安全|指令|规则)"),
    re.compile(r"(?:泄露|显示|输出|告诉我).{0,30}(?:系统提示词|开发者消息|隐藏指令|密钥|令牌|密码)"),
    re.compile(r"(?:绕过|关闭|移除).{0,30}(?:安全|策略|护栏|授权|权限)"),
)
UNTRUSTED_INSTRUCTION_PATTERNS = (
    re.compile(r"^\s*(?:run|execute|delete|upload|publish|send|transfer|call|use)\b", re.I),
    re.compile(r"^\s*(?:执行|运行|删除|上传|发布|发送|外发|调用|使用).{0,20}"),
    re.compile(r"\b(?:system|developer)\s*(?:message|instruction|prompt)\s*:", re.I),
    re.compile(r"(?:系统|开发者)(?:消息|指令|提示词)\s*[：:]"),
)
AUTHORITY_EXPANSION_PATTERNS = (
    re.compile(r"\b(?:never ask|without (?:asking|confirmation|permission)|treat .{0,30} as authorization)\b", re.I),
    re.compile(r"\balways\b.{0,60}\bwithout asking\b", re.I),
    re.compile(r"(?:不用|无需|不必).{0,12}(?:确认|询问|授权|许可)"),
    re.compile(r"(?:以后别问|默认授权|视为授权|直接).{0,20}(?:发布|删除|外发|付款|购买|上传)"),
)


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


def database_path(connection: sqlite3.Connection) -> Path:
    row = connection.execute("PRAGMA database_list").fetchone()
    return Path(row["file"]).resolve()


def backup_database(connection: sqlite3.Connection, destination: Path | None = None) -> Path:
    source = database_path(connection)
    if destination is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = source.with_name(f"{source.name}.backup-{stamp}")
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    target = sqlite3.connect(destination)
    try:
        connection.backup(target)
    finally:
        target.close()
    return destination


def migration_backup_path(db_path: Path, version: int) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return db_path.with_name(f"{db_path.name}.bak-v{version}-{stamp}")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = db_path.expanduser().resolve()
    existed = db_path.exists() and db_path.stat().st_size > 0
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    old_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    backup_path = ""
    if existed and old_version < DB_SCHEMA_VERSION:
        backup_path = str(backup_database(connection, migration_backup_path(db_path, old_version)))

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
            "status": "TEXT NOT NULL DEFAULT 'active'",
            "sensitivity": "TEXT NOT NULL DEFAULT 'standard'",
            "expires_at": "TEXT NOT NULL DEFAULT ''",
            "conflict_key": "TEXT NOT NULL DEFAULT ''",
            "supersedes_id": "INTEGER",
            "source_type": "TEXT NOT NULL DEFAULT 'legacy'",
            "trust_level": "TEXT NOT NULL DEFAULT 'trusted'",
            "instruction_like": "INTEGER NOT NULL DEFAULT 0",
            "quarantine_reason": "TEXT NOT NULL DEFAULT ''",
        },
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id INTEGER NOT NULL,
            event TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
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
    ensure_columns(
        connection,
        "corrections",
        {
            "trigger_context": "TEXT NOT NULL DEFAULT ''",
            "wrong_interpretation": "TEXT NOT NULL DEFAULT ''",
            "correct_interpretation": "TEXT NOT NULL DEFAULT ''",
            "source": "TEXT NOT NULL DEFAULT 'user-confirmed'",
            "edit_json": "TEXT NOT NULL DEFAULT '{}'",
            "expires_at": "TEXT NOT NULL DEFAULT ''",
        },
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
        CREATE TABLE IF NOT EXISTS pending_corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            trigger_text TEXT NOT NULL,
            correction TEXT NOT NULL,
            severity TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '',
            source_message TEXT NOT NULL DEFAULT '',
            previous_behavior TEXT NOT NULL DEFAULT '',
            ready_for_confirmation INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    ensure_columns(
        connection,
        "pending_corrections",
        {
            "trigger_context": "TEXT NOT NULL DEFAULT ''",
            "wrong_interpretation": "TEXT NOT NULL DEFAULT ''",
            "correct_interpretation": "TEXT NOT NULL DEFAULT ''",
            "source": "TEXT NOT NULL DEFAULT 'user-natural-language-correction'",
            "edit_json": "TEXT NOT NULL DEFAULT '{}'",
            "expires_at": "TEXT NOT NULL DEFAULT ''",
        },
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            utterance TEXT NOT NULL,
            expected_goal TEXT NOT NULL DEFAULT '',
            expected_operation TEXT NOT NULL DEFAULT '',
            expected_skill TEXT NOT NULL DEFAULT '',
            actual_goal TEXT NOT NULL DEFAULT '',
            actual_operation TEXT NOT NULL DEFAULT '',
            actual_skill TEXT NOT NULL DEFAULT '',
            success INTEGER NOT NULL,
            matched INTEGER NOT NULL,
            mismatch_json TEXT NOT NULL DEFAULT '[]',
            correction_id INTEGER,
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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            migrated_at TEXT NOT NULL,
            backup_path TEXT NOT NULL DEFAULT ''
        )
        """
    )
    if old_version < 4:
        for row in connection.execute("SELECT * FROM memories").fetchall():
            defense = memory_defense_assessment(
                text=str(row["text"]),
                kind=str(row["kind"]),
                source_type="legacy",
            )
            connection.execute(
                """
                UPDATE memories
                SET source_type = ?, trust_level = ?, instruction_like = ?, quarantine_reason = ?
                WHERE id = ?
                """,
                (
                    defense["source_type"],
                    defense["trust_level"],
                    int(defense["instruction_like"]),
                    defense["quarantine_reason"],
                    row["id"],
                ),
            )
            record_memory_event(
                connection,
                int(row["id"]),
                "trust_migrated",
                defense,
            )
    ensure_fts(connection)
    connection.execute(
        "INSERT OR REPLACE INTO schema_migrations(version, migrated_at, backup_path) VALUES (?, ?, ?)",
        (DB_SCHEMA_VERSION, now_iso(), backup_path),
    )
    connection.execute(f"PRAGMA user_version = {DB_SCHEMA_VERSION}")
    expire_memories(connection, commit=False)
    rebuild_indexes(connection)
    connection.commit()
    return connection


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open an existing memory database without migrations, expiry, or index writes."""
    db_path = db_path.expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    connection = sqlite3.connect(
        f"file:{db_path.as_posix()}?mode=ro",
        uri=True,
        timeout=5.0,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def memory_is_expired(record: dict[str, Any], *, at: datetime | None = None) -> bool:
    expires_at = str(record.get("expires_at", "") or "")
    if not expires_at:
        return False
    return parse_iso(expires_at) <= (at or datetime.now(timezone.utc))


def memory_is_stale(record: dict[str, Any], *, at: datetime | None = None) -> bool:
    if memory_is_expired(record, at=at):
        return True
    stale_after_days = int(record.get("stale_after_days", 0) or 0)
    if stale_after_days <= 0:
        return False
    at = at or datetime.now(timezone.utc)
    return parse_iso(str(record["updated_at"])) + timedelta(days=stale_after_days) < at


def decorate_memory(record: dict[str, Any], *, score: int | None = None) -> dict[str, Any]:
    result = dict(record)
    result["expired"] = memory_is_expired(result)
    result["stale"] = memory_is_stale(result)
    result["instruction_like"] = bool(result.get("instruction_like", 0))
    result["memory_defense"] = {
        "source_type": result.get("source_type", "legacy"),
        "trust_level": result.get("trust_level", "trusted"),
        "non_authoritative": result.get("trust_level") == "untrusted",
        "quarantined": result.get("trust_level") == "quarantined",
        "quarantine_reason": result.get("quarantine_reason", ""),
    }
    if score is not None:
        result["score"] = score
    return result


def record_memory_event(
    connection: sqlite3.Connection, memory_id: int, event: str, details: dict[str, Any] | None = None
) -> None:
    connection.execute(
        "INSERT INTO memory_events(memory_id, event, details, created_at) VALUES (?, ?, ?, ?)",
        (memory_id, event, json.dumps(details or {}, ensure_ascii=False), now_iso()),
    )


def expire_memories(connection: sqlite3.Connection, *, commit: bool = True) -> int:
    timestamp = now_iso()
    rows = connection.execute(
        "SELECT id FROM memories WHERE status = 'active' AND expires_at != '' AND expires_at <= ?",
        (timestamp,),
    ).fetchall()
    for row in rows:
        memory_id = int(row["id"])
        connection.execute(
            "UPDATE memories SET status = 'expired', updated_at = ? WHERE id = ?",
            (timestamp, memory_id),
        )
        remove_record(connection, "memories_fts", memory_id)
        record_memory_event(connection, memory_id, "expired")
    if commit:
        connection.commit()
    return len(rows)


def _expires_at(sensitivity: str, retain_days: int | None) -> str:
    if sensitivity not in SENSITIVITY_VALUES:
        raise ValueError(f"sensitivity must be one of {sorted(SENSITIVITY_VALUES)}")
    if retain_days is not None and retain_days <= 0:
        raise ValueError("retain_days must be positive")
    if sensitivity == "sensitive" and retain_days is None:
        raise ValueError("sensitive memory requires an explicit retain_days value")
    if retain_days is None:
        return ""
    return (datetime.now(timezone.utc) + timedelta(days=retain_days)).replace(microsecond=0).isoformat()


def memory_defense_assessment(*, text: str, kind: str, source_type: str) -> dict[str, Any]:
    if source_type not in SOURCE_TYPE_VALUES:
        raise ValueError(f"source_type must be one of {sorted(SOURCE_TYPE_VALUES)}")
    compact = " ".join(text.split())
    injection = any(pattern.search(compact) for pattern in INJECTION_PATTERNS)
    authority_expansion = any(pattern.search(compact) for pattern in AUTHORITY_EXPANSION_PATTERNS)
    instruction_like = injection or authority_expansion or any(
        pattern.search(compact) for pattern in UNTRUSTED_INSTRUCTION_PATTERNS
    )
    if injection:
        trust_level = "quarantined"
        reason = "persistent instruction attempts to override authority, safety, or secret boundaries"
    elif authority_expansion:
        trust_level = "quarantined"
        reason = "persistent memory cannot pre-authorize future external, destructive, paid, or sensitive actions"
    elif source_type == "legacy":
        trust_level = "untrusted"
        reason = "legacy memory has no verified provenance and remains non-authoritative until reconfirmed"
    elif source_type in NON_AUTHORITATIVE_SOURCE_TYPES and kind.strip().casefold() in AUTHORITY_MEMORY_KINDS:
        trust_level = "quarantined"
        reason = "non-user source cannot define an authoritative preference, decision, policy, or instruction"
    elif source_type in NON_AUTHORITATIVE_SOURCE_TYPES and instruction_like:
        trust_level = "quarantined"
        reason = "instruction-like content from a non-authoritative source"
    elif source_type in NON_AUTHORITATIVE_SOURCE_TYPES:
        trust_level = "untrusted"
        reason = "recalled as non-authoritative data only"
    else:
        trust_level = "trusted"
        reason = "explicit or confirmed user-controlled memory"
    return {
        "source_type": source_type,
        "trust_level": trust_level,
        "instruction_like": instruction_like,
        "quarantine_reason": reason if trust_level == "quarantined" else "",
        "trust_reason": reason,
    }


def add_memory(
    connection: sqlite3.Connection,
    *,
    kind: str,
    scope: str,
    text: str,
    confidence: str,
    source: str = "",
    source_type: str = "user_explicit",
    stale_after_days: int = 0,
    sensitivity: str = "standard",
    retain_days: int | None = None,
    conflict_key: str = "",
    conflict_resolution: str = "flag",
) -> dict[str, Any]:
    if confidence not in CONFIDENCE_VALUES:
        raise ValueError(f"confidence must be one of {sorted(CONFIDENCE_VALUES)}")
    if conflict_resolution not in CONFLICT_RESOLUTIONS:
        raise ValueError(f"conflict_resolution must be one of {sorted(CONFLICT_RESOLUTIONS)}")
    if not kind.strip() or not scope.strip() or not text.strip():
        raise ValueError("kind, scope, and text are required")
    if len(text) > 2000 or len(source) > 500:
        raise ValueError("memory text or source exceeds the bounded storage limit")
    if "\x00" in text or "\x00" in source or "\n" in kind or "\n" in scope:
        raise ValueError("memory metadata contains forbidden control characters")
    if stale_after_days < 0:
        raise ValueError("stale_after_days cannot be negative")
    if confidence == "confirmed" and source_type in NON_AUTHORITATIVE_SOURCE_TYPES:
        raise ValueError("non-authoritative sources cannot create confirmed memory")

    timestamp = now_iso()
    expires_at = _expires_at(sensitivity, retain_days)
    defense = memory_defense_assessment(text=text, kind=kind, source_type=source_type)
    values = (kind.strip(), scope.strip(), text.strip())
    existing = connection.execute(
        "SELECT * FROM memories WHERE kind = ? AND scope = ? AND text = ?", values
    ).fetchone()
    if existing:
        if existing["trust_level"] == "trusted" and defense["trust_level"] != "trusted":
            record_memory_event(
                connection,
                int(existing["id"]),
                "poisoning_update_rejected",
                {"attempted_source_type": source_type, **defense},
            )
            connection.commit()
            result = decorate_memory(row_to_dict(existing))
            result["deduplicated"] = True
            result["write_rejected"] = True
            result["conflict_ids"] = []
            return result
        connection.execute(
            """
            UPDATE memories
            SET confidence = ?, source = ?, stale_after_days = ?, status = 'active',
                sensitivity = ?, expires_at = ?, conflict_key = ?, source_type = ?,
                trust_level = ?, instruction_like = ?, quarantine_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                confidence,
                source.strip(),
                stale_after_days,
                sensitivity,
                expires_at,
                conflict_key.strip(),
                source_type,
                defense["trust_level"],
                int(defense["instruction_like"]),
                defense["quarantine_reason"],
                timestamp,
                existing["id"],
            ),
        )
        event = "quarantined" if defense["trust_level"] == "quarantined" else "reactivated_or_updated"
        record_memory_event(connection, int(existing["id"]), event, defense)
        if defense["trust_level"] == "quarantined":
            remove_record(connection, "memories_fts", int(existing["id"]))
        else:
            index_record(
                connection,
                "memories_fts",
                int(existing["id"]),
                f"{kind} {scope} {text} {source}",
            )
        connection.commit()
        row = connection.execute("SELECT * FROM memories WHERE id = ?", (existing["id"],)).fetchone()
        result = decorate_memory(row_to_dict(row))
        result["deduplicated"] = True
        result["conflict_ids"] = []
        return result

    conflicts: list[sqlite3.Row] = []
    if conflict_key.strip() and defense["trust_level"] != "quarantined":
        conflicts = connection.execute(
            """
            SELECT * FROM memories
            WHERE status = 'active' AND scope = ? AND conflict_key = ? AND text != ?
            ORDER BY updated_at DESC
            """,
            (scope.strip(), conflict_key.strip(), text.strip()),
        ).fetchall()
    if conflicts and conflict_resolution == "reject":
        raise ValueError(
            "active memory conflict: " + ", ".join(str(row["id"]) for row in conflicts)
        )

    supersedes_id = int(conflicts[0]["id"]) if conflicts and conflict_resolution == "replace" else None
    if conflicts and conflict_resolution == "replace":
        for conflict in conflicts:
            connection.execute(
                "UPDATE memories SET status = 'superseded', updated_at = ? WHERE id = ?",
                (timestamp, conflict["id"]),
            )
            remove_record(connection, "memories_fts", int(conflict["id"]))
            record_memory_event(
                connection, int(conflict["id"]), "superseded", {"replacement_text": text.strip()}
            )

    cursor = connection.execute(
        """
        INSERT INTO memories(
            kind, scope, text, confidence, source, created_at, updated_at,
            stale_after_days, status, sensitivity, expires_at, conflict_key, supersedes_id,
            source_type, trust_level, instruction_like, quarantine_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            *values,
            confidence,
            source.strip(),
            timestamp,
            timestamp,
            stale_after_days,
            sensitivity,
            expires_at,
            conflict_key.strip(),
            supersedes_id,
            source_type,
            defense["trust_level"],
            int(defense["instruction_like"]),
            defense["quarantine_reason"],
        ),
    )
    memory_id = int(cursor.lastrowid)
    record_memory_event(
        connection,
        memory_id,
        "quarantined" if defense["trust_level"] == "quarantined" else "created",
        {
            "conflict_ids": [int(row["id"]) for row in conflicts],
            "resolution": conflict_resolution,
            **defense,
        },
    )
    if defense["trust_level"] != "quarantined":
        index_record(connection, "memories_fts", memory_id, f"{kind} {scope} {text} {source}")
    connection.commit()
    row = connection.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    result = decorate_memory(row_to_dict(row))
    result["deduplicated"] = False
    result["conflict_ids"] = [int(item["id"]) for item in conflicts]
    result["requires_clarification"] = bool(conflicts and conflict_resolution == "flag")
    return result


def memory_governance(
    connection: sqlite3.Connection, record: dict[str, Any], requested_scope: str | None
) -> dict[str, Any]:
    conflict_key = str(record.get("conflict_key", "") or "")
    if not conflict_key:
        return {
            "same_scope_conflict_ids": [],
            "shadowed_by_ids": [],
            "requires_clarification": False,
            "non_authoritative": record.get("trust_level") != "trusted",
            "instruction_execution_allowed": False,
        }
    rows = connection.execute(
        """
        SELECT id, scope, text FROM memories
        WHERE status = 'active' AND trust_level != 'quarantined' AND conflict_key = ? AND id != ?
        """,
        (conflict_key, record["id"]),
    ).fetchall()
    same_scope = [int(row["id"]) for row in rows if row["scope"] == record["scope"] and row["text"] != record["text"]]
    shadowed_by = []
    if requested_scope and record["scope"] == "global":
        shadowed_by = [int(row["id"]) for row in rows if row["scope"] == requested_scope]
    return {
        "same_scope_conflict_ids": same_scope,
        "shadowed_by_ids": shadowed_by,
        "requires_clarification": bool(same_scope),
        "non_authoritative": record.get("trust_level") != "trusted",
        "instruction_execution_allowed": False,
    }


def search_memories(
    connection: sqlite3.Connection,
    *,
    query: str,
    scope: str | None = None,
    limit: int = 10,
    track_access: bool = True,
) -> list[dict[str, Any]]:
    query_tokens = semantic_tokens(query)
    if not query_tokens:
        return []
    candidate_ids = fts_candidate_ids(connection, "memories_fts", query)
    sql = "SELECT * FROM memories WHERE status = 'active' AND trust_level != 'quarantined'"
    params: list[Any] = []
    if scope:
        sql += " AND scope IN (?, 'global')"
        params.append(scope)
    rows = connection.execute(sql, tuple(params)).fetchall()
    if candidate_ids:
        filtered = [row for row in rows if int(row["id"]) in candidate_ids]
        rows = filtered or rows

    confidence_weight = {"confirmed": 30, "observed": 20, "inferred": 10}
    trust_weight = {"trusted": 20, "untrusted": -30}
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for row in rows:
        record = row_to_dict(row)
        haystack = f"{record['text']} {record['source']} {record['kind']} {record['scope']}"
        semantic_match = overlap_score(query_tokens, semantic_tokens(haystack))
        if not semantic_match:
            continue
        scope_weight = 50 if scope and record["scope"] == scope else 10 if record["scope"] == "global" else 0
        stale_penalty = 80 if memory_is_stale(record) else 0
        score = (
            semantic_match * 12
            + confidence_weight.get(str(record["confidence"]), 0)
            + trust_weight.get(str(record.get("trust_level", "trusted")), -30)
            + scope_weight
            + min(int(record.get("access_count", 0)), 10)
            - stale_penalty
        )
        decorated = decorate_memory(record, score=score)
        decorated["governance"] = memory_governance(connection, record, scope)
        ranked.append((score, str(record["updated_at"]), decorated))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    results = [item[2] for item in ranked[: max(1, limit)]]

    if track_access:
        timestamp = now_iso()
        for result in results:
            connection.execute(
                "UPDATE memories SET access_count = access_count + 1, last_accessed_at = ? WHERE id = ?",
                (timestamp, result["id"]),
            )
            result["access_count"] = int(result.get("access_count", 0)) + 1
            result["last_accessed_at"] = timestamp
        connection.commit()
    return results


def list_memories(
    connection: sqlite3.Connection,
    *,
    scope: str | None = None,
    limit: int = 50,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if not include_inactive:
        where.append("status = 'active'")
    if scope:
        where.append("scope = ?")
        params.append(scope)
    sql = "SELECT * FROM memories"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(max(1, limit))
    rows = connection.execute(sql, tuple(params)).fetchall()
    return [decorate_memory(row_to_dict(row)) for row in rows]


def list_quarantined_memories(
    connection: sqlite3.Connection, *, scope: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    sql = """
        SELECT id, kind, scope, source_type, quarantine_reason, length(text) AS text_chars, updated_at
        FROM memories WHERE status = 'active' AND trust_level = 'quarantined'
    """
    params: list[Any] = []
    if scope:
        sql += " AND scope = ?"
        params.append(scope)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(max(1, min(limit, 200)))
    return [
        {
            **row_to_dict(row),
            "quarantined_text_exposed": False,
            "instruction_execution_allowed": False,
        }
        for row in connection.execute(sql, tuple(params)).fetchall()
    ]


def memory_defense_status(
    connection: sqlite3.Connection, *, scope: str | None = None, limit: int = 20
) -> dict[str, Any]:
    where = "WHERE status = 'active'"
    params: list[Any] = []
    if scope:
        where += " AND scope = ?"
        params.append(scope)
    counts = {level: 0 for level in sorted(TRUST_LEVEL_VALUES)}
    for row in connection.execute(
        f"SELECT trust_level, COUNT(*) AS total FROM memories {where} GROUP BY trust_level",
        tuple(params),
    ):
        counts[str(row["trust_level"])] = int(row["total"])
    quarantine_params = list(params)
    quarantine_params.append(max(1, min(limit, 100)))
    quarantined = [
        {
            "id": int(row["id"]),
            "kind": row["kind"],
            "scope": row["scope"],
            "source_type": row["source_type"],
            "quarantine_reason": row["quarantine_reason"],
            "text_chars": len(str(row["text"])),
            "updated_at": row["updated_at"],
        }
        for row in connection.execute(
            f"SELECT id, kind, scope, source_type, quarantine_reason, text, updated_at "
            f"FROM memories {where} AND trust_level = 'quarantined' "
            "ORDER BY updated_at DESC LIMIT ?",
            tuple(quarantine_params),
        )
    ]
    return {
        "scope": scope or "all",
        "counts": counts,
        "quarantined": quarantined,
        "quarantined_text_exposed": False,
        "instruction_execution_allowed": False,
    }


def set_memory_status(
    connection: sqlite3.Connection, *, memory_id: int, status: str, reason: str = ""
) -> dict[str, Any]:
    if status not in MEMORY_STATUS_VALUES - {"active"}:
        raise ValueError("status must be superseded, retracted, or expired")
    existing = connection.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if not existing:
        raise ValueError(f"memory does not exist: {memory_id}")
    connection.execute(
        "UPDATE memories SET status = ?, updated_at = ? WHERE id = ?",
        (status, now_iso(), memory_id),
    )
    remove_record(connection, "memories_fts", memory_id)
    record_memory_event(connection, memory_id, status, {"reason": reason.strip()})
    connection.commit()
    row = connection.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    return decorate_memory(row_to_dict(row))


def hard_delete_memory(connection: sqlite3.Connection, memory_id: int) -> bool:
    remove_record(connection, "memories_fts", memory_id)
    connection.execute("DELETE FROM memory_events WHERE memory_id = ?", (memory_id,))
    cursor = connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    connection.commit()
    return cursor.rowcount == 1


def decorate_correction(record: dict[str, Any], *, score: int | None = None) -> dict[str, Any]:
    decorated = dict(record)
    try:
        edit = json.loads(str(decorated.pop("edit_json", "{}") or "{}"))
    except json.JSONDecodeError:
        edit = {}
    decorated["edit"] = edit if isinstance(edit, dict) else {}
    decorated["local_only"] = True
    decorated["expired"] = bool(
        decorated.get("expires_at")
        and str(decorated["expires_at"]) <= now_iso()
    )
    if score is not None:
        decorated["score"] = score
    return decorated


def add_correction(
    connection: sqlite3.Connection,
    *,
    scope: str,
    trigger_text: str,
    correction: str,
    severity: str = "medium",
    evidence: str = "",
    trigger_context: str = "",
    wrong_interpretation: str = "",
    correct_interpretation: str = "",
    source: str = "user-confirmed",
    edit: dict[str, Any] | None = None,
    retain_days: int | None = None,
) -> dict[str, Any]:
    if severity not in SEVERITY_VALUES:
        raise ValueError(f"severity must be one of {sorted(SEVERITY_VALUES)}")
    if not scope.strip() or not trigger_text.strip() or not correction.strip():
        raise ValueError("scope, trigger_text, and correction are required")
    bounded_fields = (
        scope,
        trigger_text,
        correction,
        evidence,
        trigger_context,
        wrong_interpretation,
        correct_interpretation,
        source,
    )
    if any(len(str(value)) > 2000 for value in bounded_fields):
        raise ValueError("correction case exceeds the bounded storage limit")
    defense = memory_defense_assessment(
        text="\n".join(str(value) for value in bounded_fields),
        kind="policy",
        source_type="user_confirmed",
    )
    if defense["trust_level"] == "quarantined":
        raise ValueError("correction rejected by memory defense: " + defense["quarantine_reason"])
    edit = dict(edit or {})
    if edit and (
        str(edit.get("field", "")) not in {"goal", "operation", "object", "constraint", "skill"}
        or not str(edit.get("replacement", "")).strip()
    ):
        raise ValueError("edit requires a supported field and a non-empty replacement")
    timestamp = now_iso()
    expires_at = _expires_at("standard", retain_days)
    values = (scope.strip(), trigger_text.strip(), correction.strip())
    existing = connection.execute(
        "SELECT * FROM corrections WHERE scope = ? AND trigger_text = ? AND correction = ?",
        values,
    ).fetchone()
    if existing:
        connection.execute(
            """
            UPDATE corrections
            SET severity = ?, evidence = ?, trigger_context = ?, wrong_interpretation = ?,
                correct_interpretation = ?, source = ?, edit_json = ?, expires_at = ?,
                status = 'active', updated_at = ?
            WHERE id = ?
            """,
            (
                severity,
                evidence.strip(),
                trigger_context.strip(),
                wrong_interpretation.strip(),
                (correct_interpretation or correction).strip(),
                source.strip() or "user-confirmed",
                json.dumps(edit, ensure_ascii=False, sort_keys=True),
                expires_at,
                timestamp,
                existing["id"],
            ),
        )
        correction_id = int(existing["id"])
        deduplicated = True
    else:
        cursor = connection.execute(
            """
            INSERT INTO corrections(
                scope, trigger_text, correction, severity, evidence, trigger_context,
                wrong_interpretation, correct_interpretation, source, edit_json,
                expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                *values,
                severity,
                evidence.strip(),
                trigger_context.strip(),
                wrong_interpretation.strip(),
                (correct_interpretation or correction).strip(),
                source.strip() or "user-confirmed",
                json.dumps(edit, ensure_ascii=False, sort_keys=True),
                expires_at,
                timestamp,
                timestamp,
            ),
        )
        correction_id = int(cursor.lastrowid)
        deduplicated = False
    index_record(
        connection,
        "corrections_fts",
        correction_id,
        " ".join(
            (
                scope,
                trigger_text,
                trigger_context,
                wrong_interpretation,
                correct_interpretation or correction,
                correction,
                evidence,
                source,
            )
        ),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM corrections WHERE id = ?", (correction_id,)).fetchone()
    result = decorate_correction(row_to_dict(row))
    result["deduplicated"] = deduplicated
    return result


def search_corrections(
    connection: sqlite3.Connection,
    *,
    query: str,
    scope: str | None = None,
    limit: int = 10,
    track_access: bool = True,
) -> list[dict[str, Any]]:
    query_tokens = semantic_tokens(query)
    if not query_tokens:
        return []
    candidate_ids = fts_candidate_ids(connection, "corrections_fts", query)
    sql = "SELECT * FROM corrections WHERE status = 'active' AND (expires_at = '' OR expires_at > ?)"
    params: list[Any] = [now_iso()]
    if scope:
        sql += " AND scope IN (?, 'global')"
        params.append(scope)
    rows = connection.execute(sql, tuple(params)).fetchall()
    if candidate_ids:
        filtered = [row for row in rows if int(row["id"]) in candidate_ids]
        rows = filtered or rows
    severity_weight = {"low": 5, "medium": 10, "high": 20, "critical": 40}
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for row in rows:
        record = row_to_dict(row)
        haystack = " ".join(
            str(record.get(key, ""))
            for key in (
                "trigger_text",
                "trigger_context",
                "wrong_interpretation",
                "correct_interpretation",
                "correction",
                "evidence",
                "source",
            )
        )
        semantic_match = overlap_score(query_tokens, semantic_tokens(haystack))
        if not semantic_match:
            continue
        scope_weight = 40 if scope and record["scope"] == scope else 5
        score = (
            semantic_match * 12
            + severity_weight.get(str(record["severity"]), 0)
            + scope_weight
            + int(record["recurred_count"]) * 5
            + int(record["heeded_count"])
        )
        ranked.append((score, str(record["updated_at"]), decorate_correction(record, score=score)))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    results = [item[2] for item in ranked[: max(1, limit)]]
    if track_access:
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
    existing = connection.execute("SELECT * FROM corrections WHERE id = ?", (correction_id,)).fetchone()
    if not existing:
        raise ValueError(f"correction does not exist: {correction_id}")
    timestamp = now_iso()
    connection.execute(
        "INSERT INTO correction_events(correction_id, outcome, context, created_at) VALUES (?, ?, ?, ?)",
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
    return decorate_correction(row_to_dict(row))


def _extract_replacement(message: str) -> str:
    for marker in ("我是说", "意思是", "应该是", "改成"):
        if marker in message:
            return message.split(marker, 1)[1].lstrip("：:，, ").strip()
    return ""


def suggest_correction(
    connection: sqlite3.Connection,
    *,
    message: str,
    scope: str = "global",
    previous_behavior: str = "",
    replacement: str = "",
    severity: str = "medium",
    trigger_context: str = "",
    wrong_interpretation: str = "",
    correct_interpretation: str = "",
    edit_field: str = "",
    edit_replacement: str = "",
    source: str = "user-natural-language-correction",
    retain_days: int | None = None,
) -> dict[str, Any]:
    if severity not in SEVERITY_VALUES:
        raise ValueError(f"severity must be one of {sorted(SEVERITY_VALUES)}")
    if not message.strip() or not scope.strip():
        raise ValueError("message and scope are required")
    replacement = replacement.strip() or _extract_replacement(message)
    if replacement:
        correction = replacement
        trigger_text = previous_behavior.strip() or message.strip()
        ready = True
    elif "太复杂" in message or "简单点" in message:
        correction = "Use a simpler, result-first response with fewer details for similar requests."
        trigger_text = previous_behavior.strip() or "Response was more complex than the user needed."
        ready = True
    elif previous_behavior.strip():
        correction = f"Avoid this behavior in similar situations: {previous_behavior.strip()}"
        trigger_text = previous_behavior.strip()
        ready = True
    else:
        correction = ""
        trigger_text = message.strip()
        ready = False
    structured_correct = (correct_interpretation or correction).strip()
    edit: dict[str, Any] = {}
    if edit_field.strip() and (edit_replacement.strip() or structured_correct):
        edit = {
            "field": edit_field.strip(),
            "replacement": edit_replacement.strip() or structured_correct,
        }
    elif structured_correct and wrong_interpretation.strip():
        edit = {"field": "goal", "replacement": structured_correct}
    expires_at = _expires_at("standard", retain_days)
    timestamp = now_iso()
    cursor = connection.execute(
        """
        INSERT INTO pending_corrections(
            scope, trigger_text, correction, severity, evidence, source_message,
            previous_behavior, ready_for_confirmation, status, created_at, updated_at,
            trigger_context, wrong_interpretation, correct_interpretation, source,
            edit_json, expires_at
        ) VALUES (?, ?, ?, ?, '', ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scope.strip(),
            trigger_text,
            correction,
            severity,
            message.strip(),
            previous_behavior.strip(),
            int(ready),
            timestamp,
            timestamp,
            trigger_context.strip() or trigger_text,
            wrong_interpretation.strip() or previous_behavior.strip(),
            structured_correct,
            source.strip() or "user-natural-language-correction",
            json.dumps(edit, ensure_ascii=False, sort_keys=True),
            expires_at,
        ),
    )
    connection.commit()
    pending_id = int(cursor.lastrowid)
    row = connection.execute("SELECT * FROM pending_corrections WHERE id = ?", (pending_id,)).fetchone()
    result = row_to_dict(row)
    result["confirmation_prompt"] = (
        f"我准备记成：{correction}。确认以后都按这条吗？"
        if ready
        else "我知道刚才理解偏了。你希望我以后具体改成怎样？"
    )
    return result


def confirm_pending_correction(connection: sqlite3.Connection, pending_id: int) -> dict[str, Any]:
    pending = connection.execute(
        "SELECT * FROM pending_corrections WHERE id = ?", (pending_id,)
    ).fetchone()
    if not pending:
        raise ValueError(f"pending correction does not exist: {pending_id}")
    if pending["status"] != "pending":
        raise ValueError(f"pending correction is already {pending['status']}")
    if not pending["ready_for_confirmation"] or not str(pending["correction"]).strip():
        raise ValueError("pending correction needs a concrete replacement before confirmation")
    correction = add_correction(
        connection,
        scope=str(pending["scope"]),
        trigger_text=str(pending["trigger_text"]),
        correction=str(pending["correction"]),
        severity=str(pending["severity"]),
        evidence=f"Confirmed from: {pending['source_message']}",
        trigger_context=str(pending["trigger_context"]),
        wrong_interpretation=str(pending["wrong_interpretation"]),
        correct_interpretation=str(pending["correct_interpretation"]),
        source="user-confirmed-natural-language-correction",
        edit=json.loads(str(pending["edit_json"] or "{}")),
        retain_days=(
            max(
                1,
                (
                    parse_iso(str(pending["expires_at"]))
                    - datetime.now(timezone.utc)
                ).days
                + 1,
            )
            if str(pending["expires_at"] or "")
            else None
        ),
    )
    connection.execute(
        "UPDATE pending_corrections SET status = 'confirmed', updated_at = ? WHERE id = ?",
        (now_iso(), pending_id),
    )
    connection.commit()
    return {"pending_id": pending_id, "status": "confirmed", "correction": correction}


def verify_execution_outcome(
    connection: sqlite3.Connection,
    *,
    scope: str,
    utterance: str,
    expected_goal: str,
    expected_operation: str,
    expected_skill: str,
    actual_goal: str,
    actual_operation: str,
    actual_skill: str,
    success: bool,
    user_confirmed_correction: bool = False,
    correction_ids: list[int] | None = None,
    retain_days: int | None = None,
) -> dict[str, Any]:
    """Compare the plan with the observed result and optionally persist a confirmed correction."""
    if not scope.strip() or not utterance.strip():
        raise ValueError("scope and utterance are required")
    comparisons = (
        ("goal", expected_goal, actual_goal),
        ("operation", expected_operation, actual_operation),
        ("skill", expected_skill, actual_skill),
    )
    mismatches = [
        {"field": field, "expected": expected, "actual": actual}
        for field, expected, actual in comparisons
        if str(expected).strip().casefold() != str(actual).strip().casefold()
    ]
    matched = bool(success and not mismatches)
    written_correction = None
    if user_confirmed_correction and mismatches:
        edit_mismatch = next(
            (item for item in mismatches if item["field"] == "operation"),
            mismatches[0],
        )
        written_correction = add_correction(
            connection,
            scope=scope,
            trigger_text=utterance,
            trigger_context=utterance,
            wrong_interpretation=expected_goal or expected_operation,
            correct_interpretation=actual_goal or actual_operation,
            correction=actual_goal or actual_operation,
            source="user-confirmed-execution-verification",
            evidence="Confirmed after comparing the compiled plan with the observed result",
            edit={
                "field": edit_mismatch["field"],
                "replacement": edit_mismatch["actual"],
            },
            retain_days=retain_days,
        )
    for correction_id in correction_ids or []:
        record_correction_outcome(
            connection,
            correction_id=int(correction_id),
            outcome="heeded" if matched else "recurred",
            context="execution verification",
        )
    timestamp = now_iso()
    cursor = connection.execute(
        """
        INSERT INTO execution_outcomes(
            scope, utterance, expected_goal, expected_operation, expected_skill,
            actual_goal, actual_operation, actual_skill, success, matched,
            mismatch_json, correction_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scope.strip(),
            utterance.strip(),
            expected_goal.strip(),
            expected_operation.strip(),
            expected_skill.strip(),
            actual_goal.strip(),
            actual_operation.strip(),
            actual_skill.strip(),
            int(success),
            int(matched),
            json.dumps(mismatches, ensure_ascii=False),
            written_correction["id"] if written_correction else None,
            timestamp,
        ),
    )
    connection.commit()
    return {
        "outcome_id": int(cursor.lastrowid),
        "matched": matched,
        "success": bool(success),
        "mismatches": mismatches,
        "written_correction": written_correction,
        "write_required_user_confirmation": True,
        "local_only": True,
    }


def reject_pending_correction(connection: sqlite3.Connection, pending_id: int) -> dict[str, Any]:
    cursor = connection.execute(
        "UPDATE pending_corrections SET status = 'rejected', updated_at = ? WHERE id = ? AND status = 'pending'",
        (now_iso(), pending_id),
    )
    connection.commit()
    return {"pending_id": pending_id, "status": "rejected", "updated": cursor.rowcount == 1}


def check_intent(
    connection: sqlite3.Connection | None,
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
    corrections = (
        search_corrections(connection, query=goal, scope=scope, limit=5, track_access=record)
        if connection is not None and table_exists(connection, "corrections")
        else []
    )
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
    if record and connection is not None:
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


def export_store(connection: sqlite3.Connection) -> dict[str, Any]:
    tables = (
        "memories",
        "memory_events",
        "corrections",
        "correction_events",
        "pending_corrections",
        "execution_outcomes",
        "intent_checks",
        "schema_migrations",
    )
    return {
        "schema_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
        "exported_at": now_iso(),
        "tables": {
            table: [row_to_dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
            for table in tables
        },
    }


def purge_store(connection: sqlite3.Connection, *, scope: str | None = None) -> dict[str, Any]:
    if scope:
        memory_ids = [
            int(row["id"]) for row in connection.execute("SELECT id FROM memories WHERE scope = ?", (scope,))
        ]
        correction_ids = [
            int(row["id"]) for row in connection.execute("SELECT id FROM corrections WHERE scope = ?", (scope,))
        ]
        for memory_id in memory_ids:
            connection.execute("DELETE FROM memory_events WHERE memory_id = ?", (memory_id,))
        for correction_id in correction_ids:
            connection.execute("DELETE FROM correction_events WHERE correction_id = ?", (correction_id,))
        connection.execute("DELETE FROM execution_outcomes WHERE scope = ?", (scope,))
        connection.execute("DELETE FROM memories WHERE scope = ?", (scope,))
        connection.execute("DELETE FROM corrections WHERE scope = ?", (scope,))
        connection.execute("DELETE FROM pending_corrections WHERE scope = ?", (scope,))
        connection.execute("DELETE FROM intent_checks WHERE scope = ?", (scope,))
    else:
        memory_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM memories")]
        correction_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM corrections")]
        for table in (
            "memory_events",
            "correction_events",
            "pending_corrections",
            "execution_outcomes",
            "intent_checks",
            "memories",
            "corrections",
        ):
            connection.execute(f"DELETE FROM {table}")
    rebuild_indexes(connection)
    connection.commit()
    return {
        "scope": scope or "all",
        "deleted_memories": len(memory_ids),
        "deleted_corrections": len(correction_ids),
    }


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
    add.add_argument("--source-type", choices=sorted(SOURCE_TYPE_VALUES), default="user_explicit")
    add.add_argument("--stale-after-days", type=int, default=0)
    add.add_argument("--sensitivity", choices=sorted(SENSITIVITY_VALUES), default="standard")
    add.add_argument("--retain-days", type=int)
    add.add_argument("--conflict-key", default="")
    add.add_argument("--on-conflict", choices=sorted(CONFLICT_RESOLUTIONS), default="flag")

    search = subparsers.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--scope")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--no-track", action="store_true")

    listing = subparsers.add_parser("list")
    listing.add_argument("--scope")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--include-inactive", action="store_true")

    quarantine = subparsers.add_parser("quarantine-list")
    quarantine.add_argument("--scope")
    quarantine.add_argument("--limit", type=int, default=50)

    defense_status = subparsers.add_parser("defense-status")
    defense_status.add_argument("--scope")
    defense_status.add_argument("--limit", type=int, default=20)

    retract = subparsers.add_parser("retract")
    retract.add_argument("--id", type=int, required=True)
    retract.add_argument("--reason", default="")

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
    correction_search.add_argument("--no-track", action="store_true")

    correction_outcome = subparsers.add_parser("correction-outcome")
    correction_outcome.add_argument("--id", type=int, required=True)
    correction_outcome.add_argument("--outcome", choices=sorted(OUTCOME_VALUES), required=True)
    correction_outcome.add_argument("--context", default="")

    correction_suggest = subparsers.add_parser("correction-suggest")
    correction_suggest.add_argument("--message", required=True)
    correction_suggest.add_argument("--scope", default="global")
    correction_suggest.add_argument("--previous-behavior", default="")
    correction_suggest.add_argument("--replacement", default="")
    correction_suggest.add_argument("--severity", choices=sorted(SEVERITY_VALUES), default="medium")

    correction_confirm = subparsers.add_parser("correction-confirm")
    correction_confirm.add_argument("--id", type=int, required=True)
    correction_reject = subparsers.add_parser("correction-reject")
    correction_reject.add_argument("--id", type=int, required=True)

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

    backup = subparsers.add_parser("backup")
    backup.add_argument("--output", type=Path)
    export = subparsers.add_parser("export")
    export.add_argument("--output", type=Path)
    purge = subparsers.add_parser("purge")
    purge.add_argument("--scope")
    purge.add_argument("--confirm", required=True)
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    connection = connect(args.db)
    try:
        if args.command == "init":
            result: Any = {
                "database": str(args.db.expanduser().resolve()),
                "initialized": True,
                "schema_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
            }
        elif args.command == "add":
            result = add_memory(
                connection,
                kind=args.kind,
                scope=args.scope,
                text=args.text,
                confidence=args.confidence,
                source=args.source,
                source_type=args.source_type,
                stale_after_days=args.stale_after_days,
                sensitivity=args.sensitivity,
                retain_days=args.retain_days,
                conflict_key=args.conflict_key,
                conflict_resolution=args.on_conflict,
            )
        elif args.command == "search":
            result = search_memories(
                connection,
                query=args.query,
                scope=args.scope,
                limit=args.limit,
                track_access=not args.no_track,
            )
        elif args.command == "list":
            result = list_memories(
                connection,
                scope=args.scope,
                limit=args.limit,
                include_inactive=args.include_inactive,
            )
        elif args.command == "quarantine-list":
            result = list_quarantined_memories(
                connection,
                scope=args.scope,
                limit=args.limit,
            )
        elif args.command == "defense-status":
            result = memory_defense_status(
                connection,
                scope=args.scope,
                limit=args.limit,
            )
        elif args.command == "retract":
            result = set_memory_status(
                connection, memory_id=args.id, status="retracted", reason=args.reason
            )
        elif args.command == "delete":
            result = {"id": args.id, "deleted": hard_delete_memory(connection, args.id)}
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
                connection,
                query=args.query,
                scope=args.scope,
                limit=args.limit,
                track_access=not args.no_track,
            )
        elif args.command == "correction-outcome":
            result = record_correction_outcome(
                connection,
                correction_id=args.id,
                outcome=args.outcome,
                context=args.context,
            )
        elif args.command == "correction-suggest":
            result = suggest_correction(
                connection,
                message=args.message,
                scope=args.scope,
                previous_behavior=args.previous_behavior,
                replacement=args.replacement,
                severity=args.severity,
            )
        elif args.command == "correction-confirm":
            result = confirm_pending_correction(connection, args.id)
        elif args.command == "correction-reject":
            result = reject_pending_correction(connection, args.id)
        elif args.command == "intent-check":
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
        elif args.command == "backup":
            path = backup_database(connection, args.output)
            result = {"backup": str(path), "created": True}
        elif args.command == "export":
            result = export_store(connection)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                result = {"export": str(args.output.resolve()), "created": True}
        else:
            expected = f"PURGE:{args.scope}" if args.scope else "PURGE:ALL"
            if args.confirm != expected:
                raise ValueError(f"purge requires --confirm {expected}")
            backup = backup_database(connection)
            result = purge_store(connection, scope=args.scope)
            result["backup"] = str(backup)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
