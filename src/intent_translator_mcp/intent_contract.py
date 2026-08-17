"""Validated intent contract exposed to Agent hosts."""

from __future__ import annotations

import hashlib
import json
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
    "diagnose",
    "search",
    "research",
    "create",
    "test",
    "change",
    "publish",
    "delete",
    "install",
    "start",
    "transfer",
]
Effect = Literal[
    "none",
    "read_public",
    "read_local",
    "write_local",
    "write_internal",
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


class ContractAction(BaseModel):
    order: int = 0
    predicate: str = Field(min_length=1)
    object: str = ""
    polarity: Literal["asserted", "prohibited"]
    temporal_role: Literal["current", "sequential", "committed", "conditional"]
    destination_role: Literal["local", "external", "public", "unknown"]
    text: str = ""
    active_now: bool
    required_grants: list[str] = Field(default_factory=list)
    gate_state: Literal["active", "dormant", "prohibited", "pending_confirmation", "allowed"]
    canonical_args: dict[str, Any] = Field(default_factory=dict)
    bundle_digest: str = ""
    per_frame_digest: str = ""
    confirmation_challenge: dict[str, Any] | None = None


class ActionOwner(BaseModel):
    kind: Literal["skill", "host", "memory"]
    name: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)


class IntentObject(BaseModel):
    value: str = ""
    source: Literal["utterance", "pending_action", "context", "missing"] = "missing"


class IntentDestination(BaseModel):
    kind: Literal[
        "local",
        "external",
        "unknown",
        "none",
        "internal_thread",
        "local_artifact",
        "public_endpoint",
        "system_target",
    ]
    value: str = ""
    externality: Literal["internal", "external", "unknown"] = "unknown"
    resolution: Literal["resolved", "unresolved", "conflicted"] = "unresolved"
    endpoint_ref: str = ""


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
    action_digest: str = ""
    canonical_action: str = ""


class SourceMapEntry(BaseModel):
    original: str
    compiled: str
    kind: str
    obvious: bool | None = None


class CommunicationContract(BaseModel):
    active: bool = False
    communication_purpose: Literal[
        "none", "show-project", "request-feedback", "fundraising", "technical-review"
    ] = "none"
    relationship_context: Literal["unspecified", "personal", "professional"] = "unspecified"
    recipient_expertise: Literal["unknown", "general", "investor", "engineer"] = "unknown"
    desired_effect: Literal[
        "unspecified", "understand", "evaluate", "invest", "contribute", "review"
    ] = "unspecified"
    recommended_artifact: Literal["none", "local-preview"] = "none"
    channel: Literal["unspecified", "email", "chat", "public"] = "unspecified"
    disclosure: Literal["local-only", "private-recipient", "public"] = "local-only"
    template: Literal[
        "none", "general-overview", "investor-overview", "engineering-overview"
    ] = "none"
    sections: list[str] = Field(default_factory=list)
    excluded_disclosures: list[str] = Field(default_factory=list)
    needs_purpose_question: bool = False
    question: str = ""


class TypedIntentContract(BaseModel):
    schema_version: int = 1
    original_utterance: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    mode: Mode
    operation: Operation
    effect: Effect
    data_egress: DataEgress
    semantic_operation: str = "none"
    semantic_id: str = ""
    discourse_role: str = "directive"
    mentioned_actions: list[str] = Field(default_factory=list)
    active_actions: list[str] = Field(default_factory=list)
    prohibited_actions: list[str] = Field(default_factory=list)
    prohibition_unbound: list[str] = Field(default_factory=list)
    semantic_recipient: dict[str, Any] = Field(default_factory=dict)
    routing_relation: dict[str, Any] = Field(default_factory=dict)
    execution_commitment: dict[str, Any] = Field(default_factory=dict)
    required_grants: list[str] = Field(default_factory=list)
    confirmation_required: bool = False
    projection_source_action_ids: list[str] = Field(default_factory=list)
    composition_trace: list[dict[str, Any]] = Field(default_factory=list)
    legacy_compatibility: dict[str, Any] = Field(default_factory=dict)
    active_task_source: ActiveTaskSource
    action_owner: ActionOwner
    object: IntentObject
    constraints: list[ContractConstraint] = Field(default_factory=list)
    prohibitions: list[ContractConstraint] = Field(default_factory=list)
    actions: list[ContractAction] = Field(default_factory=list)
    branches: list[ContractAction] = Field(default_factory=list)
    artifact: list[str] = Field(default_factory=list)
    destination: IntentDestination
    scope: str = Field(min_length=1)
    pending_action: str = ""
    required_slots: list[str] = Field(default_factory=list)
    risk: IntentRisk
    authorization: IntentAuthorization
    communication: CommunicationContract = Field(default_factory=CommunicationContract)
    alternatives: list[str] = Field(default_factory=list)
    source_map: list[SourceMapEntry] = Field(default_factory=list)


