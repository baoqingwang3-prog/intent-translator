"""Small local-first onboarding and language-rule promotion helpers."""

from __future__ import annotations

import argparse
import json
import hashlib
import os
import re
import sys
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


def default_profile_path() -> Path:
    configured = os.environ.get("INTENT_TRANSLATOR_PROFILE")
    return Path(configured).expanduser() if configured else Path.home() / ".intent-translator" / "profile.json"


def _has_personalization(profile: dict[str, Any] | None) -> bool:
    if not profile:
        return False
    if profile.get("phrase_mappings") or profile.get("cognitive_priors"):
        return True
    if profile.get("study", {}).get("enabled") or profile.get("student_life", {}).get("enabled"):
        return True
    interpretation = profile.get("interpretation_preferences", {})
    if interpretation.get("material_ambiguity", "neutral") != "neutral":
        return True
    review = profile.get("review_preferences", {})
    if review.get("sharp_review") or review.get("conditional_pua"):
        return True
    if profile.get("local_policy"):
        return True
    adaptation = profile.get("adaptation", {})
    if adaptation.get("domains") or adaptation.get("accessibility"):
        return True
    if profile.get("response_style", {}).get("verbosity", "adaptive") != "adaptive":
        return True
    memory = profile.get("memory", {})
    return memory.get("adapter") == "none" or memory.get("write_policy") == "confirmed-only"


def personalization_status(*, profile_exists: bool, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    if not profile_exists or not _has_personalization(profile):
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


def onboarding_status(*, profile_exists: bool, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "mode": personalization_status(profile_exists=profile_exists, profile=profile)["mode"],
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
    sharp_review: bool | None = None,
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
    interpretation_preferences = profile.setdefault("interpretation_preferences", {})
    interpretation_preferences["material_ambiguity"] = (
        "show-choices"
        if interpretation == "choices"
        else "ask"
        if interpretation == "ask"
        else interpretation_preferences.get("material_ambiguity", "neutral")
    )
    interpretation_preferences["natural_language_correction"] = True
    verbosity = {
        "concise": "concise",
        "balanced": "adaptive",
        "detailed": "detailed",
        "skip": profile.get("response_style", {}).get("verbosity", "adaptive"),
    }[tone]
    profile.setdefault("response_style", {})["verbosity"] = verbosity
    review_preferences = profile.setdefault("review_preferences", {})
    if sharp_review is not None:
        review_preferences["sharp_review"] = sharp_review
    else:
        review_preferences.setdefault("sharp_review", False)
    profile["onboarding"] = {"completed_at": now_iso(), "skipped_fields_allowed": True}
    _write_json(path, profile)
    return profile


def onboarding_summary(profile: dict[str, Any]) -> dict[str, Any]:
    memory = profile.get("memory", {})
    interpretation = profile.get("interpretation_preferences", {})
    response_style = profile.get("response_style", {})
    review = profile.get("review_preferences", {})
    memory_mode = (
        "off"
        if memory.get("adapter") == "none"
        else "local-confirmed-only"
        if memory.get("write_policy") == "confirmed-only"
        else "default-local"
    )
    return {
        "completed": bool(profile.get("onboarding", {}).get("completed_at")),
        "configured": _has_personalization(profile),
        "memory": memory_mode,
        "interpretation": interpretation.get("material_ambiguity", "neutral"),
        "tone": response_style.get("verbosity", "adaptive"),
        "sharp_review": bool(review.get("sharp_review", False)),
        "local_only": memory.get("adapter") in {"none", "sqlite"},
    }


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


def _ask_choice(prompt: str, choices: list[tuple[str, str]], default: str) -> str:
    print(prompt)
    for index, (_, label) in enumerate(choices, start=1):
        print(f"  {index}. {label}")
    raw = input(f"Choose 1-{len(choices)} (default: skip): ").strip()
    if not raw:
        return default
    try:
        selected = int(raw) - 1
    except ValueError:
        return default
    return choices[selected][0] if 0 <= selected < len(choices) else default


def _interactive_choices() -> tuple[str, str, str, bool]:
    print("Intent Translator setup. Every choice is local and can be skipped.")
    memory = _ask_choice(
        "What may be remembered? / 哪些内容可以记住？",
        [("local", "Only things I confirm / 只记我确认的内容"), ("off", "Remember nothing / 不记"), ("skip", "Skip / 跳过")],
        "skip",
    )
    interpretation = _ask_choice(
        "When an important sentence has multiple meanings / 重要表达有多种理解时：",
        [("choices", "Show choices / 给我选项"), ("ask", "Ask one question / 直接问一句"), ("skip", "Skip / 跳过")],
        "skip",
    )
    tone = _ask_choice(
        "Preferred answer length / 回答长度：",
        [("concise", "Concise / 简洁"), ("balanced", "Balanced / 适中"), ("detailed", "Detailed / 详细"), ("skip", "Skip / 跳过")],
        "skip",
    )
    sharp = _ask_choice(
        "Allow sharper review for important decisions / 重要决策允许更尖锐的审查？",
        [("yes", "Yes / 可以"), ("no", "No / 不需要")],
        "no",
    )
    return memory, interpretation, tone, sharp == "yes"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Configure the local Intent Translator profile.")
    parser.add_argument("--profile", type=Path, default=default_profile_path())
    parser.add_argument("--status", action="store_true", help="Show whether personalization is configured")
    parser.add_argument("--memory", choices=("local", "off", "skip"))
    parser.add_argument("--interpretation", choices=("choices", "ask", "skip"))
    parser.add_argument("--tone", choices=("concise", "balanced", "detailed", "skip"))
    parser.add_argument("--sharp-review", action="store_true", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    profile_path = args.profile.expanduser()
    if args.status:
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else None
        except (OSError, UnicodeError, json.JSONDecodeError):
            profile = None
        payload = onboarding_status(profile_exists=profile_path.exists(), profile=profile)
    else:
        supplied = any(value is not None for value in (args.memory, args.interpretation, args.tone)) or args.sharp_review
        if supplied:
            choices = (
                args.memory or "skip",
                args.interpretation or "skip",
                args.tone or "skip",
                args.sharp_review,
            )
        else:
            choices = _interactive_choices()
        profile = apply_onboarding(
            profile_path,
            memory=choices[0],
            interpretation=choices[1],
            tone=choices[2],
            sharp_review=choices[3],
        )
        payload = onboarding_summary(profile)

    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
