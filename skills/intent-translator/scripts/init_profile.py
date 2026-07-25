#!/usr/bin/env python3
"""Create or validate a local intent-translator user profile."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_profile_path() -> Path:
    configured = os.environ.get("INTENT_TRANSLATOR_PROFILE")
    return Path(configured).expanduser() if configured else Path.home() / ".intent-translator" / "profile.json"


def default_profile(language: str = "auto") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "profile_id": str(uuid.uuid4()),
        "language": language,
        "response_style": {"verbosity": "adaptive", "result_first": True},
        "autonomy": {"reversible_actions": "proceed", "high_impact_actions": "confirm"},
        "adaptation": {
            "expertise": "adaptive",
            "plain_language": "adaptive",
            "accessibility": [],
            "domains": [],
        },
        "risk_policy": {
            "high_stakes": "verify",
            "sensitive_memory": "explicit",
        },
        "optional_adapters": {
            "session_hooks": False,
            "reversible_context": False,
        },
        "phrase_mappings": {},
        "memory": {
            "adapter": "sqlite",
            "location": "~/.intent-translator/memory.db",
        },
        "cognitive_priors": [],
    }


def profile_pack_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "profile-packs"


def load_profile_pack(name_or_path: str) -> dict[str, Any]:
    candidate = Path(name_or_path).expanduser()
    path = candidate if candidate.exists() else profile_pack_dir() / f"{name_or_path}.json"
    if not path.exists():
        raise ValueError(f"profile pack not found: {name_or_path}")
    pack = json.loads(path.read_text(encoding="utf-8"))
    if pack.get("pack_schema_version") != 1 or not isinstance(pack.get("profile"), dict):
        raise ValueError(f"invalid profile pack: {path}")
    return pack


def _merge_value(current: Any, incoming: Any) -> Any:
    if isinstance(current, dict) and isinstance(incoming, dict):
        merged = copy.deepcopy(current)
        for key, value in incoming.items():
            merged[key] = _merge_value(merged[key], value) if key in merged else copy.deepcopy(value)
        return merged
    if isinstance(current, list) and isinstance(incoming, list):
        merged = copy.deepcopy(current)
        for value in incoming:
            if value not in merged:
                merged.append(copy.deepcopy(value))
        return merged
    if incoming in (None, "") and current not in (None, ""):
        return copy.deepcopy(current)
    return copy.deepcopy(incoming)


def apply_profile_pack(profile: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    merged = _merge_value(profile, pack["profile"])
    merged.setdefault("applied_profile_packs", {})[pack["name"]] = {
        "pack_schema_version": pack["pack_schema_version"],
        "applied_at": now_iso(),
    }
    return merged


def configure_study_profile(
    profile: dict[str, Any],
    *,
    goals: list[str] | None = None,
    vault_name: str | None = None,
    vault_path: str | None = None,
    managed_note: str | None = None,
    enable_shadow: bool | None = None,
    shadow_preview_chars: int | None = None,
) -> dict[str, Any]:
    study = profile.setdefault("study", {})
    if goals:
        study["goals"] = list(dict.fromkeys(goal.strip() for goal in goals if goal.strip()))
        if not study.get("active_goal") and study["goals"]:
            study["active_goal"] = study["goals"][0]
    pointers = profile.setdefault("knowledge_pointers", {})
    if vault_name is not None:
        pointers["vault_name"] = vault_name.strip()
    if vault_path is not None:
        pointers["vault_path"] = str(Path(vault_path).expanduser().resolve()) if vault_path.strip() else ""
    if managed_note is not None:
        pointers["managed_note"] = managed_note.strip()
    shadow = profile.setdefault("shadow_evaluation", {})
    if enable_shadow is not None:
        shadow["enabled"] = enable_shadow
        shadow["notify_user"] = False
    if shadow_preview_chars is not None:
        shadow["preview_chars"] = max(0, min(120, shadow_preview_chars))
    return profile


def write_profile(path: Path, profile: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(profile, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_profile(profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if profile.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must equal {SCHEMA_VERSION}")
    for key in ("profile_id", "language", "response_style", "autonomy", "phrase_mappings", "memory"):
        if key not in profile:
            errors.append(f"missing required field: {key}")
    if not isinstance(profile.get("phrase_mappings", {}), dict):
        errors.append("phrase_mappings must be an object")
    else:
        for phrase, mapping in profile.get("phrase_mappings", {}).items():
            if not isinstance(phrase, str) or not phrase.strip():
                errors.append("phrase_mappings keys must be non-empty strings")
            if isinstance(mapping, dict) and not str(mapping.get("meaning", "")).strip():
                errors.append(f"phrase mapping requires meaning: {phrase}")
            elif isinstance(mapping, dict) and mapping.get("match_mode", "exact") not in {"exact", "contains"}:
                errors.append(f"phrase mapping match_mode must be exact or contains: {phrase}")
            elif not isinstance(mapping, (str, dict)):
                errors.append(f"phrase mapping must be a string or object: {phrase}")
    adaptation = profile.get("adaptation", {})
    if not isinstance(adaptation, dict):
        errors.append("adaptation must be an object")
    elif adaptation.get("expertise", "adaptive") not in {"adaptive", "novice", "intermediate", "expert"}:
        errors.append("adaptation.expertise must be adaptive, novice, intermediate, or expert")
    risk_policy = profile.get("risk_policy", {})
    if not isinstance(risk_policy, dict):
        errors.append("risk_policy must be an object")
    elif risk_policy.get("high_stakes", "verify") not in {"verify", "standard"}:
        errors.append("risk_policy.high_stakes must be verify or standard")
    optional_adapters = profile.get("optional_adapters", {})
    if not isinstance(optional_adapters, dict):
        errors.append("optional_adapters must be an object")
    elif any(not isinstance(value, bool) for value in optional_adapters.values()):
        errors.append("optional_adapters values must be booleans")
    memory = profile.get("memory", {})
    if not isinstance(memory, dict) or memory.get("adapter") not in {"sqlite", "obsidian", "markdown", "none"}:
        errors.append("memory.adapter must be sqlite, obsidian, markdown, or none")
    study = profile.get("study")
    if study is not None:
        if not isinstance(study, dict):
            errors.append("study must be an object")
        else:
            if not isinstance(study.get("goals", []), list):
                errors.append("study.goals must be an array")
            if not _is_positive_integer(study.get("focus_window_minutes", 45)):
                errors.append("study.focus_window_minutes must be positive")
    shadow = profile.get("shadow_evaluation")
    if shadow is not None:
        if not isinstance(shadow, dict):
            errors.append("shadow_evaluation must be an object")
        elif not _is_positive_integer(shadow.get("retention_days", 30)) or not _is_positive_integer(
            shadow.get("max_events", 500)
        ):
            errors.append("shadow_evaluation retention_days and max_events must be positive")
        elif shadow.get("store_full_utterance", False):
            errors.append("shadow_evaluation.store_full_utterance must remain false")
    pointers = profile.get("knowledge_pointers")
    if pointers is not None:
        if not isinstance(pointers, dict):
            errors.append("knowledge_pointers must be an object")
        elif pointers.get("scan_vault", False):
            errors.append("knowledge_pointers.scan_vault must remain false")
    student_state = profile.get("student_state")
    if student_state is not None:
        if not isinstance(student_state, dict):
            errors.append("student_state must be an object")
        elif student_state.get("authority", "canonical-markdown") != "canonical-markdown":
            errors.append("student_state.authority must be canonical-markdown")
        elif not _is_positive_integer(student_state.get("due_soon_days", 7)):
            errors.append("student_state.due_soon_days must be positive")
        elif not _is_positive_integer(student_state.get("context_item_limit", 8)):
            errors.append("student_state.context_item_limit must be positive")
    return errors


def _is_positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def set_phrase_mapping(
    profile: dict[str, Any], *, phrase: str, meaning: str, scope: str = "global"
) -> dict[str, Any]:
    if not phrase.strip() or not meaning.strip() or not scope.strip():
        raise ValueError("phrase, meaning, and scope are required")
    profile.setdefault("phrase_mappings", {})[phrase.strip()] = {
        "meaning": meaning.strip(),
        "scope": scope.strip(),
        "match_mode": "exact",
        "confidence": "confirmed",
        "updated_at": now_iso(),
    }
    return profile["phrase_mappings"][phrase.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "validate", "show", "set-phrase", "remove-phrase", "apply-pack"))
    parser.add_argument("--profile", type=Path, default=default_profile_path())
    parser.add_argument("--language", default="auto")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--phrase")
    parser.add_argument("--meaning")
    parser.add_argument("--scope", default="global")
    parser.add_argument("--pack", default="student-exam-prep")
    parser.add_argument("--goal", action="append", default=[])
    parser.add_argument("--vault-name")
    parser.add_argument("--vault-path")
    parser.add_argument("--managed-note")
    parser.add_argument("--enable-shadow", action="store_true")
    parser.add_argument("--shadow-preview-chars", type=int)
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    path = args.profile.expanduser().resolve()

    if args.command == "init":
        if path.exists() and not args.force:
            raise SystemExit(f"profile already exists: {path}; use --force to replace it")
        profile = default_profile(args.language)
        write_profile(path, profile)
        print(json.dumps({"profile": str(path), "created": True}, ensure_ascii=False))
        return 0

    if not path.exists():
        raise SystemExit(f"profile does not exist: {path}")
    profile = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_profile(profile)
    if args.command == "validate":
        print(json.dumps({"profile": str(path), "valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
        return 0 if not errors else 2
    if errors:
        print(json.dumps({"profile": str(path), "valid": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 2
    if args.command == "apply-pack":
        try:
            pack = load_profile_pack(args.pack)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        profile = apply_profile_pack(profile, pack)
        configure_study_profile(
            profile,
            goals=args.goal,
            vault_name=args.vault_name,
            vault_path=args.vault_path,
            managed_note=args.managed_note,
            enable_shadow=True if args.enable_shadow else None,
            shadow_preview_chars=args.shadow_preview_chars,
        )
        errors = validate_profile(profile)
        if errors:
            print(json.dumps({"profile": str(path), "valid": False, "errors": errors}, ensure_ascii=False, indent=2))
            return 2
        write_profile(path, profile)
        print(json.dumps({"profile": str(path), "pack": pack["name"], "goals": profile.get("study", {}).get("goals", [])}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "set-phrase":
        if not args.phrase or not args.meaning:
            raise SystemExit("set-phrase requires --phrase and --meaning")
        mapping = set_phrase_mapping(
            profile, phrase=args.phrase, meaning=args.meaning, scope=args.scope
        )
        write_profile(path, profile)
        print(json.dumps({"profile": str(path), "phrase": args.phrase, "mapping": mapping}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "remove-phrase":
        if not args.phrase:
            raise SystemExit("remove-phrase requires --phrase")
        removed = profile.get("phrase_mappings", {}).pop(args.phrase, None) is not None
        write_profile(path, profile)
        print(json.dumps({"profile": str(path), "phrase": args.phrase, "removed": removed}, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(profile, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