_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_URL = re.compile(r"https?://[^\s]+", re.I)
_FILE = re.compile(r"(?<![\w.-])(?:[A-Za-z]:[\\/][^\s,，]+|[^\s,，]+\.[A-Za-z0-9]{1,8})")


_TRANSFER_EGRESS_VALUES = {"user_text", "private_file", "profile", "memory"}


def _infer_transfer_egress(text: str, current: str) -> str:
    """Preserve the legacy egress class when the RC4 projection only says transfer.

    The RC4 semantic layer intentionally keeps the operation separate from the
    older ``data_egress`` field.  Do not collapse a profile or memory transfer
    to the generic ``user_text`` value merely because the projection omitted
    the legacy detail.
    """
    folded = text.casefold()
    if any(term in folded for term in ("完整用户画像", "用户画像", "profile", "persona")):
        return "profile"
    if any(term in folded for term in ("记忆", "memory", "memories", "个人记忆")):
        return "memory"
    if any(
        term in folded
        for term in ("文件", "文档", "报告", "附件", "draft", "file", "document", "private")
    ) or _FILE.search(text):
        return "private_file"
    if current in _TRANSFER_EGRESS_VALUES:
        return current
    return "user_text"


def _communication_contract(text: str) -> CommunicationContract:
    folded = text.casefold()
    personal_terms = (
        "女朋友", "男朋友", "伴侣", "朋友", "家人",
        "girlfriend", "boyfriend", "partner", "friend", "family",
    )
    investor_terms = ("vc", "投资人", "天使投资", "investor", "venture capitalist")
    engineer_terms = ("工程师", "开发者", "程序员", "engineer", "developer", "maintainer")
    show_terms = ("看看", "看一下", "看的", "项目介绍", "给人看", "show", "preview", "overview")
    feedback_terms = ("试用", "挑问题", "提意见", "反馈", "try it", "feedback", "review it")
    active = any(term in folded for term in (*personal_terms, *investor_terms, *engineer_terms)) and any(
        term in folded for term in (*show_terms, *feedback_terms, "发给", "给")
    )
    if not active:
        return CommunicationContract()

    relationship = (
        "personal"
        if any(term in folded for term in personal_terms)
        else "professional"
        if any(term in folded for term in (*investor_terms, *engineer_terms))
        else "unspecified"
    )
    expertise = (
        "investor"
        if any(term in folded for term in investor_terms)
        else "engineer"
        if any(term in folded for term in engineer_terms)
        else "unknown"
    )
    if expertise == "investor":
        purpose, desired, template = "fundraising", "invest", "investor-overview"
        sections = ["problem", "target-users", "differentiation", "evidence", "risks", "ask"]
        excluded = ["source-code", "diagnostics", "profile", "private-memory", "internal-terms"]
    elif expertise == "engineer":
        purpose, desired, template = "technical-review", "contribute", "engineering-overview"
        sections = ["architecture", "tests", "contribution-entry"]
        excluded = ["profile", "private-memory", "secrets", "unrelated-diagnostics"]
    elif any(term in folded for term in feedback_terms):
        purpose, desired, template = "request-feedback", "evaluate", "general-overview"
        sections = ["what-it-is", "problem", "one-example", "how-to-try", "feedback-request"]
        excluded = ["source-code", "diagnostics", "profile", "private-memory", "internal-terms"]
    else:
        purpose, desired, template = "show-project", "understand", "general-overview"
        sections = ["what-it-is", "problem", "one-example"]
        excluded = ["source-code", "diagnostics", "profile", "private-memory", "internal-terms"]

    channel = (
        "email"
        if any(term in folded for term in ("email", "邮箱", "邮件"))
        else "chat"
        if any(term in folded for term in ("微信", "whatsapp", "message", "私信"))
        else "public"
        if any(term in folded for term in ("公开", "public", "publish"))
        and not any(term in folded for term in ("别公开", "不要公开", "do not publish", "not public"))
        else "unspecified"
    )
    disclosure = (
        "public"
        if channel == "public"
        else "private-recipient"
        if channel != "unspecified"
        else "local-only"
    )
    needs_question = purpose == "show-project" and relationship == "personal"
    return CommunicationContract(
        active=True,
        communication_purpose=purpose,
        relationship_context=relationship,
        recipient_expertise=expertise,
        desired_effect=desired,
        recommended_artifact="local-preview",
        channel=channel,
        disclosure=disclosure,
        template=template,
        sections=sections,
        excluded_disclosures=excluded,
        needs_purpose_question=needs_question,
        question="你是想让她看懂你做了什么，还是请她试用并挑问题？" if needs_question else "",
    )


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
    for marker in ("github", "gitlab", "origin"):
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
    additional_required_slots: list[str] | None = None,
    action_owner_name: str | None = None,
    action_frames: list[dict[str, Any]] | None = None,
    canonical_action: str = "",
    semantic_projection: dict[str, Any] | None = None,
) -> TypedIntentContract:
    semantic_projection = dict(semantic_projection or {})
    semantic_operation = str(semantic_projection.get("semantic_operation", "none"))
    semantic_text = " ".join(
        part.strip()
        for part in (utterance, pending_action, action_text)
        if isinstance(part, str) and part.strip()
    )
    typed_data_egress = data_egress
    if semantic_operation == "publish_public":
        # The public-publish RC4 operation carries a private artifact even when
        # the legacy classifier reported a generic text payload.
        typed_data_egress = "private_file"
    elif semantic_operation == "transfer":
        typed_data_egress = _infer_transfer_egress(semantic_text, data_egress)
    owner = ActionOwner(
        kind="skill" if primary_skill else "memory" if mode in {"remember", "recall"} else "host",
        name=primary_skill
        or action_owner_name
        or ("local-memory" if mode in {"remember", "recall"} else "agent-host"),
        evidence=[str(item) for item in (skill_candidates[0].get("matched_terms", []) if skill_candidates else [])],
    )
    object_source = (
        "pending_action"
        if pending_action and active_task_source == "pending"
        else "utterance"
        if action_text.strip()
        else "missing"
    )
    object_value = (
        pending_action.strip()
        if pending_action and active_task_source == "pending"
        else utterance.strip()
        if active_task_source == "utterance"
        else action_text.strip()
    )
    legacy_destination = _destination(" ".join((utterance, pending_action, action_text)), risk)
    destination = _destination(action_text, risk)
    projected_destination = semantic_projection.get("destination")
    if isinstance(projected_destination, dict):
        destination = IntentDestination.model_validate(projected_destination)
    required_slots: list[str] = []
    if mode not in {"answer", "diagnose"} and not object_value:
        required_slots.append("object")
    if risk.get("ambiguous_action"):
        required_slots.append("object")
    if risk.get("external") and destination.kind == "unknown":
        required_slots.append("destination")
    if short_confirmation_missing:
        required_slots.append("pending_action")
    required_slots.extend(additional_required_slots or [])

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
        action_digest=str(risk.get("action_digest", "")),
        canonical_action=canonical_action,
    )
    typed_constraints = [ContractConstraint.model_validate(item) for item in constraints]
    typed_actions = [
        ContractAction.model_validate(
            {
                **item,
                "active_now": bool(
                    item.get("polarity") == "asserted"
                    and item.get("temporal_role") in {"current", "sequential", "committed"}
                ),
                "required_grants": sorted(set(item.get("required_grants", []))),
                "gate_state": (
                    "prohibited"
                    if item.get("polarity") == "prohibited"
                    else "dormant"
                    if item.get("temporal_role") == "conditional"
                    else "allowed"
                    if risk.get("receipt_verified") and item.get("required_grants")
                    else "pending_confirmation"
                    if item.get("predicate") in {"transfer", "publish", "delete", "install"}
                    else "active"
                ),
                "canonical_args": {
                    "predicate": item.get("predicate"),
                    "object": item.get("object", ""),
                    "destination": item.get("destination_role", "unknown"),
                    "scope": scope,
                    "temporal_role": item.get("temporal_role"),
                },
                "bundle_digest": (
                    str(risk.get("action_digest", ""))
                    if item.get("polarity") == "asserted"
                    and item.get("temporal_role") in {"current", "sequential", "committed"}
                    else ""
                ),
                "per_frame_digest": hashlib.sha256(
                    json.dumps(
                        {
                            "predicate": item.get("predicate"),
                            "object": item.get("object", ""),
                            "destination": item.get("destination_role", "unknown"),
                            "scope": scope,
                            "temporal_role": item.get("temporal_role"),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                "confirmation_challenge": (
                    risk.get("confirmation_challenge")
                    if item.get("polarity") == "asserted"
                    and item.get("temporal_role") in {"current", "sequential", "committed"}
                    and not risk.get("receipt_verified")
                    and item.get("predicate") in {"transfer", "publish", "delete", "install"}
                    else None
                ),
            }
        )
        for item in (action_frames or [])
        if item.get("predicate") != "other"
    ]
    # Keep the pre-RC4 compatibility projection's historical publish value;
    # the typed field above is the stricter private-artifact classification.
    legacy_data_egress = "user_text" if semantic_operation == "publish_public" else typed_data_egress
    legacy_compatibility = {
        "schema_version": 1,
        "mode": mode,
        "operation": operation,
        "effect": effect,
        "data_egress": legacy_data_egress,
        "destination": legacy_destination.model_dump(mode="json"),
        "required_grants": list(authorization.required_grants),
        "confirmation_required": bool(risk.get("confirmation_required")),
    }
    artifacts = list(dict.fromkeys([*available_files, *[match.group(0) for match in _FILE.finditer(action_text)]]))
    return TypedIntentContract(
        original_utterance=utterance,
        goal=goal,
        mode=mode,
        operation=operation,
        effect=effect,
        data_egress=typed_data_egress,
        semantic_operation=semantic_operation,
        semantic_id=str(semantic_projection.get("semantic_id", "")),
        discourse_role=str(semantic_projection.get("discourse_role", "directive")),
        mentioned_actions=sorted(set(str(item) for item in semantic_projection.get("mentioned_actions", []))),
        active_actions=sorted(set(str(item) for item in semantic_projection.get("active_actions", []))),
        prohibited_actions=sorted(set(str(item) for item in semantic_projection.get("prohibited_actions", []))),
        prohibition_unbound=sorted(set(str(item) for item in semantic_projection.get("prohibition_unbound", []))),
        semantic_recipient=dict(semantic_projection.get("semantic_recipient") or {}),
        routing_relation=dict(semantic_projection.get("routing_relation") or {}),
        execution_commitment=dict(semantic_projection.get("execution_commitment") or {}),
        required_grants=sorted(set(str(item) for item in semantic_projection.get("required_grants", []))),
        confirmation_required=bool(semantic_projection.get("confirmation_required", risk.get("confirmation_required", False))),
        projection_source_action_ids=sorted(set(str(item) for item in semantic_projection.get("projection_source_action_ids", []))),
        composition_trace=[dict(item) for item in semantic_projection.get("composition_trace", []) if isinstance(item, dict)],
        legacy_compatibility=legacy_compatibility,
        active_task_source=active_task_source,
        action_owner=owner,
        object=IntentObject(value=object_value, source=object_source),
        constraints=typed_constraints,
        prohibitions=[item for item in typed_constraints if item.type in {"prohibited-action", "protected-data"}],
        actions=typed_actions,
        branches=[item for item in typed_actions if item.temporal_role == "conditional"],
        artifact=artifacts,
        destination=destination,
        scope=scope,
        pending_action=pending_action,
        required_slots=sorted(set(required_slots)),
        risk=IntentRisk.model_validate(risk),
        authorization=authorization,
        communication=_communication_contract(" ".join((utterance, pending_action, action_text))),
        alternatives=alternatives,
        source_map=[SourceMapEntry.model_validate(item) for item in source_map],
    )
