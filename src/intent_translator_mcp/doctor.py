"""Privacy-conscious installation diagnostics for intent-translator."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Mapping

from .core import _candidate_skill_dirs


def _display_path(path: Path, home: Path, show_paths: bool) -> str:
    resolved = path.expanduser().resolve()
    if show_paths:
        return str(resolved)
    try:
        return str(Path("~") / resolved.relative_to(home.resolve()))
    except ValueError:
        return "<outside-home>"


def _check(identifier: str, status: str, message: str, **details: Any) -> dict[str, Any]:
    result = {"id": identifier, "status": status, "message": message}
    if details:
        result["details"] = details
    return result


def run_doctor(
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    show_paths: bool = False,
) -> dict[str, Any]:
    home = (home or Path.home()).expanduser().resolve()
    env = dict(os.environ if env is None else env)
    checks: list[dict[str, Any]] = []

    supported = sys.version_info >= (3, 10)
    checks.append(
        _check(
            "python",
            "pass" if supported else "fail",
            "Python version is supported" if supported else "Python 3.10 or newer is required",
            version=".".join(str(part) for part in sys.version_info[:3]),
        )
    )

    profile_path = Path(env.get("INTENT_TRANSLATOR_PROFILE", home / ".intent-translator" / "profile.json"))
    if not profile_path.exists():
        checks.append(_check("profile", "warn", "Profile is not initialized yet"))
        profile = {"memory": {"adapter": "sqlite"}}
    else:
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            required = {"schema_version", "profile_id", "language", "phrase_mappings", "memory"}
            missing = sorted(required - set(profile))
            checks.append(
                _check(
                    "profile",
                    "fail" if missing else "pass",
                    "Profile is valid JSON" if not missing else "Profile is missing required fields",
                    path=_display_path(profile_path, home, show_paths),
                    missing=missing,
                )
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            profile = {"memory": {"adapter": "sqlite"}}
            checks.append(
                _check(
                    "profile",
                    "fail",
                    "Profile cannot be read as UTF-8 JSON",
                    path=_display_path(profile_path, home, show_paths),
                    error=type(exc).__name__,
                )
            )

    memory_location = env.get("INTENT_TRANSLATOR_MEMORY_DB") or profile.get("memory", {}).get("location")
    memory_path = Path(memory_location).expanduser() if memory_location else home / ".intent-translator" / "memory.db"
    if memory_path.exists():
        try:
            connection = sqlite3.connect(f"file:{memory_path.resolve().as_posix()}?mode=ro", uri=True)
            try:
                integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
            finally:
                connection.close()
            checks.append(
                _check(
                    "memory",
                    "pass" if integrity == "ok" else "fail",
                    "Memory database passed SQLite quick_check" if integrity == "ok" else "Memory database failed SQLite quick_check",
                    path=_display_path(memory_path, home, show_paths),
                )
            )
        except sqlite3.Error as exc:
            checks.append(
                _check(
                    "memory",
                    "fail",
                    "Memory database could not be opened read-only",
                    path=_display_path(memory_path, home, show_paths),
                    error=type(exc).__name__,
                )
            )
    else:
        parent = memory_path.parent
        writable = parent.exists() and os.access(parent, os.W_OK)
        checks.append(
            _check(
                "memory",
                "warn" if writable else "fail",
                "Memory database will be created on first authorized write" if writable else "Memory directory is not writable",
                path=_display_path(memory_path, home, show_paths),
            )
        )

    skill_dirs = _candidate_skill_dirs()
    checks.append(
        _check(
            "skill",
            "pass" if skill_dirs else "warn",
            "Installed intent-translator Skill found" if skill_dirs else "No installed Skill found; MCP can still report this condition",
            locations=[_display_path(path, home, show_paths) for path in skill_dirs],
        )
    )

    config_dir = home / ".intent-translator" / "mcp-configs"
    generated = sorted(config_dir.glob("*-mcp.*")) if config_dir.exists() else []
    checks.append(
        _check(
            "mcp_configs",
            "pass" if generated else "warn",
            "Generated MCP host snippets found" if generated else "MCP host snippets have not been generated",
            count=len(generated),
            location=_display_path(config_dir, home, show_paths),
        )
    )

    runtime_state = home / ".intent-translator" / "mcp" / "current.json"
    if not runtime_state.exists():
        checks.append(_check("mcp_runtime", "warn", "Versioned MCP runtime state was not found"))
    else:
        try:
            state = json.loads(runtime_state.read_text(encoding="utf-8-sig"))
            raw_command = str(state.get("command", "")).strip()
            command = Path(raw_command).expanduser() if raw_command else None
            version = str(state.get("version", "")).strip()
            valid = bool(version and command is not None and command.is_absolute() and command.is_file())
            checks.append(
                _check(
                    "mcp_runtime",
                    "pass" if valid else "fail",
                    "Versioned MCP runtime is installed" if valid else "Versioned MCP runtime state is stale or invalid",
                    version=version or None,
                    command=_display_path(command, home, show_paths) if command is not None else None,
                )
            )
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            checks.append(
                _check(
                    "mcp_runtime",
                    "fail",
                    "Versioned MCP runtime state cannot be read",
                    error=type(exc).__name__,
                )
            )

    semantic_command = env.get("INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON", "").strip()
    semantic_provider = env.get("INTENT_TRANSLATOR_SEMANTIC_PROVIDER", "").strip().casefold()
    if not semantic_command and not semantic_provider:
        checks.append(_check("semantic_adapter", "pass", "Optional semantic adapter is disabled"))
    elif semantic_provider in {"chat-completions", "openai-compatible"}:
        base_url = env.get("INTENT_TRANSLATOR_SEMANTIC_BASE_URL", "").strip()
        model = env.get("INTENT_TRANSLATOR_SEMANTIC_MODEL", "").strip()
        parsed = urllib.parse.urlparse(base_url)
        valid = bool(model and parsed.scheme in {"http", "https"} and parsed.netloc)
        external = (parsed.hostname or "").casefold() not in {"localhost", "127.0.0.1", "::1"}
        checks.append(
            _check(
                "semantic_adapter",
                "warn" if valid and external else "pass" if valid else "fail",
                "External chat-completions adapter is configured; each request still needs explicit egress authorization"
                if valid and external
                else "Local chat-completions adapter configuration is valid"
                if valid
                else "Chat-completions adapter requires a valid HTTP(S) base URL and model",
                provider="chat-completions",
                external=external,
            )
        )
    else:
        try:
            semantic_argv = json.loads(semantic_command)
            valid = isinstance(semantic_argv, list) and bool(semantic_argv) and all(
                isinstance(item, str) and bool(item) for item in semantic_argv
            )
        except json.JSONDecodeError:
            valid = False
        external = env.get("INTENT_TRANSLATOR_SEMANTIC_EXTERNAL", "0") == "1"
        checks.append(
            _check(
                "semantic_adapter",
                "warn" if valid and external else "pass" if valid else "fail",
                "External semantic adapter is configured; each request still needs explicit egress authorization"
                if valid and external
                else "Local semantic adapter configuration is valid"
                if valid
                else "Semantic adapter command must be a non-empty JSON string array",
                external=external,
            )
        )

    statuses = {item["status"] for item in checks}
    overall = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"
    return {
        "schema_version": 1,
        "status": overall,
        "privacy": "Home-relative paths are shown by default; use --show-paths for exact locations.",
        "checks": checks,
    }


def _render_human(report: dict[str, Any]) -> str:
    labels = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}
    lines = [f"intent-translator doctor: {labels[report['status']]}" ]
    for item in report["checks"]:
        lines.append(f"[{labels[item['status']]}] {item['id']}: {item['message']}")
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit structured JSON")
    parser.add_argument("--show-paths", action="store_true", help="Include exact local paths")
    args = parser.parse_args()
    report = run_doctor(show_paths=args.show_paths)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else _render_human(report))
    return 2 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
