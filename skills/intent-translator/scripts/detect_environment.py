#!/usr/bin/env python3
"""Report local compatibility for intent-translator without changing the system."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


SUPPORTED_SYSTEMS = {"Windows", "Darwin", "Linux"}
MINIMUM_PYTHON = (3, 10)


def default_profile_path(home: Path, env: Mapping[str, str]) -> Path:
    configured = env.get("INTENT_TRANSLATOR_PROFILE")
    return Path(configured).expanduser() if configured else home / ".intent-translator" / "profile.json"


def skill_roots(home: Path, cwd: Path, env: Mapping[str, str]) -> list[Path]:
    codex_home = Path(env.get("CODEX_HOME", home / ".codex")).expanduser()
    claude_home = Path(env.get("CLAUDE_CONFIG_DIR", home / ".claude")).expanduser()
    local_app_data = Path(env.get("LOCALAPPDATA", home / "AppData" / "Local")).expanduser()
    opencode_home = (
        local_app_data / "opencode"
        if platform.system() == "Windows"
        else Path(env.get("XDG_CONFIG_HOME", home / ".config")).expanduser() / "opencode"
    )
    candidates = [
        codex_home / "skills",
        claude_home / "skills",
        home / ".cursor" / "skills",
        home / ".gemini" / "skills",
        home / ".copilot" / "skills",
        opencode_home / "skills",
        home / ".agents" / "skills",
        cwd / ".codex" / "skills",
        cwd / ".claude" / "skills",
        cwd / ".cursor" / "skills",
        cwd / ".gemini" / "skills",
        cwd / ".github" / "skills",
        cwd / ".opencode" / "skills",
        cwd / ".agents" / "skills",
    ]
    seen: set[str] = set()
    result: list[Path] = []
    for candidate in candidates:
        key = str(candidate.resolve())
        if key not in seen:
            seen.add(key)
            result.append(candidate.resolve())
    return result


def inspect_environment(
    *,
    home: Path | None = None,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    system: str | None = None,
    python_version: Sequence[int] | None = None,
) -> dict[str, Any]:
    home = (home or Path.home()).expanduser().resolve()
    cwd = (cwd or Path.cwd()).expanduser().resolve()
    env = dict(os.environ if env is None else env)
    system = system or platform.system()
    version = tuple(python_version or sys.version_info[:3])
    roots = skill_roots(home, cwd, env)

    command_names = (
        "python",
        "python3",
        "codex",
        "claude",
        "cursor",
        "gemini",
        "copilot",
        "opencode",
        "obsidian",
    )
    commands = {name: which(name) for name in command_names}
    hosts: list[str] = []
    codex_home = Path(env.get("CODEX_HOME", home / ".codex")).expanduser()
    claude_home = Path(env.get("CLAUDE_CONFIG_DIR", home / ".claude")).expanduser()
    if commands["codex"] or codex_home.exists():
        hosts.append("codex")
    if commands["claude"] or claude_home.exists():
        hosts.append("claude-code")
    if commands["cursor"] or (home / ".cursor").exists():
        hosts.append("cursor")
    if commands["gemini"] or (home / ".gemini").exists():
        hosts.append("gemini-cli")
    if commands["copilot"] or (home / ".copilot").exists():
        hosts.append("github-copilot")
    opencode_config = (
        Path(env.get("LOCALAPPDATA", home / "AppData" / "Local")) / "opencode"
        if system == "Windows"
        else Path(env.get("XDG_CONFIG_HOME", home / ".config")) / "opencode"
    )
    if commands["opencode"] or opencode_config.exists():
        hosts.append("opencode")

    profile = default_profile_path(home, env).resolve()
    memory_db = Path(env.get("INTENT_TRANSLATOR_MEMORY_DB", home / ".intent-translator" / "memory.db")).expanduser().resolve()
    obsidian_vault = env.get("OBSIDIAN_VAULT")
    obsidian_available = bool(commands["obsidian"] or obsidian_vault)

    warnings: list[str] = []
    if system not in SUPPORTED_SYSTEMS:
        warnings.append(f"untested operating system: {system}")
    if version < MINIMUM_PYTHON:
        warnings.append("Python 3.10 or newer is required")
    if not hosts:
        warnings.append("no Codex or Claude Code host detected; manual installation may be required")
    if not os.access(profile.parent if profile.parent.exists() else home, os.W_OK):
        warnings.append("default profile location may not be writable")

    compatible = system in SUPPORTED_SYSTEMS and version >= MINIMUM_PYTHON
    return {
        "schema_version": 1,
        "compatible": compatible,
        "system": system,
        "release": platform.release(),
        "machine": platform.machine(),
        "python": {
            "version": ".".join(str(part) for part in version),
            "supported": version >= MINIMUM_PYTHON,
            "executable": sys.executable,
        },
        "hosts": hosts,
        "commands": commands,
        "paths": {
            "home": str(home),
            "cwd": str(cwd),
            "profile": str(profile),
            "memory_db": str(memory_db),
            "skill_roots": [str(path) for path in roots],
        },
        "memory": {
            "recommended_adapter": "sqlite",
            "obsidian_available": obsidian_available,
            "obsidian_vault": obsidian_vault,
            "sqlite_available": True,
        },
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compact", action="store_true")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    report = inspect_environment()
    payload = json.dumps(report, ensure_ascii=False, indent=None if args.compact else 2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0 if report["compatible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
