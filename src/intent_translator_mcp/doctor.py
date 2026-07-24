"""Privacy-conscious installation diagnostics for intent-translator."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Mapping

from .core import _candidate_skill_dirs


def _display_path(path: Path, home: Path, show_paths: bool) -> str:
    resolved = path.expanduser().resolve()
    if show_paths:
        return str(resolved)
    try:
        return str(Path("~") / resolved.relative_to(home.resolve()))
    except ValueError:
        return "<outside-home>"


def _check(identifier: str, status: str, message: str, **details: Any) -> dict[str, Any]:
    result = {"id": identifier, "status": status, "message": message}
    if details:
        result["details"] = details
    return result


def run_doctor(
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    show_paths: bool = False,
) -> dict[str, Any]:
    home = (home or Path.home()).expanduser().resolve()
    env = dict(os.environ if env is None else env)
    checks: list[dict[str, Any]] = []

    supported = sys.version_info >= (3, 10)
    checks.append(
        _check(
            "python",
            "pass" if supported else "fail",
            "Python version is supported" if supported else "Python 3.10 or newer is required",
            version=".".join(str(part) for part in sys.version_info[:3]),
        )
    )

    profile_path = Path(env.get("INTENT_TRANSLATOR_PROFILE", home / ".intent-translator" / "profile.json"))
    if not profile_path.exists():
        checks.append(_check("profile", "warn", "Profile is not initialized yet"))
        profile = {"memory": {"adapter": "sqlite"}}
    else:
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            required = {"schema_version", "profile_id", "language", "phrase_mappings", "memory"}
            missing = sorted(required - set(profile))
            checks.append(
                _check(
                    "profile",
                    "fail" if missing else "pass",
                    "Profile is valid JSON" if not missing else "Profile is missing required fields",
                    path=_display_path(profile_path, home, show_paths),
                    missing=missing,
                )
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            profile = {"memory": {"adapter": "sqlite"}}
            checks.append(
                _check(
                    "profile",
                    "fail",
                    "Profile cannot be read as UTF-8 JSON",
                    path=_display_path(profile_path, home, show_paths),
                    error=type(exc).__name__,
                )
            )

    memory_location = env.get("INTENT_TRANSLATOR_MEMORY_DB") or profile.get("memory", {}).get("location")
    memory_path = Path(memory_location).expanduser() if memory_location else home / ".intent-translator" / "memory.db"
    if memory_path.exists():
        try:
            connection = sqlite3.connect(f"file:{memory_path.resolve().as_posix()}?mode=ro", uri=True)
            try:
                integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
            finally:
                connection.close()
            checks.append(
                _check(
                    "memory",
                    "pass" if integrity == "ok" else "fail",
                    "Memory database passed SQLite quick_check" if integrity == "ok" else "Memory database failed SQLite quick_check",
                    path=_display_path(memory_path, home, show_paths),
                )
            )
        except sqlite3.Error as exc:
            checks.append(
                _check(
                    "memory",
                    "fail",
                    "Memory database could not be opened read-only",
                    path=_display_path(memory_path, home, show_paths),
                    error=type(exc).__name__,
                )
            )
    else:
        parent = memory_path.parent
        writable = parent.exists() and os.access(parent, os.W_OK)
        checks.append(
            _check(
                "memory",
                "warn" if writable else "fail",
                "Memory database will be created on first authorized write" if writable else "Memory directory is not writable",
                path=_display_path(memory_path, home, show_paths),
            )
        )

    skill_dirs = _candidate_skill_dirs()
    checks.append(
        _check(
            "skill",
            "pass" if skill_dirs else "warn",
            "Installed intent-translator Skill found" if skill_dirs else "No installed Skill found; MCP can still report this condition",
            locations=[_display_path(path, home, show_paths) for path in skill_dirs],
        )
    )

    config_dir = home / ".intent-translator" / "mcp-configs"
    generated = sorted(config_dir.glob("*-mcp.*")) if config_dir.exists() else []
    checks.append(
        _check(
            "mcp_configs",
            "pass" if generated else "warn",
            "Generated MCP host snippets found" if generated else "MCP host snippets have not been generated",
            count=len(generated),
            location=_display_path(config_dir, home, show_paths),
        )
    )

    statuses = {item["status"] for item in checks}
    overall = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"
    return {
        "schema_version": 1,
        "status": overall,
        "privacy": "Home-relative paths are shown by default; use --show-paths for exact locations.",
        "checks": checks,
    }


def _render_human(report: dict[str, Any]) -> str:
    labels = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}
    lines = [f"intent-translator doctor: {labels[report['status']]}" ]
    for item in report["checks"]:
        lines.append(f"[{labels[item['status']]}] {item['id']}: {item['message']}")
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit structured JSON")
    parser.add_argument("--show-paths", action="store_true", help="Include exact local paths")
    args = parser.parse_args()
    report = run_doctor(show_paths=args.show_paths)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else _render_human(report))
    return 2 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
