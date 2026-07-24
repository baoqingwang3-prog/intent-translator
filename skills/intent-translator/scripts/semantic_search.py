#!/usr/bin/env python3
"""Dependency-free FTS5 indexing and Chinese n-gram scoring helpers."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from typing import Any, Iterable


ASCII_WORD_RE = re.compile(r"[a-z0-9_+-]+", re.IGNORECASE)
CJK_RUN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().strip()


def semantic_tokens(text: str) -> set[str]:
    """Return ASCII words plus CJK unigrams, bigrams, and trigrams."""
    normalized = normalize_text(text)
    tokens = set(ASCII_WORD_RE.findall(normalized))
    for run in CJK_RUN_RE.findall(normalized):
        tokens.add(run)
        tokens.update(run[index : index + 1] for index in range(len(run)))
        for size in (2, 3):
            if len(run) >= size:
                tokens.update(run[index : index + size] for index in range(len(run) - size + 1))
    return {token for token in tokens if token}


def token_weight(token: str) -> int:
    if ASCII_WORD_RE.fullmatch(token):
        return 4
    if len(token) >= 3:
        return 4
    if len(token) == 2:
        return 2
    return 1


def overlap_score(query_tokens: set[str], record_tokens: set[str]) -> int:
    return sum(token_weight(token) for token in query_tokens & record_tokens)


def ensure_fts(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts "
            "USING fts5(record_id UNINDEXED, terms, tokenize='unicode61')"
        )
        connection.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS corrections_fts "
            "USING fts5(record_id UNINDEXED, terms, tokenize='unicode61')"
        )
        return True
    except sqlite3.OperationalError:
        return False


def fts_available(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def index_record(connection: sqlite3.Connection, table: str, record_id: int, text: str) -> None:
    if not fts_available(connection, table):
        return
    connection.execute(f"DELETE FROM {table} WHERE record_id = ?", (record_id,))
    terms = " ".join(sorted(semantic_tokens(text)))
    connection.execute(
        f"INSERT INTO {table}(record_id, terms) VALUES (?, ?)", (record_id, terms)
    )


def remove_record(connection: sqlite3.Connection, table: str, record_id: int) -> None:
    if fts_available(connection, table):
        connection.execute(f"DELETE FROM {table} WHERE record_id = ?", (record_id,))


def rebuild_indexes(connection: sqlite3.Connection) -> None:
    if not ensure_fts(connection):
        return
    connection.execute("DELETE FROM memories_fts")
    connection.execute("DELETE FROM corrections_fts")
    for row in connection.execute(
        "SELECT id, kind, scope, text, source FROM memories WHERE status = 'active'"
    ):
        index_record(
            connection,
            "memories_fts",
            int(row["id"]),
            f"{row['kind']} {row['scope']} {row['text']} {row['source']}",
        )
    for row in connection.execute(
        "SELECT id, scope, trigger_text, correction, evidence FROM corrections WHERE status = 'active'"
    ):
        index_record(
            connection,
            "corrections_fts",
            int(row["id"]),
            f"{row['scope']} {row['trigger_text']} {row['correction']} {row['evidence']}",
        )


def fts_candidate_ids(
    connection: sqlite3.Connection, table: str, query: str, *, limit: int = 200
) -> set[int]:
    if not fts_available(connection, table):
        return set()
    tokens = sorted(semantic_tokens(query), key=lambda item: (token_weight(item), len(item)), reverse=True)
    useful = [token for token in tokens if len(token) > 1 or ASCII_WORD_RE.fullmatch(token)][:24]
    if not useful:
        useful = tokens[:12]
    if not useful:
        return set()
    expression = " OR ".join('"' + token.replace('"', '""') + '"' for token in useful)
    try:
        rows = connection.execute(
            f"SELECT record_id FROM {table} WHERE {table} MATCH ? LIMIT ?",
            (expression, max(1, limit)),
        ).fetchall()
    except sqlite3.OperationalError:
        return set()
    return {int(row["record_id"]) for row in rows}


def rank_texts(query: str, records: Iterable[dict[str, Any]], text_key: str) -> list[tuple[int, dict[str, Any]]]:
    query_tokens = semantic_tokens(query)
    ranked = []
    for record in records:
        score = overlap_score(query_tokens, semantic_tokens(str(record[text_key])))
        if score:
            ranked.append((score, record))
    return sorted(ranked, key=lambda item: item[0], reverse=True)
