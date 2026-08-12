#!/usr/bin/env python3
"""Run the reproducible GitHub Alpha release quality gate."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]

OFFICIAL_CAPABILITY_AUDIT = {
    "checked_at": "2026-07-28",
    "refresh_after_days": 45,
    "preserve_local_workflows": True,
    "native_host_first": True,
    "hosts": {
        "codex": [
            "https://learn.chatgpt.com/docs/prompting",
            "https://learn.chatgpt.com/docs/personalize",
            "https://learn.chatgpt.com/docs/skills-and-plugins",
            "https://learn.chatgpt.com/docs/permission-modes",
        ],
        "claude": [
            "https://code.claude.com/docs/en/memory",
            "https://code.claude.com/docs/en/skills",
            "https://code.claude.com/docs/en/permissions",
            "https://code.claude.com/docs/en/hooks-guide",
        ],
        "grok": [
            "https://docs.x.ai/build/overview",
            "https://docs.x.ai/build/modes-and-commands",
            "https://docs.x.ai/developers/model-capabilities/text/structured-outputs",
            "https://docs.x.ai/developers/tools/function-calling",
            "https://docs.x.ai/developers/advanced-api-usage/context-compaction",
        ],
    },
}
OFFICIAL_CAPABILITY_DOMAINS = {
    "codex": {"learn.chatgpt.com", "developers.openai.com"},
    "claude": {"code.claude.com", "docs.anthropic.com"},
    "grok": {"docs.x.ai"},
}


def validate_official_capability_audit(
    manifest: dict[str, Any] = OFFICIAL_CAPABILITY_AUDIT,
    *,
    as_of: date | None = None,
) -> list[str]:
    errors: list[str] = []
    as_of = as_of or date.today()
    try:
        checked_at = datetime.strptime(str(manifest.get("checked_at", "")), "%Y-%m-%d").date()
    except ValueError:
        errors.append("official capability checked_at must use YYYY-MM-DD")
        checked_at = as_of
    refresh_days = manifest.get("refresh_after_days")
    if not isinstance(refresh_days, int) or not 1 <= refresh_days <= 180:
        errors.append("official capability refresh_after_days must be 1..180")
        refresh_days = 0
    if checked_at > as_of + timedelta(days=1):
        errors.append("official capability checked_at cannot be more than one day in the future")
    elif checked_at <= as_of and refresh_days and (as_of - checked_at).days > refresh_days:
        errors.append("official capability audit is stale")
    if manifest.get("preserve_local_workflows") is not True:
        errors.append("official capability policy must preserve useful local workflows")
    if manifest.get("native_host_first") is not True:
        errors.append("official capability policy must be native-host-first")
    hosts = manifest.get("hosts")
    if not isinstance(hosts, dict):
        return [*errors, "official capability hosts must be an object"]
    for host in ("codex", "claude", "grok"):
        sources = hosts.get(host)
        if not isinstance(sources, list) or not sources:
            errors.append(f"official capability sources missing for {host}")
            continue
        for source in sources:
            parsed = urlparse(str(source))
            if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_CAPABILITY_DOMAINS[host]:
                errors.append(f"unofficial capability source for {host}: {source}")
    return errors


def official_capability_step() -> dict[str, Any]:
    errors = validate_official_capability_audit()
    result: dict[str, Any] = {"name": "official-capability-audit", "passed": not errors}
    if errors:
        result["errors"] = errors
    return result


def source_tree_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    return env



def run_step(
    name: str,
    command: list[str],
    *,
    cwd: Path = REPO_ROOT,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    result: dict[str, Any] = {"name": name, "passed": completed.returncode == 0}
    if completed.returncode != 0:
        result["returncode"] = completed.returncode
        result["output_tail"] = (completed.stdout + completed.stderr)[-3000:]
    return result


def installed_wheel_steps(
    wheel: Path, root: Path, python: str, *, sbom_path: Path
) -> list[dict[str, Any]]:
    target = root / "installed-wheel"
    env = dict(os.environ)
    env.update(
        {
            "HOME": str(root),
            "USERPROFILE": str(root),
            "INTENT_TRANSLATOR_PROFILE": str(root / "data" / "profile.json"),
            "INTENT_TRANSLATOR_MEMORY_DB": str(root / "data" / "memory.db"),
            "PIP_CACHE_DIR": str(root / "pip-cache"),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INDEX": "1",
            "PYTHONUTF8": "1",
            "PYTHONPATH": str(target)
            + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""),
        }
    )
    steps = [
        run_step(
            "wheel-target-install",
            [
                python,
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                "--target",
                str(target),
                str(wheel),
            ],
            env=env,
        )
    ]
    if not steps[-1]["passed"]:
        return steps
    steps.append(
        run_step(
            "wheel-sbom",
            [
                python,
                "scripts/generate_sbom.py",
                "--python",
                python,
                "--output",
                str(sbom_path),
            ],
            env=env,
        )
    )
    if not steps[-1]["passed"]:
        return steps
    steps.extend(
        [
            run_step(
                "wheel-doctor",
                [python, "-m", "intent_translator_mcp.doctor", "--json"],
                env=env,
            ),
            run_step(
                "wheel-onboarding",
                [
                    python,
                    "-m",
                    "intent_translator_mcp.onboarding",
                    "--memory",
                    "local",
                    "--interpretation",
                    "choices",
                    "--tone",
                    "concise",
                    "--json",
                ],
                env=env,
            ),
            run_step(
                "wheel-mcp-import",
                [python, "-c", "from intent_translator_mcp.server import mcp; assert mcp"],
                env=env,
            ),
            run_step(
                "wheel-intentbench-v1",
                [
                    python,
                    "-m",
                    "intent_translator_mcp.intentbench",
                    "--system",
                    "compiler",
                    "--fail-on-dangerous-miss",
                    "--minimum-field-accuracy",
                    "1.0",
                ],
                cwd=root,
                env=env,
            ),
            run_step(
                "wheel-intentbench-v2",
                [
                    python,
                    "-m",
                    "intent_translator_mcp.intentbench",
                    "--benchmark",
                    "intentbench-v2",
                    "--system",
                    "compiler",
                    "--fail-on-dangerous-miss",
                    "--minimum-field-accuracy",
                    "1.0",
                ],
                cwd=root,
                env=env,
            ),
        ]
    )
    return steps


def run_gate(mode: str, python: str = sys.executable) -> dict[str, Any]:
    source_env = source_tree_environment()
    steps = [
        run_step("release-metadata", [python, "tests/check_release_metadata.py"]),
        official_capability_step(),
        run_step("compileall", [python, "-m", "compileall", "-q", "skills", "src", "tests", "scripts"]),
    ]
    if mode == "quick":
        tests = (
            "tests.test_onboarding",
            "tests.test_onboarding_cli",
            "tests.test_install_lifecycle",
            "tests.test_personalization_firewall",
            "tests.test_release_audit",
            "tests.test_stranger_smoke",
        )
        steps.append(run_step("focused-tests", [python, "-m", "unittest", *tests, "-v"]))
    else:
        steps.append(run_step("full-tests", [python, "-m", "unittest", "discover", "-s", "tests", "-v"]))
    steps.extend(
        [
            run_step(
                "intentbench-v1",
                [
                    python,
                    "-m",
                    "intent_translator_mcp.intentbench",
                    "--system",
                    "compiler",
                    "--fail-on-dangerous-miss",
                    "--minimum-field-accuracy",
                    "1.0",
                ],
                env=source_env,
            ),
            run_step(
                "intentbench-v2",
                [
                    python,
                    "-m",
                    "intent_translator_mcp.intentbench",
                    "--benchmark",
                    "intentbench-v2",
                    "--system",
                    "compiler",
                    "--fail-on-dangerous-miss",
                    "--minimum-field-accuracy",
                    "1.0",
                ],
                env=source_env,
            ),
            run_step("stranger-smoke", [python, "scripts/stranger_smoke.py"]),
            run_step("release-audit", [python, "scripts/release_audit.py", "--repo", str(REPO_ROOT)]),
        ]
    )
    if mode != "quick":
        steps.append(
            run_step(
                "codex-operator-host-trace",
                [python, "scripts/codex_host_trace_smoke.py", "--python", python],
                env=source_env,
            )
        )

    package_report: dict[str, Any] | None = None
    if mode == "full" and all(step["passed"] for step in steps):
        with tempfile.TemporaryDirectory() as temp:
            dist = Path(temp) / "dist"
            build = run_step(
                "package-build",
                [python, "-m", "build", "--no-isolation", "--outdir", str(dist)],
            )
            steps.append(build)
            if build["passed"]:
                wheel = next(dist.glob("*.whl"))
                sbom = dist / "intent-translator-sbom.cdx.json"
                steps.extend(installed_wheel_steps(wheel, Path(temp), python, sbom_path=sbom))
                package_audit = run_step(
                    "package-audit",
                    [python, "scripts/release_audit.py", "--repo", str(REPO_ROOT), "--dist", str(dist)],
                )
                steps.append(package_audit)
                package_report = {"artifacts": sorted(path.name for path in dist.iterdir())}

    passed = all(step["passed"] for step in steps)
    return {
        "schema_version": 1,
        "mode": mode,
        "passed": passed,
        "steps": steps,
        "package": package_report,
        "git_publish_performed": False,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("quick", "ci", "full"), default="quick")
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    if not shutil.which(args.python) and not Path(args.python).exists():
        raise SystemExit(f"Python executable not found: {args.python}")
    report = run_gate(args.mode, args.python)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
