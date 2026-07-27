"""Public envelope shaping shared by the SDK and MCP adapter."""

from __future__ import annotations

from typing import Any


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
    compact["risk"] = risk
    compact["intent_contract"] = contract
    for key in ("phrase_match", "constraints", "gate_resolution", "prompt_source_map"):
        if envelope.get(key):
            compact[key] = envelope[key]
    if envelope.get("interpretation_gate", {}).get("required"):
        compact["interpretation_gate"] = envelope["interpretation_gate"]
    if envelope.get("host_prompt"):
        compact["host_prompt"] = envelope["host_prompt"]
    compact["routing"] = {
        "primary_skill": routing.get("primary_skill"),
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
    diagnostic_refs = {
        "correction_ids": [item.get("id") for item in envelope.get("corrections", [])],
        "memory_ids": [item.get("id") for item in envelope.get("memories", [])],
    }
    if any(diagnostic_refs.values()):
        compact["diagnostic_refs"] = diagnostic_refs
    return compact


__all__ = ["compact_envelope"]
