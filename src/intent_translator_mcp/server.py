"""FastMCP stdio server for the local intent compiler."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .core import (
    IntentCompiler,
    _candidate_skill_dirs,
    _load_skill_script,
    _memory_enabled,
    _memory_path,
    _profile_path,
)
from .models import (
    CheckRequest,
    CompileRequest,
    CorrectionRequest,
    CorrectionSuggestionRequest,
    MemoryDefenseRequest,
    OnboardingApplyRequest,
    OnboardingStatusRequest,
    OutcomeRequest,
    PendingCorrectionRequest,
    RecallRequest,
    ShadowObserveRequest,
    ShadowReviewRequest,
    StudyPointerRequest,
    StudentStateRequest,
)
from .onboarding import (
    apply_onboarding,
    default_profile_path,
    onboarding_status,
    onboarding_summary,
)
from .student_state import (
    bootstrap_from_profile,
    connect as connect_state,
    list_state_items,
    refresh_from_canonical,
    set_focus,
    state_db_path,
    summarize_state,
    sync_state_note,
    update_state_status,
    upsert_state_item,
)
from .study_shadow import (
    connect as connect_study,
    list_pointers,
    observe_shadow,
    render_pointer_index,
    reuse_pointer,
    review_shadow,
    study_db_path,
    sync_pointer_index,
    upsert_pointer,
)


mcp = FastMCP(
    "intent-translator",
    instructions=(
        "Call intent_compile before acting on terse, implicit, context-dependent, or consequential "
        "requests. Treat its output as a deterministic preflight, not as mind reading."
    ),
)


def _path_signature(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
        return str(path), stat.st_mtime_ns, stat.st_size
    except OSError:
        return str(path), 0, 0


def _compiler_cache_key() -> tuple[Any, ...]:
    semantic_env = tuple(
        os.environ.get(name, "")
        for name in (
            "INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON",
            "INTENT_TRANSLATOR_SEMANTIC_PROVIDER",
            "INTENT_TRANSLATOR_SEMANTIC_BASE_URL",
            "INTENT_TRANSLATOR_SEMANTIC_MODEL",
            "INTENT_TRANSLATOR_SEMANTIC_EXTERNAL",
        )
    )
    return (
        _path_signature(_profile_path()),
        tuple(_path_signature(path) for path in _candidate_skill_dirs()),
        semantic_env,
    )


@lru_cache(maxsize=4)
def _cached_compiler(cache_key: tuple[Any, ...]) -> IntentCompiler:
    return IntentCompiler(entrypoint="mcp")


def compiler() -> IntentCompiler:
    return _cached_compiler(_compiler_cache_key())


def _compact_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    routing = envelope.get("routing", {})
    runtime = envelope.get("runtime_status", {})
    compact = {
        key: envelope[key]
        for key in (
            "schema_version",
            "normalized_goal",
            "path",
            "mode",
            "memory_action",
            "clarification_required",
            "preserve_voice",
            "confidence",
            "confidence_calibration",
            "phrase_match",
            "short_confirmation_status",
            "risk",
            "constraints",
            "semantic_fidelity",
            "interpretation_gate",
            "prompt_source_map",
            "intent_contract",
            "current_status",
            "completion_contract",
            "host_prompt",
            "decision_receipt",
        )
        if key in envelope
    }
    compact["routing"] = {
        "primary_skill": routing.get("primary_skill"),
        "route_reason": (
            envelope.get("decision_receipt", {}) or {}
        ).get("route_reason", ""),
        "acquisition_policy": routing.get("acquisition_policy", []),
    }
    compact["semantic"] = {
        key: envelope.get("semantic", {}).get(key)
        for key in ("status", "provider", "proposal", "error")
        if envelope.get("semantic", {}).get(key) is not None
    }
    study = envelope.get("study_context", {})
    if study.get("enabled"):
        compact["study_context"] = study
        compact["state_status"] = envelope.get("state_status", {})
    if envelope.get("adaptive_autonomy", {}).get("mode") == "cautious":
        compact["adaptive_autonomy"] = envelope["adaptive_autonomy"]
    compact["runtime_status"] = {
        "state": runtime.get("state"),
        "restart_required": runtime.get("restart_required", False),
        "version": runtime.get("versions", {}).get("actual_runtime"),
    }
    diagnostic_refs = {
        "correction_ids": [item.get("id") for item in envelope.get("corrections", [])],
        "memory_ids": [item.get("id") for item in envelope.get("memories", [])],
    }
    if any(diagnostic_refs.values()):
        compact["diagnostic_refs"] = diagnostic_refs
    return compact


@mcp.tool(
    title="Compile user intent",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True),
    structured_output=True,
)
def intent_compile(request: CompileRequest) -> dict[str, Any]:
    """Compile wording into an envelope, optionally using an explicitly configured semantic adapter."""
    envelope = compiler().compile(request)
    return envelope if request.include_diagnostics else _compact_envelope(envelope)


@mcp.tool(
    title="Inspect onboarding status",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    structured_output=True,
)
def intent_onboarding_status(request: OnboardingStatusRequest) -> dict[str, Any]:
    """Return the three skippable local onboarding choices without claiming personal knowledge."""
    path = default_profile_path()
    try:
        profile = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        profile = None
    return onboarding_status(
        profile_exists=path.exists(), profile=profile, entrypoint="mcp:onboarding"
    )


@mcp.tool(
    title="Apply local onboarding choices",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    structured_output=True,
)
def intent_apply_onboarding(request: OnboardingApplyRequest) -> dict[str, Any]:
    """Apply memory, interpretation, and tone choices to the local profile."""
    profile = apply_onboarding(default_profile_path(), **request.model_dump())
    return onboarding_summary(profile)


@mcp.tool(
    title="Check action risk",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    structured_output=True,
)
def intent_check(request: CheckRequest) -> dict[str, Any]:
    """Check authorization, reversibility, external effects, and correction history without writing."""
    instance = compiler()
    memory = _load_skill_script("memory_store")
    path = _memory_path(instance.profile)
    connection = (
        memory.connect_readonly(path)
        if _memory_enabled(instance.profile) and path.exists()
        else None
    )
    try:
        return memory.check_intent(connection, record=False, **request.model_dump())
    finally:
        if connection is not None:
            connection.close()


@mcp.tool(
    title="Recall past corrections",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    structured_output=True,
)
def intent_recall_corrections(request: RecallRequest) -> dict[str, Any]:
    """Retrieve relevant active corrections without changing retrieval counters."""
    return {"corrections": compiler().recall_corrections(**request.model_dump())}


@mcp.tool(
    title="Inspect memory defense",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    structured_output=True,
)
def intent_memory_defense(request: MemoryDefenseRequest) -> dict[str, Any]:
    """Report memory trust counts and quarantine metadata without exposing quarantined text."""
    instance = compiler()
    memory = _load_skill_script("memory_store")
    path = _memory_path(instance.profile)
    if not _memory_enabled(instance.profile) or not path.exists():
        return {
            "scope": request.scope or "all",
            "counts": {"trusted": 0, "quarantined": 0, "untrusted": 0},
            "quarantined": [],
            "quarantined_text_exposed": False,
            "instruction_execution_allowed": False,
            "memory_mode": "off" if not _memory_enabled(instance.profile) else "empty",
        }
    connection = memory.connect_readonly(path)
    try:
        if not memory.table_exists(connection, "memories"):
            return {
                "scope": request.scope or "all",
                "counts": {"trusted": 0, "quarantined": 0, "untrusted": 0},
                "quarantined": [],
                "quarantined_text_exposed": False,
                "instruction_execution_allowed": False,
                "memory_mode": "empty",
            }
        return memory.memory_defense_status(connection, **request.model_dump())
    finally:
        connection.close()


@mcp.tool(
    title="Record an intent correction",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    structured_output=True,
)
def intent_record_correction(request: CorrectionRequest) -> dict[str, Any]:
    """Store a user-confirmed interpretation correction in the local SQLite ledger."""
    instance = compiler()
    memory = _load_skill_script("memory_store")
    connection = memory.connect(_memory_path(instance.profile))
    try:
        return memory.add_correction(connection, **request.model_dump())
    finally:
        connection.close()


@mcp.tool(
    title="Suggest a correction",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    structured_output=True,
)
def intent_suggest_correction(request: CorrectionSuggestionRequest) -> dict[str, Any]:
    """Create a pending correction and return one concise confirmation prompt."""
    instance = compiler()
    memory = _load_skill_script("memory_store")
    connection = memory.connect(_memory_path(instance.profile))
    try:
        return memory.suggest_correction(connection, **request.model_dump())
    finally:
        connection.close()


@mcp.tool(
    title="Confirm a pending correction",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    structured_output=True,
)
def intent_confirm_correction(request: PendingCorrectionRequest) -> dict[str, Any]:
    """Promote a user-confirmed pending correction into the durable correction ledger."""
    instance = compiler()
    memory = _load_skill_script("memory_store")
    connection = memory.connect(_memory_path(instance.profile))
    try:
        return memory.confirm_pending_correction(connection, request.pending_id)
    finally:
        connection.close()


@mcp.tool(
    title="Record correction outcome",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    structured_output=True,
)
def intent_record_outcome(request: OutcomeRequest) -> dict[str, Any]:
    """Record whether a retrieved correction was followed or the same failure recurred."""
    instance = compiler()
    memory = _load_skill_script("memory_store")
    connection = memory.connect(_memory_path(instance.profile))
    try:
        return memory.record_correction_outcome(connection, **request.model_dump())
    finally:
        connection.close()


@mcp.tool(
    title="Observe an intent decision in shadow mode",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    structured_output=True,
)
def intent_shadow_observe(request: ShadowObserveRequest) -> dict[str, Any]:
    """Record a privacy-bounded comparison without interrupting the user or storing the full utterance."""
    instance = compiler()
    connection = connect_study(study_db_path(instance.profile))
    try:
        payload = request.model_dump()
        payload["host_mode"] = payload.pop("codex_mode")
        payload["host_skill"] = payload.pop("codex_skill")
        payload["host_clarification"] = payload.pop("codex_clarification")
        return observe_shadow(connection, instance.profile, **payload)
    finally:
        connection.close()


@mcp.tool(
    title="Review shadow evaluation",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    structured_output=True,
)
def intent_shadow_review(request: ShadowReviewRequest) -> dict[str, Any]:
    """Aggregate local mismatch, interruption, and material-reuse metrics."""
    instance = compiler()
    connection = connect_study(study_db_path(instance.profile))
    try:
        return review_shadow(connection, days=request.days)
    finally:
        connection.close()


@mcp.tool(
    title="Manage study material pointers",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True),
    structured_output=True,
)
def intent_study_pointer(request: StudyPointerRequest) -> dict[str, Any]:
    """Upsert, find, reuse, or explicitly sync local study pointers without scanning the vault."""
    instance = compiler()
    connection = connect_study(study_db_path(instance.profile))
    try:
        if request.action == "upsert":
            return {"pointer": upsert_pointer(connection, **request.model_dump(include={"path", "title", "purpose", "subject", "exam_goal", "authority_level"}))}
        if request.action == "reuse":
            if not request.path.strip():
                raise ValueError("reuse requires path")
            return {"pointer": reuse_pointer(connection, path=request.path)}
        pointers = list_pointers(
            connection,
            query=request.query,
            subject=request.subject,
            exam_goal=request.exam_goal,
            limit=request.limit,
        )
        if request.action == "list":
            return {"pointers": pointers, "count": len(pointers)}
        content = render_pointer_index(list_pointers(connection, limit=100))
        return {**sync_pointer_index(instance.profile, content), "pointer_count": len(pointers)}
    finally:
        connection.close()


@mcp.tool(
    title="Manage local university state",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True),
    structured_output=True,
)
def intent_student_state(request: StudentStateRequest) -> dict[str, Any]:
    """Manage local goals, deadlines, focus, next actions, and an optional Obsidian state mirror."""
    instance = compiler()
    connection = connect_state(state_db_path(instance.profile))
    try:
        if request.action == "summary":
            return summarize_state(connection, due_soon_days=int(instance.profile.get("student_state", {}).get("due_soon_days", 7)))
        if request.action == "list":
            return {
                "items": list_state_items(
                    connection,
                    category=request.category,
                    status=request.status,
                    query=request.query,
                    limit=request.limit,
                )
            }
        if request.action == "bootstrap":
            result = bootstrap_from_profile(connection, instance.profile)
            return {**result, "canonical": sync_state_note(connection, instance.profile)}
        if request.action == "upsert":
            if not request.category or not request.title.strip():
                raise ValueError("upsert requires category and title")
            item = upsert_state_item(
                    connection,
                    item_key=request.item_key,
                    category=request.category,
                    title=request.title,
                    status=request.status or "planned",
                    priority=request.priority,
                    deadline=request.deadline,
                    next_action=request.next_action,
                    subject=request.subject,
                    goal=request.goal,
                    source_pointer=request.source_pointer,
                    details=request.details,
                    sensitive=request.sensitive,
                    retain_days=request.retain_days,
                )
            return {"item": item, "canonical": sync_state_note(connection, instance.profile)}
        if request.action == "focus":
            item = set_focus(connection, item_key=request.item_key)
            return {"item": item, "canonical": sync_state_note(connection, instance.profile)}
        if request.action in {"complete", "archive"}:
            item = update_state_status(
                    connection,
                    item_key=request.item_key,
                    status="done" if request.action == "complete" else "archived",
                )
            return {"item": item, "canonical": sync_state_note(connection, instance.profile)}
        if request.action == "refresh":
            return refresh_from_canonical(connection, instance.profile, confirmed=request.confirmed)
        summary = summarize_state(connection, due_soon_days=int(instance.profile.get("student_state", {}).get("due_soon_days", 7)))
        return sync_state_note(connection, instance.profile, summary)
    finally:
        connection.close()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
