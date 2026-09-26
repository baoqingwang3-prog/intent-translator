"""Public envelope shaping shared by the SDK and MCP adapter."""

from __future__ import annotations

from typing import Any

def build_value_receipt(envelope: dict[str, Any]) -> dict[str, Any]:
    """Count observable preflight activity without inventing no-Skill benefit."""
    contract = envelope.get("intent_contract") if isinstance(envelope.get("intent_contract"), dict) else {}
    routing = envelope.get("routing") if isinstance(envelope.get("routing"), dict) else {}
    risk = envelope.get("risk") if isinstance(envelope.get("risk"), dict) else {}
    gateway = envelope.get("tool_gateway") if isinstance(envelope.get("tool_gateway"), dict) else {}
    semantic = envelope.get("semantic") if isinstance(envelope.get("semantic"), dict) else {}
    usage = envelope.get("input_usage") if isinstance(envelope.get("input_usage"), dict) else {}
    memories = envelope.get("memories") or envelope.get("memory_refs") or []
    corrections = envelope.get("corrections") or envelope.get("correction_refs") or []
    source_map = contract.get("source_map") or envelope.get("prompt_source_map") or []
    constraints = contract.get("constraints") or envelope.get("constraints") or []
    prohibitions = contract.get("prohibitions") or []
    non_obvious = [
        item
        for item in source_map
        if isinstance(item, dict) and item.get("obvious") is False
    ]
    context_chars = sum(
        int(usage.get(key, 0) or 0)
        for key in ("utterance_chars", "context_chars", "pending_action_chars")
    )
    gateway_decision = str(gateway.get("decision", "unknown"))
    execution_allowed = bool(envelope.get("completion_contract", {}).get("execute", False))
    semantic_status = str(semantic.get("status", ""))
    return {
        "schema_version": 1,
        "evidence_scope": "single-preflight",
        "recovered_fields_count": len(non_obvious),
        "preserved_constraints_count": len(constraints),
        "preserved_prohibitions_count": len(prohibitions),
        "memory_hits": len([item for item in memories if isinstance(item, dict)]),
        "correction_hits": len([item for item in corrections if isinstance(item, dict)]),
        "skill_route_selected": bool(routing.get("primary_skill")),
        "skill_route_state": routing.get("selection_state"),
        "clarification_triggered": bool(envelope.get("clarification_required", False)),
        "confirmation_added": bool(risk.get("confirmation_required", False)),
        "blocked_by_preflight": gateway_decision != "allow" and not execution_allowed,
        "semantic_model_calls_observed": 1 if semantic_status in {"applied", "error"} else 0,
        "context_chars_loaded": context_chars,
        "estimated_context_tokens": (context_chars + 3) // 4,
        "route_changed_vs_no_skill": None,
        "clarifications_avoided": None,
        "unsafe_action_prevented": None,
        "counterfactual_status": "not-run",
        "benefit_claim": "observable-activity-only",
    }



