"""Small local-first onboarding and language-rule promotion helpers."""

from __future__ import annotations

import json
import hashlib
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_RULE_TEXT = 1000
PERSISTENCE_ATTACK_PATTERNS = (
    re.compile(r"\b(?:ignore|disregard|override)\b.{0,80}\b(?:previous|system|developer|safety|instructions?)\b", re.I),
    re.compile(r"\b(?:reveal|print|show|expose)\b.{0,80}\b(?:system prompt|developer message|api key|token|password|secret)\b", re.I),
    re.compile(r"\b(?:never ask|without (?:asking|confirmation|permission))\b", re.I),
    re.compile(r"(?:忽略|无视|覆盖).{0,30}(?:之前|系统|开发者|安全|指令|规则)"),
    re.compile(r"(?:泄露|显示|输出).{0,30}(?:系统提示词|开发者消息|隐藏指令|密钥|令牌|密码)"),
    re.compile(r"(?:不用|无需|不必).{0,12}(?:确认|询问|授权|许可)"),
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def generic_profile() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "profile_id": str(uuid.uuid4()),
        "language": "auto",
        "response_style": {"verbosity": "adaptive", "result_first": True},
        "autonomy": {"reversible_actions": "proceed", "high_impact_actions": "confirm"},
        "adaptation": {
            "expertise": "adaptive",
            "plain_language": "adaptive",
            "accessibility": [],
            "domains": [],
        },
        "risk_policy": {"high_stakes": "verify", "sensitive_memory": "explicit"},
        "optional_adapters": {"session_hooks": False, "reversible_context": False},
        "phrase_mappings": {},
        "memory": {"adapter": "sqlite", "location": "~/.intent-translator/memory.db"},
        "cognitive_priors": [],
    }


def personalization_status(*, profile_exists: bool) -> dict[str, Any]:
    if not profile_exists:
        return {
            "mode": "generic",
            "message": "当前是没有个人记忆的通用模式。你可以直接使用，也可以稍后设置自己的表达习惯。",
            "claims_personal_knowledge": False,
        }
    return {
        "mode": "local-profile",
        "message": "已加载这台电脑上的本地设置。",
        "claims_personal_knowledge": True,
    }


