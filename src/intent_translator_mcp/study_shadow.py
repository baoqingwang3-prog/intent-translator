"""Private shadow evaluation and study-material pointer storage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def study_db_path(profile: dict[str, Any]) -> Path:
    configured = os.environ.get("INTENT_TRANSLATOR_STUDY_DB") or os.environ.get("INTENT_TRANSLATOR_MEMORY_DB")
    location = configured or profile.get("memory", {}).get("location")
    return Path(location).expanduser() if location else Path.home() / ".intent-translator" / "memory.db"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS shadow_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            utterance_hash TEXT NOT NULL,
            utterance_preview TEXT NOT NULL,
            compiler_mode TEXT NOT NULL,
            compiler_skill TEXT NOT NULL,
            compiler_clarification INTEGER NOT NULL,
            host_mode TEXT NOT NULL,
            host_skill TEXT NOT NULL,
            host_clarification INTEGER NOT NULL,
            intent_mismatch INTEGER NOT NULL,
            skill_mismatch INTEGER NOT NULL,
            clarification_mismatch INTEGER NOT NULL,
            unnecessary_clarification INTEGER NOT NULL,
            context_switch_cost INTEGER NOT NULL,
            pointer_reused INTEGER NOT NULL,
            subject TEXT NOT NULL,
            exam_goal TEXT NOT NULL,
            sample_reason TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_shadow_events_created_at ON shadow_events(created_at);

        CREATE TABLE IF NOT EXISTS study_pointers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            purpose TEXT NOT NULL,
            subject TEXT NOT NULL,
            exam_goal TEXT NOT NULL,
            authority_level TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            reuse_count INTEGER NOT NULL DEFAULT 0,
            last_used_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_study_pointers_subject ON study_pointers(subject, exam_goal);
        """
    )
    connection.commit()
    return connection


