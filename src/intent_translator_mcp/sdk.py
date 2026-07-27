"""Small public Python SDK facade for the intent compiler."""

from __future__ import annotations

import copy
from typing import Any, Literal

from .core import IntentCompiler, _load_skill_script, _memory_enabled, _memory_path
from .intent_contract import TypedIntentContract
from .models import CheckRequest, CompileRequest, InterpretationOption
from .presentation import compact_envelope


class CompilationResult:
    """Typed view over one compiler result without hiding the raw envelope."""

    __slots__ = ("_envelope", "contract")

    def __init__(self, envelope: dict[str, Any], *, include_diagnostics: bool = False) -> None:
        public_envelope = envelope if include_diagnostics else compact_envelope(envelope)
        self._envelope = copy.deepcopy(public_envelope)
        if self._envelope.get("host_prompt") is None:
            self._envelope.pop("host_prompt", None)
        self.contract = TypedIntentContract.model_validate(envelope["intent_contract"])

    @property
    def selected_skill(self) -> str | None:
        return self._envelope.get("routing", {}).get("primary_skill")

    @property
    def tool_decision(self) -> str:
        return str(self._envelope.get("tool_gateway", {}).get("decision", "human_review"))

    @property
    def can_execute(self) -> bool:
        completion = bool(self._envelope.get("completion_contract", {}).get("execute", False))
        return completion and self.tool_decision == "allow"

    @property
    def requires_clarification(self) -> bool:
        return bool(self._envelope.get("clarification_required", False))

    @property
    def requires_confirmation(self) -> bool:
        return bool(self._envelope.get("risk", {}).get("confirmation_required", False))

    @property
    def model_used(self) -> bool:
        return self._envelope.get("semantic", {}).get("status") == "applied"

    @property
    def value_receipt(self) -> dict[str, Any]:
        """Observable activity for this preflight, not a no-Skill benefit claim."""
        return copy.deepcopy(self._envelope.get("value_receipt") or {})

    @property
    def interpretation_gate(self) -> dict[str, Any] | None:
        gate = self._envelope.get("interpretation_gate", {})
        return copy.deepcopy(gate) if gate.get("required") else None

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._envelope)


class IntentTranslatorSDK:
    """Stable local-first entry point for embedding Intent Translator."""

    def __init__(self, compiler: IntentCompiler | None = None) -> None:
        self._compiler = compiler or IntentCompiler(entrypoint="python-sdk")

    def compile(
        self,
        utterance: str,
        *,
        context: str = "",
        pending_action: str = "",
        scope: str = "global",
        authorization: Literal["granted", "unknown", "denied"] = "unknown",
        confirmation_receipt: str = "",
        available_files: list[str] | None = None,
        semantic_mode: Literal["off", "auto", "required"] = "auto",
        allow_external_semantic: bool = False,
        allow_sensitive_semantic: bool = False,
        include_prompt: bool = False,
        include_diagnostics: bool = False,
    ) -> CompilationResult:
        request = CompileRequest(
            utterance=utterance,
            context=context,
            pending_action=pending_action,
            scope=scope,
            authorization=authorization,
            confirmation_receipt=confirmation_receipt,
            available_files=list(available_files or []),
            semantic_mode=semantic_mode,
            allow_external_semantic=allow_external_semantic,
            allow_sensitive_semantic=allow_sensitive_semantic,
            include_prompt=include_prompt,
            include_diagnostics=include_diagnostics,
        )
        return CompilationResult(
            self._compiler.compile(request),
            include_diagnostics=include_diagnostics,
        )

    def check(
        self,
        goal: str,
        *,
        scope: str = "global",
        impact: Literal["low", "medium", "high"] = "low",
        reversible: Literal["yes", "no", "unknown"] = "yes",
        external: bool = False,
        sensitive: bool = False,
        authorization: Literal["granted", "unknown", "denied"] = "unknown",
    ) -> dict[str, Any]:
        request = CheckRequest(
            goal=goal,
            scope=scope,
            impact=impact,
            reversible=reversible,
            external=external,
            sensitive=sensitive,
            authorization=authorization,
        )
        memory = _load_skill_script("memory_store")
        path = _memory_path(self._compiler.profile)
        connection = (
            memory.connect_readonly(path)
            if _memory_enabled(self._compiler.profile) and path.exists()
            else None
        )
        try:
            return memory.check_intent(connection, record=False, **request.model_dump())
        finally:
            if connection is not None:
                connection.close()

    def resolve(
        self,
        previous: CompilationResult,
        selection: str,
        *,
        context: str = "",
        pending_action: str = "",
        semantic_mode: Literal["off", "auto", "required"] = "auto",
        include_prompt: bool = False,
    ) -> CompilationResult:
        gate = previous.interpretation_gate
        if gate is None:
            raise ValueError("the previous result has no unresolved interpretation gate")
        options = [InterpretationOption.model_validate(item) for item in gate.get("candidates", [])]
        if not options:
            raise ValueError("the interpretation gate has no selectable options")
        request = CompileRequest(
            utterance=selection,
            context=context,
            pending_action=pending_action,
            scope=previous.contract.scope,
            semantic_mode=semantic_mode,
            include_prompt=include_prompt,
            interpretation_gate_id=str(gate.get("id", "")),
            interpretation_options=options,
        )
        return CompilationResult(self._compiler.compile(request))

    @staticmethod
    def receipt(
        result: CompilationResult, *, semantic: bool = False
    ) -> dict[str, Any] | None:
        key = "semantic_confirmation_challenge" if semantic else "confirmation_challenge"
        challenge = result.to_dict().get("risk", {}).get(key)
        return copy.deepcopy(challenge) if challenge else None


IntentTranslator = IntentTranslatorSDK


__all__ = ["CompilationResult", "IntentTranslator", "IntentTranslatorSDK"]
