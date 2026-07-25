"""Deterministic pre-tool authorization gate."""

from __future__ import annotations

from typing import Any


PROTECTED_OPERATIONS = {"publish", "delete", "transfer", "install"}
PROTECTED_EFFECTS = {"write_external", "destructive", "system_change"}


def decide_tool_access(
    *,
    operation: str,
    effect: str,
    data_egress: str,
    risk: dict[str, Any],
    clarification_required: bool,
    required_slots: list[str] | None = None,
    semantic_suggestion: str = "",
) -> dict[str, Any]:
    """Return allow, deny, or human_review without trusting model permission hints."""
    required_slots = list(required_slots or [])
    reasons: list[str] = []
    if risk.get("blocked"):
        decision = "deny"
        reasons.append("deterministic policy blocked the action")
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
    }
