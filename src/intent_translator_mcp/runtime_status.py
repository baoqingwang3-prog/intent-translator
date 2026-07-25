"""Privacy-bounded runtime and installed-copy version handshake."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .host_paths import HOSTS, default_skill_dir


UNKNOWN_VERSIONS = {None, "", "legacy-unversioned", "unknown", "unreadable"}
SUPPORTED_PROFILE_SCHEMA = 1


def candidate_skill_dirs(
    *, home: Path | None = None, env: Mapping[str, str] | None = None
) -> list[Path]:
    env = dict(os.environ if env is None else env)
    configured = env.get("INTENT_TRANSLATOR_SKILL_DIR")
    package_repo = Path(__file__).resolve().parents[2]
    configured_home = str(env.get("INTENT_TRANSLATOR_HOME", "")).strip()
    home = (home or (Path(configured_home) if configured_home else Path.home())).expanduser()
    candidates = [
        Path(configured).expanduser() if configured else None,
        package_repo / "skills" / "intent-translator",
        *(default_skill_dir(host, home=home, env=env) for host in HOSTS),
        home / ".agents" / "skills" / "intent-translator",
    ]
    result: list[Path] = []
    for path in candidates:
        if path and path.exists():
            resolved = path.resolve()
            if resolved not in result:
                result.append(resolved)
    return result


def skill_version(path: Path) -> str:
    version_path = path / "VERSION"
    if not version_path.is_file():
        return "legacy-unversioned"
    try:
        return version_path.read_text(encoding="utf-8-sig").strip() or "unknown"
    except (OSError, UnicodeError):
        return "unreadable"


def _data_dir(home: Path, env: Mapping[str, str]) -> Path:
    configured = str(env.get("INTENT_TRANSLATOR_DATA_DIR", "")).strip()
    return Path(configured).expanduser() if configured else home / ".intent-translator"


def _installed_runtime(data_dir: Path) -> tuple[str | None, bool, bool]:
    state_path = data_dir / "mcp" / "current.json"
    if not state_path.is_file():
        return None, False, False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8-sig"))
        version = str(state.get("version", "")).strip() or None
        raw_command = str(state.get("command", "")).strip()
        command = Path(raw_command).expanduser() if raw_command else None
        valid = bool(version and command and command.is_absolute() and command.is_file())
        return version, valid, True
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None, False, True


def build_runtime_status(
    *,
    actual_version: str,
    profile: Mapping[str, Any] | None,
    entrypoint: str,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    skill_dirs: Sequence[Path] | None = None,
) -> dict[str, Any]:
    """Report actual loaded code versus installed disk state without exposing paths."""
    env = dict(os.environ if env is None else env)
    configured_home = str(env.get("INTENT_TRANSLATOR_HOME", "")).strip()
    home = (home or (Path(configured_home) if configured_home else Path.home())).expanduser().resolve()
    directories = list(skill_dirs) if skill_dirs is not None else candidate_skill_dirs(home=home, env=env)
    versions = [skill_version(path) for path in directories]
    active_skill = versions[0] if versions else None
    comparable_skill = active_skill if active_skill not in UNKNOWN_VERSIONS else None
    comparable_copies = {item for item in versions if item not in UNKNOWN_VERSIONS}
    copies_differ = len(comparable_copies) > 1
    installed_runtime, runtime_valid, runtime_state_exists = _installed_runtime(_data_dir(home, env))
    profile_schema = (profile or {}).get("schema_version")

    stale_reasons: list[str] = []
    degraded_reasons: list[str] = []
    if installed_runtime and installed_runtime != actual_version:
        stale_reasons.append("installed runtime and running process versions differ")
    if comparable_skill and comparable_skill != actual_version:
        stale_reasons.append("active Skill and running process versions differ")
    if copies_differ:
        stale_reasons.append("installed Skill copies have different versions")
    if not runtime_state_exists:
        degraded_reasons.append("versioned MCP runtime state is missing")
    elif not runtime_valid:
        degraded_reasons.append("versioned MCP runtime state is invalid")
    if not directories:
        degraded_reasons.append("installed Skill copy is missing")
    elif comparable_skill is None:
        degraded_reasons.append("active Skill version is unavailable")
    if profile_schema not in {None, SUPPORTED_PROFILE_SCHEMA}:
        degraded_reasons.append("profile schema is not supported by this runtime")

    state = "stale" if stale_reasons else "degraded" if degraded_reasons else "active"
    return {
        "state": state,
        "active": state == "active",
        "stale_runtime": state == "stale",
        "degraded": state == "degraded",
        "restart_required": bool(stale_reasons),
        "entrypoint": entrypoint,
        "mcp_connected": entrypoint.startswith("mcp"),
        "versions": {
            "package": actual_version,
            "actual_runtime": actual_version,
            "installed_runtime": installed_runtime,
            "active_skill": active_skill,
            "skill_copies": versions,
            "profile_schema": profile_schema,
            "supported_profile_schema": SUPPORTED_PROFILE_SCHEMA,
        },
        "sources": {
            "actual_runtime": "running-process",
            "installed_runtime": "versioned-runtime-state" if runtime_state_exists else "missing",
            "active_skill": "installed-skill-precedence" if directories else "missing",
            "profile_schema": "local-profile" if profile_schema is not None else "generic-default",
        },
        "reasons": [*stale_reasons, *degraded_reasons],
        "message": (
            "当前已连接并运行同版本。"
            if state == "active"
            else "磁盘版本与当前运行进程不一致，需要重启或重载宿主。"
            if state == "stale"
            else "当前以基础模式运行，部分可选安装状态不完整。"
        ),
    }
