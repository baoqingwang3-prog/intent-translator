"""Deterministic intent preflight, memory retrieval, and Skill routing."""

from __future__ import annotations

import importlib.util
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

from .models import CompileRequest


MODE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("remember", ("记住", "记一下", "存下来", "remember")),
    ("recall", ("之前", "老样子", "回忆", "recall", "之前定的")),
    ("search", ("查一下", "搜索", "搜一下", "调研", "search", "look up")),
    ("diagnose", ("报错", "原因", "装好了吗", "为什么", "diagnose")),
    ("route", ("提示词", "prompt", "另一个 agent", "另一个agent")),
    ("build", ("做一个", "整一个", "搞个", "创建", "设计", "上架", "发布", "发到 github", "妙招", "中枢", "build", "creating")),
    ("change", ("修改", "修复", "安装", "装好", "接一下", "旋转", "删除", "全删", "改文件", "整利索", "change", "validation")),
]

SKILL_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("obsidian-cli", ("obsidian", "文件记", "写简历", "知识库")),
    ("skill-creator", ("skill", "技能", "创建并验证")),
    ("domain-modeling", ("产品架构", "设计不变量", "中枢", "编译器", "小学老师", "方案", "妙招", "architecture", "metaphor")),
    ("diagnosing-bugs", ("报错", "失败命令", "诊断")),
    ("agent-reach", ("全网", "大家怎么评价", "外部搜索", "查一下", "搜索")),
    ("pdf", ("pdf",)),
    ("scientific-critical-thinking", ("反驳", "人格类型", "实证", "科学")),
    ("prompt-lookup", ("提示词", "prompt", "另一个 agent", "另一个agent")),
]

HIGH_STAKES = ("处方药", "诊断", "投资", "贷款", "法律意见", "手术")
EXTERNAL_TERMS = ("github", "发布", "上架", "上传", "发给外部", "外部搜索", "部署", "公开")
DESTRUCTIVE_TERMS = ("全删", "全部删除", "永久删除", "覆盖", "销毁")
SENSITIVE_TERMS = ("过敏", "身份证", "密码", "token", "api key", "病史", "完整用户画像")
APPROVAL_TERMS = {"可以", "好", "确认了", "行", "可以的"}
CONTINUE_TERMS = {"继续", "往下", "再往下", "好了", "已登录", "已安装"}


def _candidate_skill_dirs() -> list[Path]:
    configured = os.environ.get("INTENT_TRANSLATOR_SKILL_DIR")
    package_repo = Path(__file__).resolve().parents[2]
    home = Path.home()
    candidates = [
        Path(configured).expanduser() if configured else None,
        package_repo / "skills" / "intent-translator",
        home / ".codex" / "skills" / "intent-translator",
        home / ".agents" / "skills" / "intent-translator",
    ]
    return [path.resolve() for path in candidates if path and path.exists()]


@lru_cache(maxsize=None)
def _load_skill_script(name: str) -> ModuleType:
    for skill_dir in _candidate_skill_dirs():
        script = skill_dir / "scripts" / f"{name}.py"
        if not script.exists():
            continue
        spec = importlib.util.spec_from_file_location(f"intent_translator_{name}", script)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise RuntimeError(f"intent-translator support script not found: {name}.py")


def _profile_path() -> Path:
    configured = os.environ.get("INTENT_TRANSLATOR_PROFILE")
    return Path(configured).expanduser() if configured else Path.home() / ".intent-translator" / "profile.json"


def load_profile() -> dict[str, Any]:
    path = _profile_path()
    if not path.exists():
        return {"language": "auto", "phrase_mappings": {}, "memory": {"adapter": "sqlite"}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"language": "auto", "phrase_mappings": {}, "memory": {"adapter": "sqlite"}}


def _memory_path(profile: dict[str, Any]) -> Path:
    configured = os.environ.get("INTENT_TRANSLATOR_MEMORY_DB")
    location = configured or profile.get("memory", {}).get("location")
    return Path(location).expanduser() if location else Path.home() / ".intent-translator" / "memory.db"


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    folded = text.casefold()
    return any(term.casefold() in folded for term in terms)


