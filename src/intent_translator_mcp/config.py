"""Generate host-specific MCP configuration without mutating host settings."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .host_paths import HOSTS, default_skill_dir


def server_spec(command: str, skill_dir: str | None = None, host: str = "unspecified") -> dict[str, Any]:
    env = {
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "INTENT_TRANSLATOR_HOST": host,
    }
    if skill_dir:
        env["INTENT_TRANSLATOR_SKILL_DIR"] = skill_dir
    result: dict[str, Any] = {"command": command, "args": []}
    if env:
        result["env"] = env
    return result


def generate_config(host: str, command: str, skill_dir: str | None = None) -> str:
    if host not in HOSTS:
        raise ValueError(f"unsupported host: {host}")
    spec = server_spec(command, skill_dir, host)
    if host == "codex":
        lines = [
            '[mcp_servers.intent-translator]',
            f'command = {json.dumps(command, ensure_ascii=False)}',
            'args = []',
        ]
        lines.extend(
            [
                '[mcp_servers.intent-translator.env]',
                'PYTHONUTF8 = "1"',
                'PYTHONIOENCODING = "utf-8"',
                f'INTENT_TRANSLATOR_HOST = {json.dumps(host)}',
            ]
        )
        if skill_dir:
            lines.append(
                f'INTENT_TRANSLATOR_SKILL_DIR = {json.dumps(skill_dir, ensure_ascii=False)}'
            )
        return "\n".join(lines) + "\n"
    if host in {"claude", "cursor", "copilot"}:
        return json.dumps(
            {"mcpServers": {"intent-translator": spec}}, ensure_ascii=False, indent=2
        ) + "\n"
    if host == "gemini":
        return json.dumps(
            {"mcpServers": {"intent-translator": spec}}, ensure_ascii=False, indent=2
        ) + "\n"
    return json.dumps(
        {"mcp": {"intent-translator": {"type": "local", **spec}}},
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=HOSTS + ("all",), default="all")
    parser.add_argument("--command", default=os.environ.get("INTENT_TRANSLATOR_MCP_COMMAND", "intent-translator-mcp"))
    parser.add_argument("--skill-dir")
    parser.add_argument("--home", type=Path, help="Home directory used to derive host-specific Skill paths")
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
            skill_dir = args.skill_dir or str(default_skill_dir(host, home=args.home))
            path.write_text(generate_config(host, args.command, skill_dir), encoding="utf-8")
            outputs[host] = str(path.resolve())
        print(json.dumps(outputs, ensure_ascii=False, indent=2))
    else:
        for host in hosts:
            skill_dir = args.skill_dir or str(default_skill_dir(host, home=args.home))
            print(f"# {host}\n{generate_config(host, args.command, skill_dir)}", end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
