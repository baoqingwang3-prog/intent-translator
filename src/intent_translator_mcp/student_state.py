"""Local-only university state for goals, deadlines, focus, and next actions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CATEGORIES = {
    "goal",
    "course",
    "assignment",
    "exam",
    "research",
    "project",
    "career",
    "campus",
    "routine",
    "wellbeing",
    "finance",
}
STATUSES = {"planned", "active", "blocked", "waiting", "done", "archived"}
PRIORITIES = {"low", "medium", "high", "critical"}
PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
MAX_TEXT_LENGTHS = {
    "item_key": 200,
    "title": 500,
    "next_action": 2000,
    "subject": 200,
    "goal": 500,
    "source_pointer": 1000,
    "details": 4000,
}
PERSISTENCE_ATTACK_PATTERNS = (
    re.compile(r"\b(?:ignore|disregard|override)\b.{0,80}\b(?:previous|system|developer|safety|instructions?)\b", re.I),
    re.compile(r"\b(?:reveal|print|show|expose)\b.{0,80}\b(?:system prompt|developer message|api key|token|password|secret)\b", re.I),
    re.compile(r"\b(?:bypass|disable|evade)\b.{0,80}\b(?:safety|authorization|permissions?)\b", re.I),
    re.compile(r"(?:忽略|无视|覆盖).{0,30}(?:之前|系统|开发者|安全|指令|规则)"),
    re.compile(r"(?:泄露|显示|输出).{0,30}(?:系统提示词|开发者消息|隐藏指令|密钥|令牌|密码)"),
    re.compile(r"(?:绕过|关闭).{0,30}(?:安全|策略|授权|权限)"),
    re.compile(r"(?:不用|无需|不必).{0,12}(?:确认|询问|授权|许可).{0,30}(?:发布|删除|外发|付款|购买|上传)"),
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def state_db_path(profile: dict[str, Any]) -> Path:
    configured = (
        os.environ.get("INTENT_TRANSLATOR_STATE_DB")
        or os.environ.get("INTENT_TRANSLATOR_MEMORY_DB")
    )
    location = configured or profile.get("memory", {}).get("location")
    return Path(location).expanduser() if location else Path.home() / ".intent-translator" / "memory.db"


def canonical_state_path(profile: dict[str, Any]) -> Path:
    configured = os.environ.get("INTENT_TRANSLATOR_STATE_MARKDOWN")
    if configured:
        return Path(configured).expanduser()
    settings = profile.get("student_state", {})
    local_path = str(settings.get("local_path", "")).strip()
    if local_path:
        return Path(local_path).expanduser()
    vault_path = str(profile.get("knowledge_pointers", {}).get("vault_path", "")).strip()
    managed_note = str(settings.get("managed_note", "AI/university-state.md")).replace("\\", "/").lstrip("/")
    if vault_path:
        root = Path(vault_path).expanduser().resolve()
        target = (root / managed_note).resolve()
        if root != target and root not in target.parents:
            raise ValueError("student state note escapes configured vault path")
        return target
    return Path.home() / ".intent-translator" / "student-state.md"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS student_state_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_key TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            priority TEXT NOT NULL,
            deadline TEXT,
            next_action TEXT NOT NULL,
            subject TEXT NOT NULL,
            goal TEXT NOT NULL,
            source_pointer TEXT NOT NULL,
            details TEXT NOT NULL,
            sensitive INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_student_state_status
            ON student_state_items(status, priority, deadline);
        CREATE INDEX IF NOT EXISTS idx_student_state_category
            ON student_state_items(category, subject, goal);

        CREATE TABLE IF NOT EXISTS student_state_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(student_state_items)")
    }
    if "expires_at" not in columns:
        connection.execute("ALTER TABLE student_state_items ADD COLUMN expires_at TEXT")
    connection.commit()
    return connection


def _stable_key(category: str, title: str) -> str:
    digest = hashlib.sha256(f"{category}\0{title.casefold().strip()}".encode("utf-8")).hexdigest()[:16]
    return f"{category}:{digest}"


def _validate_deadline(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    try:
        datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        try:
            date.fromisoformat(normalized)
        except ValueError:
            raise ValueError("deadline must be an ISO date or datetime") from exc
    return normalized


def _clean_text(value: str, *, field: str) -> str:
    normalized = "".join(
        character for character in str(value) if character in "\n\t" or ord(character) >= 32
    ).strip()
    maximum = MAX_TEXT_LENGTHS[field]
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    if field != "details":
        normalized = " ".join(normalized.split())
    if field == "source_pointer":
        if "[[" in normalized or "]]" in normalized or "://" in normalized:
            raise ValueError("source_pointer must be a plain local note pointer")
        if re.search(r"(?i)^(?:[a-z]:[\\/]|/home/|/users/)", normalized):
            raise ValueError("source_pointer must not expose an absolute user path")
    return normalized


def _assert_non_executable_state(*values: str) -> None:
    compact = " ".join(str(value) for value in values if value)
    if any(pattern.search(compact) for pattern in PERSISTENCE_ATTACK_PATTERNS):
        raise ValueError("student state rejected a persistent authority or prompt-injection attempt")


def _public_item(
    row: sqlite3.Row | dict[str, Any], *, include_sensitive: bool = False
) -> dict[str, Any]:
    item = dict(row)
    item["sensitive"] = bool(item.get("sensitive"))
    if item["sensitive"] and not include_sensitive:
        for field in ("title", "next_action", "subject", "goal", "source_pointer", "details"):
            item.pop(field, None)
        item["redacted"] = True
    return item


def upsert_state_item(
    connection: sqlite3.Connection,
    *,
    category: str,
    title: str,
    item_key: str = "",
    status: str = "planned",
    priority: str = "medium",
    deadline: str = "",
    next_action: str = "",
    subject: str = "",
    goal: str = "",
    source_pointer: str = "",
    details: str = "",
    sensitive: bool = False,
    retain_days: int | None = None,
) -> dict[str, Any]:
    category = category.strip()
    status = status.strip()
    priority = priority.strip()
    title = _clean_text(title, field="title")
    if category not in CATEGORIES:
        raise ValueError(f"unsupported state category: {category}")
    if status not in STATUSES:
        raise ValueError(f"unsupported state status: {status}")
    if priority not in PRIORITIES:
        raise ValueError(f"unsupported state priority: {priority}")
    if not title:
        raise ValueError("title is required")
    key = _clean_text(item_key, field="item_key") or _stable_key(category, title)
    if sensitive and retain_days is None:
        raise ValueError("sensitive student state requires retain_days")
    if retain_days is not None and not 1 <= retain_days <= 3650:
        raise ValueError("retain_days must be between 1 and 3650")
    cleaned_next_action = _clean_text(next_action, field="next_action")
    cleaned_subject = _clean_text(subject, field="subject")
    cleaned_goal = _clean_text(goal, field="goal")
    cleaned_pointer = _clean_text(source_pointer, field="source_pointer")
    cleaned_details = _clean_text(details, field="details")
    _assert_non_executable_state(
        title,
        cleaned_next_action,
        cleaned_subject,
        cleaned_goal,
        cleaned_pointer,
        cleaned_details,
    )
    timestamp = now_iso()
    completed_at = timestamp if status == "done" else None
    expires_at = (
        (datetime.now(timezone.utc) + timedelta(days=retain_days))
        .replace(microsecond=0)
        .isoformat()
        if retain_days is not None
        else None
    )
    connection.execute(
        """
        INSERT INTO student_state_items (
            item_key, category, title, status, priority, deadline, next_action,
            subject, goal, source_pointer, details, sensitive, expires_at,
            created_at, updated_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(item_key) DO UPDATE SET
            category=excluded.category,
            title=excluded.title,
            status=excluded.status,
            priority=excluded.priority,
            deadline=excluded.deadline,
            next_action=excluded.next_action,
            subject=excluded.subject,
            goal=excluded.goal,
            source_pointer=excluded.source_pointer,
            details=excluded.details,
            sensitive=excluded.sensitive,
            expires_at=excluded.expires_at,
            updated_at=excluded.updated_at,
            completed_at=CASE
                WHEN excluded.status = 'done' THEN COALESCE(student_state_items.completed_at, excluded.completed_at)
                ELSE NULL
            END
        """,
        (
            key,
            category,
            title,
            status,
            priority,
            _validate_deadline(deadline),
            cleaned_next_action,
            cleaned_subject,
            cleaned_goal,
            cleaned_pointer,
            cleaned_details,
            int(sensitive),
            expires_at,
            timestamp,
            timestamp,
            completed_at,
        ),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM student_state_items WHERE item_key = ?", (key,)).fetchone()
    return _public_item(row)


def list_state_items(
    connection: sqlite3.Connection,
    *,
    category: str = "",
    status: str = "",
    query: str = "",
    limit: int = 50,
    include_archived: bool = False,
    include_sensitive: bool = False,
) -> list[dict[str, Any]]:
    clauses: list[str] = ["(expires_at IS NULL OR expires_at > ?)"]
    values: list[Any] = [now_iso()]
    if not include_sensitive:
        clauses.append("sensitive = 0")
    if not include_archived:
        clauses.append("status != 'archived'")
    if category.strip():
        clauses.append("category = ?")
        values.append(category.strip())
    if status.strip():
        clauses.append("status = ?")
        values.append(status.strip())
    if query.strip():
        needle = f"%{query.strip()}%"
        clauses.append("(title LIKE ? OR next_action LIKE ? OR subject LIKE ? OR goal LIKE ?)")
        values.extend([needle, needle, needle, needle])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    values.append(max(1, min(200, limit)))
    rows = connection.execute(
        f"""
        SELECT * FROM student_state_items {where}
        ORDER BY
            CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
            CASE WHEN deadline IS NULL OR deadline = '' THEN 1 ELSE 0 END,
            deadline,
            updated_at DESC
        LIMIT ?
        """,
        values,
    ).fetchall()
    return [_public_item(row, include_sensitive=include_sensitive) for row in rows]


def set_focus(connection: sqlite3.Connection, *, item_key: str) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM student_state_items WHERE item_key = ?", (item_key.strip(),)).fetchone()
    if row is None:
        raise ValueError("state item not found")
    if row["status"] in {"done", "archived"}:
        raise ValueError("cannot focus a completed or archived state item")
    timestamp = now_iso()
    connection.execute(
        """
        INSERT INTO student_state_meta(key, value, updated_at) VALUES ('active_item_key', ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """,
        (item_key.strip(), timestamp),
    )
    connection.execute(
        "UPDATE student_state_items SET status='active', updated_at=? WHERE item_key=? AND status='planned'",
        (timestamp, item_key.strip()),
    )
    connection.commit()
    focused = connection.execute("SELECT * FROM student_state_items WHERE item_key = ?", (item_key.strip(),)).fetchone()
    return _public_item(focused)


def update_state_status(connection: sqlite3.Connection, *, item_key: str, status: str) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"unsupported state status: {status}")
    timestamp = now_iso()
    completed_at = timestamp if status == "done" else None
    cursor = connection.execute(
        """
        UPDATE student_state_items
        SET status=?, updated_at=?, completed_at=?
        WHERE item_key=?
        """,
        (status, timestamp, completed_at, item_key.strip()),
    )
    if cursor.rowcount == 0:
        raise ValueError("state item not found")
    if status in {"done", "archived"}:
        connection.execute(
            "DELETE FROM student_state_meta WHERE key='active_item_key' AND value=?",
            (item_key.strip(),),
        )
    connection.commit()
    row = connection.execute("SELECT * FROM student_state_items WHERE item_key = ?", (item_key.strip(),)).fetchone()
    return _public_item(row)


def _deadline_date(value: str) -> date | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.date()
    except ValueError:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None


def summarize_state(connection: sqlite3.Connection, *, due_soon_days: int = 7, limit: int = 8) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT * FROM student_state_items
        WHERE status != 'archived' AND sensitive = 0
          AND (expires_at IS NULL OR expires_at > ?)
        """,
        (now_iso(),),
    ).fetchall()
    items = [_public_item(row) for row in rows]
    active_key_row = connection.execute(
        "SELECT value FROM student_state_meta WHERE key='active_item_key'"
    ).fetchone()
    active_key = active_key_row["value"] if active_key_row else ""
    active_focus = next((item for item in items if item["item_key"] == active_key), None)
    today = datetime.now(timezone.utc).date()
    due_limit = today + timedelta(days=max(1, due_soon_days))
    overdue: list[dict[str, Any]] = []
    due_soon: list[dict[str, Any]] = []
    for item in items:
        if item["status"] in {"done", "archived"}:
            continue
        deadline = _deadline_date(item.get("deadline", ""))
        if deadline is None:
            continue
        if deadline < today:
            overdue.append(item)
        elif deadline <= due_limit:
            due_soon.append(item)
    rank = lambda item: (
        PRIORITY_ORDER.get(item.get("priority", "medium"), 2),
        item.get("deadline") or "9999-12-31",
        item.get("updated_at") or "",
    )
    actionable = sorted(
        [item for item in items if item["status"] in {"active", "planned", "blocked", "waiting"}],
        key=rank,
    )[: max(1, limit)]
    counts: dict[str, int] = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "enabled": True,
        "active_focus": active_focus,
        "overdue": sorted(overdue, key=rank),
        "due_soon": sorted(due_soon, key=rank),
        "actionable": actionable,
        "counts": counts,
        "total": len(items),
        "due_soon_days": max(1, due_soon_days),
    }