def _phrase_mapping(profile: dict[str, Any], utterance: str, scope: str) -> dict[str, Any] | None:
    normalized = utterance.strip()
    candidates: list[tuple[int, str, Any]] = []
    for phrase, raw in profile.get("phrase_mappings", {}).items():
        if phrase not in normalized and normalized not in phrase:
            continue
        mapping = raw if isinstance(raw, dict) else {"meaning": str(raw), "scope": "global"}
        if mapping.get("scope", "global") not in {"global", scope}:
            continue
        candidates.append((len(phrase), phrase, mapping))
    if not candidates:
        return None
    _, phrase, mapping = max(candidates, key=lambda item: item[0])
    return {"phrase": phrase, **mapping}


def _classify_mode(text: str, pending: str) -> str:
    lowered = text.strip().casefold()
    if lowered in APPROVAL_TERMS | CONTINUE_TERMS and pending:
        return _classify_mode(pending, "")
    if "只解释" in lowered or "别改" in lowered:
        return "diagnose"
    if "以后" in lowered and _contains(lowered, ("别问", "直接做", "默认")):
        return "remember"
    for mode, terms in MODE_RULES:
        if _contains(lowered, terms):
            return mode
    return "answer"


def _memory_action(text: str, mode: str) -> str:
    if mode == "remember":
        return "write"
    if mode == "recall" or _contains(text, ("按上次", "还是按", "完整用户画像")):
        return "read"
    if _contains(text, ("删除记忆", "记忆全删", "清空记忆")):
        return "update"
    return "none"


def _risk(text: str, authorization: str) -> dict[str, Any]:
    external = _contains(text, EXTERNAL_TERMS)
    sensitive = _contains(text, SENSITIVE_TERMS)
    irreversible = _contains(text, DESTRUCTIVE_TERMS) or (external and _contains(text, ("发布", "公开", "上架")))
    high_stakes = _contains(text, HIGH_STAKES)
    impact = "high" if high_stakes or irreversible or (external and sensitive) else "medium" if external or sensitive else "low"
    reasons: list[str] = []
    if authorization == "denied":
        reasons.append("authorization is denied")
    elif authorization == "unknown":
        if external:
            reasons.append("external action lacks explicit authorization")
        if irreversible:
            reasons.append("irreversible action lacks explicit authorization")
        if external and sensitive:
            reasons.append("sensitive external transfer lacks explicit authorization")
    if high_stakes:
        reasons.append("high-stakes request requires verified evidence and bounded guidance")
    return {
        "impact": impact,
        "reversible": "no" if irreversible else "unknown" if high_stakes else "yes",
        "external": external,
        "sensitive": sensitive,
        "high_stakes": high_stakes,
        "authorization": authorization,
        "blocked": authorization == "denied",
        "confirmation_required": bool(reasons) and authorization != "denied",
        "reasons": reasons,
    }


