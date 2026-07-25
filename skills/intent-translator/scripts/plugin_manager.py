#!/usr/bin/env python3
"""Discover, enable, and invoke local optional Intent Translator plugins."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from init_profile import default_profile, profile_transaction


PLUGIN_API_VERSION = 1
PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "optional"
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PROFILE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def default_profile_path() -> Path:
    configured = os.environ.get("INTENT_TRANSLATOR_PROFILE")
    return Path(configured).expanduser() if configured else Path.home() / ".intent-translator" / "profile.json"


def load_profile(path: Path) -> dict[str, Any]:
    path = path.expanduser()
    if not path.exists():
        return default_profile()
    return json.loads(path.read_text(encoding="utf-8"))


def _validated_manifest(plugin_dir: Path) -> dict[str, Any]:
    manifest_path = plugin_dir / "adapter.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "schema_version", "name", "profile_key", "entrypoint", "default_state",
        "default_enabled", "operations", "network",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise ValueError(f"{plugin_dir.name}: missing manifest fields: {', '.join(missing)}")
    if manifest["schema_version"] != PLUGIN_API_VERSION:
        raise ValueError(f"{plugin_dir.name}: unsupported plugin API version")
    if not isinstance(manifest["name"], str) or not NAME_PATTERN.fullmatch(manifest["name"]):
        raise ValueError(f"{plugin_dir.name}: invalid plugin name")
    if not isinstance(manifest["profile_key"], str) or not PROFILE_KEY_PATTERN.fullmatch(
        manifest["profile_key"]
    ):
        raise ValueError(f"{plugin_dir.name}: invalid profile key")
    if manifest["default_enabled"] is not False:
        raise ValueError(f"{plugin_dir.name}: optional plugins must default to disabled")
    if not isinstance(manifest["default_state"], str) or not manifest["default_state"].strip():
        raise ValueError(f"{plugin_dir.name}: invalid default state path")
    operations = manifest["operations"]
    if not isinstance(operations, list) or not operations or any(
        not isinstance(item, str) or not NAME_PATTERN.fullmatch(item.replace("_", "-")) for item in operations
    ):
        raise ValueError(f"{plugin_dir.name}: operations must be a non-empty string list")
    if manifest["network"] is not False:
        raise ValueError(f"{plugin_dir.name}: this local plugin runner does not permit network plugins")
    entrypoint = (plugin_dir / str(manifest["entrypoint"])).resolve()
    try:
        entrypoint.relative_to(plugin_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"{plugin_dir.name}: entrypoint escapes the plugin directory") from exc
    if not entrypoint.is_file() or entrypoint.suffix != ".py":
        raise ValueError(f"{plugin_dir.name}: Python entrypoint is missing")
    return {**manifest, "plugin_dir": plugin_dir, "entrypoint_path": entrypoint}


def discover_plugins(root: Path = PLUGIN_ROOT) -> list[dict[str, Any]]:
    plugins: list[dict[str, Any]] = []
    if not root.is_dir():
        return plugins
    for plugin_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        if (plugin_dir / "adapter.json").is_file():
            try:
                plugin_dir.resolve().relative_to(root.resolve())
            except ValueError as exc:
                raise ValueError(f"{plugin_dir.name}: plugin directory escapes the plugin root") from exc
            plugins.append(_validated_manifest(plugin_dir))
    names = [item["name"] for item in plugins]
    if len(names) != len(set(names)):
        raise ValueError("duplicate plugin names are not allowed")
    profile_keys = [item["profile_key"] for item in plugins]
    if len(profile_keys) != len(set(profile_keys)):
        raise ValueError("duplicate plugin profile keys are not allowed")
    return plugins


def _plugin_by_name(name: str, root: Path = PLUGIN_ROOT) -> dict[str, Any]:
    for plugin in discover_plugins(root):
        if plugin["name"] == name:
            return plugin
    raise ValueError(f"unknown plugin: {name}")


def plugin_enabled(plugin: dict[str, Any], profile: dict[str, Any]) -> bool:
    return bool(profile.get("optional_adapters", {}).get(plugin["profile_key"], False))


def plugin_status(profile_path: Path, root: Path = PLUGIN_ROOT) -> list[dict[str, Any]]:
    profile = load_profile(profile_path)
    return [
        {
            "name": plugin["name"],
            "enabled": plugin_enabled(plugin, profile),
            "default_enabled": plugin["default_enabled"],
            "operations": plugin["operations"],
            "network": False,
        }
        for plugin in discover_plugins(root)
    ]


def set_plugin_enabled(profile_path: Path, name: str, enabled: bool, root: Path = PLUGIN_ROOT) -> dict[str, Any]:
    plugin = _plugin_by_name(name, root)
    with profile_transaction(profile_path, create=True) as profile:
        profile.setdefault("optional_adapters", {})[plugin["profile_key"]] = enabled
    return {"name": name, "enabled": enabled, "profile_updated": True}


def _load_entrypoint(plugin: dict[str, Any]):
    module_name = f"intent_translator_plugin_{plugin['name'].replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, plugin["entrypoint_path"])
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load plugin: {plugin['name']}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if getattr(module, "PLUGIN_API_VERSION", None) != PLUGIN_API_VERSION or not callable(
        getattr(module, "invoke", None)
    ):
        raise ValueError(f"{plugin['name']}: incompatible entrypoint contract")
    return module


def invoke_plugin(
    profile_path: Path,
    name: str,
    operation: str,
    payload: dict[str, Any],
    *,
    state_path: Path | None = None,
    root: Path = PLUGIN_ROOT,
) -> dict[str, Any]:
    plugin = _plugin_by_name(name, root)
    profile = load_profile(profile_path)
    if not plugin_enabled(plugin, profile):
        raise ValueError(f"plugin is disabled: {name}")
    if operation not in plugin["operations"]:
        raise ValueError(f"unsupported operation for {name}: {operation}")
    state = state_path or Path(str(plugin["default_state"])).expanduser()
    result = _load_entrypoint(plugin).invoke(operation, payload, state)
    return {"plugin": name, "operation": operation, "result": result}


def _read_payload(path: Path | None) -> dict[str, Any]:
    if path:
        value = json.loads(path.read_text(encoding="utf-8"))
    elif sys.stdin.isatty():
        value = {}
    else:
        raw = sys.stdin.read().strip()
        value = json.loads(raw) if raw else {}
    if not isinstance(value, dict):
        raise ValueError("plugin payload must be a JSON object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=default_profile_path())
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list")
    for command in ("enable", "disable"):
        item = subparsers.add_parser(command)
        item.add_argument("name")
    invoke = subparsers.add_parser("invoke")
    invoke.add_argument("name")
    invoke.add_argument("operation")
    invoke.add_argument("--input", type=Path, help="JSON payload file; defaults to stdin")
    invoke.add_argument("--state", type=Path, help="Override the plugin's local state path")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    try:
        if args.command == "list":
            result: Any = {"plugins": plugin_status(args.profile)}
        elif args.command in {"enable", "disable"}:
            result = set_plugin_enabled(args.profile, args.name, args.command == "enable")
        else:
            result = invoke_plugin(
                args.profile,
                args.name,
                args.operation,
                _read_payload(args.input),
                state_path=args.state,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
