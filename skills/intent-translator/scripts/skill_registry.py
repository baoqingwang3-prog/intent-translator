#!/usr/bin/env python3
"""Build and query compact JSON and Markdown registries from installed SKILL.md files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from discover_skills import default_roots, discover_skills


LATIN_TOKEN_RE = re.compile(r"[A-Za-z0-9_+-]+")
CJK_TOKEN_RE = re.compile(r"[\u3400-\u9fff]+")
CONCEPT_ALIASES = {
    "diagnose": ("诊断", "排查", "故障", "错误", "bug", "debug", "regression", "回归"),
    "search": ("搜索", "查找", "检索", "search", "research", "lookup"),
    "study": ("学习", "备考", "复习", "study", "exam", "quiz"),
    "document": ("文档", "文件", "word", "docx", "pdf", "document"),
    "skill": ("技能", "skill", "skills", "能力"),
}


def tokens(text: str) -> set[str]:
    lowered = text.casefold()
    result: set[str] = set()
    for token in LATIN_TOKEN_RE.findall(lowered):
        result.add(token)
        result.update(part for part in re.split(r"[_+-]+", token) if part)
    for chunk in CJK_TOKEN_RE.findall(lowered):
        result.add(chunk)
        if len(chunk) > 1:
            result.update(chunk[index : index + 2] for index in range(len(chunk) - 1))
    for concept, aliases in CONCEPT_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            result.add(concept)
    return result


def search_registry(registry: dict[str, Any], query: str, limit: int = 10) -> list[dict[str, Any]]:
    query_tokens = tokens(query)
    if not query_tokens:
        return []
    ranked = []
    for skill in registry.get("skills", []):
        name_tokens = tokens(str(skill.get("name", "")))
        description_tokens = tokens(str(skill.get("description", "")))
        overlap = len(query_tokens & description_tokens)
        name_overlap = len(query_tokens & name_tokens)
        if not overlap and not name_overlap:
            continue
        concept_overlap = len(set(CONCEPT_ALIASES) & query_tokens & (name_tokens | description_tokens))
        score = name_overlap * 20 + concept_overlap * 12 + overlap * 5 + int(bool(skill.get("model_invoked")))
        if score >= 10:
            ranked.append((score, str(skill.get("name", "")), skill))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [{**item[2], "score": item[0]} for item in ranked[: max(1, limit)]]


def render_markdown(registry: dict[str, Any]) -> str:
    """Render the lightweight capability map; keep full Skill bodies at their source paths."""
    lines = [
        "# Local Skill Capability Map",
        "",
        "> Generated from installed `SKILL.md` files. Use this as an index; read the matched source file only when executing that capability.",
        "",
        "## Skills",
        "",
        "| Skill | Description | Invocation | Source | SHA-256 |",
        "|---|---|---|---|---|",
    ]
    for skill in registry.get("skills", []):
        name = str(skill.get("name", "")).replace("|", "\\|")
        description = " ".join(str(skill.get("description", "")).split()).replace("|", "\\|")
        invocation = "model" if skill.get("model_invoked") else "user"
        source = str(skill.get("skill_md", "")).replace("\\", "/").replace("|", "\\|")
        digest = str(skill.get("sha256", ""))[:12]
        lines.append(f"| `{name}` | {description} | {invocation} | `{source}` | `{digest}` |")

    lines.extend(["", "## Duplicate Names", ""])
    duplicates = registry.get("duplicates", [])
    if duplicates:
        for duplicate in duplicates:
            paths = ", ".join(
                f"`{str(item.get('path', '')).replace(chr(92), '/')}`"
                for item in duplicate.get("alternates", [])
            )
            lines.append(f"- `{duplicate.get('name', '')}`: {paths}")
    else:
        lines.append("- None.")

    lines.extend(["", "## Discovery Errors", ""])
    errors = registry.get("errors", [])
    if errors:
        for error in errors:
            lines.append(f"- `{error.get('path', '')}`: {error.get('error', '')}")
    else:
        lines.append("- None.")
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", type=Path)
    parser.add_argument("--registry", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--markdown-output", type=Path)
    query = subparsers.add_parser("query")
    query.add_argument("--text", required=True)
    query.add_argument("--limit", type=int, default=10)
    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--name", required=True)
    return parser


def load_registry(path: Path | None, roots: list[Path] | None) -> dict[str, Any]:
    if path:
        return json.loads(path.read_text(encoding="utf-8"))
    return discover_skills(roots or default_roots())


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    registry = load_registry(args.registry, args.root)
    if args.command == "build":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        markdown_output = args.markdown_output or args.output.with_suffix(".md")
        markdown_output.parent.mkdir(parents=True, exist_ok=True)
        markdown_output.write_text(render_markdown(registry), encoding="utf-8")
        result: Any = {
            "registry": str(args.output.resolve()),
            "catalog": str(markdown_output.resolve()),
            **registry.get("summary", {}),
        }
    elif args.command == "query":
        result = search_registry(registry, args.text, args.limit)
    else:
        matches = [skill for skill in registry.get("skills", []) if skill.get("name") == args.name]
        result = matches[0] if matches else {"error": f"Skill not found: {args.name}"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if "error" not in result else 2


if __name__ == "__main__":
    raise SystemExit(main())
