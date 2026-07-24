#!/usr/bin/env python3
"""Build concise decision receipts without exposing hidden reasoning."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


FORBIDDEN_KEYS = {
    "analysis",
    "chain_of_thought",
    "hidden_reasoning",
    "internal_monologue",
    "reasoning_trace",
    "scratchpad",
}


def compact_text(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def safe_reference(item: dict[str, Any]) -> dict[str, Any]:
    result = {"id": item.get("id"), "summary": compact_text(item.get("summary") or item.get("text"))}
    if item.get("scope"):
        result["scope"] = compact_text(item["scope"], 60)
    if item.get("stale"):
        result["stale"] = True
    governance = item.get("governance") or {}
    if governance.get("requires_clarification"):
        result["conflict"] = True
    return result


def build_receipt(envelope: dict[str, Any]) -> dict[str, Any]:
    """Project an execution envelope into auditable, user-safe evidence."""
    understood_as = compact_text(
        envelope.get("understood_as") or envelope.get("normalized_goal") or envelope.get("goal")
    )
    routing = envelope.get("routing") if isinstance(envelope.get("routing"), dict) else {}
    selected_skill = envelope.get("selected_skill") or routing.get("primary_skill")
    route_reason = compact_text(
        envelope.get("route_reason")
        or routing.get("reason")
        or ("matched the installed Skill registry" if selected_skill else "no specialized Skill required")
    )
    memories = envelope.get("memories") or envelope.get("memory_refs") or []
    corrections = envelope.get("corrections") or envelope.get("correction_refs") or []
    risk = envelope.get("risk") if isinstance(envelope.get("risk"), dict) else {}
    confirmation_required = bool(
        envelope.get("confirmation_required")
        or envelope.get("clarification_required")
        or risk.get("confirmation_required")
    )
    reasons = envelope.get("confirmation_reasons") or risk.get("reasons") or []
    receipt = {
        "understood_as": understood_as,
        "mode": compact_text(envelope.get("mode"), 40),
        "used_memory": [safe_reference(item) for item in memories if isinstance(item, dict)][:5],
        "applied_corrections": [safe_reference(item) for item in corrections if isinstance(item, dict)][:5],
        "selected_skill": compact_text(selected_skill, 80) if selected_skill else None,
        "route_reason": route_reason,
        "confirmation_required": confirmation_required,
        "confirmation_reasons": [compact_text(item, 140) for item in reasons][:5],
    }
    receipt["summary"] = render_summary(receipt)
    return receipt


def render_summary(receipt: dict[str, Any]) -> str:
    parts = [f"我理解为：{receipt['understood_as'] or '按当前明确任务继续'}"]
    if receipt.get("used_memory"):
        ids = ", ".join(str(item.get("id")) for item in receipt["used_memory"])
        parts.append(f"参考记忆：{ids}")
    if receipt.get("selected_skill"):
        parts.append(f"调用：{receipt['selected_skill']}")
    if receipt.get("confirmation_required"):
        parts.append("需要确认后再执行高影响部分")
    return "；".join(parts) + "。"


def assert_no_hidden_reasoning(value: Any) -> None:
    if isinstance(value, dict):
        forbidden = FORBIDDEN_KEYS & {str(key).casefold() for key in value}
        if forbidden:
            raise ValueError("decision receipt contains forbidden internal reasoning fields")
        for nested in value.values():
            assert_no_hidden_reasoning(nested)
    elif isinstance(value, list):
        for nested in value:
            assert_no_hidden_reasoning(nested)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Execution envelope JSON; defaults to stdin")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    raw = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
    try:
        envelope = json.loads(raw)
        if not isinstance(envelope, dict):
            raise ValueError("input must be a JSON object")
        receipt = build_receipt(envelope)
        assert_no_hidden_reasoning(receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0
    except (json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
