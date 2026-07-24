#!/usr/bin/env python3
"""Create or validate a local intent-translator user profile."""

from __future__ import annotations

import argparse
import json
import os
import sys
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
            "location": str(Path.home() / ".intent-translator" / "memory.db"),
        },
        "cognitive_priors": [],
    }


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
    return errors


def set_phrase_mapping(
    profile: dict[str, Any], *, phrase: str, meaning: str, scope: str = "global"
) -> dict[str, Any]:
    if not phrase.strip() or not meaning.strip() or not scope.strip():
        raise ValueError("phrase, meaning, and scope are required")
    profile.setdefault("phrase_mappings", {})[phrase.strip()] = {
        "meaning": meaning.strip(),
        "scope": scope.strip(),
        "confidence": "confirmed",
        "updated_at": now_iso(),
    }
    return profile["phrase_mappings"][phrase.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "validate", "show", "set-phrase", "remove-phrase"))
    parser.add_argument("--profile", type=Path, default=default_profile_path())
    parser.add_argument("--language", default="auto")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--phrase")
    parser.add_argument("--meaning")
    parser.add_argument("--scope", default="global")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    path = args.profile.expanduser().resolve()

    if args.command == "init":
        if path.exists() and not args.force:
            raise SystemExit(f"profile already exists: {path}; use --force to replace it")
        path.parent.mkdir(parents=True, exist_ok=True)
        profile = default_profile(args.language)
        path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    if args.command == "set-phrase":
        if not args.phrase or not args.meaning:
            raise SystemExit("set-phrase requires --phrase and --meaning")
        mapping = set_phrase_mapping(
            profile, phrase=args.phrase, meaning=args.meaning, scope=args.scope
        )
        path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"profile": str(path), "phrase": args.phrase, "mapping": mapping}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "remove-phrase":
        if not args.phrase:
            raise SystemExit("remove-phrase requires --phrase")
        removed = profile.get("phrase_mappings", {}).pop(args.phrase, None) is not None
        path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"profile": str(path), "phrase": args.phrase, "removed": removed}, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(profile, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
