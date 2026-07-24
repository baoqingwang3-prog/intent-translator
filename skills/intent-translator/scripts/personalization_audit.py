#!/usr/bin/env python3
"""Audit generic defaults for creator-profile leakage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from init_profile import default_profile


DEFAULT_PROFILE_FORBIDDEN = {
    "exam_goal": ("考研", "雅思"),
    "personality_label": ("ENTP",),
    "pressure_style": ("PUA",),
    "private_path": ("C:\\Users\\", "D:\\测试"),
}
GENERIC_CORE_FORBIDDEN = {
    "creator_metaphor": ("妙招", "小学老师"),
    "private_path": ("D:\\测试\\测试",),
}
TEXT_SUFFIXES = {
    ".cfg", ".ini", ".json", ".jsonl", ".md", ".ps1", ".py", ".sh",
    ".toml", ".txt", ".yaml", ".yml",
}


def _tracked_text_files(repo_root: Path) -> list[Path]:
    try:
        relative_paths: list[str] = []
        for command in (
            ["git", "ls-files", "-z"],
            ["git", "ls-files", "-z", "--others", "--exclude-standard"],
        ):
            result = subprocess.run(command, cwd=repo_root, check=True, capture_output=True)
            relative_paths.extend(
                item for item in result.stdout.decode("utf-8", errors="strict").split("\0") if item
            )
        relative_paths = list(dict.fromkeys(relative_paths))
        return [repo_root / item for item in relative_paths if Path(item).suffix.casefold() in TEXT_SUFFIXES]
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return [
            path for path in repo_root.rglob("*")
            if path.is_file()
            and path.suffix.casefold() in TEXT_SUFFIXES
            and not any(part in {".git", ".venv", "work"} for part in path.parts)
        ]


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()[:12]


def audit_repository(repo_root: Path, *, private_terms: list[str] | None = None) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    private_terms = [term.strip() for term in (private_terms or []) if term.strip()]
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

    tracked_files = _tracked_text_files(repo_root)
    placeholder = r"(?!someone(?:[\\/])|example(?:[\\/])|user(?:[\\/])|username(?:[\\/]))"
    absolute_path_pattern = re.compile(
        rf"(?i)(?:[A-Z]:\\Users\\{placeholder}[A-Za-z0-9._-]+\\[^\s\"'<>]+|"
        rf"/home/{placeholder}[A-Za-z0-9._-]+/[^\s\"'<>]+|"
        rf"/Users/{placeholder}[A-Za-z0-9._-]+/[^\s\"'<>]+)"
    )
    indicator_count += len(tracked_files)
    for path in tracked_files:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        if absolute_path_pattern.search(text):
            findings.append(
                {"scope": "tracked-content", "rule": "absolute-user-path", "file": str(path.relative_to(repo_root))}
            )
        for term in private_terms:
            indicator_count += 1
            if term.casefold() in text.casefold():
                findings.append(
                    {
                        "scope": "tracked-content",
                        "rule": "private-term",
                        "file": str(path.relative_to(repo_root)),
                        "indicator_fingerprint": _fingerprint(term),
                    }
                )

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
        "tracked_text_files": len(tracked_files),
        "private_terms_checked": len(private_terms),
        "findings": findings,
        "optional_scope_policy": "Profile packs, labeled evals, and user-confirmed onboarding are excluded from generic defaults.",
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--private-term", action="append", default=[], help="Local-only term to scan without printing it")
    args = parser.parse_args()
    env_terms = [item for item in os.environ.get("INTENT_TRANSLATOR_AUDIT_PRIVATE_TERMS", "").split(os.pathsep) if item]
    report = audit_repository(args.repo, private_terms=[*args.private_term, *env_terms])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["findings"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
