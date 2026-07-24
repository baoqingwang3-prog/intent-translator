#!/usr/bin/env python3
"""Verify package, Skill, and repository release versions agree."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_version() -> str:
    return (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()


def pyproject_version() -> str:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise ValueError("pyproject.toml project version not found")
    return match.group(1)


def check_versions(tag: str = "") -> list[str]:
    init_text = (REPO_ROOT / "src" / "intent_translator_mcp" / "__init__.py").read_text(encoding="utf-8")
    init_match = re.search(r'^__version__\s*=\s*"([^"]+)"', init_text, re.MULTILINE)
    versions = {
        "VERSION": read_version(),
        "Skill VERSION": (REPO_ROOT / "skills" / "intent-translator" / "VERSION").read_text(encoding="utf-8").strip(),
        "pyproject": pyproject_version(),
        "package __version__": init_match.group(1) if init_match else "<missing>",
    }
    errors = []
    if len(set(versions.values())) != 1:
        errors.append("version files disagree: " + ", ".join(f"{key}={value}" for key, value in versions.items()))
    if tag and tag.startswith("v") and tag[1:] != versions["VERSION"]:
        errors.append(f"tag {tag} does not match version {versions['VERSION']}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    errors = check_versions(args.tag)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 2
    print(f"release metadata matches {read_version()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
