#!/usr/bin/env python3
"""Audit generic defaults for creator-profile leakage."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from init_profile import default_profile


DEFAULT_PROFILE_FORBIDDEN = {
    "creator_name": ("BBG",),
    "exam_goal": ("考研", "雅思"),
    "personality_label": ("ENTP",),
    "pressure_style": ("PUA",),
    "private_path": ("C:\\Users\\", "D:\\测试"),
}
GENERIC_CORE_FORBIDDEN = {
    "creator_metaphor": ("妙招", "小学老师"),
    "creator_name": ("BBG",),
    "private_path": ("C:\\Users\\BBG", "D:\\测试\\测试"),
}


def audit_repository(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    findings: list[dict[str, Any]] = []
    profile_text = json.dumps(default_profile(), ensure_ascii=False, sort_keys=True)
    indicator_count = 0
    for rule, terms in DEFAULT_PROFILE_FORBIDDEN.items():
        for term in terms:
            indicator_count += 1
            if term.casefold() in profile_text.casefold():
                findings.append({"scope": "default-profile", "rule": rule, "indicator": term})

    core_path = repo_root / "src" / "intent_translator_mcp" / "core.py"
    core_text = core_path.read_text(encoding="utf-8")
    for rule, terms in GENERIC_CORE_FORBIDDEN.items():
        for term in terms:
            indicator_count += 1
            if term.casefold() in core_text.casefold():
                findings.append({"scope": "generic-core", "rule": rule, "indicator": term})

    absolute_path_pattern = re.compile(r"(?i)(?:[A-Z]:\\Users\\[^\\\s]+|/home/[^/\s]+)")
    indicator_count += 1
    for path in (
        core_path,
        repo_root / "skills" / "intent-translator" / "scripts" / "init_profile.py",
    ):
        if absolute_path_pattern.search(path.read_text(encoding="utf-8")):
            findings.append({"scope": "generic-default", "rule": "absolute-user-path", "file": str(path.relative_to(repo_root))})

    install_text = (repo_root / "install.ps1").read_text(encoding="utf-8")
    indicator_count += 1
    if "apply-pack" in install_text:
        findings.append({"scope": "clean-install", "rule": "optional-pack-auto-applied", "file": "install.ps1"})

    rate = len(findings) / indicator_count if indicator_count else 0.0
    return {
        "schema_version": 1,
        "default_user_contamination_rate": round(rate, 6),
        "creator_shadow_leakage": len(findings),
        "indicator_count": indicator_count,
        "findings": findings,
        "optional_scope_policy": "Profile packs, labeled evals, and user-confirmed onboarding are excluded from generic defaults.",
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
    args = parser.parse_args()
    report = audit_repository(args.repo)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["findings"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
