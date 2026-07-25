"""Validated intent contract exposed to Agent hosts."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field


Mode = Literal[
    "answer",
    "diagnose",
    "change",
    "build",
    "search",
    "learn",
    "remember",
    "recall",
    "compress",
    "route",
]
Operation = Literal[
    "answer",
    "search",
    "research",
    "create",
    "test",
    "change",
    "publish",
    "delete",
    "install",
    "transfer",
]
Effect = Literal[
    "none",
    "read_public",
    "read_local",
    "write_local",
    "write_external",
    "destructive",
    "system_change",
]
DataEgress = Literal["none", "public_query", "user_text", "private_file", "profile", "memory"]
ActiveTaskSource = Literal["utterance", "pending", "context", "project", "profile"]
ConstraintType = Literal[
    "prohibited-action",
    "deferred-action",
    "future-compatibility",
    "protected-data",
]


class ContractConstraint(BaseModel):
    type: ConstraintType
    action: str = Field(min_length=1)
    text: str = ""
    source: str = "explicit-user-wording"
    active_now: bool | None = None


class ActionOwner(BaseModel):
    kind: Literal["skill", "host", "memory"]
    name: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)


class IntentObject(BaseModel):
    value: str = ""
    source: Literal["utterance", "pending_action", "context", "missing"] = "missing"


class IntentDestination(BaseModel):
    kind: Literal["local", "external", "unknown", "none"]
    value: str = ""


class IntentRisk(BaseModel):
    impact: Literal["low", "medium", "high"]
    reversible: Literal["yes", "no", "unknown"]
    external: bool
    sensitive: bool
    high_stakes: bool
    system_change: bool = False
    ambiguous_action: bool = False
    blocked: bool
    confirmation_required: bool


class IntentAuthorization(BaseModel):
    state: Literal["untrusted", "confirmed", "denied"]
    receipt_verified: bool
    required_grants: list[str] = Field(default_factory=list)


class SourceMapEntry(BaseModel):
    original: str
    compiled: str
    kind: str
    obvious: bool | None = None


class TypedIntentContract(BaseModel):
    schema_version: int = 1
    original_utterance: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    mode: Mode
    operation: Operation
    effect: Effect
    data_egress: DataEgress
    active_task_source: ActiveTaskSource
    action_owner: ActionOwner
    object: IntentObject
    constraints: list[ContractConstraint] = Field(default_factory=list)
    prohibitions: list[ContractConstraint] = Field(default_factory=list)
    artifact: list[str] = Field(default_factory=list)
    destination: IntentDestination
    scope: str = Field(min_length=1)
    pending_action: str = ""
    required_slots: list[str] = Field(default_factory=list)
    risk: IntentRisk
    authorization: IntentAuthorization
    alternatives: list[str] = Field(default_factory=list)
    source_map: list[SourceMapEntry] = Field(default_factory=list)


_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_URL = re.compile(r"https?://[^\s]+", re.I)
_FILE = re.compile(r"(?<![\w.-])(?:[A-Za-z]:[\\/][^\s,，]+|[^\s,，]+\.[A-Za-z0-9]{1,8})")


def _destination(text: str, risk: dict[str, Any]) -> IntentDestination:
    folded = text.casefold()
    if not risk.get("external") and risk.get("effect") != "read_public":
        return IntentDestination(kind="local", value="local environment")
    email = _EMAIL.search(text)
    url = _URL.search(text)
    if email:
        return IntentDestination(kind="external", value=email.group(0))
    if url:
        return IntentDestination(kind="external", value=url.group(0))
    for marker in ("github", "gitlab", "origin", "remote", "互联网", "外部"):
        if marker in folded:
            return IntentDestination(kind="external", value=marker)
    if risk.get("effect") == "read_public":
        return IntentDestination(kind="external", value="public web")
    return IntentDestination(kind="unknown")


def build_typed_contract(
    *,
    utterance: str,
    goal: str,
    mode: str,
    operation: str,
    effect: str,
    data_egress: str,
    active_task_source: str,
    action_text: str,
    primary_skill: str | None,
    skill_candidates: list[dict[str, Any]],
    constraints: list[dict[str, Any]],
    available_files: list[str],
    scope: str,
    pending_action: str,
    short_confirmation_missing: bool,
    risk: dict[str, Any],
    authorization_hint: str,
    alternatives: list[str],
    source_map: list[dict[str, Any]],
) -> TypedIntentContract:
    owner = ActionOwner(
        kind="skill" if primary_skill else "memory" if mode in {"remember", "recall"} else "host",
        name=primary_skill or ("local-memory" if mode in {"remember", "recall"} else "agent-host"),
        evidence=[str(item) for item in (skill_candidates[0].get("matched_terms", []) if skill_candidates else [])],
    )
    object_source = (
        "pending_action"
        if pending_action
        else "utterance"
        if action_text.strip()
        else "missing"
    )
    object_value = pending_action.strip() or action_text.strip()
    destination = _destination(" ".join((utterance, pending_action, action_text)), risk)
    required_slots: list[str] = []
    if mode not in {"answer", "diagnose"} and not object_value:
        required_slots.append("object")
    if risk.get("ambiguous_action"):
        required_slots.append("object")
    if risk.get("external") and destination.kind == "unknown":
        required_slots.append("destination")
    if short_confirmation_missing:
        required_slots.append("pending_action")

    grants: list[str] = []
    challenge = risk.get("confirmation_challenge", {})
    grants.extend(str(item) for item in challenge.get("grants", []))
    if risk.get("receipt_verified"):
        grants.extend(
            item
            for item, enabled in (
                ("external", risk.get("external")),
                ("destructive", risk.get("reversible") == "no"),
                ("sensitive", risk.get("sensitive")),
                ("install", risk.get("system_change")),
            )
            if enabled
        )
    authorization = IntentAuthorization(
        state=(
            "denied"
            if authorization_hint == "denied"
            else "confirmed"
            if risk.get("receipt_verified")
            else "untrusted"
        ),
        receipt_verified=bool(risk.get("receipt_verified")),
        required_grants=sorted(set(grants)),
    )
    typed_constraints = [ContractConstraint.model_validate(item) for item in constraints]
    artifacts = list(dict.fromkeys([*available_files, *[match.group(0) for match in _FILE.finditer(action_text)]]))
    return TypedIntentContract(
        original_utterance=utterance,
        goal=goal,
        mode=mode,
        operation=operation,
        effect=effect,
        data_egress=data_egress,
        active_task_source=active_task_source,
        action_owner=owner,
        object=IntentObject(value=object_value, source=object_source),
        constraints=typed_constraints,
        prohibitions=[item for item in typed_constraints if item.type in {"prohibited-action", "protected-data"}],
        artifact=artifacts,
        destination=destination,
        scope=scope,
        pending_action=pending_action,
        required_slots=sorted(set(required_slots)),
        risk=IntentRisk.model_validate(risk),
        authorization=authorization,
        alternatives=alternatives,
        source_map=[SourceMapEntry.model_validate(item) for item in source_map],
    )
