"""FastMCP stdio server for the local intent compiler."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Settings as FastMCPSettings
from mcp.types import ToolAnnotations

from .control_plane import (
    AdmissionDecision,
    ClaimLevel,
    ControlPlane,
    ExecutionEnvelope,
    ExecutionEvidence,
)
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
    ControlRecordRequest,
    ControlResumeRequest,
    CorrectionRequest,
    CorrectionSuggestionRequest,
    ExecutionVerificationRequest,
    LanguageRuleConfirmRequest,
    LanguageRuleObservationRequest,
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
from .presentation import compact_envelope
from .invocation import build_invocation_receipt
from .onboarding import (
    apply_onboarding,
    confirm_language_rule,
    default_profile_path,
    observe_language_correction,
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


FastMCPSettings.model_rebuild()

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


def _skill_roots_signature() -> tuple[tuple[str, int, int], ...]:
    roots = tuple(Path(root) for root in _load_skill_script("discover_skills").default_roots())
    root_entries: list[tuple[int, Path, list[os.DirEntry[str]]]] = []
    for priority, root in enumerate(roots):
        if not root.exists():
            root_entries.append((priority, root, []))
            continue
        try:
            entries = sorted(os.scandir(root), key=lambda item: item.name.casefold())
        except OSError:
            root_entries.append((priority, root, []))
            continue
        directories: list[os.DirEntry[str]] = []
        for entry in entries:
            try:
                if not entry.is_dir():
                    continue
            except OSError:
                continue
            directories.append(entry)
        root_entries.append((priority, root, directories))

    signatures: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    for priority, root, entries in root_entries:
        if not entries:
            signatures.append((f"{priority}:{root}", 0, 0))
            continue
        for entry in entries:
            skill_path = os.path.join(entry.path, "SKILL.md")
            canonical = os.path.normcase(os.path.abspath(skill_path))
            if canonical in seen:
                continue
            try:
                stat = os.stat(skill_path)
            except OSError:
                continue
            seen.add(canonical)
            signatures.append((f"{priority}:{canonical}", stat.st_mtime_ns, stat.st_size))
    return tuple(signatures)


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
        _skill_roots_signature(),
        semantic_env,
    )


@lru_cache(maxsize=4)
def _cached_compiler(cache_key: tuple[Any, ...]) -> IntentCompiler:
    return IntentCompiler(entrypoint="mcp")


def compiler() -> IntentCompiler:
    return _cached_compiler(_compiler_cache_key())


def _control_state_path() -> Path:
    configured = os.environ.get("INTENT_TRANSLATOR_CONTROL_DB", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".intent-translator" / "control-plane.db").resolve()


@lru_cache(maxsize=8)
def _cached_control_plane(state_path: str) -> ControlPlane:
    return ControlPlane(state_path=state_path)


def control_plane() -> ControlPlane:
    return _cached_control_plane(str(_control_state_path()))


def _server_claim_level(envelope: dict[str, Any]) -> ClaimLevel:
    risk = envelope.get("risk", {})
    contract = envelope.get("intent_contract", {})
    if (
        not envelope.get("completion_contract", {}).get("execute", False)
        or envelope.get("tool_gateway", {}).get("decision") != "allow"
        or envelope.get("clarification_required", False)
        or risk.get("blocked", False)
    ):
        return ClaimLevel.READ_ONLY_FORM
    protected = bool(
        risk.get("external")
        or risk.get("sensitive")
        or risk.get("high_stakes")
        or risk.get("system_change")
        or risk.get("reversible") == "no"
        or contract.get("required_grants")
    )
    if protected and not risk.get("receipt_verified", False):
        return ClaimLevel.READ_ONLY_FORM
    if risk.get("external") or contract.get("data_egress") not in {None, "", "none"}:
        return ClaimLevel.ONE_SEND_AUTHORIZED
    if protected:
        return ClaimLevel.EXECUTION_AUTHORIZED
    return ClaimLevel.ACTION_AUTHORIZED


def _execution_envelope(
    request: CompileRequest,
    compiled: dict[str, Any],
    invocation_receipt: dict[str, Any],
) -> ExecutionEnvelope:
    if request.control is None:
        raise ValueError("control identity is required")
    contract = compiled["intent_contract"]
    risk = compiled.get("risk", {})
    destination = contract.get("destination") or {}
    destination_value = (
        destination.get("endpoint_ref")
        or destination.get("value")
        or destination.get("kind")
        or "unresolved"
    )
    action_digest = str(risk.get("action_digest") or contract.get("authorization", {}).get("action_digest") or "")
    if risk.get("receipt_verified", False) and action_digest:
        authorization_id = f"confirmation:{action_digest}"
    elif risk.get("confirmation_required", False):
        authorization_id = "ungranted"
    else:
        authorization_id = "compiler:unprotected"
    data_class = "sensitive" if risk.get("sensitive", False) else request.control.data_class
    return ExecutionEnvelope(
        goal_id=request.control.goal_id,
        task_id=request.control.task_id,
        dedupe_key=request.control.dedupe_key,
        frame_id=request.control.frame_id,
        object=str(contract.get("object", {}).get("value") or contract.get("goal") or request.utterance),
        operation=str(contract.get("operation") or compiled.get("mode") or "unknown"),
        effect=str(contract.get("effect") or "unknown"),
        destination=str(destination_value),
        data_class=data_class,
        authorization_id=authorization_id,
        owner_thread=request.control.owner_thread,
        generation=request.control.generation,
        provenance=(f"intent_compile:{invocation_receipt['receipt_id']}",),
        required_artifacts=tuple(request.control.required_artifacts),
        cannot_prove=tuple(request.control.cannot_prove),
        reason_code="COMPILED",
    )


def _control_projection(
    decision: AdmissionDecision,
    *,
    plane: ControlPlane,
    include_receipts: bool,
) -> dict[str, Any]:
    lease = decision.lease
    projected: dict[str, Any] = {
        "schema_version": 1,
        "state": decision.state.value,
        "admitted": decision.admitted,
        "execute": decision.execute,
        "completed": decision.completed,
        "claim_level": decision.claim_level.value,
        "reason_code": decision.reason_code,
        "next_action": decision.next_action,
        "envelope": decision.envelope.model_dump(mode="json"),
        "lease": (
            {
                "owner_thread": lease.owner_thread,
                "generation": lease.generation,
                "lease_epoch": lease.lease_epoch,
                "last_heartbeat": lease.last_heartbeat.isoformat(),
                "expires_at": lease.expires_at.isoformat(),
            }
            if lease is not None
            else None
        ),
        "enforcement_scope": "intent-mcp-path-only",
        "host_enforcement_verified": False,
    }
    if decision.evidence is not None:
        projected["evidence"] = decision.evidence.model_dump(mode="json")
    if include_receipts and decision.admitted and decision.lease is not None:
        projected["admission_receipt"] = plane.seal_admission_receipt(decision)
        projected["resume_receipt"] = plane.seal_resume_receipt(decision)
    return projected


@mcp.tool(
    title="Compile user intent",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True),
    structured_output=True,
)
def intent_compile(request: CompileRequest) -> dict[str, Any]:
    """Compile wording into an envelope, optionally using an explicitly configured semantic adapter."""
    envelope = compiler().compile(request)
    invocation_receipt = build_invocation_receipt(request, envelope)
    envelope["invocation_receipt"] = invocation_receipt
    if request.control is not None:
        plane = control_plane()
        claim_level = _server_claim_level(envelope)
        decision = plane.authorize(
            _execution_envelope(request, envelope, invocation_receipt),
            claim_level,
            continuation_receipt=request.control.continuation_receipt,
            lease_ttl_seconds=request.control.lease_ttl_seconds,
        )
        if (
            claim_level == ClaimLevel.READ_ONLY_FORM
            and envelope.get("risk", {}).get("confirmation_required", False)
        ):
            decision = plane.wait_for_authorization(decision)
        envelope["control"] = _control_projection(
            decision,
            plane=plane,
            include_receipts=True,
        )
    return envelope if request.include_diagnostics else compact_envelope(envelope)


@mcp.tool(
    title="Record controlled execution evidence",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    structured_output=True,
)
def intent_control_record(request: ControlRecordRequest) -> dict[str, Any]:
    """Record evidence only for a server-signed, still-current admission."""
    plane = control_plane()
    decision = plane.record_receipt(
        request.admission_receipt,
        ExecutionEvidence(
            command=request.command,
            session=request.session,
            pid=request.pid,
            artifact=request.artifact,
            artifact_sha256=request.artifact_sha256,
            true_exit=request.true_exit,
            cannot_prove=tuple(request.cannot_prove),
        ),
    )
    return _control_projection(decision, plane=plane, include_receipts=False)


@mcp.tool(
    title="Resume a controlled execution safely",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    structured_output=True,
)
def intent_control_resume(request: ControlResumeRequest) -> dict[str, Any]:
    """Invalidate the old owner and return a review-only recovery generation."""
    plane = control_plane()
    decision = plane.resume_receipt(request.resume_receipt)
    return _control_projection(decision, plane=plane, include_receipts=False)


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
    title="Observe a language rule correction",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    structured_output=True,
)
def intent_observe_language_rule(request: LanguageRuleObservationRequest) -> dict[str, Any]:
    """Record a local-only repeated wording correction before suggesting profile promotion."""
    return observe_language_correction(default_profile_path(), **request.model_dump())


@mcp.tool(
    title="Confirm a language rule",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    structured_output=True,
)
def intent_confirm_language_rule(request: LanguageRuleConfirmRequest) -> dict[str, Any]:
    """Promote a user-confirmed wording meaning into the local profile."""
    return confirm_language_rule(default_profile_path(), **request.model_dump())


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
    title="Verify an execution outcome",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    structured_output=True,
)
def intent_verify_execution(request: ExecutionVerificationRequest) -> dict[str, Any]:
    """Compare the compiled plan with the observed result and write back only confirmed corrections."""
    instance = compiler()
    memory = _load_skill_script("memory_store")
    connection = memory.connect(_memory_path(instance.profile))
    try:
        payload = request.model_dump()
        invocation_receipt_id = payload.pop("invocation_receipt_id", "")
        result = memory.verify_execution_outcome(connection, **payload)
        result["execution_trace"] = {
            "invocation_receipt_id": invocation_receipt_id or None,
            "planned": {
                "goal": request.expected_goal,
                "operation": request.expected_operation,
                "skill": request.expected_skill,
            },
            "actual": {
                "goal": request.actual_goal,
                "operation": request.actual_operation,
                "skill": request.actual_skill,
                "success": request.success,
            },
            "matched": result["matched"],
            "host_enforcement_verified": False,
        }
        return result
    finally:
        connection.close()


@mcp.tool(
    title="Authorize a compiled tool action",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True),
    structured_output=True,
)
def intent_tool_gateway(request: CompileRequest) -> dict[str, Any]:
    """Return the deterministic allow, deny, or human-review decision for one proposed action."""
    envelope = compiler().compile(request)
    invocation_receipt = build_invocation_receipt(request, envelope, tool="intent_tool_gateway")
    return {
        "tool_gateway": envelope["tool_gateway"],
        "intent_contract": envelope["intent_contract"],
        "runtime_status": envelope["runtime_status"],
        "decision_receipt": envelope.get("decision_receipt"),
        "invocation_receipt": invocation_receipt,
    }


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