def _canonical_hash(content: str) -> str:
    return hashlib.sha256(content.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def canonical_change_status(connection: sqlite3.Connection, profile: dict[str, Any]) -> dict[str, Any]:
    path = canonical_state_path(profile)
    if not path.exists():
        return {"changed": False, "exists": False, "path": str(path)}
    content = path.read_text(encoding="utf-8")
    current_hash = _canonical_hash(content)
    row = connection.execute(
        "SELECT value FROM student_state_meta WHERE key='canonical_markdown_hash'"
    ).fetchone()
    confirmed_hash = row["value"] if row else ""
    return {
        "changed": current_hash != confirmed_hash,
        "exists": True,
        "path": str(path),
        "current_hash": current_hash,
        "confirmed_hash": confirmed_hash,
    }


def read_state_summary(path: Path, profile: dict[str, Any]) -> dict[str, Any]:
    settings = profile.get("student_state", {})
    if not isinstance(settings, dict) or not settings.get("enabled", False):
        return {"enabled": False}
    if not path.exists():
        return {"enabled": True, "active_focus": None, "overdue": [], "due_soon": [], "actionable": [], "counts": {}, "total": 0}
    try:
        connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='student_state_items'"
        ).fetchone()
        if table is None:
            return {"enabled": True, "active_focus": None, "overdue": [], "due_soon": [], "actionable": [], "counts": {}, "total": 0}
        summary = summarize_state(
            connection,
            due_soon_days=int(settings.get("due_soon_days", 7)),
            limit=int(settings.get("context_item_limit", 8)),
        )
        change = canonical_change_status(connection, profile)
        summary["canonical_markdown"] = {
            "exists": change["exists"],
            "pending_confirmation": change["changed"],
        }
        return summary
    except (OSError, sqlite3.Error, ValueError):
        return {"enabled": True, "error": "student state is unavailable", "active_focus": None, "overdue": [], "due_soon": [], "actionable": [], "counts": {}, "total": 0}
    finally:
        if "connection" in locals():
            connection.close()


