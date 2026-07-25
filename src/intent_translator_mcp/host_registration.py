"""Inspect and repair host MCP registration without editing host config files directly."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .host_paths import default_skill_dir


SERVER_NAME = "intent-translator"
AWAITING_HOST_EXIT = 3
REPAIR_COMMAND = "intent-translator-host repair --host codex"
REQUIRED_ENV = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


class HostRegistrationError(RuntimeError):
    def __init__(self, message: str, *, restored_previous: bool = False) -> None:
        super().__init__(message)
        self.restored_previous = restored_previous


def _resolved_home(home: Path | None, env: Mapping[str, str]) -> Path:
    configured = str(env.get("INTENT_TRANSLATOR_HOME", "")).strip()
    return (home or (Path(configured) if configured else Path.home())).expanduser().resolve()


def _data_dir(home: Path, env: Mapping[str, str]) -> Path:
    configured = str(env.get("INTENT_TRANSLATOR_DATA_DIR", "")).strip()
    return Path(configured).expanduser() if configured else home / ".intent-translator"


def _codex_home(home: Path, env: Mapping[str, str]) -> Path:
    configured = str(env.get("CODEX_HOME", "")).strip()
    return (Path(configured) if configured else home / ".codex").expanduser().resolve()


def _runtime_spec(home: Path, env: Mapping[str, str]) -> dict[str, Any] | None:
    state_path = _data_dir(home, env) / "mcp" / "current.json"
    if not state_path.is_file():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8-sig"))
        version = str(state.get("version", "")).strip()
        command_text = str(state.get("command", "")).strip()
        command = Path(command_text).expanduser() if command_text else None
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return {"valid": False, "version": None, "command": None}
    valid = bool(version and command and command.is_absolute() and command.is_file())
    return {"valid": valid, "version": version or None, "command": command}


def find_codex_cli(
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> Path | None:
    env = dict(os.environ if env is None else env)
    home = _resolved_home(home, env)
    platform = platform or os.name
    configured = str(env.get("CODEX_CLI_PATH", "")).strip()
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return candidate.resolve()

    if platform == "nt":
        local_app_data = Path(env.get("LOCALAPPDATA", home / "AppData" / "Local"))
        bin_root = local_app_data / "OpenAI" / "Codex" / "bin"
        candidates = list(bin_root.glob("*/codex.exe")) if bin_root.is_dir() else []
        candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0].resolve()

    discovered = shutil.which(
        "codex.exe" if platform == "nt" else "codex",
        path=env.get("PATH", ""),
    )
    if discovered:
        return Path(discovered).resolve()
    return None


def _codex_is_running(*, env: Mapping[str, str] | None = None) -> bool:
    env = dict(os.environ if env is None else env)
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Codex.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, **env},
                check=False,
            )
            if result.returncode != 0:
                return True
            return any(line.lstrip().casefold().startswith('"codex.exe"') for line in result.stdout.splitlines())
        result = subprocess.run(
            ["ps", "-A", "-o", "comm="],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, **env},
            check=False,
        )
        if result.returncode != 0:
            return True
        return any(Path(line.strip()).name.casefold() == "codex" for line in result.stdout.splitlines())
    except OSError:
        return True


def _run_codex(
    cli: Path,
    codex_home: Path,
    env: Mapping[str, str],
    args: Sequence[str],
) -> subprocess.CompletedProcess[str]:
    process_env = {**os.environ, **env, "CODEX_HOME": str(codex_home)}
    return subprocess.run(
        [str(cli), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=process_env,
        check=False,
    )


def _registered_spec(
    cli: Path, codex_home: Path, env: Mapping[str, str]
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        result = _run_codex(cli, codex_home, env, ["mcp", "get", SERVER_NAME, "--json"])
    except OSError:
        return None, "codex CLI could not inspect MCP registration"
    if result.returncode != 0:
        missing = "no mcp server named" in result.stderr.casefold() or "not found" in result.stderr.casefold()
        return (None, None) if missing else (None, "codex CLI could not inspect MCP registration")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "codex CLI returned unreadable MCP registration"
    return value if isinstance(value, dict) else None, None


def _path_equal(left: str | Path | None, right: str | Path | None) -> bool:
    if not left or not right:
        return False
    left_path = Path(left).expanduser().resolve(strict=False)
    right_path = Path(right).expanduser().resolve(strict=False)
    return os.path.normcase(os.fspath(left_path)) == os.path.normcase(os.fspath(right_path))


def _matches_runtime(spec: Mapping[str, Any], runtime: Mapping[str, Any], skill_dir: Path) -> bool:
    transport = spec.get("transport") if isinstance(spec.get("transport"), Mapping) else {}
    registered_env = transport.get("env") if isinstance(transport.get("env"), Mapping) else {}
    return bool(
        spec.get("enabled", True)
        and transport.get("type") == "stdio"
        and _path_equal(transport.get("command"), runtime.get("command"))
        and list(transport.get("args") or []) == []
        and all(str(registered_env.get(key, "")) == value for key, value in REQUIRED_ENV.items())
        and _path_equal(registered_env.get("INTENT_TRANSLATOR_SKILL_DIR"), skill_dir)
    )


def codex_registration_status(
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    active_runtime: bool = False,
) -> dict[str, Any]:
    env = dict(os.environ if env is None else env)
    home = _resolved_home(home, env)
    runtime = _runtime_spec(home, env)
    base = {
        "host": "codex",
        "repair_command": REPAIR_COMMAND,
        "installed": bool(runtime and runtime.get("valid")),
        "registered": False,
        "matches_runtime": False,
        "host_running": False,
        "restart_required": False,
    }
    if runtime is None:
        return {**base, "state": "not-installed", "message": "MCP runtime is not installed"}
    if not runtime.get("valid"):
        return {**base, "state": "installed-invalid", "message": "Installed MCP runtime state is invalid"}

    cli = find_codex_cli(home=home, env=env)
    if cli is None:
        return {
            **base,
            "state": "installed-not-registered",
            "message": "Codex CLI was not found, so registration could not be verified",
        }
    codex_home = _codex_home(home, env)
    spec, inspect_error = _registered_spec(cli, codex_home, env)
    if inspect_error:
        return {**base, "state": "registration-unknown", "message": inspect_error}
    if spec is None:
        return {
            **base,
            "state": "installed-not-registered",
            "message": "Runtime is installed but Codex MCP registration is missing",
        }

    running = _codex_is_running(env=env)
    skill_dir = default_skill_dir("codex", home=home, env={**env, "CODEX_HOME": str(codex_home)})
    matches = _matches_runtime(spec, runtime, skill_dir)
    if not matches:
        return {
            **base,
            "state": "registered-stale",
            "registered": True,
            "host_running": running,
            "restart_required": True,
            "message": "Codex is registered to a different runtime or Skill copy",
        }
    if active_runtime:
        state = "active"
        message = "Codex is connected to the installed runtime"
    elif running:
        state = "registered-pending-restart"
        message = "Registration matches disk; restart Codex if this runtime was just installed"
    else:
        state = "registered"
        message = "Codex registration matches the installed runtime"
    return {
        **base,
        "state": state,
        "registered": True,
        "matches_runtime": True,
        "host_running": running,
        "restart_required": state == "registered-pending-restart",
        "message": message,
    }


def _add_args(spec: Mapping[str, Any]) -> list[str]:
    transport = spec.get("transport") if isinstance(spec.get("transport"), Mapping) else {}
    command = str(transport.get("command", "")).strip()
    if not command:
        raise HostRegistrationError("MCP registration has no command")
    registered_env = transport.get("env") if isinstance(transport.get("env"), Mapping) else {}
    args = ["mcp", "add", SERVER_NAME]
    for key, value in registered_env.items():
        args.extend(["--env", f"{key}={value}"])
    args.extend(["--", command, *[str(item) for item in transport.get("args") or []]])
    return args


def _desired_spec(runtime: Mapping[str, Any], skill_dir: Path) -> dict[str, Any]:
    return {
        "name": SERVER_NAME,
        "enabled": True,
        "transport": {
            "type": "stdio",
            "command": str(runtime["command"]),
            "args": [],
            "env": {**REQUIRED_ENV, "INTENT_TRANSLATOR_SKILL_DIR": str(skill_dir)},
        },
    }


def repair_codex_registration(
    *, home: Path | None = None, env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    env = dict(os.environ if env is None else env)
    home = _resolved_home(home, env)
    runtime = _runtime_spec(home, env)
    if runtime is None or not runtime.get("valid"):
        raise HostRegistrationError("Install a valid MCP runtime before repairing Codex registration")
    if _codex_is_running(env=env):
        return {
            "host": "codex",
            "state": "awaiting-host-exit",
            "changed": False,
            "exit_code": AWAITING_HOST_EXIT,
            "repair_command": REPAIR_COMMAND,
            "message": "Close Codex, run the repair command once, then reopen Codex",
        }

    cli = find_codex_cli(home=home, env=env)
    if cli is None:
        raise HostRegistrationError("Codex CLI was not found")
    codex_home = _codex_home(home, env)
    skill_dir = default_skill_dir("codex", home=home, env={**env, "CODEX_HOME": str(codex_home)})
    current, inspect_error = _registered_spec(cli, codex_home, env)
    if inspect_error:
        raise HostRegistrationError(inspect_error)
    if current is not None and _matches_runtime(current, runtime, skill_dir):
        return {
            "host": "codex",
            "state": "registered",
            "changed": False,
            "exit_code": 0,
            "repair_command": REPAIR_COMMAND,
            "message": "Codex registration already matches the installed runtime",
        }

    desired = _desired_spec(runtime, skill_dir)
    if current is not None:
        removed = _run_codex(cli, codex_home, env, ["mcp", "remove", SERVER_NAME])
        if removed.returncode != 0:
            raise HostRegistrationError("Codex CLI could not remove the stale MCP registration")

    added = _run_codex(cli, codex_home, env, _add_args(desired))
    if added.returncode != 0:
        restored = False
        if current is not None:
            restored = _run_codex(cli, codex_home, env, _add_args(current)).returncode == 0
        raise HostRegistrationError(
            "Codex CLI could not add the MCP registration",
            restored_previous=restored,
        )
    return {
        "host": "codex",
        "state": "registered",
        "changed": True,
        "exit_code": 0,
        "repair_command": REPAIR_COMMAND,
        "message": "Codex registration updated; reopen Codex to load it",
    }


def _print_result(result: Mapping[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"intent-translator Codex registration: {result['state']}")
        print(result["message"])
        if result.get("state") not in {"registered", "active"}:
            print(f"Repair: {result['repair_command']}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "repair"))
    parser.add_argument("--host", choices=("codex",), default="codex")
    parser.add_argument("--home", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = (
            codex_registration_status(home=args.home)
            if args.action == "status"
            else repair_codex_registration(home=args.home)
        )
    except HostRegistrationError as exc:
        result = {
            "host": args.host,
            "state": "repair-failed",
            "message": str(exc),
            "restored_previous": exc.restored_previous,
            "repair_command": REPAIR_COMMAND,
        }
        _print_result(result, as_json=args.json)
        return 2
    _print_result(result, as_json=args.json)
    return int(result.get("exit_code", 0))


if __name__ == "__main__":
    raise SystemExit(main())
