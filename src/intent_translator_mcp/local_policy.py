"""Local-only interaction policy helpers with conservative generic defaults."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ILLEGAL_HARM_PATTERNS = (
    re.compile(r"(?:造谣|诽谤|抹黑|栽赃|伪造证据)"),
    re.compile(r"\b(?:defame|frame|fabricate evidence)\b", re.I),
)
EXPLICIT_SHARP_REVIEW_TERMS = (
    "尖锐反驳",
    "狠狠批评",
    "强力质疑",
    "sharp critique",
    "adversarial review",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_interpretation_gate(
    candidates: list[str], *, selection: str, correction: str = ""
) -> dict[str, Any]:
    cleaned = list(dict.fromkeys(item.strip() for item in candidates if item.strip()))[:5]
    if selection.startswith("interpretation-"):
        try:
            index = int(selection.rsplit("-", 1)[1]) - 1
            resolved = cleaned[index]
        except (ValueError, IndexError) as exc:
            raise ValueError("interpretation selection does not exist") from exc
        return {"resolved": resolved, "needs_natural_language_correction": False}
    if selection == "merge":
        if not cleaned:
            raise ValueError("merge requires at least one candidate")
        return {
            "resolved": "；然后".join(cleaned),
            "needs_natural_language_correction": False,
        }
    if selection == "none":
        return {"resolved": "", "needs_natural_language_correction": True}
    if selection == "correct":
        corrected = " ".join(correction.split())
        if not corrected:
            raise ValueError("correction is required")
        return {"resolved": corrected, "needs_natural_language_correction": False}
    raise ValueError("unsupported interpretation selection")


def sparse_source_map(transformations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in transformations
        if str(item.get("original", "")) != str(item.get("compiled", ""))
        or str(item.get("kind", "direct")) != "direct"
    ]


def revise_compilation(
    current: dict[str, Any], *, previous: dict[str, Any], field: str, replacement: Any
) -> dict[str, Any]:
    if field not in current:
        raise ValueError(f"unknown compilation field: {field}")
    compiled = dict(current)
    compiled[field] = replacement
    return {
        "compiled": compiled,
        "changed_field": field,
        "offer_restore_previous_complete_version": compiled != previous,
        "previous_complete_version": dict(previous),
    }


def _connect(path: Path) -> sqlite3.Connection:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS local_policy_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            event TEXT NOT NULL,
            wrong TEXT NOT NULL DEFAULT '',
            correct TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def record_misunderstanding(
    db_path: Path, *, wrong: str, correct: str, scope: str = "global"
) -> dict[str, Any]:
    wrong = " ".join(wrong.split())
    correct = " ".join(correct.split())
    scope = " ".join(scope.split())
    if not wrong or not correct or not scope:
        raise ValueError("wrong, correct, and scope are required")
    if max(len(wrong), len(correct), len(scope)) > 1000:
        raise ValueError("misunderstanding record exceeds the bounded storage limit")
    connection = _connect(db_path)
    try:
        connection.execute(
            "INSERT INTO local_policy_events(scope, event, wrong, correct, created_at) VALUES (?, 'misunderstanding', ?, ?, ?)",
            (scope, wrong, correct, now_iso()),
        )
        connection.commit()
        return autonomy_status(db_path, scope=scope)
    finally:
        connection.close()


def record_correct_restatement(db_path: Path, *, scope: str = "global") -> dict[str, Any]:
    scope = " ".join(scope.split())
    if not scope:
        raise ValueError("scope is required")
    connection = _connect(db_path)
    try:
        connection.execute(
            "INSERT INTO local_policy_events(scope, event, created_at) VALUES (?, 'correct_restatement', ?)",
            (scope, now_iso()),
        )
        connection.commit()
    finally:
        connection.close()
    status = autonomy_status(db_path, scope=scope)
    status["ask_before_restoring"] = status["mode"] == "cautious"
    return status


def autonomy_status(db_path: Path, *, scope: str = "global") -> dict[str, Any]:
    if not Path(db_path).expanduser().exists():
        return {
            "scope": scope,
            "mode": "normal",
            "misunderstanding_count": 0,
            "correct_restatement_count": 0,
            "automatic_restore_allowed": True,
        }
    connection = _connect(db_path)
    try:
        row = connection.execute(
            """
            SELECT
                SUM(CASE WHEN event = 'misunderstanding' THEN 1 ELSE 0 END) AS misunderstandings,
                SUM(CASE WHEN event = 'correct_restatement' THEN 1 ELSE 0 END) AS correct_restatements
            FROM local_policy_events WHERE scope = ?
            """,
            (scope,),
        ).fetchone()
        misunderstandings = int(row["misunderstandings"] or 0)
        correct_restatements = int(row["correct_restatements"] or 0)
        cautious = misunderstandings >= 2
        return {
            "scope": scope,
            "mode": "cautious" if cautious else "normal",
            "misunderstanding_count": misunderstandings,
            "correct_restatement_count": correct_restatements,
            "automatic_restore_allowed": False if cautious else True,
        }
    finally:
        connection.close()


def _spend_policy(text: str, profile: dict[str, Any], authorization: str) -> dict[str, Any]:
    guard = profile.get("risk_policy", {}).get("spend_guard")
    if not isinstance(guard, dict):
        return {"enabled": False}
    threshold = guard.get("single_amount")
    if not isinstance(threshold, (int, float)) or threshold <= 0:
        return {"enabled": False}
    match = re.search(r"(?<!\d)(\d+(?:\.\d{1,2})?)\s*(?:元|rmb|cny)", text, re.I)
    amount = float(match.group(1)) if match else None
    exceeded = amount is not None and amount >= float(threshold)
    return {
        "enabled": True,
        "amount": amount,
        "threshold_exceeded": exceeded,
        "confirmation_required": exceeded and authorization != "granted",
    }


def assess_local_risk(
    text: str, *, profile: dict[str, Any], authorization: str = "unknown"
) -> dict[str, Any]:
    if authorization not in {"granted", "unknown", "denied"}:
        raise ValueError("authorization must be granted, unknown, or denied")
    if any(pattern.search(text) for pattern in ILLEGAL_HARM_PATTERNS):
        return {
            "blocked": True,
            "confirmation_required": False,
            "reason": "illegal or abusive harm remains blocked regardless of authorization",
            "alternative": "可以提供合法替代，例如事实核验、正式投诉、澄清声明或证据整理。",
            "spend": {"enabled": False},
        }
    spend = _spend_policy(text, profile, authorization)
    return {
        "blocked": authorization == "denied",
        "confirmation_required": bool(spend.get("confirmation_required")),
        "reason": "authorization denied" if authorization == "denied" else "",
        "alternative": "",
        "spend": spend,
    }


def conditional_review(
    text: str, *, profile: dict[str, Any], installed_skills: set[str]
) -> dict[str, Any]:
    available = "pua" in installed_skills
    explicit = any(term.casefold() in text.casefold() for term in EXPLICIT_SHARP_REVIEW_TERMS)
    opted_in = bool(profile.get("review_preferences", {}).get("conditional_pua", False))
    return {
        "available": available,
        "use_pua": available and (explicit or opted_in),
        "trigger": "explicit-request" if explicit else "local-opt-in" if opted_in else "none",
        "full_debate_requires_opt_in": True,
    }
