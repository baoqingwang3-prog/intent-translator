"""FastMCP stdio server for the local intent compiler."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .core import IntentCompiler, _load_skill_script, _memory_path
from .models import (
    CheckRequest,
    CompileRequest,
    CorrectionRequest,
    CorrectionSuggestionRequest,
    OutcomeRequest,
    PendingCorrectionRequest,
    RecallRequest,
    ShadowObserveRequest,
    ShadowReviewRequest,
    StudyPointerRequest,
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


def compiler() -> IntentCompiler:
    return IntentCompiler()


@mcp.tool(
    title="Compile user intent",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True),
    structured_output=True,
)
def intent_compile(request: CompileRequest) -> dict[str, Any]:
    """Compile wording into an envelope, optionally using an explicitly configured semantic adapter."""
    return compiler().compile(request)


@mcp.tool(
    title="Check action risk",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    structured_output=True,
)
def intent_check(request: CheckRequest) -> dict[str, Any]:
    """Check authorization, reversibility, external effects, and correction history without writing."""
    instance = compiler()
    memory = _load_skill_script("memory_store")
    connection = memory.connect(_memory_path(instance.profile))
    try:
        return memory.check_intent(connection, record=False, **request.model_dump())
    finally:
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


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
