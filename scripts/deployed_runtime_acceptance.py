#!/usr/bin/env python3
"""Exercise an installed intent-translator MCP over a fresh stdio process."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run(command: Path, skill_dir: Path) -> dict[str, object]:
    env = dict(os.environ)
    env.update(
        {
            "INTENT_TRANSLATOR_HOST": "codex",
            "INTENT_TRANSLATOR_SKILL_DIR": str(skill_dir),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    params = StdioServerParameters(command=str(command), args=[], env=env)
    pending_action = (
        "安装第一批学习与安全工具：Zotero、Anki、SumatraPDF、Bitwarden；"
        "仅这四项，使用官方 winget 来源，串行安装，支持自定义路径时优先 D 盘，"
        "逐项验证版本和实际路径；不安装其他应用，不删除现有软件。"
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            first = await session.call_tool(
                "intent_compile",
                {
                    "request": {
                        "utterance": "继续",
                        "pending_action": pending_action,
                        "semantic_mode": "off",
                        "include_prompt": False,
                    }
                },
            )
            challenge = first.structuredContent["risk"]["confirmation_challenge"]
            second = await session.call_tool(
                "intent_compile",
                {
                    "request": {
                        "utterance": "继续",
                        "pending_action": pending_action,
                        "confirmation_receipt": challenge["receipt"],
                        "semantic_mode": "off",
                        "include_prompt": False,
                    }
                },
            )
            route = await session.call_tool(
                "intent_compile",
                {
                    "request": {
                        "utterance": "帮我批改雅思作文",
                        "semantic_mode": "off",
                        "include_prompt": False,
                    }
                },
            )

    before = first.structuredContent
    after = second.structuredContent
    routed = route.structuredContent
    return {
        "before_receipt": {
            "operation": before["intent_contract"]["operation"],
            "effect": before["intent_contract"]["effect"],
            "required_grants": before["intent_contract"]["authorization"]["required_grants"],
            "constraint_types": sorted(item["type"] for item in before["constraints"]),
        },
        "after_receipt": {
            "operation": after["intent_contract"]["operation"],
            "effect": after["intent_contract"]["effect"],
            "required_grants": after["intent_contract"]["authorization"]["required_grants"],
            "receipt_verified": after["risk"]["receipt_verified"],
            "execute": after["completion_contract"]["execute"],
        },
        "route": routed["routing"]["primary_skill"],
        "runtime": after["runtime_status"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", type=Path, required=True)
    parser.add_argument("--skill-dir", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run(args.command.resolve(), args.skill_dir.resolve()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    expected = (
        result["before_receipt"]["operation"] == "install"
        and result["before_receipt"]["effect"] == "system_change"
        and result["before_receipt"]["required_grants"] == ["install"]
        and "prohibited-action" in result["before_receipt"]["constraint_types"]
        and result["after_receipt"]["receipt_verified"] is True
        and result["after_receipt"]["execute"] is True
        and result["route"] == "ielts-writing"
    )
    return 0 if expected else 2


if __name__ == "__main__":
    raise SystemExit(main())