def bootstrap_from_profile(connection: sqlite3.Connection, profile: dict[str, Any]) -> dict[str, Any]:
    goals = [str(goal).strip() for goal in profile.get("study", {}).get("goals", []) if str(goal).strip()]
    active_goal = str(profile.get("study", {}).get("active_goal", "")).strip()
    created: list[str] = []
    for goal in goals:
        key = f"goal:{hashlib.sha256(goal.casefold().encode('utf-8')).hexdigest()[:16]}"
        if connection.execute("SELECT 1 FROM student_state_items WHERE item_key=?", (key,)).fetchone():
            continue
        upsert_state_item(
            connection,
            item_key=key,
            category="goal",
            title=goal,
            status="active",
            priority="high" if goal == active_goal else "medium",
            next_action=f"继续最近未完成的{goal}任务",
            goal=goal,
            source_pointer="AI/用户画像.md",
        )
        created.append(key)
    focus_row = connection.execute("SELECT value FROM student_state_meta WHERE key='active_item_key'").fetchone()
    if focus_row is None and goals:
        preferred = active_goal or goals[0]
        preferred_key = f"goal:{hashlib.sha256(preferred.casefold().encode('utf-8')).hexdigest()[:16]}"
        set_focus(connection, item_key=preferred_key)
    return {"created": created, "created_count": len(created), "goals": goals, "summary": summarize_state(connection)}