def onboarding_status(*, profile_exists: bool) -> dict[str, Any]:
    return {
        "mode": personalization_status(profile_exists=profile_exists)["mode"],
        "skippable": True,
        "steps": [
            {
                "id": "memory",
                "question": "哪些内容可以记住？默认只保存在本机，也可以选择完全不记。",
                "choices": ["只记我确认的内容", "不记", "跳过"],
            },
            {
                "id": "interpretation",
                "question": "一句话有多种重要理解时，你希望先看候选解释，还是直接问一句？",
                "choices": ["给我选项", "直接问我", "跳过"],
            },
            {
                "id": "tone",
                "question": "回答要简洁还是详细？是否接受必要时更尖锐地审查方案？",
                "choices": ["简洁", "适中", "详细", "跳过"],
            },
        ],
        "real_button_ui": False,
        "selection_protocol": "choice-id",
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_onboarding(
    profile_path: Path,
    *,
    memory: str = "skip",
    interpretation: str = "skip",
    tone: str = "skip",
    sharp_review: bool = False,
) -> dict[str, Any]:
    if memory not in {"local", "off", "skip"}:
        raise ValueError("memory must be local, off, or skip")
    if interpretation not in {"choices", "ask", "skip"}:
        raise ValueError("interpretation must be choices, ask, or skip")
    if tone not in {"concise", "balanced", "detailed", "skip"}:
        raise ValueError("tone must be concise, balanced, detailed, or skip")
    path = Path(profile_path).expanduser()
    profile = json.loads(path.read_text(encoding="utf-8")) if path.exists() else generic_profile()
    if memory == "off":
        profile["memory"] = {"adapter": "none", "location": ""}
    elif memory == "local":
        profile["memory"] = {
            "adapter": "sqlite",
            "location": "~/.intent-translator/memory.db",
            "local_only": True,
            "write_policy": "confirmed-only",
        }
    profile["interpretation_preferences"] = {
        "material_ambiguity": "show-choices" if interpretation == "choices" else "ask" if interpretation == "ask" else "neutral",
        "natural_language_correction": True,
    }
    verbosity = {
        "concise": "concise",
        "balanced": "adaptive",
        "detailed": "detailed",
        "skip": profile.get("response_style", {}).get("verbosity", "adaptive"),
    }[tone]
    profile.setdefault("response_style", {})["verbosity"] = verbosity
    profile["review_preferences"] = {"sharp_review": bool(sharp_review)}
    profile["onboarding"] = {"completed_at": now_iso(), "skipped_fields_allowed": True}
    _write_json(path, profile)
    return profile


def _observations_path(profile_path: Path) -> Path:
    return Path(profile_path).expanduser().parent / "language-observations.json"


def _validated_rule(phrase: str, corrected_meaning: str, scope: str) -> tuple[str, str, str]:
    phrase = " ".join(phrase.split())
    corrected_meaning = " ".join(corrected_meaning.split())
    scope = " ".join(scope.split())
    if not phrase or not corrected_meaning or not scope:
        raise ValueError("phrase, corrected_meaning, and scope are required")
    if max(len(phrase), len(corrected_meaning), len(scope)) > MAX_RULE_TEXT:
        raise ValueError("language rule exceeds the bounded storage limit")
    compact = f"{phrase} {corrected_meaning}"
    if any(pattern.search(compact) for pattern in PERSISTENCE_ATTACK_PATTERNS):
        raise ValueError("language rule rejected a persistent authority or prompt-injection attempt")
    return phrase, corrected_meaning, scope


def observe_language_correction(
    profile_path: Path, *, phrase: str, corrected_meaning: str, scope: str = "global"
) -> dict[str, Any]:
    phrase, corrected_meaning, scope = _validated_rule(phrase, corrected_meaning, scope)
    path = _observations_path(profile_path)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": 1, "observations": {}}
    key = hashlib.sha256(f"{scope}\0{phrase}\0{corrected_meaning}".encode("utf-8")).hexdigest()
    item = data["observations"].setdefault(
        key,
        {"fingerprint": key, "scope": scope, "count": 0},
    )
    item["count"] = int(item.get("count", 0)) + 1
    item["updated_at"] = now_iso()
    _write_json(path, data)
    return {
        "corrected_understanding": corrected_meaning,
        "applied_to_current_turn": True,
        "observation_count": item["count"],
        "promotion_suggested": item["count"] >= 2,
        "promotion_requires_confirmation": True,
        "raw_observation_stored": False,
    }


def confirm_language_rule(
    profile_path: Path, *, phrase: str, corrected_meaning: str, scope: str = "global"
) -> dict[str, Any]:
    phrase, corrected_meaning, scope = _validated_rule(phrase, corrected_meaning, scope)
    path = Path(profile_path).expanduser()
    profile = json.loads(path.read_text(encoding="utf-8")) if path.exists() else generic_profile()
    profile.setdefault("phrase_mappings", {})[phrase] = {
        "meaning": corrected_meaning,
        "scope": scope,
        "confidence": "confirmed",
        "updated_at": now_iso(),
    }
    _write_json(path, profile)
    return profile["phrase_mappings"][phrase]


def interpretation_gate(
    *, primary: str, alternatives: list[str], recommended: int = 0
) -> dict[str, Any]:
    candidates = [item.strip() for item in [primary, *alternatives] if item and item.strip()]
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) < 2:
        return {"required": False, "candidates": [], "controls": []}
    recommended = max(0, min(recommended, len(candidates) - 1))
    return {
        "required": True,
        "primary_understanding": candidates[0],
        "candidates": [
            {"id": f"interpretation-{index + 1}", "text": text, "recommended": index == recommended}
            for index, text in enumerate(candidates)
        ],
        "controls": [
            {"id": "merge", "label": "合并"},
            {"id": "none", "label": "都不对"},
            {"id": "correct", "label": "用一句话纠正"},
        ],
        "wait_for_selection": True,
        "real_button_ui": False,
    }
