"""Typed MCP request models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CompileRequest(BaseModel):
    utterance: str = Field(min_length=1, description="The user's latest exact wording.")
    context: str = Field(default="", description="Compact recent conversation context.")
    pending_action: str = Field(default="", description="Last explicitly proposed unfinished action.")
    scope: str = Field(default="global", min_length=1)
    authorization: Literal["granted", "unknown", "denied"] = "unknown"
    available_files: list[str] = Field(default_factory=list)
    include_prompt: bool = True
    semantic_mode: Literal["off", "auto", "required"] = "auto"
    allow_external_semantic: bool = False
    allow_sensitive_semantic: bool = False


class OnboardingStatusRequest(BaseModel):
    pass


class OnboardingApplyRequest(BaseModel):
    memory: Literal["local", "off", "skip"] = "skip"
    interpretation: Literal["choices", "ask", "skip"] = "skip"
    tone: Literal["concise", "balanced", "detailed", "skip"] = "skip"
    sharp_review: bool | None = None


class CheckRequest(BaseModel):
    goal: str = Field(min_length=1)
    scope: str = "global"
    impact: Literal["low", "medium", "high"] = "low"
    reversible: Literal["yes", "no", "unknown"] = "yes"
    external: bool = False
    sensitive: bool = False
    authorization: Literal["granted", "unknown", "denied"] = "unknown"


class RecallRequest(BaseModel):
    query: str = Field(min_length=1)
    scope: str = "global"
    limit: int = Field(default=5, ge=1, le=20)


class MemoryDefenseRequest(BaseModel):
    scope: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class CorrectionRequest(BaseModel):
    trigger_text: str = Field(min_length=1)
    correction: str = Field(min_length=1)
    scope: str = "global"
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    evidence: str = ""


class CorrectionSuggestionRequest(BaseModel):
    message: str = Field(min_length=1, description="The user's brief correction, such as '太复杂了'.")
    scope: str = "global"
    previous_behavior: str = ""
    replacement: str = ""
    severity: Literal["low", "medium", "high", "critical"] = "medium"


class PendingCorrectionRequest(BaseModel):
    pending_id: int = Field(ge=1)


class OutcomeRequest(BaseModel):
    correction_id: int = Field(ge=1)
    outcome: Literal["heeded", "recurred", "unknown"]
    context: str = ""


class ShadowObserveRequest(BaseModel):
    utterance: str = Field(min_length=1)
    compiler_mode: str = Field(min_length=1)
    compiler_skill: str = ""
    compiler_clarification: bool = False
    codex_mode: str = Field(min_length=1)
    codex_skill: str = ""
    codex_clarification: bool = False
    subject: str = ""
    exam_goal: str = ""
    context_switched: bool = False
    pointer_reused: bool = False
    sample_reason: str = "ambiguous-or-study-routing"


class ShadowReviewRequest(BaseModel):
    days: int = Field(default=30, ge=1, le=365)


class StudyPointerRequest(BaseModel):
    action: Literal["upsert", "list", "reuse", "sync"]
    path: str = ""
    title: str = ""
    purpose: str = ""
    subject: str = ""
    exam_goal: str = ""
    authority_level: Literal["reference", "official", "teacher", "working", "personal"] = "working"
    query: str = ""
    limit: int = Field(default=20, ge=1, le=100)


class StudentStateRequest(BaseModel):
    action: Literal["summary", "list", "upsert", "focus", "complete", "archive", "bootstrap", "sync", "refresh"]
    item_key: str = ""
    category: Literal["", "goal", "course", "assignment", "exam", "research", "project", "career", "campus", "routine", "wellbeing", "finance"] = ""
    title: str = ""
    status: Literal["", "planned", "active", "blocked", "waiting", "done", "archived"] = ""
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    deadline: str = ""
    next_action: str = ""
    subject: str = ""
    goal: str = ""
    source_pointer: str = ""
    details: str = ""
    sensitive: bool = False
    retain_days: int | None = Field(default=None, ge=1, le=3650)
    confirmed: bool = False
    query: str = ""
    limit: int = Field(default=50, ge=1, le=200)