def _escape_cell(value: Any) -> str:
    return str(value or "").replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def _split_table_row(line: str) -> list[str]:
    body = line.strip().strip("|")
    cells = re.split(r"(?<!\\)\|", body)
    return [cell.strip().replace("\\|", "|").replace("\\\\", "\\").replace("<br>", "\n") for cell in cells]


def render_state_note(summary: dict[str, Any], items: list[dict[str, Any]]) -> str:
    items = [item for item in items if not item.get("sensitive")]
    lines = [
        "# 大学生状态",
        "",
        "> 此页由 intent-translator 管理，只保存状态、截止时间、下一步和资料指针，不复制课程或笔记正文。",
        "",
        "## 当前焦点",
        "",
    ]
    focus = summary.get("active_focus")
    if focus:
        lines.append(f"- **{focus['title']}**：{focus.get('next_action') or '等待设置下一步'}")
        if focus.get("source_pointer"):
            lines.append(f"- 资料：[[{focus['source_pointer'].removesuffix('.md')}]]")
    else:
        lines.append("- 尚未设置")
    lines.extend(["", "## 临近截止", ""])
    due_items = list(summary.get("overdue", [])) + list(summary.get("due_soon", []))
    if not due_items:
        lines.append("- 暂无")
    for item in due_items:
        marker = "已逾期" if item in summary.get("overdue", []) else "临近"
        lines.append(f"- [{marker}] {item['title']} · {item.get('deadline') or '无日期'} · {item.get('next_action') or '未设置下一步'}")
    lines.extend(["", "## 进行中", ""])
    actionable = [item for item in summary.get("actionable", []) if item.get("status") != "done"]
    if not actionable:
        lines.append("- 暂无")
    for item in actionable:
        pointer = f" · [[{item['source_pointer'].removesuffix('.md')}]]" if item.get("source_pointer") else ""
        lines.append(
            f"- **{item['title']}** · {item['category']} · {item['status']} · {item['priority']}"
            f" · 下一步：{item.get('next_action') or '未设置'}{pointer}"
        )
    lines.extend(["", "---", f"更新时间：{now_iso()}", ""])
    lines.extend(
        [
            "## 可编辑状态表",
            "",
            "> 下表是此状态层的最高权威。手动修改后，Codex 会先复述变化并等待确认，再重建本地索引。",
            "",
            f"- 当前焦点键：{focus.get('item_key', '') if focus else ''}",
            "",
            "<!-- intent-translator-state:start -->",
            "| 键 | 类别 | 标题 | 状态 | 优先级 | 截止 | 下一步 | 科目 | 目标 | 资料指针 | 备注 | 敏感 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for item in items:
        cells = [
            item.get("item_key"),
            item.get("category"),
            item.get("title"),
            item.get("status"),
            item.get("priority"),
            item.get("deadline"),
            item.get("next_action"),
            item.get("subject"),
            item.get("goal"),
            item.get("source_pointer"),
            item.get("details"),
            "yes" if item.get("sensitive") else "no",
        ]
        lines.append("| " + " | ".join(_escape_cell(cell) for cell in cells) + " |")
    lines.extend(["<!-- intent-translator-state:end -->", ""])
    return "\n".join(lines)


def parse_state_note(content: str) -> dict[str, Any]:
    match = re.search(
        r"<!-- intent-translator-state:start -->(.*?)<!-- intent-translator-state:end -->",
        content,
        re.DOTALL,
    )
    if not match:
        raise ValueError("canonical state table markers are missing")
    active_match = re.search(r"^- 当前焦点键：(.*)$", content, re.MULTILINE)
    active_key = active_match.group(1).strip() if active_match else ""
    table_lines = [line for line in match.group(1).splitlines() if line.strip().startswith("|")]
    if len(table_lines) < 2:
        raise ValueError("canonical state table is incomplete")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in table_lines[2:]:
        cells = _split_table_row(line)
        if len(cells) != 12:
            raise ValueError("canonical state row must contain 12 columns")
        key, category, title, status, priority, deadline, next_action, subject, goal, pointer, details, sensitive = cells
        if not key:
            key = _stable_key(category, title)
        if key in seen:
            raise ValueError(f"duplicate state key: {key}")
        seen.add(key)
        if category not in CATEGORIES or status not in STATUSES or priority not in PRIORITIES or not title:
            raise ValueError(f"invalid canonical state row: {key}")
        _assert_non_executable_state(title, next_action, subject, goal, pointer, details)
        is_sensitive = sensitive.casefold() in {"yes", "true", "1", "是"}
        if is_sensitive:
            raise ValueError("sensitive state cannot be imported from canonical Markdown")
        items.append(
            {
                "item_key": key,
                "category": category,
                "title": title,
                "status": status,
                "priority": priority,
                "deadline": _validate_deadline(deadline),
                "next_action": next_action,
                "subject": subject,
                "goal": goal,
                "source_pointer": pointer,
                "details": details,
                "sensitive": False,
            }
        )
    if active_key and active_key not in seen:
        raise ValueError("active focus key does not exist in canonical state table")
    return {"active_item_key": active_key, "items": items}


def sync_state_note(
    connection: sqlite3.Connection,
    profile: dict[str, Any],
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary = summary or summarize_state(
        connection,
        due_soon_days=int(profile.get("student_state", {}).get("due_soon_days", 7)),
    )
    items = list_state_items(connection, limit=200, include_archived=True)
    content = render_state_note(summary, items)
    path = canonical_state_path(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    content_hash = _canonical_hash(content)
    connection.execute(
        """
        INSERT INTO student_state_meta(key, value, updated_at)
        VALUES ('canonical_markdown_hash', ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """,
        (content_hash, now_iso()),
    )
    connection.commit()
    return {"synced": True, "method": "canonical-markdown", "path": str(path), "state_count": len(items)}


def refresh_from_canonical(
    connection: sqlite3.Connection,
    profile: dict[str, Any],
    *,
    confirmed: bool = False,
) -> dict[str, Any]:
    path = canonical_state_path(profile)
    if not path.exists():
        return {"changed": False, "confirmation_required": False, "reason": "canonical Markdown does not exist"}
    content = path.read_text(encoding="utf-8")
    parsed = parse_state_note(content)
    change = canonical_change_status(connection, profile)
    if not change["changed"]:
        return {"changed": False, "confirmation_required": False, "item_count": len(parsed["items"])}
    current_count = connection.execute(
        "SELECT COUNT(*) FROM student_state_items WHERE sensitive = 0"
    ).fetchone()[0]
    preview = {
        "before_count": current_count,
        "after_count": len(parsed["items"]),
        "active_item_key": parsed["active_item_key"],
        "titles": [item["title"] for item in parsed["items"][:8]],
    }
    if not confirmed:
        return {
            "changed": True,
            "confirmation_required": True,
            "preview": preview,
            "confirmation_prompt": "我检测到你手改了状态 Markdown。是否按上面的变化重建本地状态索引？",
        }
    connection.execute(
        """
        DELETE FROM student_state_meta
        WHERE key='active_item_key'
          AND value IN (SELECT item_key FROM student_state_items WHERE sensitive = 0)
        """
    )
    connection.execute("DELETE FROM student_state_items WHERE sensitive = 0")
    connection.commit()
    for item in parsed["items"]:
        upsert_state_item(connection, **item)
    if parsed["active_item_key"]:
        set_focus(connection, item_key=parsed["active_item_key"])
    connection.execute(
        """
        INSERT INTO student_state_meta(key, value, updated_at)
        VALUES ('canonical_markdown_hash', ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """,
        (_canonical_hash(content), now_iso()),
    )
    connection.commit()
    return {
        "changed": True,
        "confirmation_required": False,
        "applied": True,
        "preview": preview,
        "summary": summarize_state(connection),
    }


def _load_profile(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bootstrap", "summary", "list", "upsert", "focus", "complete", "archive", "sync", "refresh"))
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path(os.environ.get("INTENT_TRANSLATOR_PROFILE", Path.home() / ".intent-translator" / "profile.json")),
    )
    parser.add_argument("--item-key", default="")
    parser.add_argument("--category", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--status", default="planned")
    parser.add_argument("--priority", default="medium")
    parser.add_argument("--deadline", default="")
    parser.add_argument("--next-action", default="")
    parser.add_argument("--subject", default="")
    parser.add_argument("--goal", default="")
    parser.add_argument("--source-pointer", default="")
    parser.add_argument("--details", default="")
    parser.add_argument("--sensitive", action="store_true")
    parser.add_argument("--retain-days", type=int)
    parser.add_argument("--confirmed", action="store_true")
    parser.add_argument("--query", default="")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    profile = _load_profile(args.profile)
    connection = connect(state_db_path(profile))
    try:
        if args.command == "bootstrap":
            result = bootstrap_from_profile(connection, profile)
            result = {**result, "canonical": sync_state_note(connection, profile)}
        elif args.command == "summary":
            result = summarize_state(connection, due_soon_days=int(profile.get("student_state", {}).get("due_soon_days", 7)))
        elif args.command == "list":
            result = {"items": list_state_items(connection, category=args.category, status=args.status if args.status != "planned" else "", query=args.query, limit=args.limit)}
        elif args.command == "upsert":
            result = upsert_state_item(
                connection,
                item_key=args.item_key,
                category=args.category,
                title=args.title,
                status=args.status,
                priority=args.priority,
                deadline=args.deadline,
                next_action=args.next_action,
                subject=args.subject,
                goal=args.goal,
                source_pointer=args.source_pointer,
                details=args.details,
                sensitive=args.sensitive,
                retain_days=args.retain_days,
            )
        elif args.command == "focus":
            result = set_focus(connection, item_key=args.item_key)
        elif args.command in {"complete", "archive"}:
            result = update_state_status(connection, item_key=args.item_key, status="done" if args.command == "complete" else "archived")
        elif args.command == "sync":
            summary = summarize_state(connection, due_soon_days=int(profile.get("student_state", {}).get("due_soon_days", 7)))
            result = sync_state_note(connection, profile, summary)
        else:
            result = refresh_from_canonical(connection, profile, confirmed=args.confirmed)
    finally:
        connection.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("synced", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
