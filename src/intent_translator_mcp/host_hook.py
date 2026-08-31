"""Enforce the preflight inside a host that can veto a tool call before it runs.

A host hook is the only place where this project stops being advisory. Claude Code
runs `PreToolUse` before every tool call and honors a hook's `deny` ahead of its own
permission rules, so a compile result can prevent an action instead of merely
describing it.

Two events are needed, because a `PreToolUse` hook receives the tool call and not the
user's wording, while the compiler requires the exact wording:

1. `UserPromptSubmit` records the latest prompt for the session.
2. `PreToolUse` compiles that prompt, classifies the tool call the host is about to
   make, and returns a decision.

The hook only ever raises friction. An allowed verdict prints nothing and exits 0,
which Claude Code treats as "no decision" and leaves the host's own permission flow
untouched. Returning `allow` would *skip* the host's permission prompt, so this
module never does that: a preflight may not widen what a host would have permitted.
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

SERVER_TOOL_PREFIX = "mcp__intent-translator__"
DEFAULT_TOOL_MATCHER = "Bash|PowerShell|Write|Edit|NotebookEdit|WebFetch|mcp__.*"
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
        out = sys.stdout if out is None else out
        err = sys.stderr if err is None else err
        if self.payload is not None:
            out.write(json.dumps(self.payload, ensure_ascii=False))
        if self.stderr:
            err.write(self.stderr)
        return self.exit_code


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


def _pre_tool_payload(decision: str, reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": PRE_TOOL_EVENT,
            "permissionDecision": decision,
            "permissionDecisionReason": _clip(reason),
        }
    }


def _no_decision(decision: str = "no-decision", **detail: Any) -> HookOutcome:
    return HookOutcome(decision=decision, detail=detail)


def _deny(reason: str, **detail: Any) -> HookOutcome:
    return HookOutcome(
        payload=_pre_tool_payload("deny", reason),
        exit_code=BLOCKING_EXIT_CODE,
        stderr=_clip(reason),
        decision="deny",
        detail=detail,
    )


def _ask(reason: str, **detail: Any) -> HookOutcome:
    return HookOutcome(payload=_pre_tool_payload("ask", reason), decision="ask", detail=detail)


def _on_error_decision() -> str:
    configured = str(os.environ.get("INTENT_TRANSLATOR_HOOK_ON_ERROR", "")).strip().casefold()
    return configured if configured in {"ask", "deny", "allow"} else "ask"


def _failure(reason: str, **detail: Any) -> HookOutcome:
    """Decide what an unusable preflight means. Claude Code cannot fail closed for us.

    A crashed or unparseable hook is a non-blocking error in Claude Code, so the tool
    call would proceed. This module therefore takes its own position: by default it
    escalates to the user rather than silently allowing or hard blocking.
    """
    decision = _on_error_decision()
    if decision == "deny":
        return _deny(reason, **detail)
    if decision == "allow":
        return _no_decision("allow-on-error", **detail)
    return _ask(reason, **detail)


def _compile_envelope(utterance: str, *, pending_action: str, scope: str, actor: str) -> dict[str, Any]:
    from .core import IntentCompiler
    from .models import CompileRequest

    compiler = IntentCompiler(entrypoint="claude-code-hook", semantic_adapter=None)
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


def handle_pre_tool_use(event: Mapping[str, Any], store: SessionStore) -> HookOutcome:
    tool_name = str(event.get("tool_name", ""))
    tool_input = event.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, Mapping) else {}
    classified = classify_tool_call(tool_name, tool_input)
    action = classified["summary"]
    if classified["effect"] == "none":
        return _no_decision("allow", tool_effect="none", action=action)

    prompt = store.recall(str(event.get("session_id", "")))
    if not prompt:
        if classified["effect"] not in CONSEQUENTIAL_EFFECTS:
            return _no_decision("allow", tool_effect=classified["effect"], action=action)
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
            scope=_scope_for(event.get("cwd", "")),
            actor=str(event.get("actor", "")),
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
        return _no_decision(
            "allow", tool_effect=classified["effect"], action=action, gateway=decision
        )

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
    return _no_decision(
        "allow", tool_effect=classified["effect"], action=action, gateway=decision
    )


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


def handle(event: Mapping[str, Any], store: SessionStore | None = None) -> HookOutcome:
    """Turn one hook event into a decision without ever widening host permissions."""
    store = store or SessionStore()
    name = str(event.get("hook_event_name", "")).strip()
    if name == PROMPT_EVENT:
        store.remember(str(event.get("session_id", "")), str(event.get("prompt", "")))
        return _no_decision("recorded")
    if name == SESSION_END_EVENT:
        store.forget(str(event.get("session_id", "")))
        return _no_decision("forgotten")
    if name == PRE_TOOL_EVENT:
        return handle_pre_tool_use(event, store)
    return _no_decision("unsupported-event", event=name)


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
        "args": ["-m", "intent_translator_mcp.host_hook", "run"],
        "timeout": timeout,
        "statusMessage": "Intent Translator preflight",
    }
    return {
        PROMPT_EVENT: [{"hooks": [dict(handler)]}],
        PRE_TOOL_EVENT: [{"matcher": matcher, "hooks": [dict(handler)]}],
        SESSION_END_EVENT: [{"hooks": [dict(handler)]}],
    }


def _is_ours(handler: Any) -> bool:
    return (
        isinstance(handler, Mapping)
        and list(handler.get("args") or [])[:2] == ["-m", "intent_translator_mcp.host_hook"]
    )


def _settings_path(scope: str, *, home: Path | None = None, project: Path | None = None) -> Path:
    if scope == "project":
        return (project or Path.cwd()) / ".claude" / "settings.json"
    return (home or Path.home()) / ".claude" / "settings.json"


def install_hook(
    *,
    scope: str = "user",
    home: Path | None = None,
    project: Path | None = None,
    python: str | None = None,
    matcher: str = DEFAULT_TOOL_MATCHER,
    remove: bool = False,
) -> dict[str, Any]:
    """Merge the hook into a Claude Code settings file without disturbing other hooks."""
    from .atomic_io import locked_json_document

    path = _settings_path(scope, home=home, project=project)
    desired = settings_block(python=python, matcher=matcher)
    changed = False
    with locked_json_document(path, dict) as document:
        hooks = document.get("hooks")
        if not isinstance(hooks, dict):
            hooks = {}
        for event, groups in desired.items():
            existing = [item for item in (hooks.get(event) or []) if isinstance(item, Mapping)]
            kept: list[dict[str, Any]] = []
            for group in existing:
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
        if hooks:
            document["hooks"] = hooks
        else:
            document.pop("hooks", None)
    return {
        "host": "claude-code",
        "settings_path": str(path),
        "installed": not remove,
        "changed": changed,
        "events": sorted(desired),
        "matcher": matcher,
        "message": (
            "Hook removed; restart Claude Code to drop it"
            if remove
            else "Hook installed; restart Claude Code to load it"
        ),
    }


def _read_event(stream) -> Mapping[str, Any]:
    raw = stream.read()
    payload = json.loads(raw) if raw.strip() else {}
    return payload if isinstance(payload, Mapping) else {}


def _run(argv: argparse.Namespace) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        event = _read_event(sys.stdin)
    except (json.JSONDecodeError, UnicodeError, OSError) as exc:
        outcome = _failure(f"Intent Translator could not read the hook input ({type(exc).__name__}).")
        return outcome.emit()
    outcome = handle(event)
    if argv.explain:
        sys.stderr.write(json.dumps({"decision": outcome.decision, **outcome.detail}, ensure_ascii=False))
    return outcome.emit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        nargs="?",
        default="run",
        choices=("run", "install", "uninstall", "print-settings"),
    )
    parser.add_argument("--host", choices=("claude-code",), default="claude-code")
    parser.add_argument("--scope", choices=("user", "project"), default="user")
    parser.add_argument("--home", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--matcher", default=DEFAULT_TOOL_MATCHER)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--explain", action="store_true", help="Write the decision to stderr.")
    args = parser.parse_args(argv)

    if args.action == "run":
        return _run(args)
    if args.action == "print-settings":
        print(json.dumps({"hooks": settings_block(matcher=args.matcher)}, ensure_ascii=False, indent=2))
        return 0
    result = install_hook(
        scope=args.scope,
        home=args.home,
        project=args.project,
        matcher=args.matcher,
        remove=args.action == "uninstall",
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"intent-translator Claude Code hook: {result['settings_path']}")
        print(result["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
