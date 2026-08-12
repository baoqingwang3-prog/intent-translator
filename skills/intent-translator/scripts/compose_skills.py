#!/usr/bin/env python3
"""Plan and validate a small staged composition of installed Agent Skills."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from discover_skills import default_roots, discover_skills


SEARCH_ROUTES = ("agent-reach", "smart-search", "anysearch", "global-search")
SEARCH_FAMILY = set(SEARCH_ROUTES)
FORMAT_FAMILY = {"docx", "pdf", "pptx", "xlsx"}
STUDY_CHILDREN = {
    "study-teach",
    "study-quiz",
    "study-feynman",
    "study-mindmap",
    "study-img",
}


def has(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def first_available(available: set[str], *names: str) -> str | None:
    return next((name for name in names if name in available), None)


def add_unique(items: list[str], skill: str | None) -> None:
    if skill and skill not in items:
        items.append(skill)


def infer_primary(text: str, available: set[str]) -> tuple[str | None, str]:
    rules: list[tuple[tuple[str, ...], tuple[str, ...], str]] = [
        ((r"(?:找|查|搜索|有没有|安装).{0,8}(?:技能|skill)", r"(?:技能|skill).{0,8}(?:查找|搜索|安装)"), ("skill-lookup",), "find or install a Skill"),
        ((r"(?:创建|新建|更新|修改|优化|重构|开发|制作|缝合).{0,16}(?:技能|skill|intent[ -]?translator)", r"(?:技能|skill|intent[ -]?translator).{0,16}(?:创建|更新|修改|优化|重构|开发|缝合)"), ("skill-creator",), "create or update a Skill"),
        ((r"bug", r"debug", r"报错", r"故障", r"失败", r"变慢", r"\b[45]\d\d\b", r"修复"), ("diagnosing-bugs",), "diagnose a defect"),
        ((r"代码审查", r"code review", r"review.*(?:diff|pr|branch)"), ("code-review",), "review a code change"),
        ((r"泄露", r"密钥", r"secret", r"credential"), ("security-secret-audit",), "audit secrets"),
        ((r"考研", r"复习", r"学习", r"出题", r"讲解", r"费曼"), ("study-assistant",), "orchestrate study"),
        ((r"求职", r"职位", r"岗位", r"招聘", r"job"), ("job-market-radar", "career-ops"), "handle a job workflow"),
        ((r"知识库", r"整理笔记", r"organize notes"), ("knowledge-base-organizer",), "organize knowledge"),
        ((r"架构", r"模块边界", r"domain model", r"领域模型"), ("codebase-design", "domain-modeling"), "design code or domain boundaries"),
        ((r"调研", r"搜索", r"搜一下", r"搜搜", r"全网搜", r"查找", r"查一下", r"research", r"search", r"https?://"), ("agent-reach", "smart-search", "anysearch"), "retrieve external information"),
        ((r"\.?docx(?:\s|$|[，。；：,.!?])", r"word 文档", r"word document"), ("docx",), "work with a Word document"),
        ((r"\.?pdf(?:\s|$|[，。；：,.!?])",), ("pdf",), "work with a PDF"),
        ((r"\.?pptx?(?:\s|$|[，。；：,.!?])", r"幻灯片", r"演示文稿"), ("pptx",), "work with slides"),
        ((r"\.?xlsx?(?:\s|$|[，。；：,.!?])", r"\.?csv(?:\s|$|[，。；：,.!?])", r"电子表格"), ("xlsx",), "work with a spreadsheet"),
        ((r"图片", r"图像", r"信息图", r"流程图", r"diagram"), ("baoyu-infographic", "imagegen", "excalidraw-diagram"), "create a visual artifact"),
    ]
    for triggers, candidates, reason in rules:
        if has(text, *triggers):
            chosen = first_available(available, *candidates)
            if chosen:
                return chosen, reason
    return None, "no high-confidence primary route"


def plan_composition(
    utterance: str,
    context: str,
    registry: dict[str, Any],
    requested_primary: str | None = None,
) -> dict[str, Any]:
    text = f"{utterance}\n{context}".strip()
    records = {item["name"]: item for item in registry.get("skills", [])}
    available = set(records)
    warnings: list[str] = []
    missing: list[str] = []
    pre: list[str] = []
    post: list[str] = []
    fallbacks: list[str] = []
    suppressed: list[dict[str, str]] = []

    if requested_primary:
        primary = requested_primary if requested_primary in available else None
        reason = "explicit primary Skill"
        if primary is None:
            missing.append(requested_primary)
    else:
        primary, reason = infer_primary(text, available)

    if primary in SEARCH_FAMILY:
        if has(text, r"https?://", r"网页", r"文章"):
            add_unique(post, first_available(available, "defuddle"))
        if has(text, r"深度", r"系统综述", r"文献综述", r"严谨", r"fact.?check"):
            add_unique(post, first_available(available, "deep-research", "research"))
        elif has(text, r"调研", r"research", r"搜一下", r"搜搜", r"全网搜", r"搜索") and has(text, r"报告", r"简报", r"文档", r"report"):
            add_unique(post, first_available(available, "research", "deep-research"))
        for candidate in SEARCH_ROUTES:
            if candidate != primary and candidate in available:
                add_unique(fallbacks, candidate)
                break

    if primary in {"research", "deep-research", "scientific-critical-thinking"} and has(
        text, r"最新", r"当前", r"实时", r"网络", r"来源", r"文献", r"论文"
    ):
        add_unique(pre, first_available(available, "agent-reach", "smart-search", "anysearch"))

    mentioned_formats = [
        name
        for name in ("docx", "pdf", "pptx", "xlsx")
        if has(text, rf"\.?{name}(?:\s|$|[，。；：,.!?])")
    ]
    if primary in SEARCH_FAMILY:
        for name in mentioned_formats:
            add_unique(post, name if name in available else None)
    if primary == "doc-coauthoring":
        for name in mentioned_formats:
            add_unique(post, name if name in available else None)
    elif primary in FORMAT_FAMILY and has(text, r"起草", r"撰写", r"方案", r"报告", r"proposal", r"spec"):
        add_unique(pre, first_available(available, "doc-coauthoring"))

    if primary == "study-assistant":
        explicit_children = []
        child_rules = [
            ((r"图片", r"扫描", r"手写", r"截图"), "study-img"),
            ((r"出题", r"测验", r"模拟卷", r"错题"), "study-quiz"),
            ((r"费曼", r"掌握程度"), "study-feynman"),
            ((r"思维导图", r"知识图谱"), "study-mindmap"),
            ((r"讲解", r"讲义", r"没看懂"), "study-teach"),
        ]
        for triggers, child in child_rules:
            if has(text, *triggers) and child in available:
                explicit_children.append(child)
        if len(explicit_children) == 1:
            add_unique(post, explicit_children[0])
        elif len(explicit_children) > 1:
            warnings.append("study-assistant should sequence its own child Skills; do not invoke all children at once")

    if primary == "diagnosing-bugs":
        if has(text, r"修复", r"fix", r"改好", r"解决"):
            add_unique(post, first_available(available, "tdd"))
        add_unique(post, first_available(available, "code-review"))

    if primary in {"tdd", "prototype", "codebase-design", "domain-modeling"} and has(
        text, r"实现", r"修改", r"构建", r"build", r"refactor"
    ):
        add_unique(post, first_available(available, "code-review"))

    if primary == "skill-creator":
        add_unique(pre, first_available(available, "skill-lookup") if has(text, r"找.*技能", r"有没有.*技能") else None)
        add_unique(post, first_available(available, "skill-refactor"))

    if primary == "knowledge-base-organizer" and has(text, r"obsidian", r"笔记", r"vault"):
        add_unique(post, first_available(available, "obsidian-cli"))

    if primary == "job-market-radar":
        add_unique(pre, first_available(available, "agent-reach"))
        if has(text, r"简历", r"投递", r"面试", r"offer", r"jd"):
            add_unique(post, first_available(available, "career-ops"))

    if primary in SEARCH_FAMILY:
        for stage_name, stage in (("pre", pre), ("post", post)):
            for name in list(stage):
                if name in SEARCH_FAMILY:
                    stage.remove(name)
                    suppressed.append({"skill": name, "reason": f"duplicate search owner in {stage_name} stage"})
    if primary == "study-assistant" and len([name for name in post if name in STUDY_CHILDREN]) > 1:
        keep = next(name for name in post if name in STUDY_CHILDREN)
        for name in list(post):
            if name in STUDY_CHILDREN and name != keep:
                post.remove(name)
                suppressed.append({"skill": name, "reason": "study orchestrator sequences child Skills"})

    for stage in (pre, post, fallbacks):
        if primary in stage:
            stage.remove(primary)

    if primary is None:
        warnings.append("No primary Skill selected; use the ExecutionEnvelope and generic host workflow")

    return {
        "schema_version": 1,
        "objective": utterance,
        "primary_skill": primary,
        "primary_reason": reason,
        "pre_skills": pre,
        "post_skills": post,
        "fallback_skills": fallbacks,
        "suppressed": suppressed,
        "missing_skills": missing,
        "warnings": warnings,
        "composition_size": (1 if primary else 0) + len(pre) + len(post),
        "available_skill_count": len(available),
    }


def load_registry(path: Path | None, roots: Iterable[Path] | None) -> dict[str, Any]:
    if path:
        return json.loads(path.read_text(encoding="utf-8"))
    return discover_skills(roots or default_roots())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--utterance", required=True)
    parser.add_argument("--context", default="")
    parser.add_argument("--primary")
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--root", action="append", type=Path)
    parser.add_argument("--compact", action="store_true")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    result = plan_composition(
        args.utterance,
        args.context,
        load_registry(args.registry, args.root),
        requested_primary=args.primary,
    )
    print(json.dumps(result, ensure_ascii=False, indent=None if args.compact else 2))
    return 2 if result["missing_skills"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