def _positive_int(value: Any, default: int, maximum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        value = default
    return min(value, maximum) if maximum is not None else value


def _redacted_preview(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    compact = " ".join(text.split())
    compact = re.sub(r"[A-Za-z]:\\[^\s]+", "[LOCAL_PATH]", compact)
    compact = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", compact)
    compact = re.sub(r"(?i)(api[_ -]?key|token|password)\s*[:=]\s*\S+", r"\1=[REDACTED]", compact)
    return compact[:limit]


def _event_hash(profile: dict[str, Any], utterance: str) -> str:
    salt = str(profile.get("profile_id", "local-profile"))
    normalized = " ".join(utterance.casefold().split())
    return hashlib.sha256(f"{salt}\0{normalized}".encode("utf-8")).hexdigest()


def _shadow_settings(profile: dict[str, Any]) -> dict[str, Any]:
    configured = profile.get("shadow_evaluation", {})
    return {
        "enabled": bool(configured.get("enabled", False)),
        "retention_days": _positive_int(configured.get("retention_days"), 30, 3650),
        "max_events": _positive_int(configured.get("max_events"), 500, 100_000),
        "preview_chars": min(_positive_int(configured.get("preview_chars"), 1, 120), 120)
        if configured.get("preview_chars")
        else 0,
    }


def prune_shadow_events(connection: sqlite3.Connection, *, retention_days: int, max_events: int) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).replace(microsecond=0).isoformat()
    connection.execute("DELETE FROM shadow_events WHERE created_at < ?", (cutoff,))
    connection.execute(
        "DELETE FROM shadow_events WHERE id NOT IN (SELECT id FROM shadow_events ORDER BY id DESC LIMIT ?)",
        (max_events,),
    )
    connection.commit()


def observe_shadow(
    connection: sqlite3.Connection,
    profile: dict[str, Any],
    *,
    utterance: str,
    compiler_mode: str,
    compiler_skill: str = "",
    compiler_clarification: bool = False,
    host_mode: str,
    host_skill: str = "",
    host_clarification: bool = False,
    subject: str = "",
    exam_goal: str = "",
    context_switched: bool = False,
    pointer_reused: bool = False,
    sample_reason: str = "ambiguous-or-study-routing",
) -> dict[str, Any]:
    settings = _shadow_settings(profile)
    if not settings["enabled"]:
        return {"recorded": False, "reason": "shadow evaluation disabled"}
    intent_mismatch = compiler_mode != host_mode
    skill_mismatch = (compiler_skill or "") != (host_skill or "")
    clarification_mismatch = bool(compiler_clarification) != bool(host_clarification)
    unnecessary_clarification = bool(host_clarification) and not bool(compiler_clarification)
    cursor = connection.execute(
        """
        INSERT INTO shadow_events (
            created_at, utterance_hash, utterance_preview,
            compiler_mode, compiler_skill, compiler_clarification,
            host_mode, host_skill, host_clarification,
            intent_mismatch, skill_mismatch, clarification_mismatch,
            unnecessary_clarification, context_switch_cost, pointer_reused,
            subject, exam_goal, sample_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now_iso(),
            _event_hash(profile, utterance),
            _redacted_preview(utterance, settings["preview_chars"]),
            compiler_mode,
            compiler_skill,
            int(compiler_clarification),
            host_mode,
            host_skill,
            int(host_clarification),
            int(intent_mismatch),
            int(skill_mismatch),
            int(clarification_mismatch),
            int(unnecessary_clarification),
            int(context_switched),
            int(pointer_reused),
            subject,
            exam_goal,
            sample_reason,
        ),
    )
    connection.commit()
    prune_shadow_events(connection, retention_days=settings["retention_days"], max_events=settings["max_events"])
    return {
        "recorded": True,
        "event_id": cursor.lastrowid,
        "differences": {
            "intent": intent_mismatch,
            "skill_routing": skill_mismatch,
            "clarification": clarification_mismatch,
            "unnecessary_clarification": unnecessary_clarification,
            "study_context_switch_cost": bool(context_switched),
            "material_pointer_reused": bool(pointer_reused),
        },
        "privacy": "No full utterance is stored; preview storage is controlled by the local profile.",
    }


def review_shadow(connection: sqlite3.Connection, *, days: int = 30) -> dict[str, Any]:
    days = max(1, min(days, 365))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    row = connection.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(intent_mismatch), 0) AS intent_mismatches,
            COALESCE(SUM(skill_mismatch), 0) AS skill_mismatches,
            COALESCE(SUM(clarification_mismatch), 0) AS clarification_mismatches,
            COALESCE(SUM(unnecessary_clarification), 0) AS unnecessary_clarifications,
            COALESCE(SUM(context_switch_cost), 0) AS context_switch_costs,
            COALESCE(SUM(pointer_reused), 0) AS pointer_reuses
        FROM shadow_events WHERE created_at >= ?
        """,
        (cutoff,),
    ).fetchone()
    total = int(row["total"])
    counts = {key: int(row[key]) for key in row.keys() if key != "total"}
    rates = {key: round(value / total, 4) if total else 0.0 for key, value in counts.items()}
    recommendations: list[str] = []
    if rates["skill_mismatches"] >= 0.2:
        recommendations.append("Refine profile routing terms or preferred Skill order.")
    if rates["unnecessary_clarifications"] >= 0.15:
        recommendations.append("Proceed more often on reversible in-scope study actions.")
    if counts["context_switch_costs"]:
        recommendations.append("Batch nonurgent maintenance until the study session ends.")
    if total and rates["pointer_reuses"] < 0.2:
        recommendations.append("Check the study pointer index before asking for materials again.")
    return {"days": days, "events": total, "counts": counts, "rates": rates, "recommendations": recommendations}


def upsert_pointer(
    connection: sqlite3.Connection,
    *,
    path: str,
    title: str,
    purpose: str = "",
    subject: str = "",
    exam_goal: str = "",
    authority_level: str = "working",
) -> dict[str, Any]:
    if not path.strip() or not title.strip():
        raise ValueError("path and title are required")
    timestamp = now_iso()
    connection.execute(
        """
        INSERT INTO study_pointers(path, title, purpose, subject, exam_goal, authority_level, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            title=excluded.title,
            purpose=excluded.purpose,
            subject=excluded.subject,
            exam_goal=excluded.exam_goal,
            authority_level=excluded.authority_level,
            updated_at=excluded.updated_at
        """,
        (path.strip(), title.strip(), purpose.strip(), subject.strip(), exam_goal.strip(), authority_level.strip(), timestamp),
    )
    connection.commit()
    return dict(connection.execute("SELECT * FROM study_pointers WHERE path = ?", (path.strip(),)).fetchone())


def list_pointers(
    connection: sqlite3.Connection,
    *,
    query: str = "",
    subject: str = "",
    exam_goal: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    if query.strip():
        clauses.append("(title LIKE ? OR purpose LIKE ? OR path LIKE ?)")
        needle = f"%{query.strip()}%"
        values.extend([needle, needle, needle])
    if subject.strip():
        clauses.append("subject = ?")
        values.append(subject.strip())
    if exam_goal.strip():
        clauses.append("exam_goal = ?")
        values.append(exam_goal.strip())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    values.append(max(1, min(100, limit)))
    rows = connection.execute(
        f"SELECT * FROM study_pointers {where} ORDER BY reuse_count DESC, updated_at DESC LIMIT ?",
        values,
    ).fetchall()
    return [dict(row) for row in rows]


def reuse_pointer(connection: sqlite3.Connection, *, path: str) -> dict[str, Any] | None:
    connection.execute(
        "UPDATE study_pointers SET reuse_count = reuse_count + 1, last_used_at = ? WHERE path = ?",
        (now_iso(), path.strip()),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM study_pointers WHERE path = ?", (path.strip(),)).fetchone()
    return dict(row) if row else None


def _wikilink_text(value: str) -> str:
    return value.replace("]]", "] ]").replace("|", "-").strip()


def render_pointer_index(pointers: list[dict[str, Any]]) -> str:
    lines = [
        "# 意图中枢学习索引",
        "",
        "> 此页由 intent-translator 管理，只保存资料指针，不复制学习内容，也不扫描整个仓库。",
        "",
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for pointer in pointers:
        grouped.setdefault(pointer.get("exam_goal") or "未分类目标", []).append(pointer)
    if not grouped:
        lines.append("暂无已登记资料。")
    for goal, items in grouped.items():
        lines.extend([f"## {goal}", ""])
        for item in items:
            details = " / ".join(
                str(part) for part in (item.get("subject"), item.get("purpose"), item.get("authority_level")) if part
            )
            path = _wikilink_text(str(item["path"])).removesuffix(".md")
            title = _wikilink_text(str(item["title"]))
            lines.append(f"- [[{path}|{title}]]" + (f"：{details}" if details else ""))
        lines.append("")
    lines.extend(["---", f"更新时间：{now_iso()}", ""])
    return "\n".join(lines)


def sync_pointer_index(
    profile: dict[str, Any],
    content: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    settings = profile.get("knowledge_pointers", {})
    note = str(settings.get("managed_note", "AI/意图中枢-学习索引.md")).replace("\\", "/").lstrip("/")
    vault_name = str(settings.get("vault_name", "")).strip()
    executable = shutil.which("obsidian")
    if executable and vault_name:
        escaped_content = content.replace("\n", "\\n")
        result = runner(
            [
                executable,
                f"vault={vault_name}",
                "create",
                f"path={note}",
                f"content={escaped_content}",
                "silent",
                "overwrite",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        if result.returncode == 0:
            return {"synced": True, "method": "obsidian-cli", "note": note, "vault": vault_name}
    vault_path = str(settings.get("vault_path", "")).strip()
    if not vault_path:
        return {"synced": False, "reason": "No available Obsidian CLI target or local vault path", "note": note}
    root = Path(vault_path).expanduser().resolve()
    target = (root / note).resolve()
    if root != target and root not in target.parents:
        raise ValueError("managed note escapes configured vault path")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")
    return {"synced": True, "method": "direct-local-file", "note": note, "vault": vault_name}


def _load_profile(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.expanduser().read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise SystemExit(f"profile not found: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"profile cannot be read: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("profile root must be a JSON object")
    return payload


def main() -> int:
    if hasattr(os.sys.stdout, "reconfigure"):
        os.sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("pointer-list", "pointer-sync", "shadow-review"))
    parser.add_argument("--profile", type=Path, default=Path.home() / ".intent-translator" / "profile.json")
    parser.add_argument("--query", default="")
    parser.add_argument("--subject", default="")
    parser.add_argument("--exam-goal", default="")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    profile = _load_profile(args.profile)
    connection = connect(study_db_path(profile))
    try:
        if args.command == "shadow-review":
            result = review_shadow(connection, days=args.days)
        else:
            pointers = list_pointers(
                connection,
                query=args.query,
                subject=args.subject,
                exam_goal=args.exam_goal,
                limit=100,
            )
            result = {"pointers": pointers, "count": len(pointers)}
            if args.command == "pointer-sync":
                result = {**sync_pointer_index(profile, render_pointer_index(pointers)), "pointer_count": len(pointers)}
    finally:
        connection.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
