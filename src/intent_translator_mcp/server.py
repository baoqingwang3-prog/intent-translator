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
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    structured_output=True,
)
def intent_compile(request: CompileRequest) -> dict[str, Any]:
    """Compile exact user wording and recent context into an execution envelope."""
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


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
