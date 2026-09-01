"""Enforce the preflight inside a host that can veto a tool call before it runs.

A host hook is the only place where this project stops being advisory. Claude Code
and Cursor both run a hook before an action executes and honor its refusal, so a
compile result can prevent the action instead of merely describing it.

Two events are needed on each host, because a pre-action hook receives the action and
not the user's wording, while the compiler requires the exact wording:

| Purpose | Claude Code | Cursor |
|---|---|---|
| Record the latest prompt | `UserPromptSubmit` | `beforeSubmitPrompt` |
| Decide before the action | `PreToolUse` | `beforeShellExecution`, `beforeMCPExecution` |
| Forget the prompt | `SessionEnd` | `sessionEnd` |

One decision core serves both. The event names are disjoint, so a single entrypoint
recognizes which host is calling and renders the verdict in that host's shape. That
also means Cursor can load this hook through its Claude Code compatibility path.

The hook only ever raises friction. On Claude Code an allowed verdict prints nothing,
which that host documents as "no decision: the normal permission flow applies";
returning `allow` there would *skip* the user's permission prompt. Cursor's schema has
no way to abstain, so an allowed verdict returns `allow` and Cursor's own allowlist
and review remain the layer behind it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .authorization import shared_data_dir


PROMPT_EVENT = "UserPromptSubmit"
PRE_TOOL_EVENT = "PreToolUse"
SESSION_END_EVENT = "SessionEnd"

CURSOR_PROMPT_EVENT = "beforeSubmitPrompt"
CURSOR_SHELL_EVENT = "beforeShellExecution"
CURSOR_MCP_EVENT = "beforeMCPExecution"
CURSOR_TOOL_EVENT = "preToolUse"
CURSOR_SESSION_END_EVENT = "sessionEnd"

MODULE_ENTRYPOINT = "intent_translator_mcp.host_hook"
SERVER_NAME = "intent-translator"
SERVER_TOOL_PREFIX = f"mcp__{SERVER_NAME}__"
DEFAULT_TOOL_MATCHER = "Bash|PowerShell|Write|Edit|NotebookEdit|WebFetch|mcp__.*"
CURSOR_FILE_TOOL_MATCHER = "Write|Delete"
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_SESSION_TTL_SECONDS = 12 * 60 * 60
BLOCKING_EXIT_CODE = 2
MAX_REASON_CHARS = 900

# The tool call's own effect, named with the compiler's vocabulary so the two can be
# compared directly. Only these three classes are treated as consequential.
CONSEQUENTIAL_EFFECTS = frozenset({"write_external", "destructive", "system_change"})

_DESTRUCTIVE_PATTERNS = (
    re.compile(r"\brm\s+(?:-\w+\s+)*-\w*[rf]", re.I),
    re.compile(r"\brmdir\s+/s|\bdel\s+/[fsq]", re.I),
    re.compile(r"\bremove-item\b[^\n]*-(?:recurse|force)", re.I),
    re.compile(r"\bgit\s+(?:reset\s+--hard|clean\s+-\w*[fd])", re.I),
    re.compile(r"\b(?:drop\s+(?:table|database)|truncate\s+table|delete\s+from)\b", re.I),
    re.compile(r"\b(?:mkfs\w*|shred|dd\s+if=)", re.I),
    re.compile(r"\bfind\b[^\n]*\s-delete\b", re.I),
    re.compile(r"\b(?:kubectl\s+delete|docker\s+system\s+prune|terraform\s+destroy)\b", re.I),
)
_EXTERNAL_PATTERNS = (
    re.compile(r"\bgit\s+push\b", re.I),
    re.compile(r"\bgh\s+(?:pr\s+create|release\s+create|repo\s+create|api\b)", re.I),
    re.compile(r"\b(?:npm|pnpm|yarn)\s+publish\b", re.I),
    re.compile(r"\b(?:twine\s+upload|cargo\s+publish|docker\s+push)\b", re.I),
    re.compile(r"\b(?:scp|sftp|ssh|rclone)\b", re.I),
    re.compile(r"\brsync\b[^\n]*\s[\w.-]+@[\w.-]+:", re.I),
    re.compile(r"\bcurl\b[^\n]*(?:\s-X\s*(?:POST|PUT|PATCH|DELETE)|--upload-file|\s-[a-zA-Z]*d\b|--data)", re.I),
    re.compile(r"\bwget\b[^\n]*--post", re.I),
    re.compile(r"\b(?:aws|gcloud|az)\b[^\n]*\b(?:cp|sync|upload|publish|push)\b", re.I),
)
_SYSTEM_CHANGE_PATTERNS = (
    re.compile(r"\bsudo\b", re.I),
    re.compile(r"\b(?:apt|apt-get|yum|dnf|pacman|zypper)\s+(?:install|remove|purge)\b", re.I),
    re.compile(r"\b(?:brew|choco|winget|scoop)\s+(?:install|uninstall)\b", re.I),
    re.compile(r"\b(?:npm|pnpm|yarn)\s+(?:install|add|i)\b", re.I),
    re.compile(r"\b(?:pip3?|pipx|uv)\s+(?:install|uninstall)\b", re.I),
    re.compile(r"\b(?:gem|cargo|go|dotnet)\s+install\b", re.I),
    re.compile(r"\b(?:systemctl|launchctl|service)\b", re.I),
    re.compile(r"\breg\s+(?:add|delete)\b|\bset-itemproperty\b[^\n]*hk(?:lm|cu)", re.I),
)
_LOCAL_WRITE_PATTERNS = (
    re.compile(r"(?<![<>])>>?(?![>])", re.I),
    re.compile(r"\b(?:tee|mv|cp|mkdir|touch|chmod|chown|ln)\b", re.I),
    re.compile(r"\bsed\b[^\n]*\s-i\b", re.I),
    re.compile(r"\bgit\s+(?:add|commit|checkout|switch|merge|rebase|stash|apply|tag)\b", re.I),
)
_MUTATING_MCP_TOOL = re.compile(
    r"(?:^|_)(?:write|create|update|delete|remove|send|post|publish|push|upload|merge|deploy)",
    re.I,
)

_MEMORY_SESSIONS: dict[str, tuple[str, int]] = {}


@dataclass(frozen=True)
class HookOutcome:
    """What the hook prints and returns to the host."""

    payload: dict[str, Any] | None = None
    exit_code: int = 0
    stderr: str = ""
    decision: str = "no-decision"
    detail: dict[str, Any] = field(default_factory=dict)

    def emit(self, out=None, err=None) -> int:
        if self.payload is not None:
            _write(sys.stdout if out is None else out, json.dumps(self.payload, ensure_ascii=False))
        if self.stderr:
            _write(sys.stderr if err is None else err, self.stderr)
        return self.exit_code


def _write(stream, text: str) -> None:
    """Write UTF-8 regardless of the host's console encoding.

    A hook exchanges the user's own wording with the host, so the payload is often not
    representable in a Windows console code page. Bypassing the text layer keeps the
    reason readable instead of raising while a tool call waits on a decision.
    """
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        stream.write(text)
        return
    buffer.write(text.encode("utf-8"))
    buffer.flush()


def _session_ttl() -> int:
    raw = str(os.environ.get("INTENT_TRANSLATOR_HOOK_SESSION_TTL", "")).strip()
    try:
        configured = int(raw)
    except ValueError:
        return DEFAULT_SESSION_TTL_SECONDS
    return configured if configured > 0 else DEFAULT_SESSION_TTL_SECONDS


class SessionStore:
    """Hold the latest prompt per session so `PreToolUse` can compile real wording.

    The prompt is the user's own text, so it is kept in one row per session rather
    than a history, expires, is removed when the session ends, and is written with
    owner-only permissions. Set `INTENT_TRANSLATOR_HOOK_SESSION_TTL` to shorten its
    lifetime.
    """

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            directory = shared_data_dir()
            path = directory / "hook-sessions.db" if directory is not None else None
        self.path = path
        self.shared = False
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = self._connect()
            try:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS session_prompts (
                        session_id TEXT PRIMARY KEY,
                        prompt TEXT NOT NULL,
                        expires_at INTEGER NOT NULL
                    )
                    """
                )
            finally:
                connection.close()
            if os.name != "nt":
                os.chmod(path, 0o600)
            self.shared = True
        except (OSError, sqlite3.Error):
            self.path = None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def remember(self, session_id: str, prompt: str) -> None:
        session_id, prompt = session_id.strip(), prompt.strip()
        if not session_id or not prompt:
            return
        expires_at = int(time.time()) + _session_ttl()
        if self.path is None:
            _MEMORY_SESSIONS[session_id] = (prompt, expires_at)
            return
        try:
            connection = self._connect()
            try:
                connection.execute(
                    "INSERT INTO session_prompts(session_id, prompt, expires_at) VALUES (?, ?, ?)"
                    " ON CONFLICT(session_id) DO UPDATE SET prompt = excluded.prompt,"
                    " expires_at = excluded.expires_at",
                    (session_id, prompt, expires_at),
                )
                connection.execute(
                    "DELETE FROM session_prompts WHERE expires_at < ?", (int(time.time()),)
                )
            finally:
                connection.close()
        except sqlite3.Error:
            _MEMORY_SESSIONS[session_id] = (prompt, expires_at)

    def recall(self, session_id: str) -> str:
        session_id = session_id.strip()
        if not session_id:
            return ""
        now = int(time.time())
        if self.path is not None:
            try:
                connection = self._connect()
                try:
                    row = connection.execute(
                        "SELECT prompt FROM session_prompts WHERE session_id = ? AND expires_at >= ?",
                        (session_id, now),
                    ).fetchone()
                finally:
                    connection.close()
                if row is not None:
                    return str(row[0])
            except sqlite3.Error:
                pass
        remembered = _MEMORY_SESSIONS.get(session_id)
        if remembered and remembered[1] >= now:
            return remembered[0]
        return ""

    def forget(self, session_id: str) -> None:
        session_id = session_id.strip()
        if not session_id:
            return
        _MEMORY_SESSIONS.pop(session_id, None)
        if self.path is None:
            return
        try:
            connection = self._connect()
            try:
                connection.execute("DELETE FROM session_prompts WHERE session_id = ?", (session_id,))
            finally:
                connection.close()
        except sqlite3.Error:
            pass


