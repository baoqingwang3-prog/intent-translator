#!/usr/bin/env python3
"""Run the reproducible GitHub Alpha release quality gate."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


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
    steps = [
        run_step("release-metadata", [python, "tests/check_release_metadata.py"]),
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
