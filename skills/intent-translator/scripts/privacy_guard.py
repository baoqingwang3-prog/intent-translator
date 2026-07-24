#!/usr/bin/env python3
"""Scan or redact obvious secrets and personal identifiers before external egress."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "private_key",
        "critical",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    ),
    ("github_token", "critical", re.compile(r"\b(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b")),
    ("openai_token", "critical", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("aws_access_key", "critical", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("jwt", "critical", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")),
    (
        "assigned_secret",
        "critical",
        re.compile(
            r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*"
            r"['\"][A-Za-z0-9_./+\-=]{12,}['\"]"
        ),
    ),
    ("email", "personal", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("cn_phone", "personal", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("international_phone", "personal", re.compile(r"(?<!\w)\+\d[\d ()-]{8,}\d(?!\w)")),
    ("ipv4", "personal", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("payment_card", "critical", re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")),
]


def masked_example(value: str) -> str:
    compact = value.replace("\n", " ")
    if len(compact) <= 8:
        return "[masked]"
    return f"{compact[:3]}...{compact[-2:]}"


def scan_text(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for category, severity, pattern in PATTERNS:
        matches = list(pattern.finditer(text))
        if matches:
            findings.append(
                {
                    "category": category,
                    "severity": severity,
                    "count": len(matches),
                    "example": masked_example(matches[0].group(0)),
                }
            )
    return findings


def redact_text(text: str) -> str:
    redacted = text
    for category, _, pattern in PATTERNS:
        redacted = pattern.sub(f"[REDACTED:{category.upper()}]", redacted)
    return redacted


def inspect_text(text: str, *, include_redacted: bool = False) -> dict[str, Any]:
    findings = scan_text(text)
    result: dict[str, Any] = {
        "safe_to_send": not findings,
        "requires_review": bool(findings),
        "finding_count": sum(int(item["count"]) for item in findings),
        "findings": findings,
    }
    if include_redacted:
        redacted = redact_text(text)
        result["redacted_text"] = redacted
        result["redacted_safe_to_send"] = not scan_text(redacted)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Read UTF-8 text from a file; defaults to stdin")
    parser.add_argument("--output", type=Path, help="Write the JSON report to a file")
    parser.add_argument("--redact", action="store_true", help="Include redacted text in the report")
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--fail-on-findings", action="store_true")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    text = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
    result = inspect_text(text, include_redacted=args.redact)
    payload = json.dumps(result, ensure_ascii=False, indent=None if args.compact else 2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    if args.fail_on_findings and result["requires_review"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
