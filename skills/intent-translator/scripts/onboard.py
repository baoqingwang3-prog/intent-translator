#!/usr/bin/env python3
"""Run a skippable, local-first three-question onboarding."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from init_profile import default_profile, default_profile_path, now_iso, validate_profile, write_profile


TEXT = {
    "zh-CN": {
        "generic": "当前是没有个人记忆的通用模式。可以直接使用，也可以用三分钟设置自己的习惯。",
        "configured": "已加载这台电脑上的本地设置。",
        "memory": "只在本机记住你明确确认的内容吗？[Y=是 / N=不记 / S=跳过] ",
        "interpretation": "一句话有多种重要理解时，先给候选选项吗？[Y=给选项 / N=直接问 / S=跳过] ",
        "tone": "回答风格：[1=简洁 / 2=适中 / 3=详细 / S=跳过] ",
        "sharp": "重要方案是否接受必要时更尖锐的审查？[y/N] ",
        "done": "设置完成，之后仍可随时用自然语言修改。",
    },
    "en": {
        "generic": "Generic mode is active with no personal memory. You can use it now or set your preferences in about three minutes.",
        "configured": "Local settings from this computer are loaded.",
        "memory": "Remember only content you explicitly confirm, stored locally? [Y=yes / N=off / S=skip] ",
        "interpretation": "When wording has multiple important meanings, show choices first? [Y=choices / N=ask / S=skip] ",
        "tone": "Answer style: [1=concise / 2=balanced / 3=detailed / S=skip] ",
        "sharp": "Allow sharper review for important proposals when useful? [y/N] ",
        "done": "Setup is complete. You can change these choices later in natural language.",
    },
}


def load_or_default(path: Path, language: str) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default_profile(language)


def apply_choices(
    path: Path,
    *,
    memory: str,
    interpretation: str,
    tone: str,
    sharp_review: str,
    language: str,
) -> dict[str, Any]:
    profile = load_or_default(path, language)
    if memory == "local":
        profile["memory"] = {
            "adapter": "sqlite",
            "location": "~/.intent-translator/memory.db",
            "local_only": True,
            "write_policy": "confirmed-only",
        }
    elif memory == "off":
        profile["memory"] = {"adapter": "none", "location": ""}
    profile["interpretation_preferences"] = {
        "material_ambiguity": {
            "choices": "show-choices",
            "ask": "ask",
            "skip": profile.get("interpretation_preferences", {}).get("material_ambiguity", "neutral"),
        }[interpretation],
        "natural_language_correction": True,
    }
    if tone != "skip":
        profile.setdefault("response_style", {})["verbosity"] = {
            "concise": "concise",
            "balanced": "adaptive",
            "detailed": "detailed",
        }[tone]
    if sharp_review != "skip":
        profile.setdefault("review_preferences", {})["sharp_review"] = sharp_review == "on"
    else:
        profile.setdefault("review_preferences", {}).setdefault("sharp_review", False)
    profile["onboarding"] = {
        "completed_at": now_iso(),
        "categories": ["memory", "interpretation", "tone"],
        "skipped_fields_allowed": True,
    }
    errors = validate_profile(profile)
    if errors:
        raise ValueError("invalid profile after onboarding: " + "; ".join(errors))
    write_profile(path, profile)
    return profile


def has_personalization(profile: dict[str, Any]) -> bool:
    if profile.get("phrase_mappings") or profile.get("cognitive_priors"):
        return True
    if profile.get("study", {}).get("enabled") or profile.get("student_life", {}).get("enabled"):
        return True
    interpretation = profile.get("interpretation_preferences", {})
    if interpretation.get("material_ambiguity", "neutral") != "neutral":
        return True
    review = profile.get("review_preferences", {})
    if review.get("sharp_review") or review.get("conditional_pua"):
        return True
    if profile.get("local_policy"):
        return True
    adaptation = profile.get("adaptation", {})
    if adaptation.get("domains") or adaptation.get("accessibility"):
        return True
    if profile.get("response_style", {}).get("verbosity", "adaptive") != "adaptive":
        return True
    memory = profile.get("memory", {})
    return memory.get("adapter") == "none" or memory.get("write_policy") == "confirmed-only"


def summary(profile: dict[str, Any]) -> dict[str, Any]:
    memory = profile.get("memory", {})
    memory_mode = (
        "off"
        if memory.get("adapter") == "none"
        else "local-confirmed-only"
        if memory.get("write_policy") == "confirmed-only"
        else "default-local"
    )
    return {
        "completed": True,
        "configured": has_personalization(profile),
        "memory": memory_mode,
        "interpretation": profile.get("interpretation_preferences", {}).get("material_ambiguity", "neutral"),
        "tone": profile.get("response_style", {}).get("verbosity", "adaptive"),
        "sharp_review": bool(profile.get("review_preferences", {}).get("sharp_review", False)),
        "local_only": memory.get("adapter") in {"none", "sqlite"},
    }


def status(path: Path, language: str) -> dict[str, Any]:
    strings = TEXT[language]
    exists = path.exists()
    profile = json.loads(path.read_text(encoding="utf-8")) if exists else {}
    personalized = has_personalization(profile)
    return {
        "mode": "local-profile" if personalized else "generic",
        "message": strings["configured"] if personalized else strings["generic"],
        "completed": bool(profile.get("onboarding", {}).get("completed_at")),
        "skippable": True,
        "questions": ["memory", "interpretation", "tone"],
    }


def interactive(path: Path, language: str) -> dict[str, Any]:
    strings = TEXT[language]
    print(status(path, language)["message"])
    memory_answer = input(strings["memory"]).strip().casefold()
    interpretation_answer = input(strings["interpretation"]).strip().casefold()
    tone_answer = input(strings["tone"]).strip().casefold()
    sharp_answer = input(strings["sharp"]).strip().casefold()
    profile = apply_choices(
        path,
        memory="off" if memory_answer == "n" else "skip" if memory_answer == "s" else "local",
        interpretation="ask" if interpretation_answer == "n" else "skip" if interpretation_answer == "s" else "choices",
        tone={"1": "concise", "3": "detailed", "s": "skip"}.get(tone_answer, "balanced"),
        sharp_review="on" if sharp_answer in {"y", "yes"} else "off",
        language=language,
    )
    print(strings["done"])
    return profile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "apply", "start"))
    parser.add_argument("--profile", type=Path, default=default_profile_path())
    parser.add_argument("--language", choices=("zh-CN", "en"), default="zh-CN")
    parser.add_argument("--memory", choices=("local", "off", "skip"), default="skip")
    parser.add_argument("--interpretation", choices=("choices", "ask", "skip"), default="skip")
    parser.add_argument("--tone", choices=("concise", "balanced", "detailed", "skip"), default="skip")
    parser.add_argument("--sharp-review", choices=("on", "off", "skip"), default="skip")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    path = args.profile.expanduser()
    if args.command == "status":
        result = status(path, args.language)
    elif args.command == "start":
        profile = interactive(path, args.language)
        result = summary(profile)
    else:
        profile = apply_choices(
            path,
            memory=args.memory,
            interpretation=args.interpretation,
            tone=args.tone,
            sharp_review=args.sharp_review,
            language=args.language,
        )
        result = summary(profile)
    if args.command != "start":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