def _command_text(tool_input: Mapping[str, Any]) -> str:
    return " ".join(str(tool_input.get("command", "")).split())


def classify_tool_call(tool_name: str, tool_input: Mapping[str, Any]) -> dict[str, Any]:
    """Name the effect of the action the host is about to take.

    This reads the tool call, not the user's wording, so that a benign request cannot
    be used to carry a consequential action. Shell text is matched with patterns
    rather than parsed, so an unrecognized command is reported as `read_local`: the
    classifier raises suspicion on what it recognizes and never invents it.
    """
    tool_name = tool_name.strip()
    summary = describe_tool_call(tool_name, tool_input)
    if not tool_name or tool_name.startswith(SERVER_TOOL_PREFIX):
        return {"effect": "none", "summary": summary, "recognized": True}

    if tool_name.startswith("mcp__"):
        mutating = bool(_MUTATING_MCP_TOOL.search(tool_name.split("__")[-1]))
        return {
            "effect": "write_external" if mutating else "read_public",
            "summary": summary,
            "recognized": mutating,
        }
    if tool_name in {"WebFetch", "WebSearch"}:
        return {"effect": "read_public", "summary": summary, "recognized": True}
    if tool_name in {"Write", "Edit", "NotebookEdit", "MultiEdit"}:
        return {"effect": "write_local", "summary": summary, "recognized": True}
    if tool_name in {"Read", "Glob", "Grep"}:
        return {"effect": "read_local", "summary": summary, "recognized": True}

    command = _command_text(tool_input)
    if not command:
        return {"effect": "read_local", "summary": summary, "recognized": False}
    for effect, patterns in (
        ("destructive", _DESTRUCTIVE_PATTERNS),
        ("write_external", _EXTERNAL_PATTERNS),
        ("system_change", _SYSTEM_CHANGE_PATTERNS),
        ("write_local", _LOCAL_WRITE_PATTERNS),
    ):
        for pattern in patterns:
            if pattern.search(command):
                return {"effect": effect, "summary": summary, "recognized": True}
    return {"effect": "read_local", "summary": summary, "recognized": False}


