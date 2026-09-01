"""Optional structured semantic interpretation adapters."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from pydantic import BaseModel, Field


MODES = ("answer", "diagnose", "change", "build", "search", "learn", "remember", "recall", "compress", "route")
RISK_HINTS = ("external", "sensitive", "irreversible", "high_stakes")


class SemanticProposal(BaseModel):
    """Bounded semantic output; explanations are summaries, not hidden reasoning."""

    normalized_goal: str = Field(min_length=1, max_length=1000)
    interpretation: str = Field(default="", max_length=1500)
    mode: str | None = None
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    alternatives: list[str] = Field(default_factory=list, max_length=5)
    confidence: float = Field(ge=0.0, le=1.0)
    primary_skill: str | None = Field(default=None, max_length=120)
    risk_hints: list[str] = Field(default_factory=list, max_length=4)
    clarification_recommended: bool = False
    language: str = Field(default="", max_length=40)

    def model_post_init(self, __context: Any) -> None:
        if self.mode is not None and self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        invalid_risks = sorted(set(self.risk_hints) - set(RISK_HINTS))
        if invalid_risks:
            raise ValueError(f"unknown risk hints: {invalid_risks}")


class SemanticAdapter(Protocol):
    name: str
    external: bool

    def interpret(self, payload: dict[str, Any]) -> SemanticProposal:
        """Return one structured interpretation proposal."""


@dataclass
class CommandSemanticAdapter:
    """Run an explicitly configured JSON-in/JSON-out command without a shell."""

    argv: list[str]
    name: str = "command"
    external: bool = False
    timeout_seconds: float = 20.0

    def interpret(self, payload: dict[str, Any]) -> SemanticProposal:
        completed = subprocess.run(
            self.argv,
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"semantic command exited with code {completed.returncode}")
        try:
            data = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("semantic command did not return one JSON object") from exc
        return SemanticProposal.model_validate(data)


@dataclass
class ChatCompletionsSemanticAdapter:
    """Call a user-configured `/chat/completions` JSON endpoint."""

    base_url: str
    model: str
    api_key: str = ""
    name: str = "chat-completions"
    timeout_seconds: float = 30.0
    opener: Callable[..., Any] = urllib.request.urlopen

    @property
    def external(self) -> bool:
        host = (urllib.parse.urlparse(self.base_url).hostname or "").casefold()
        return host not in {"localhost", "127.0.0.1", "::1"}

    def interpret(self, payload: dict[str, Any]) -> SemanticProposal:
        endpoint = self.base_url.rstrip("/") + "/chat/completions"
        request_body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a semantic interpreter inside an intent compiler. Return exactly one JSON "
                        "object matching the supplied response_schema. Do not include markdown, hidden reasoning, "
                        "authorization decisions, or extra keys."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                response_body = json.loads(response.read().decode("utf-8"))
            content = response_body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("chat-completions endpoint returned an invalid response") from exc
        if not isinstance(content, str):
            raise RuntimeError("chat-completions content must be a JSON string")
        stripped = content.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            return SemanticProposal.model_validate(json.loads(stripped))
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError("chat-completions content did not match the semantic schema") from exc


def adapter_from_env(env: dict[str, str] | None = None) -> SemanticAdapter | None:
    env = dict(os.environ if env is None else env)
    raw = env.get("INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON", "").strip()
    provider = env.get("INTENT_TRANSLATOR_SEMANTIC_PROVIDER", "").strip().casefold()
    if not raw and not provider:
        return None
    try:
        timeout = float(env.get("INTENT_TRANSLATOR_SEMANTIC_TIMEOUT", "20"))
    except ValueError as exc:
        raise ValueError("INTENT_TRANSLATOR_SEMANTIC_TIMEOUT must be numeric") from exc
    timeout = max(1.0, min(timeout, 120.0))
    if provider in {"chat-completions", "openai-compatible"}:
        base_url = env.get("INTENT_TRANSLATOR_SEMANTIC_BASE_URL", "").strip()
        model = env.get("INTENT_TRANSLATOR_SEMANTIC_MODEL", "").strip()
        if not base_url or not model:
            raise ValueError("chat-completions provider requires SEMANTIC_BASE_URL and SEMANTIC_MODEL")
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("INTENT_TRANSLATOR_SEMANTIC_BASE_URL must be an HTTP(S) URL")
        return ChatCompletionsSemanticAdapter(
            base_url=base_url,
            model=model,
            api_key=env.get("INTENT_TRANSLATOR_SEMANTIC_API_KEY", ""),
            name=env.get("INTENT_TRANSLATOR_SEMANTIC_NAME", "chat-completions"),
            timeout_seconds=timeout,
        )
    if provider and provider != "command":
        raise ValueError(f"unsupported semantic provider: {provider}")
    if not raw:
        raise ValueError("command provider requires INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON")
    try:
        argv = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON must be a JSON array") from exc
    if not isinstance(argv, list) or not argv or any(not isinstance(item, str) or not item for item in argv):
        raise ValueError("INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON must be a non-empty string array")
    return CommandSemanticAdapter(
        argv=argv,
        name=env.get("INTENT_TRANSLATOR_SEMANTIC_NAME", "command"),
        external=env.get("INTENT_TRANSLATOR_SEMANTIC_EXTERNAL", "0") == "1",
        timeout_seconds=timeout,
    )


def semantic_payload(
    *,
    utterance: str,
    context: str,
    pending_action: str,
    deterministic: dict[str, Any],
    skills: list[dict[str, Any]],
    relevant_skills: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    required_names = {
        "agent-reach", "skill-lookup", "skill-installer", "skill-creator",
        "diagnosing-bugs", "browser", "obsidian-cli", "pdf", "docx", "xlsx", "pptx",
    }
    eligible = [
        item
        for item in skills
        if item.get("model_invoked") is not False
    ]
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*(relevant_skills or []), *eligible]:
        name = str(item.get("name", ""))
        if not name or name in seen:
            continue
        if relevant_skills or name in required_names:
            selected.append(item)
            seen.add(name)
        if len(selected) >= 40:
            break
    return {
        "schema_version": 1,
        "instruction": (
            "Interpret the user's likely goal. Return only the documented JSON fields. "
            "Do not decide authorization, do not claim certainty about identity, and do not include hidden reasoning."
        ),
        "utterance": utterance,
        "context": context[-6000:],
        "pending_action": pending_action,
        "deterministic_draft": deterministic,
        "allowed_modes": list(MODES),
        "allowed_risk_hints": list(RISK_HINTS),
        "installed_skills": [
            {"name": item.get("name"), "description": str(item.get("description", ""))[:500]}
            for item in selected
        ],
        "response_schema": SemanticProposal.model_json_schema(),
    }


def run_semantic_adapter(
    adapter: SemanticAdapter | None,
    *,
    payload: dict[str, Any],
    semantic_mode: str,
    allow_external: bool,
    allow_sensitive: bool,
    sensitive: bool,
) -> dict[str, Any]:
    if semantic_mode == "off":
        return {"status": "disabled", "provider": None, "proposal": None}
    if adapter is None:
        return {
            "status": "error" if semantic_mode == "required" else "unavailable",
            "provider": None,
            "proposal": None,
            "error": "no semantic adapter configured",
        }
    if adapter.external and not allow_external:
        return {
            "status": "blocked",
            "provider": adapter.name,
            "external": True,
            "proposal": None,
            "error": "external semantic interpretation lacks explicit authorization",
        }
    if adapter.external and sensitive and not allow_sensitive:
        return {
            "status": "blocked",
            "provider": adapter.name,
            "external": True,
            "proposal": None,
            "error": "sensitive semantic interpretation lacks explicit authorization",
        }
    try:
        proposal = adapter.interpret(payload)
    except Exception as exc:
        return {
            "status": "error",
            "provider": adapter.name,
            "external": adapter.external,
            "proposal": None,
            "error": type(exc).__name__,
        }
    return {
        "status": "applied",
        "provider": adapter.name,
        "external": adapter.external,
        "proposal": proposal.model_dump(),
    }
