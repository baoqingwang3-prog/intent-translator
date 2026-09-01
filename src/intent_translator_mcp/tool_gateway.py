"""Deterministic pre-tool authorization gate."""

from __future__ import annotations

from typing import Any


PROTECTED_OPERATIONS = {"publish", "delete", "transfer", "install"}
PROTECTED_EFFECTS = {"write_external", "destructive", "system_change"}

_SEMANTIC_LEGACY: dict[str, tuple[str, str, set[str]]] = {
    "request_ruling_request": ("answer", "none", {"none"}),
    "report_status": ("answer", "none", {"none"}),
    "pending_route": ("answer", "none", {"none"}),
    "route_internal_dispatch": ("change", "write_internal", {"none"}),
    "register_internal_thread": ("change", "write_internal", {"none"}),
    "register_local_artifact": ("change", "write_local", {"none"}),
    "publish_public": ("publish", "write_external", {"private_file"}),
    "transfer": ("transfer", "write_external", {"user_text", "private_file", "profile", "memory"}),
    "install": ("install", "system_change", {"none"}),
    "delete": ("delete", "destructive", {"none"}),
}


def _resolution(value: dict[str, Any]) -> str:
    return str(value.get("resolution", "unresolved")).casefold()


def _is_resolved(value: dict[str, Any]) -> bool:
    return _resolution(value) == "resolved"


def _recipient_is_present(value: dict[str, Any]) -> bool:
    return bool(
        str(value.get("recipient_type", "")).strip()
        and str(value.get("relationship", "")).strip()
    )


