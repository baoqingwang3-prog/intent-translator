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


PLUGIN_API_VERSION = 1
MARKER_PREFIX = "context-ref:sha256:"
MAX_PREVIEW_CHARS = 500
MIN_HASH_PREFIX_CHARS = 16
MAX_ID_CHARS = 200
MAX_SUMMARY_CHARS = 1000
MAX_SOURCE_POINTER_CHARS = 2000


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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS context_sources (
            content_hash TEXT NOT NULL,
            source_pointer TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(content_hash, source_pointer)
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
        section_id = str(section.get("id", index)).strip()
        source = str(section.get("source_pointer", section.get("source", ""))).strip()
        summary = str(section.get("summary", "")).strip()
        if not section_id or len(section_id) > MAX_ID_CHARS:
            raise ValueError(f"section {index} id must contain at most {MAX_ID_CHARS} characters")
        if len(source) > MAX_SOURCE_POINTER_CHARS:
            raise ValueError(f"section {index} source pointer exceeds {MAX_SOURCE_POINTER_CHARS} characters")
        if len(summary) > MAX_SUMMARY_CHARS:
            raise ValueError(f"section {index} summary exceeds {MAX_SUMMARY_CHARS} characters")
        normalized.append(
            {
                "id": section_id,
                "content": section["content"],
                "source": source,
                "summary": summary,
            }
        )
    return normalized


def pack_sections(
    connection: sqlite3.Connection, sections: list[dict[str, str]], *, preview_chars: int = 120
) -> list[dict[str, Any]]:
    preview_chars = max(0, min(int(preview_chars), MAX_PREVIEW_CHARS))
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
        if section["source"]:
            connection.execute(
                """
                INSERT OR IGNORE INTO context_sources(content_hash, source_pointer, created_at)
                VALUES (?, ?, ?)
                """,
                (digest, section["source"], now_iso()),
            )
        preview = " ".join(section["content"].split())[:preview_chars]
        summary = " ".join(section.get("summary", "").split()) or preview
        marker = f"[{MARKER_PREFIX}{digest}]"
        manifest.append(
            {
                "id": section["id"],
                "marker": marker,
                "content_hash": digest,
                "source_pointer": section["source"],
                "characters": len(section["content"]),
                "preview": preview,
                "summary": summary,
                "compact_text": f"{summary} {marker}".strip(),
            }
        )
    connection.commit()
    return manifest


def retrieve(connection: sqlite3.Connection, digest_or_prefix: str) -> dict[str, Any]:
    digest_or_prefix = digest_or_prefix.strip().casefold()
    if digest_or_prefix.startswith("[") and digest_or_prefix.endswith("]"):
        digest_or_prefix = digest_or_prefix[1:-1]
    if digest_or_prefix.startswith(MARKER_PREFIX):
        digest_or_prefix = digest_or_prefix[len(MARKER_PREFIX):]
    if not digest_or_prefix or any(character not in "0123456789abcdef" for character in digest_or_prefix):
        raise ValueError("context hash must be a hexadecimal SHA-256 prefix or marker")
    if len(digest_or_prefix) < MIN_HASH_PREFIX_CHARS:
        raise ValueError(f"context hash prefix must contain at least {MIN_HASH_PREFIX_CHARS} characters")
    rows = connection.execute(
        "SELECT * FROM context_blobs WHERE content_hash LIKE ? ORDER BY content_hash LIMIT 2",
        (f"{digest_or_prefix}%",),
    ).fetchall()
    if not rows:
        raise ValueError("context hash not found")
    if len(rows) > 1:
        raise ValueError("context hash prefix is ambiguous")
    result = dict(rows[0])
    actual = hashlib.sha256(result["content"].encode("utf-8")).hexdigest()
    legacy_source = result.pop("source")
    source_pointers = [
        row[0]
        for row in connection.execute(
            "SELECT source_pointer FROM context_sources WHERE content_hash = ? ORDER BY created_at, source_pointer",
            (result["content_hash"],),
        ).fetchall()
    ]
    if legacy_source and legacy_source not in source_pointers:
        source_pointers.insert(0, legacy_source)
    result["source_pointer"] = source_pointers[0] if source_pointers else ""
    result["source_pointers"] = source_pointers
    result["integrity_verified"] = actual == result["content_hash"]
    if not result["integrity_verified"]:
        raise ValueError("stored context failed SHA-256 integrity verification")
    return result


def invoke(operation: str, payload: dict[str, Any], state_path: Path) -> dict[str, Any]:
    connection = connect(state_path)
    try:
        if operation == "pack":
            return {
                "sections": pack_sections(
                    connection,
                    normalize_sections(payload),
                    preview_chars=payload.get("preview_chars", 120),
                )
            }
        if operation == "get":
            return retrieve(connection, str(payload.get("hash", payload.get("marker", ""))))
        raise ValueError(f"unsupported operation: {operation}")
    finally:
        connection.close()


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
