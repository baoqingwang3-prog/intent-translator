#!/usr/bin/env python3
"""Store exact context sections by hash and emit compact reversible markers."""

from __future__ import annotations

import argparse
import hashlib
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
        CREATE TABLE IF NOT EXISTS context_blobs (
            content_hash TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def normalize_sections(payload: Any) -> list[dict[str, str]]:
    sections = payload.get("sections") if isinstance(payload, dict) else payload
    if not isinstance(sections, list):
        raise ValueError("input must be a list or an object containing a sections list")
    normalized: list[dict[str, str]] = []
    for index, section in enumerate(sections, start=1):
        if not isinstance(section, dict) or not isinstance(section.get("content"), str):
            raise ValueError(f"section {index} requires string content")
        normalized.append(
            {
                "id": str(section.get("id", index)),
                "content": section["content"],
                "source": str(section.get("source", "")),
            }
        )
    return normalized


def pack_sections(
    connection: sqlite3.Connection, sections: list[dict[str, str]], *, preview_chars: int = 120
) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for section in sections:
        digest = hashlib.sha256(section["content"].encode("utf-8")).hexdigest()
        connection.execute(
            """
            INSERT OR IGNORE INTO context_blobs(content_hash, content, source, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (digest, section["content"], section["source"], now_iso()),
        )
        preview = " ".join(section["content"].split())[: max(0, preview_chars)]
        manifest.append(
            {
                "id": section["id"],
                "marker": f"[context:{digest}]",
                "content_hash": digest,
                "source": section["source"],
                "characters": len(section["content"]),
                "preview": preview,
            }
        )
    connection.commit()
    return manifest


def retrieve(connection: sqlite3.Connection, digest_or_prefix: str) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT * FROM context_blobs WHERE content_hash LIKE ? ORDER BY content_hash LIMIT 2",
        (f"{digest_or_prefix}%",),
    ).fetchall()
    if not rows:
        raise ValueError("context hash not found")
    if len(rows) > 1:
        raise ValueError("context hash prefix is ambiguous")
    return dict(rows[0])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    pack = subparsers.add_parser("pack")
    pack.add_argument("--input", type=Path, help="JSON file; defaults to stdin")
    pack.add_argument("--preview-chars", type=int, default=120)
    get = subparsers.add_parser("get")
    get.add_argument("--hash", required=True)
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    connection = connect(args.store)
    try:
        if args.command == "pack":
            raw = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
            result: Any = {
                "sections": pack_sections(
                    connection,
                    normalize_sections(json.loads(raw)),
                    preview_chars=args.preview_chars,
                )
            }
        else:
            result = retrieve(connection, args.hash)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
