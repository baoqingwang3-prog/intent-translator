#!/usr/bin/env python3
"""Host-neutral session start/end storage for optional lifecycle hooks."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
            created_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def save_snapshot(
    connection: sqlite3.Connection,
    *,
    project: str,
    summary: str,
    next_action: str = "",
    decisions: list[str] | None = None,
) -> dict[str, Any]:
    cursor = connection.execute(
        """
        INSERT INTO session_snapshots(project, summary, next_action, decisions, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (project.strip(), summary.strip(), next_action.strip(), json.dumps(decisions or []), now_iso()),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM session_snapshots WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    result = dict(row)
    result["decisions"] = json.loads(result["decisions"])
    return result


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
    result = dict(row)
    result["decisions"] = json.loads(result["decisions"])
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--project", required=True)
    end = subparsers.add_parser("end")
    end.add_argument("--project", required=True)
    end.add_argument("--summary", required=True)
    end.add_argument("--next-action", default="")
    end.add_argument("--decision", action="append", default=[])
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    connection = connect(args.db)
    try:
        if args.command == "start":
            result: Any = {"project": args.project, "latest": load_snapshot(connection, project=args.project)}
        else:
            result = save_snapshot(
                connection,
                project=args.project,
                summary=args.summary,
                next_action=args.next_action,
                decisions=args.decision,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
