#!/usr/bin/env python3
"""Host-neutral session start/end storage for optional lifecycle hooks."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PLUGIN_API_VERSION = 1
MAX_PROJECT_CHARS = 200
MAX_SUMMARY_CHARS = 4000
MAX_NEXT_ACTION_CHARS = 1000
MAX_LIST_ITEMS = 20
MAX_ITEM_CHARS = 1000
MAX_SNAPSHOTS_PER_PROJECT = 200


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: Path) -> sqlite3.Connection:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS session_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            summary TEXT NOT NULL,
            next_action TEXT NOT NULL DEFAULT '',
            decisions TEXT NOT NULL DEFAULT '[]',
            corrections TEXT NOT NULL DEFAULT '[]',
            tags TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        )
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(session_snapshots)")}
    for name in ("corrections", "tags"):
        if name not in columns:
            connection.execute(
                f"ALTER TABLE session_snapshots ADD COLUMN {name} TEXT NOT NULL DEFAULT '[]'"
            )
    connection.commit()
    return connection


def _bounded_text(value: Any, field: str, limit: int, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{field} is required")
    if len(value) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return value


def _bounded_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_LIST_ITEMS:
        raise ValueError(f"{field} must be a list with at most {MAX_LIST_ITEMS} items")
    return [_bounded_text(item, field, MAX_ITEM_CHARS, required=True) for item in value]


def _decoded(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for field in ("decisions", "corrections", "tags"):
        result[field] = json.loads(result.get(field, "[]"))
    return result


def save_snapshot(
    connection: sqlite3.Connection,
    *,
    project: str,
    summary: str,
    next_action: str = "",
    decisions: list[str] | None = None,
    corrections: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    project = _bounded_text(project, "project", MAX_PROJECT_CHARS, required=True)
    summary = _bounded_text(summary, "summary", MAX_SUMMARY_CHARS, required=True)
    next_action = _bounded_text(next_action, "next_action", MAX_NEXT_ACTION_CHARS)
    decisions = _bounded_list(decisions, "decisions")
    corrections = _bounded_list(corrections, "corrections")
    tags = _bounded_list(tags, "tags")
    cursor = connection.execute(
        """
        INSERT INTO session_snapshots(
            project, summary, next_action, decisions, corrections, tags, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project,
            summary,
            next_action,
            json.dumps(decisions, ensure_ascii=False),
            json.dumps(corrections, ensure_ascii=False),
            json.dumps(tags, ensure_ascii=False),
            now_iso(),
        ),
    )
    connection.execute(
        """
        DELETE FROM session_snapshots
        WHERE project = ? AND id NOT IN (
            SELECT id FROM session_snapshots
            WHERE project = ? ORDER BY created_at DESC, id DESC LIMIT ?
        )
        """,
        (project, project, MAX_SNAPSHOTS_PER_PROJECT),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM session_snapshots WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _decoded(row)


def load_snapshot(connection: sqlite3.Connection, *, project: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT * FROM session_snapshots
        WHERE project = ? ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        (project.strip(),),
    ).fetchone()
    if not row:
        return None
    return _decoded(row)


def load_relevant_snapshots(
    connection: sqlite3.Connection,
    *,
    project: str,
    query: str = "",
    limit: int = 3,
) -> list[dict[str, Any]]:
    project = _bounded_text(project, "project", MAX_PROJECT_CHARS, required=True)
    query = _bounded_text(query, "query", 2000)
    limit = max(1, min(int(limit), 5))
    rows = connection.execute(
        """
        SELECT * FROM session_snapshots
        WHERE project = ? ORDER BY created_at DESC, id DESC LIMIT 50
        """,
        (project,),
    ).fetchall()
    snapshots = [_decoded(row) for row in rows]
    terms = {item.casefold() for item in re.findall(r"[A-Za-z0-9_]{2,}", query)}
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", query):
        terms.add(run)
        terms.update(run[index:index + 2] for index in range(len(run) - 1))
    if terms:
        def score(item: dict[str, Any]) -> int:
            searchable = " ".join(
                [
                    item["summary"],
                    item["next_action"],
                    *item["decisions"],
                    *item["corrections"],
                    *item["tags"],
                ]
            ).casefold()
            return sum(searchable.count(term) for term in terms)

        snapshots.sort(key=lambda item: (score(item), item["created_at"], item["id"]), reverse=True)
    return snapshots[:limit]


def invoke(operation: str, payload: dict[str, Any], state_path: Path) -> dict[str, Any]:
    connection = connect(state_path)
    try:
        if operation == "session_start":
            snapshots = load_relevant_snapshots(
                connection,
                project=payload.get("project", ""),
                query=payload.get("query", ""),
                limit=payload.get("limit", 3),
            )
            return {
                "project": payload.get("project", ""),
                "snapshots": snapshots,
                "loaded_count": len(snapshots),
                "max_loaded": 5,
            }
        if operation == "session_end":
            return save_snapshot(
                connection,
                project=payload.get("project", ""),
                summary=payload.get("summary", ""),
                next_action=payload.get("next_action", ""),
                decisions=payload.get("decisions"),
                corrections=payload.get("corrections"),
                tags=payload.get("tags"),
            )
        raise ValueError(f"unsupported operation: {operation}")
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--project", required=True)
    start.add_argument("--query", default="")
    start.add_argument("--limit", type=int, default=3)
    end = subparsers.add_parser("end")
    end.add_argument("--project", required=True)
    end.add_argument("--summary", required=True)
    end.add_argument("--next-action", default="")
    end.add_argument("--decision", action="append", default=[])
    end.add_argument("--correction", action="append", default=[])
    end.add_argument("--tag", action="append", default=[])
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    connection = connect(args.db)
    try:
        if args.command == "start":
            snapshots = load_relevant_snapshots(
                connection,
                project=args.project,
                query=args.query,
                limit=args.limit,
            )
            result: Any = {"project": args.project, "snapshots": snapshots, "loaded_count": len(snapshots)}
        else:
            result = save_snapshot(
                connection,
                project=args.project,
                summary=args.summary,
                next_action=args.next_action,
                decisions=args.decision,
                corrections=args.correction,
                tags=args.tag,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
