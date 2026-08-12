#!/usr/bin/env python3
"""Discover installed Agent Skills without external dependencies."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable


KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):(?:\s*(.*))?$")
IGNORED_DIRECTORY_PREFIXES = (".backup", ".backups", ".archive", ".retired")


def ignored_skill_path(skill_md: Path, root: Path) -> bool:
    try:
        relative = skill_md.relative_to(root)
    except ValueError:
        return False
    return any(
        part.casefold().startswith(IGNORED_DIRECTORY_PREFIXES)
        for part in relative.parts[:-1]
    )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decode_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value[0:1] in {"'", '"'} and value[-1:] == value[0]:
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1]
    return value


def parse_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing YAML frontmatter")

    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration as exc:
        raise ValueError("unterminated YAML frontmatter") from exc

    frontmatter = lines[1:end]
    result: dict[str, Any] = {}
    index = 0
    while index < len(frontmatter):
        line = frontmatter[index]
        match = KEY_RE.match(line)
        if not match:
            index += 1
            continue

        key, raw_value = match.group(1), (match.group(2) or "")
        if raw_value in {">", ">-", ">+", "|", "|-", "|+"}:
            block: list[str] = []
            index += 1
            while index < len(frontmatter):
                candidate = frontmatter[index]
                if candidate and not candidate[0].isspace() and KEY_RE.match(candidate):
                    index -= 1
                    break
                block.append(candidate.strip())
                index += 1
            if raw_value.startswith(">"):
                result[key] = " ".join(part for part in block if part)
            else:
                result[key] = "\n".join(block).strip()
        else:
            result[key] = _decode_scalar(raw_value)
        index += 1

    return result


def default_roots(
    cwd: Path | None = None,
    home: Path | None = None,
    env: dict[str, str] | None = None,
) -> list[Path]:
    cwd = cwd or Path.cwd()
    home = home or Path.home()
    env = dict(os.environ if env is None else env)
    codex_home = Path(env.get("CODEX_HOME", home / ".codex"))
    claude_home = Path(env.get("CLAUDE_CONFIG_DIR", home / ".claude"))
    local_app_data = Path(env.get("LOCALAPPDATA", home / "AppData" / "Local"))
    opencode_home = (
        local_app_data / "opencode"
        if os.name == "nt"
        else Path(env.get("XDG_CONFIG_HOME", home / ".config")) / "opencode"
    )
    configured = [Path(item) for item in env.get("INTENT_TRANSLATOR_SKILL_ROOTS", "").split(os.pathsep) if item]
    candidates = configured + [
        codex_home / "skills",
        claude_home / "skills",
        home / ".cursor" / "skills",
        home / ".gemini" / "skills",
        home / ".copilot" / "skills",
        opencode_home / "skills",
        home / ".agents" / "skills",
        cwd / ".codex" / "skills",
        cwd / ".claude" / "skills",
        cwd / ".cursor" / "skills",
        cwd / ".gemini" / "skills",
        cwd / ".github" / "skills",
        cwd / ".opencode" / "skills",
        cwd / ".agents" / "skills",
    ]
    seen: set[str] = set()
    roots: list[Path] = []
    for candidate in candidates:
        resolved = str(candidate.expanduser().resolve())
        if resolved not in seen:
            seen.add(resolved)
            roots.append(Path(resolved))
    return roots


def discover_skills(roots: Iterable[Path]) -> dict[str, Any]:
    root_list = [Path(root).expanduser().resolve() for root in roots]
    selected: dict[str, dict[str, Any]] = {}
    duplicates: dict[str, list[dict[str, str]]] = {}
    errors: list[dict[str, str]] = []

    for precedence, root in enumerate(root_list):
        if not root.exists():
            continue
        for skill_md in sorted(root.rglob("SKILL.md"), key=lambda item: str(item).lower()):
            if ignored_skill_path(skill_md, root):
                continue
            try:
                metadata = parse_frontmatter(skill_md)
                name = str(metadata.get("name", "")).strip()
                description = str(metadata.get("description", "")).strip()
                if not name or not description:
                    raise ValueError("frontmatter requires name and description")
                record = {
                    "name": name,
                    "description": description,
                    "path": str(skill_md.parent.resolve()),
                    "source_root": str(root),
                    "precedence": precedence,
                    "model_invoked": not bool(metadata.get("disable-model-invocation", False)),
                    "skill_md": str(skill_md.resolve()),
                    "sha256": file_sha256(skill_md),
                }
                if name not in selected:
                    selected[name] = record
                else:
                    duplicates.setdefault(name, []).append(
                        {"path": record["path"], "source_root": record["source_root"]}
                    )
            except (OSError, UnicodeError, ValueError) as exc:
                errors.append({"path": str(skill_md), "error": str(exc)})

    return {
        "schema_version": 2,
        "roots": [str(root) for root in root_list],
        "skills": sorted(selected.values(), key=lambda item: item["name"].lower()),
        "duplicates": [
            {"name": name, "alternates": alternates}
            for name, alternates in sorted(duplicates.items())
        ],
        "errors": errors,
        "summary": {
            "selected": len(selected),
            "duplicate_names": len(duplicates),
            "errors": len(errors),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", type=Path, help="Skill root; repeat for precedence")
    parser.add_argument("--output", type=Path, help="Write registry JSON to this path")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    registry = discover_skills(args.root or default_roots())
    payload = json.dumps(
        registry,
        ensure_ascii=False,
        indent=None if args.compact else 2,
        sort_keys=False,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
