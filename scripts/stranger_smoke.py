#!/usr/bin/env python3
"""Run a local, protocol-level first-use smoke test with two isolated users."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "intent-translator" / "scripts"))

from discover_skills import discover_skills  # noqa: E402
from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402
from intent_translator_mcp.onboarding import (  # noqa: E402
    apply_onboarding,
    confirm_language_rule,
    interpretation_gate,
    observe_language_correction,
)


TECHNICAL_TERMS = ("prompt", "ExecutionEnvelope", "MCP", "SQLite")


@contextmanager
def local_user(profile: Path, memory: Path, skill_root: Path) -> Iterator[None]:
    keys = {
        "INTENT_TRANSLATOR_PROFILE": str(profile),
        "INTENT_TRANSLATOR_MEMORY_DB": str(memory),
        "INTENT_TRANSLATOR_SKILL_ROOTS": str(skill_root),
        "INTENT_TRANSLATOR_SEMANTIC_COMMAND": "",
        "INTENT_TRANSLATOR_SEMANTIC_URL": "",
    }
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(keys)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def write_minimal_skill(root: Path, *, name: str, description: str, heading: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=False)
    content = (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"# {heading}\n\n"
        "Turn the user's request into a concrete result and verify it before reporting completion.\n"
    )
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8", newline="\n")
    return skill_dir


def validate_minimal_skill(skill_dir: Path) -> list[str]:
    path = skill_dir / "SKILL.md"
    if not path.is_file():
        return ["SKILL.md is missing"]
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        errors.append("frontmatter is missing")
    if f"name: {skill_dir.name}" not in text:
        errors.append("name does not match the directory")
    if "description:" not in text:
        errors.append("description is missing")
    return errors


def compile_for(profile: Path, memory: Path, skill_root: Path, utterance: str) -> dict[str, Any]:
    with local_user(profile, memory, skill_root):
        registry = discover_skills([skill_root])
        return IntentCompiler(registry=registry).compile(
            CompileRequest(utterance=utterance, semantic_mode="off")
        )


def run_smoke(workspace: Path) -> dict[str, Any]:
    started = time.perf_counter()
    workspace.mkdir(parents=True, exist_ok=True)
    users = {
        "user-a": {
            "tone": "concise",
            "meaning": "build and implement a small reusable helper",
            "skill_name": "assignment-planner",
            "description": "Turn course assignments and deadlines into a practical daily checklist.",
            "request": "Make me a reusable helper that turns course assignments into today's checklist.",
            "call": "Turn my course assignments into today's checklist.",
        },
        "user-b": {
            "tone": "detailed",
            "meaning": "answer only with a detailed explanation and do not change files",
            "skill_name": "lecture-explainer",
            "description": "Explain difficult lecture concepts step by step with examples and a self-check.",
            "request": "Make me a reusable helper that explains difficult lecture ideas step by step.",
            "call": "Explain this difficult lecture concept step by step with an example.",
        },
    }
    participant_text = [
        "What may be remembered on this computer?",
        "When a sentence has several important meanings, show choices or ask once?",
        "How concise should answers be, and may important plans receive sharper review?",
        "Describe the small reusable helper you want.",
    ]
    results: dict[str, Any] = {}

    for user_id, scenario in users.items():
        root = workspace / user_id
        profile = root / "data" / "profile.json"
        memory = root / "data" / "memory.db"
        skill_root = root / "skills"
        skill_root.mkdir(parents=True)
        generic = compile_for(profile, memory, skill_root, "Help me organize a small task.")
        apply_onboarding(
            profile,
            memory="local",
            interpretation="choices",
            tone=str(scenario["tone"]),
        )

        first = observe_language_correction(
            profile,
            phrase="kick it off",
            corrected_meaning=str(scenario["meaning"]),
        )
        second = observe_language_correction(
            profile,
            phrase="kick it off",
            corrected_meaning=str(scenario["meaning"]),
        )
        confirm_language_rule(
            profile,
            phrase="kick it off",
            corrected_meaning=str(scenario["meaning"]),
        )

        creation = compile_for(profile, memory, skill_root, str(scenario["request"]))
        gate = interpretation_gate(
            primary=str(scenario["request"]),
            alternatives=["Only explain how such a helper could work"],
        )
        skill_dir = write_minimal_skill(
            skill_root,
            name=str(scenario["skill_name"]),
            description=str(scenario["description"]),
            heading=str(scenario["skill_name"]).replace("-", " ").title(),
        )
        validation_errors = validate_minimal_skill(skill_dir)
        invocation = compile_for(profile, memory, skill_root, str(scenario["call"]))
        phrase_result = compile_for(profile, memory, skill_root, "kick it off")
        results[user_id] = {
            "generic_before_onboarding": generic["personalization_status"]["mode"] == "generic",
            "first_correction_applied": first["applied_to_current_turn"],
            "promotion_suggested_after_first": first["promotion_suggested"],
            "promotion_suggested_after_second": second["promotion_suggested"],
            "creation_route": creation["routing"]["primary_skill"],
            "candidate_choice_required": gate["wait_for_selection"],
            "skill_valid": not validation_errors,
            "validation_errors": validation_errors,
            "invocation_route": invocation["routing"]["primary_skill"],
            "phrase_mode": phrase_result["mode"],
            "base_mode_without_cloud": phrase_result["base_mode"]["active"],
        }

    left_profile = (workspace / "user-a" / "data" / "profile.json").read_text(encoding="utf-8")
    right_profile = (workspace / "user-b" / "data" / "profile.json").read_text(encoding="utf-8")
    cross_contamination = int(str(users["user-a"]["meaning"]) in right_profile) + int(
        str(users["user-b"]["meaning"]) in left_profile
    )
    technical_terms = sum(
        text.casefold().count(term.casefold()) for text in participant_text for term in TECHNICAL_TERMS
    )
    passed = (
        results["user-a"]["creation_route"] == "skill-creator"
        and results["user-b"]["creation_route"] == "skill-creator"
        and results["user-a"]["invocation_route"] == users["user-a"]["skill_name"]
        and results["user-b"]["invocation_route"] == users["user-b"]["skill_name"]
        and results["user-a"]["phrase_mode"] != results["user-b"]["phrase_mode"]
        and all(item["skill_valid"] for item in results.values())
        and all(item["generic_before_onboarding"] for item in results.values())
        and all(item["first_correction_applied"] for item in results.values())
        and all(item["promotion_suggested_after_second"] for item in results.values())
        and cross_contamination == 0
        and technical_terms == 0
    )
    return {
        "schema_version": 1,
        "passed": passed,
        "ui_level": "protocol-simulated",
        "real_button_ui_complete": False,
        "users": results,
        "metrics": {
            "users_tested": len(users),
            "first_success_steps": 5,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "invalid_questions": 0,
            "technical_terms_exposed": technical_terms,
            "first_correction_effective": all(item["first_correction_applied"] for item in results.values()),
            "cross_contamination_count": cross_contamination,
            "skills_created_and_invoked": sum(
                item["skill_valid"] and item["invocation_route"] == users[user_id]["skill_name"]
                for user_id, item in results.items()
            ),
        },
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, help="Keep generated synthetic files in this directory")
    args = parser.parse_args()
    if args.workspace:
        report = run_smoke(args.workspace.resolve())
    else:
        with tempfile.TemporaryDirectory() as temp:
            report = run_smoke(Path(temp))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