def decide_tool_access(
    *,
    operation: str,
    effect: str,
    data_egress: str,
    risk: dict[str, Any],
    clarification_required: bool,
    required_slots: list[str] | None = None,
    semantic_suggestion: str = "",
    semantic_operation: str = "",
    semantic_id: str = "",
    semantic_recipient: dict[str, Any] | None = None,
    semantic_destination: dict[str, Any] | None = None,
    authorized: bool = False,
    expected_data_egress: str | None = None,
) -> dict[str, Any]:
    """Return allow, deny, or human_review without trusting model permission hints."""
    required_slots = list(required_slots or [])
    semantic_recipient = dict(semantic_recipient or {})
    semantic_destination = dict(semantic_destination or {})
    reasons: list[str] = []
    consistency_errors: list[str] = []
    review_reasons: list[str] = []
    route_call_count = 0
    if semantic_operation:
        if semantic_operation not in _SEMANTIC_LEGACY and semantic_operation != "none":
            consistency_errors.append("unknown semantic_operation")
        elif semantic_operation in _SEMANTIC_LEGACY:
            expected_operation, expected_effect, expected_egress = _SEMANTIC_LEGACY[semantic_operation]
            if expected_data_egress is not None and expected_data_egress not in expected_egress:
                consistency_errors.append("caller expected_data_egress diverges from semantic truth")
            if operation != expected_operation:
                consistency_errors.append("legacy operation diverges from semantic_operation")
            if effect != expected_effect:
                consistency_errors.append("legacy effect diverges from semantic_operation")
            if data_egress not in expected_egress:
                consistency_errors.append("data_egress diverges from semantic truth")
        if semantic_operation != "none" and not semantic_id:
            consistency_errors.append("semantic_id missing")
        destination_kind = semantic_destination.get("kind", "unknown")
        destination_externality = semantic_destination.get("externality", "unknown")
        destination_resolution = semantic_destination.get("resolution", "unresolved")
        if semantic_operation in {"route_internal_dispatch", "register_internal_thread"}:
            if destination_kind != "internal_thread":
                consistency_errors.append("internal route requires internal_thread destination")
            if destination_externality != "internal":
                consistency_errors.append("internal route requires internal destination")
            if semantic_operation == "route_internal_dispatch" and destination_resolution != "resolved":
                consistency_errors.append("internal route destination unresolved")
        if semantic_operation == "register_local_artifact" and destination_kind != "local_artifact":
            consistency_errors.append("local artifact registration requires local_artifact destination")
        if semantic_operation == "register_local_artifact" and destination_externality != "internal":
            consistency_errors.append("local artifact registration requires internal destination")
        if semantic_operation == "publish_public":
            if destination_kind != "public_endpoint":
                consistency_errors.append("public publish requires public_endpoint destination")
            if destination_externality != "external":
                consistency_errors.append("public publish requires external destination")
            if not _is_resolved(semantic_destination):
                review_reasons.append("public publish destination remains unresolved")
        if semantic_operation == "transfer":
            if destination_externality == "internal":
                consistency_errors.append("external transfer cannot target an internal destination")
            elif destination_externality != "external":
                review_reasons.append("transfer destination remains unresolved")
            if not _recipient_is_present(semantic_recipient) or not _is_resolved(semantic_recipient):
                review_reasons.append("transfer recipient remains unresolved")
        if semantic_operation in {"route_internal_dispatch", "register_internal_thread"}:
            if not _recipient_is_present(semantic_recipient) or not _is_resolved(semantic_recipient):
                review_reasons.append("internal route recipient remains unresolved")
        if semantic_operation in {"route_internal_dispatch", "register_internal_thread", "register_local_artifact"} and not authorized:
            reasons.append("internal route is not authorized by the typed projection")
        if semantic_operation in {"request_ruling_request", "report_status"}:
            route_call_count = 0
        if semantic_operation == "pending_route":
            review_reasons.append("internal route destination is pending human selection")
    if consistency_errors:
        decision = "deny"
        reasons.extend(consistency_errors)
        reasons.append("pre-dispatch typed semantic consistency failed")
    elif risk.get("blocked"):
        decision = "deny"
        reasons.append("deterministic policy blocked the action")
    elif review_reasons:
        decision = "human_review"
        reasons.extend(review_reasons)
    elif clarification_required or required_slots:
        decision = "human_review"
        reasons.append("material interpretation or required execution fields remain unresolved")
    elif risk.get("confirmation_required"):
        decision = "human_review"
        reasons.append("the exact action still requires concrete authorization")
    elif operation in PROTECTED_OPERATIONS or effect in PROTECTED_EFFECTS:
        if not risk.get("receipt_verified"):
            decision = "human_review"
            reasons.append("protected tool path lacks an action-bound confirmation receipt")
        else:
            decision = "allow"
    else:
        decision = "allow"

    if semantic_operation in {"route_internal_dispatch", "register_internal_thread", "register_local_artifact"}:
        if not authorized and decision == "allow":
            decision = "human_review"
        if semantic_operation == "route_internal_dispatch" and decision != "allow":
            route_call_count = 0

    semantic_suggestion = semantic_suggestion.strip().casefold()
    semantic_applied = False
    if semantic_suggestion in {"deny", "human_review"} and decision == "allow":
        decision = "human_review"
        reasons.append("semantic layer raised risk for deterministic review")
        semantic_applied = True
    elif semantic_suggestion == "allow" and decision != "allow":
        reasons.append("semantic allow suggestion cannot lower deterministic controls")

    return {
        "decision": decision,
        "operation": operation,
        "effect": effect,
        "data_egress": data_egress,
        "reasons": reasons,
        "required_slots": required_slots,
        "semantic_suggestion": semantic_suggestion or None,
        "semantic_suggestion_applied": semantic_applied,
        "local_deterministic_authority": True,
        "semantic_operation": semantic_operation or None,
        "semantic_id": semantic_id or None,
        "semantic_recipient": semantic_recipient,
        "semantic_destination": semantic_destination,
        "data_egress_source": "typed_semantic_truth" if semantic_operation else "legacy_classifier",
        "pre_dispatch_consistency": {
            "passed": not consistency_errors,
            "errors": consistency_errors,
            "authorized": authorized,
        },
        "route_call_count": route_call_count,
        "route_invocation_count": route_call_count,
        "actual_route_count": route_call_count,
        "route_count_source": "gateway_decision_only",
    }