def compact_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Return the stable public result without raw memory or diagnostics."""

    routing = envelope.get("routing", {})
    runtime = envelope.get("runtime_status", {})
    contract = dict(envelope.get("intent_contract", {}))
    for key in ("prohibitions", "artifact", "pending_action", "alternatives", "source_map"):
        if not contract.get(key):
            contract.pop(key, None)
    if not contract.get("communication", {}).get("active"):
        contract.pop("communication", None)

    # A passive answer has no executable frame to inspect. Keep its public
    # decision fields without repeating the internal default projection.
    if (
        contract.get("mode") == "answer"
        and contract.get("operation") == "answer"
        and contract.get("effect") == "none"
        and contract.get("data_egress") == "none"
        and not contract.get("actions")
        and not contract.get("branches")
        and not contract.get("constraints")
        and not contract.get("prohibitions")
        and not contract.get("required_slots")
        and not contract.get("required_grants")
        and not contract.get("confirmation_required")
    ):
        authorization = contract.get("authorization", {})
        contract = {
            "schema_version": contract.get("schema_version"),
            "goal": contract.get("goal"),
            "mode": "answer",
            "operation": "answer",
            "effect": "none",
            "data_egress": "none",
            "scope": contract.get("scope"),
            "active_task_source": contract.get("active_task_source"),
            "action_owner": contract.get("action_owner"),
            "actions": [],
            "branches": [],
            "constraints": [],
            "prohibitions": [],
            "authorization": {
                key: authorization.get(key)
                for key in ("state", "receipt_verified", "required_grants", "action_digest")
            },
        }

    risk_source = envelope.get("risk", {})
    risk = {
        key: risk_source.get(key)
        for key in (
            "impact",
            "reversible",
            "external",
            "sensitive",
            "high_stakes",
            "system_change",
            "ambiguous_action",
            "unknown_executable",
            "blocked",
            "confirmation_required",
            "receipt_verified",
            "action_digest",
            "reasons",
        )
        if key in risk_source
    }
    for key in ("confirmation_challenge", "semantic_confirmation_challenge"):
        if risk_source.get(key):
            risk[key] = risk_source[key]
    if risk_source.get("receipt_status", {}).get("reason") not in {None, "not required"}:
        risk["receipt_status"] = risk_source["receipt_status"]
    if risk_source.get("semantic_authorization", {}).get("required"):
        risk["semantic_authorization"] = risk_source["semantic_authorization"]
    local_policy = risk_source.get("local_policy", {})
    if local_policy.get("blocked") or local_policy.get("confirmation_required"):
        risk["local_policy"] = local_policy

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
            "short_confirmation_status",
            "current_status",
            "completion_contract",
            "decision_receipt",
            "invocation_receipt",
        )
        if key in envelope
    }
    if compact.get("short_confirmation_status", {}).get("state") == "resolved" and compact[
        "short_confirmation_status"
    ].get("source") == "not-applicable":
        compact.pop("short_confirmation_status", None)
    value_receipt = envelope.get("value_receipt", {})
    if value_receipt:
        compact["value_receipt"] = {
            key: value_receipt[key]
            for key in (
                "benefit_claim",
                "counterfactual_status",
                "recovered_fields_count",
                "preserved_constraints_count",
                "preserved_prohibitions_count",
                "memory_hits",
                "correction_hits",
                "skill_route_selected",
                "blocked_by_preflight",
                "estimated_context_tokens",
            )
            if value_receipt.get(key) is not None
        }
    compact["risk"] = risk
    compact["intent_contract"] = contract
    for key in ("phrase_match", "constraints", "gate_resolution", "prompt_source_map"):
        if envelope.get(key):
            compact[key] = envelope[key]
    if envelope.get("interpretation_gate", {}).get("required"):
        compact["interpretation_gate"] = envelope["interpretation_gate"]
    if envelope.get("host_prompt"):
        compact["host_prompt"] = envelope["host_prompt"]
    primary_role = routing.get("primary_capability_role") or {}
    compact["routing"] = {
        "primary_skill": routing.get("primary_skill"),
        "primary_capability_role": (
            {
                key: primary_role[key]
                for key in ("role", "parent_skill")
                if primary_role.get(key)
            }
            if primary_role
            else None
        ),
        "selection_state": routing.get("selection_state"),
        "activation_state": routing.get("activation_state"),
        "installed": routing.get("capability_facts", {}).get("installed", False),
        "acquisition_policy": routing.get("acquisition_policy", []),
    }
    gateway = envelope.get("tool_gateway", {})
    compact["tool_gateway"] = {
        "decision": gateway.get("decision"),
        "local_deterministic_authority": gateway.get("local_deterministic_authority", True),
    }
    if gateway.get("decision") != "allow":
        compact["tool_gateway"]["reasons"] = gateway.get("reasons", [])
        compact["tool_gateway"]["required_slots"] = gateway.get("required_slots", [])
    compact["semantic"] = {
        key: envelope.get("semantic", {}).get(key)
        for key in ("status", "provider", "proposal", "error")
        if envelope.get("semantic", {}).get(key) is not None
    }
    fidelity = envelope.get("semantic_fidelity", {})
    if fidelity.get("status") not in {None, "not-applied"}:
        compact["semantic_fidelity"] = fidelity
    study = envelope.get("study_context", {})
    if study.get("enabled"):
        compact["study_context"] = study
        compact["state_status"] = envelope.get("state_status", {})
    if envelope.get("adaptive_autonomy", {}).get("mode") == "cautious":
        compact["adaptive_autonomy"] = envelope["adaptive_autonomy"]
    if envelope.get("personal_semantics", {}).get("status") != "none":
        compact["personal_semantics"] = envelope["personal_semantics"]
    compact["runtime_status"] = {
        "state": runtime.get("state"),
        "restart_required": runtime.get("restart_required", False),
        "version": runtime.get("versions", {}).get("actual_runtime"),
    }
    orchestration = envelope.get("orchestration", {})
    if orchestration.get("recommended"):
        compact["orchestration"] = {
            "delegate": "parallel-independent",
            "visible_task": "explicit-only",
            "main_retains": ["shared-writes", "conflicts", "acceptance"],
            "authority": "unchanged",
        }
    diagnostic_refs = {
        "correction_ids": [item.get("id") for item in envelope.get("corrections", [])],
        "memory_ids": [item.get("id") for item in envelope.get("memories", [])],
    }
    if any(diagnostic_refs.values()):
        compact["diagnostic_refs"] = diagnostic_refs
    return compact


__all__ = ["build_value_receipt", "compact_envelope"]
