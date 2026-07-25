"""Host-specific local paths shared by installers, config generation, and discovery."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


HOSTS = ("codex", "claude", "cursor", "gemini", "copilot", "opencode")


def default_skill_dir(
    host: str,
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> Path:
    if host not in HOSTS:
        raise ValueError(f"unsupported host: {host}")
    home = (home or Path.home()).expanduser()
    env = dict(os.environ if env is None else env)
    platform = platform or os.name
    if host == "codex":
        root = Path(env.get("CODEX_HOME", home / ".codex"))
    elif host == "claude":
        root = Path(env.get("CLAUDE_CONFIG_DIR", home / ".claude"))
    elif host == "cursor":
        root = home / ".cursor"
    elif host == "gemini":
        root = home / ".gemini"
    elif host == "copilot":
        root = home / ".copilot"
    elif platform == "nt":
        root = Path(env.get("LOCALAPPDATA", home / "AppData" / "Local")) / "opencode"
    else:
        root = Path(env.get("XDG_CONFIG_HOME", home / ".config")) / "opencode"
    return root.expanduser() / "skills" / "intent-translator"