def _route_skill(text: str, discovered: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    installed = {item["name"]: item for item in discovered.get("skills", [])}
    scores: list[tuple[int, str, list[str]]] = []
    for name, terms in SKILL_ALIASES:
        matched = [term for term in terms if term.casefold() in text.casefold()]
        if matched and (not installed or name in installed):
            scores.append((len(matched) * 100 + max(map(len, matched)), name, matched))
    best: dict[str, tuple[int, list[str]]] = {}
    for score, name, matched in scores:
        if name not in best or score > best[name][0]:
            best[name] = (score, matched)
    ranked = sorted(best.items(), key=lambda item: (-item[1][0], item[0]))[:5]
    candidates = [
        {"name": name, "score": score, "matched_terms": matched}
        for name, (score, matched) in ranked
    ]
    return (candidates[0]["name"] if candidates else None), candidates


def _path_and_clarification(text: str, mode: str, risk: dict[str, Any], memories: list[dict[str, Any]]) -> tuple[str, bool]:
    review_terms = ("我想到", "我认为", "反驳", "提示词", "小学老师", "人格类型", "老样子", "之前定的")
    stale = any(item.get("stale") for item in memories)
    unsafe_default = _contains(text, ("所有操作都别问", "以后都别问", "直接做"))
    deletion = _contains(text, ("记忆全删", "删除记忆", "清空记忆"))
    stale = stale or _contains(text, ("marked stale", "120 days old", "已过期"))
    clarification = risk["confirmation_required"] or stale or unsafe_default or deletion
    review = clarification or risk["high_stakes"] or mode in {"remember", "recall", "route"} or _contains(text, review_terms)
    return ("review" if review else "fast"), clarification


class IntentCompiler:
    """Compile user language into a compact, auditable execution envelope."""

    def __init__(self, *, registry: dict[str, Any] | None = None) -> None:
        self.profile = load_profile()
        if registry is None:
            discover = _load_skill_script("discover_skills")
            registry = discover.discover_skills(discover.default_roots())
        self.registry = registry

    def recall_corrections(self, query: str, scope: str = "global", limit: int = 5) -> list[dict[str, Any]]:
        memory = _load_skill_script("memory_store")
        connection = memory.connect(_memory_path(self.profile))
        try:
            return memory.search_corrections(
                connection, query=query, scope=scope, limit=limit, track_access=False
            )
        finally:
            connection.close()

    def recall_memories(self, query: str, scope: str = "global", limit: int = 5) -> list[dict[str, Any]]:
        memory = _load_skill_script("memory_store")
        connection = memory.connect(_memory_path(self.profile))
        try:
            return memory.search_memories(
                connection, query=query, scope=scope, limit=limit, track_access=False
            )
        finally:
            connection.close()

    def compile(self, request: CompileRequest) -> dict[str, Any]:
        utterance = request.utterance.strip()
        mapping = _phrase_mapping(self.profile, utterance, request.scope)
        expanded = mapping.get("meaning", "") if mapping else ""
        source_text = " ".join(
            part for part in (utterance, expanded, request.context, request.pending_action) if part
        )
        mode = _classify_mode(utterance, request.pending_action)
        if mode == "answer" and (utterance in APPROVAL_TERMS | CONTINUE_TERMS or len(utterance) <= 4):
            mode = _classify_mode(" ".join((request.pending_action, request.context)), "")
        if utterance in CONTINUE_TERMS and mode == "answer":
            mode = "change"
        if utterance in APPROVAL_TERMS and mode == "answer" and request.context:
            mode = "build" if _contains(request.context, ("create", "build", "设计", "创建")) else "change"
        memory_action = _memory_action(source_text, mode)
        risk = _risk(source_text, request.authorization)
        corrections = self.recall_corrections(source_text, request.scope)
        memories = self.recall_memories(source_text, request.scope) if memory_action == "read" else []
        path, clarification = _path_and_clarification(source_text, mode, risk, memories)
        routing_text = source_text if utterance in APPROVAL_TERMS | CONTINUE_TERMS or len(utterance) <= 4 else " ".join((utterance, expanded))
        primary_skill, skill_candidates = _route_skill(routing_text, self.registry)
        if utterance in CONTINUE_TERMS and "obsidian" in source_text.casefold():
            primary_skill = "obsidian-cli"
        confidence = 0.95 if mapping else 0.82 if request.context or request.pending_action else 0.68
        if clarification:
            confidence = min(confidence, 0.72)
        normalized = expanded or request.pending_action if utterance in APPROVAL_TERMS | CONTINUE_TERMS else utterance
        prompt = (
            "Interpret the latest user message using this execution envelope. Preserve the user's voice. "
            "Do not expand authorization beyond the stated scope. Execute reversible in-scope work, but ask "
            "before external, irreversible, sensitive, or otherwise high-impact actions. "
            f"Mode={mode}; path={path}; normalized_goal={normalized!r}; primary_skill={primary_skill!r}; "
            f"memory_action={memory_action}; clarification_required={clarification}; "
            f"risk_reasons={risk['reasons']}; correction_ids={[item['id'] for item in corrections]}."
        )
        envelope = {
            "schema_version": 1,
            "normalized_goal": normalized,
            "path": path,
            "mode": mode,
            "memory_action": memory_action,
            "clarification_required": clarification,
            "preserve_voice": True,
            "confidence": confidence,
            "phrase_match": mapping,
            "risk": risk,
            "corrections": corrections,
            "memories": memories,
            "routing": {
                "primary_skill": primary_skill,
                "candidates": skill_candidates,
                "discovered_skill_count": len(self.registry.get("skills", [])),
                "discovery_errors": len(self.registry.get("errors", [])),
            },
            "completion_contract": {
                "execute": mode not in {"answer", "diagnose"} and not risk["blocked"] and not clarification,
                "verify": mode in {"build", "change", "route"},
                "report_evidence": mode in {"build", "change", "diagnose"},
            },
            "host_prompt": prompt if request.include_prompt else None,
        }
        try:
            receipt = _load_skill_script("decision_receipt").build_receipt(envelope)
        except RuntimeError:
            receipt = None
        envelope["decision_receipt"] = receipt
        return envelope
