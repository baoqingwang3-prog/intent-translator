"""Generate host-specific MCP configuration without mutating host settings."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


HOSTS = ("codex", "claude", "cursor", "gemini", "copilot", "opencode")


def server_spec(command: str, skill_dir: str | None = None) -> dict[str, Any]:
    env = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    if skill_dir:
        env["INTENT_TRANSLATOR_SKILL_DIR"] = skill_dir
    result: dict[str, Any] = {"command": command, "args": []}
    if env:
        result["env"] = env
    return result


def generate_config(host: str, command: str, skill_dir: str | None = None) -> str:
    if host not in HOSTS:
        raise ValueError(f"unsupported host: {host}")
    spec = server_spec(command, skill_dir)
    if host == "codex":
        lines = ['[mcp_servers.intent-translator]', f'command = {json.dumps(command)}', 'args = []']
        lines.extend(
            [
                '[mcp_servers.intent-translator.env]',
                'PYTHONUTF8 = "1"',
                'PYTHONIOENCODING = "utf-8"',
            ]
        )
        if skill_dir:
            lines.append(f'INTENT_TRANSLATOR_SKILL_DIR = {json.dumps(skill_dir)}')
        return "\n".join(lines) + "\n"
    if host in {"claude", "cursor", "copilot"}:
        return json.dumps({"mcpServers": {"intent-translator": spec}}, indent=2) + "\n"
    if host == "gemini":
        return json.dumps({"mcpServers": {"intent-translator": spec}}, indent=2) + "\n"
    return json.dumps({"mcp": {"intent-translator": {"type": "local", **spec}}}, indent=2) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=HOSTS + ("all",), default="all")
    parser.add_argument("--command", default=os.environ.get("INTENT_TRANSLATOR_MCP_COMMAND", "intent-translator-mcp"))
    parser.add_argument("--skill-dir")
    parser.add_argument("--output-dir", type=Path)
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    hosts = HOSTS if args.host == "all" else (args.host,)
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        outputs = {}
        for host in hosts:
            suffix = "toml" if host == "codex" else "json"
            path = args.output_dir / f"{host}-mcp.{suffix}"
            path.write_text(generate_config(host, args.command, args.skill_dir), encoding="utf-8")
            outputs[host] = str(path.resolve())
        print(json.dumps(outputs, ensure_ascii=False, indent=2))
    else:
        for host in hosts:
            print(f"# {host}\n{generate_config(host, args.command, args.skill_dir)}", end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