def describe_tool_call(tool_name: str, tool_input: Mapping[str, Any]) -> str:
    """Render the tool call exactly, for the pending action and the shown reason."""
    tool_name = tool_name.strip() or "unknown tool"
    command = _command_text(tool_input)
    if command:
        return f"{tool_name}: {command}"
    for key in ("file_path", "url", "notebook_path", "path", "pattern"):
        value = str(tool_input.get(key, "")).strip()
        if value:
            return f"{tool_name}: {value}"
    if not tool_input:
        return tool_name
    try:
        rendered = json.dumps(tool_input, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        rendered = str(tool_input)
    return f"{tool_name}: {rendered[:400]}"


def _clip(text: str) -> str:
    collapsed = " ".join(str(text).split())
    return collapsed if len(collapsed) <= MAX_REASON_CHARS else collapsed[: MAX_REASON_CHARS - 1] + "…"


@dataclass(frozen=True)
class Verdict:
    """One host-independent decision about one action."""

    decision: str
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


def _allow(**detail: Any) -> Verdict:
    return Verdict("allow", detail=detail)


def _deny(reason: str, **detail: Any) -> Verdict:
    return Verdict("deny", _clip(reason), detail)


def _ask(reason: str, **detail: Any) -> Verdict:
    return Verdict("ask", _clip(reason), detail)


def _on_error_decision() -> str:
    configured = str(os.environ.get("INTENT_TRANSLATOR_HOOK_ON_ERROR", "")).strip().casefold()
    return configured if configured in {"ask", "deny", "allow"} else "ask"


def _failure(reason: str, **detail: Any) -> Verdict:
    """Decide what an unusable preflight means. No host fails closed for us by default.

    A crashed or unparseable hook is a non-blocking error in Claude Code, and fail-open
    in Cursor unless `failClosed` is set. This module therefore takes its own position:
    by default it escalates to the user rather than silently allowing or hard blocking.
    """
    decision = _on_error_decision()
    if decision == "deny":
        return _deny(reason, **detail)
    if decision == "allow":
        return Verdict("allow", detail={**detail, "on_error": True})
    return _ask(reason, **detail)


def _compile_envelope(
    utterance: str, *, pending_action: str, scope: str, actor: str, host: str = "host"
) -> dict[str, Any]:
    from .core import IntentCompiler
    from .models import CompileRequest

    compiler = IntentCompiler(entrypoint=f"{host}-hook", semantic_adapter=None)
    return compiler.compile(
        CompileRequest(
            utterance=utterance,
            pending_action=pending_action,
            scope=scope,
            actor=actor,
            semantic_mode="off",
            include_prompt=False,
        )
    )


def _scope_for(cwd: str) -> str:
    cleaned = str(cwd).strip()
    return cleaned or "global"


def evaluate_action(
    *,
    tool_name: str,
    tool_input: Mapping[str, Any],
    prompt: str,
    cwd: str = "",
    actor: str = "",
    host: str = "host",
) -> Verdict:
    """Decide one action. Host-independent: every host renders this same verdict."""
    classified = classify_tool_call(tool_name, tool_input)
    action = classified["summary"]
    if classified["effect"] == "none":
        return _allow(tool_effect="none", action=action)

    if not prompt:
        if classified["effect"] not in CONSEQUENTIAL_EFFECTS:
            return _allow(tool_effect=classified["effect"], action=action)
        return _failure(
            "Intent Translator could not see the request behind this action, so it cannot "
            f"confirm the action was asked for. The action is: {action}",
            tool_effect=classified["effect"],
            action=action,
            cause="no-recorded-prompt",
        )

    try:
        envelope = _compile_envelope(
            prompt,
            pending_action=action,
            scope=_scope_for(cwd),
            actor=actor,
            host=host,
        )
    except Exception as exc:  # noqa: BLE001 - a broken preflight must not fail open silently
        return _failure(
            f"Intent Translator could not complete its preflight ({type(exc).__name__}), "
            f"so this action is unverified. The action is: {action}",
            tool_effect=classified["effect"],
            action=action,
            cause="compile-failed",
        )

    gateway = envelope.get("tool_gateway", {})
    decision = str(gateway.get("decision", "human_review"))
    risk = envelope.get("risk", {})
    goal = str(envelope.get("normalized_goal", "")).strip()
    reasons = "; ".join(str(item) for item in gateway.get("reasons", []) if str(item).strip())

    if decision == "deny":
        return _deny(
            f"Intent Translator denied this action. Request: {prompt}. Action: {action}."
            + (f" Reason: {reasons}." if reasons else ""),
            tool_effect=classified["effect"],
            action=action,
            gateway=decision,
        )

    prohibited = _prohibited_action(envelope, classified["effect"])
    if prohibited:
        return _deny(
            f"The request prohibited {prohibited!r}, and this action would perform it. "
            f"Request: {prompt}. Action: {action}.",
            tool_effect=classified["effect"],
            action=action,
            gateway=decision,
            cause="prohibited-action",
        )

    if classified["effect"] not in CONSEQUENTIAL_EFFECTS:
        # An unresolved request means the consequential step needs confirmation, not that
        # the agent may not read a file or write a local draft while preparing it.
        return _allow(tool_effect=classified["effect"], action=action, gateway=decision)

    if decision == "human_review":
        return _ask(
            f"Intent Translator needs your confirmation before this action. Request: {prompt}. "
            f"Action: {action}." + (f" Reason: {reasons}." if reasons else ""),
            tool_effect=classified["effect"],
            action=action,
            gateway=decision,
        )

    compiled_effect = str(risk.get("effect", "")) or str(
        envelope.get("intent_contract", {}).get("risk", {}).get("effect", "")
    )
    if compiled_effect != classified["effect"]:
        return _ask(
            f"This action is more consequential than the request appears to be. The request "
            f"compiles to {goal or 'an unclear goal'} ({compiled_effect or 'no effect'}), but the "
            f"action would {classified['effect'].replace('_', ' ')}. Request: {prompt}. "
            f"Action: {action}.",
            tool_effect=classified["effect"],
            action=action,
            gateway=decision,
            cause="effect-mismatch",
            compiled_effect=compiled_effect,
        )
    return _allow(tool_effect=classified["effect"], action=action, gateway=decision)


PROHIBITED_ACTION_EFFECTS = {
    "publish": {"write_external"},
    "transfer": {"write_external"},
    "delete": {"destructive"},
    "uninstall": {"destructive", "system_change"},
    "install": {"system_change"},
    "overwrite": {"destructive", "write_local"},
}


def _prohibited_action(envelope: Mapping[str, Any], tool_effect: str) -> str:
    """Return a prohibited action that this tool call would carry out, if any.

    A contract prohibition names the action class and not the object, because that is
    what the compiler records: `不要删除 data 目录` becomes a prohibition on `delete`.
    The hook enforces the contract as written, so it blocks the class. Narrowing a
    prohibition to one object is compiler work, not hook work.
    """
    contract = envelope.get("intent_contract", {})
    prohibitions = contract.get("prohibitions") if isinstance(contract, Mapping) else None
    for item in prohibitions or []:
        if not isinstance(item, Mapping):
            continue
        prohibited = str(item.get("action", "")).strip()
        if prohibited and tool_effect in PROHIBITED_ACTION_EFFECTS.get(prohibited, set()):
            return prohibited
    return ""


def _session_key(event: Mapping[str, Any]) -> str:
    """Identify the conversation this event belongs to, across both hosts."""
    for key in ("conversation_id", "session_id"):
        value = str(event.get(key, "")).strip()
        if value:
            return value
    return ""


def _noted(decision: str, **detail: Any) -> HookOutcome:
    return HookOutcome(decision=decision, detail=detail)


def _claude_outcome(verdict: Verdict) -> HookOutcome:
    """Render a verdict for Claude Code, staying silent when there is nothing to add.

    Silence is what leaves the host's permission flow intact. Returning `allow` would
    skip the prompt the user configured, so an allowed verdict prints nothing at all.
    """
    if verdict.decision == "allow":
        return HookOutcome(decision="allow", detail=verdict.detail)
    payload = {
        "hookSpecificOutput": {
            "hookEventName": PRE_TOOL_EVENT,
            "permissionDecision": verdict.decision,
            "permissionDecisionReason": verdict.reason,
        }
    }
    if verdict.decision == "deny":
        return HookOutcome(
            payload=payload,
            exit_code=BLOCKING_EXIT_CODE,
            stderr=verdict.reason,
            decision="deny",
            detail=verdict.detail,
        )
    return HookOutcome(payload=payload, decision="ask", detail=verdict.detail)


def _cursor_outcome(verdict: Verdict, *, ask_supported: bool = True) -> HookOutcome:
    """Render a verdict for Cursor, which has no way to abstain.

    Cursor's schema offers only allow, deny, and ask, so an allowed verdict must say
    `allow`; its own allowlist and review remain the layer behind that. On the generic
    `preToolUse` event Cursor accepts `ask` without enforcing it, so a confirmation
    there would silently become an approval; those events ask for `deny` instead.
    """
    decision = verdict.decision
    downgraded = decision == "ask" and not ask_supported
    if downgraded:
        decision = "deny"
    payload: dict[str, Any] = {"permission": decision}
    if verdict.reason:
        payload["user_message"] = verdict.reason
        payload["agent_message"] = verdict.reason
    detail = {**verdict.detail}
    if downgraded:
        detail["ask_downgraded_to_deny"] = True
    return HookOutcome(payload=payload, decision=decision, detail=detail)


def _tool_from_cursor_event(event: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    """Normalize a Cursor event into the tool name and input the classifier expects."""
    name = str(event.get("hook_event_name", "")).strip()
    if name == CURSOR_SHELL_EVENT:
        return "Shell", {"command": str(event.get("command", ""))}
    if name == CURSOR_MCP_EVENT:
        server = str(event.get("mcp_server_name", "")).strip()
        tool = str(event.get("tool_name", "")).strip()
        raw_input = event.get("tool_input")
        if isinstance(raw_input, str):
            try:
                parsed = json.loads(raw_input)
            except (json.JSONDecodeError, ValueError):
                parsed = {"tool_input": raw_input}
            raw_input = parsed if isinstance(parsed, Mapping) else {"tool_input": raw_input}
        # An unnamed server cannot be recognized, so it must not inherit this project's
        # own exemption. Cursor's documentation makes the same point.
        return f"mcp__{server or 'unknown'}__{tool}", raw_input if isinstance(raw_input, Mapping) else {}
    tool_input = event.get("tool_input")
    return str(event.get("tool_name", "")), tool_input if isinstance(tool_input, Mapping) else {}


def handle(event: Mapping[str, Any], store: SessionStore | None = None) -> HookOutcome:
    """Turn one hook event into a decision without ever widening host permissions.

    The two hosts use disjoint event names, so the caller does not have to say which
    host is running. That matters because Cursor can also load this hook through its
    Claude Code compatibility path, where the Claude Code event names arrive instead.
    """
    store = store or SessionStore()
    name = str(event.get("hook_event_name", "")).strip()
    session = _session_key(event)

    if name in {PROMPT_EVENT, CURSOR_PROMPT_EVENT}:
        store.remember(session, str(event.get("prompt", "")))
        if name == CURSOR_PROMPT_EVENT:
            # Cursor treats missing or unparseable output as a hook failure, which a
            # fail-closed configuration would turn into a blocked prompt.
            return HookOutcome(payload={"continue": True}, decision="recorded")
        return _noted("recorded")
    if name in {SESSION_END_EVENT, CURSOR_SESSION_END_EVENT}:
        store.forget(session)
        return _noted("forgotten")

    if name == PRE_TOOL_EVENT:
        tool_input = event.get("tool_input")
        return _claude_outcome(
            evaluate_action(
                tool_name=str(event.get("tool_name", "")),
                tool_input=tool_input if isinstance(tool_input, Mapping) else {},
                prompt=store.recall(session),
                cwd=str(event.get("cwd", "")),
                actor=str(event.get("actor", "")),
                host="claude-code",
            )
        )

    if name in {CURSOR_SHELL_EVENT, CURSOR_MCP_EVENT, CURSOR_TOOL_EVENT}:
        tool_name, tool_input = _tool_from_cursor_event(event)
        return _cursor_outcome(
            evaluate_action(
                tool_name=tool_name,
                tool_input=tool_input,
                prompt=store.recall(session),
                cwd=str(event.get("cwd", "")),
                actor=str(event.get("user_email", "")),
                host="cursor",
            ),
            ask_supported=name != CURSOR_TOOL_EVENT,
        )

    return _noted("unsupported-event", event=name)


def settings_block(
    *,
    python: str | None = None,
    matcher: str = DEFAULT_TOOL_MATCHER,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Build the Claude Code `hooks` block that installs this enforcement."""
    handler = {
        "type": "command",
        "command": python or sys.executable,
        "args": ["-m", MODULE_ENTRYPOINT, "run", "--host", "claude-code"],
        "timeout": timeout,
        "statusMessage": "Intent Translator preflight",
    }
    return {
        PROMPT_EVENT: [{"hooks": [dict(handler)]}],
        PRE_TOOL_EVENT: [{"matcher": matcher, "hooks": [dict(handler)]}],
        SESSION_END_EVENT: [{"hooks": [dict(handler)]}],
    }


def _is_ours(handler: Any) -> bool:
    if not isinstance(handler, Mapping):
        return False
    if list(handler.get("args") or [])[:2] == ["-m", MODULE_ENTRYPOINT]:
        return True
    return MODULE_ENTRYPOINT in str(handler.get("command", ""))


def _hook_command(python: str | None, host: str) -> str:
    """Build a single command string, which is all Cursor's schema accepts."""
    executable = python or sys.executable
    quoted = f'"{executable}"' if " " in executable else executable
    return f"{quoted} -m {MODULE_ENTRYPOINT} run --host {host}"


def cursor_hooks_block(
    *,
    python: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    fail_closed: bool = True,
    gate_file_tools: bool = False,
) -> dict[str, Any]:
    """Build the Cursor `hooks` block that installs this enforcement.

    `failClosed` is applied to the gating events only. Cursor counts a crash, a timeout
    or unparseable output as a failure, and on `beforeSubmitPrompt` that would block the
    user's own prompt rather than an action, which is not a safety gain.
    """
    command = _hook_command(python, "cursor")
    gate = {"command": command, "timeout": timeout, "failClosed": fail_closed}
    block: dict[str, Any] = {
        CURSOR_PROMPT_EVENT: [{"command": command, "timeout": timeout}],
        CURSOR_SHELL_EVENT: [dict(gate)],
        CURSOR_MCP_EVENT: [dict(gate)],
        CURSOR_SESSION_END_EVENT: [{"command": command, "timeout": timeout}],
    }
    if gate_file_tools:
        block[CURSOR_TOOL_EVENT] = [{**gate, "matcher": CURSOR_FILE_TOOL_MATCHER}]
    return block


def _settings_path(
    host: str, scope: str, *, home: Path | None = None, project: Path | None = None
) -> Path:
    root = (project or Path.cwd()) if scope == "project" else (home or Path.home())
    if host == "cursor":
        return root / ".cursor" / "hooks.json"
    return root / ".claude" / "settings.json"


def _merge_claude_hooks(
    hooks: dict[str, Any], desired: dict[str, Any], *, remove: bool
) -> bool:
    changed = False
    for event, groups in desired.items():
        kept: list[dict[str, Any]] = []
        for group in [item for item in (hooks.get(event) or []) if isinstance(item, Mapping)]:
            handlers = [item for item in (group.get("hooks") or []) if not _is_ours(item)]
            if len(handlers) != len(list(group.get("hooks") or [])):
                changed = True
            if handlers:
                kept.append({**group, "hooks": handlers})
            elif not group.get("hooks"):
                kept.append(dict(group))
        if not remove:
            kept.extend(groups)
            changed = True
        hooks[event] = kept
        if not hooks[event]:
            hooks.pop(event)
    return changed


def _merge_cursor_hooks(
    hooks: dict[str, Any], desired: dict[str, Any], *, remove: bool
) -> bool:
    changed = False
    for event, handlers in desired.items():
        existing = [
            item
            for item in (hooks.get(event) or [])
            if isinstance(item, Mapping) and not _is_ours(item)
        ]
        if len(existing) != len(list(hooks.get(event) or [])):
            changed = True
        if not remove:
            existing.extend(handlers)
            changed = True
        hooks[event] = existing
        if not hooks[event]:
            hooks.pop(event)
    return changed


def install_hook(
    *,
    host: str = "claude-code",
    scope: str = "user",
    home: Path | None = None,
    project: Path | None = None,
    python: str | None = None,
    matcher: str = DEFAULT_TOOL_MATCHER,
    fail_closed: bool = True,
    gate_file_tools: bool = False,
    remove: bool = False,
) -> dict[str, Any]:
    """Merge the hook into a host config file without disturbing anything else in it."""
    from .atomic_io import locked_json_document

    path = _settings_path(host, scope, home=home, project=project)
    cursor = host == "cursor"
    desired = (
        cursor_hooks_block(
            python=python, fail_closed=fail_closed, gate_file_tools=gate_file_tools
        )
        if cursor
        else settings_block(python=python, matcher=matcher)
    )
    with locked_json_document(path, dict) as document:
        hooks = document.get("hooks")
        hooks = hooks if isinstance(hooks, dict) else {}
        merge = _merge_cursor_hooks if cursor else _merge_claude_hooks
        changed = merge(hooks, desired, remove=remove)
        if hooks:
            document["hooks"] = hooks
        else:
            document.pop("hooks", None)
        if cursor and hooks:
            document.setdefault("version", 1)
    label = "Cursor" if cursor else "Claude Code"
    result = {
        "host": host,
        "settings_path": str(path),
        "installed": not remove,
        "changed": changed,
        "events": sorted(desired),
        "message": (
            f"Hook removed; restart {label} to drop it"
            if remove
            else f"Hook installed; restart {label} to load it"
        ),
    }
    if cursor:
        result["fail_closed"] = fail_closed
        result["file_tools_gated"] = gate_file_tools
    else:
        result["matcher"] = matcher
    return result


def _read_event(stream) -> Mapping[str, Any]:
    buffer = getattr(stream, "buffer", None)
    raw = buffer.read().decode("utf-8", errors="replace") if buffer is not None else stream.read()
    payload = json.loads(raw) if raw.strip() else {}
    return payload if isinstance(payload, Mapping) else {}


def _render(verdict: Verdict, host: str) -> HookOutcome:
    return _cursor_outcome(verdict) if host == "cursor" else _claude_outcome(verdict)


def _run(argv: argparse.Namespace) -> int:
    try:
        event = _read_event(sys.stdin)
    except (json.JSONDecodeError, UnicodeError, OSError) as exc:
        # The event could not be read, so the host cannot be recognized from it. The
        # `--host` the installer wrote into the command decides the reply shape.
        return _render(
            _failure(
                f"Intent Translator could not read the hook input ({type(exc).__name__})."
            ),
            argv.host,
        ).emit()
    outcome = handle(event)
    if argv.explain:
        _write(sys.stderr, json.dumps({"decision": outcome.decision, **outcome.detail}, ensure_ascii=False))
    return outcome.emit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        nargs="?",
        default="run",
        choices=("run", "install", "uninstall", "print-settings"),
    )
    parser.add_argument("--host", choices=("claude-code", "cursor"), default="claude-code")
    parser.add_argument("--scope", choices=("user", "project"), default="user")
    parser.add_argument("--home", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--matcher", default=DEFAULT_TOOL_MATCHER)
    parser.add_argument(
        "--fail-open",
        action="store_true",
        help="Cursor only: let a crashed or timed-out hook allow the action through.",
    )
    parser.add_argument(
        "--gate-file-tools",
        action="store_true",
        help=(
            "Cursor only: also gate its Write and Delete tools. Cursor cannot ask for "
            "confirmation on that event, so a confirmation becomes a refusal there."
        ),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--explain", action="store_true", help="Write the decision to stderr.")
    args = parser.parse_args(argv)

    if args.action == "run":
        return _run(args)
    if args.action == "print-settings":
        block = (
            cursor_hooks_block(
                fail_closed=not args.fail_open, gate_file_tools=args.gate_file_tools
            )
            if args.host == "cursor"
            else settings_block(matcher=args.matcher)
        )
        payload: dict[str, Any] = {"hooks": block}
        if args.host == "cursor":
            payload = {"version": 1, "hooks": block}
        _write(sys.stdout, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return 0
    result = install_hook(
        host=args.host,
        scope=args.scope,
        home=args.home,
        project=args.project,
        matcher=args.matcher,
        fail_closed=not args.fail_open,
        gate_file_tools=args.gate_file_tools,
        remove=args.action == "uninstall",
    )
    label = "Cursor" if args.host == "cursor" else "Claude Code"
    report = (
        json.dumps(result, ensure_ascii=False, indent=2)
        if args.json
        else f"intent-translator {label} hook: {result['settings_path']}\n{result['message']}"
    )
    _write(sys.stdout, report + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
