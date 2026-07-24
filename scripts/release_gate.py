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


def installed_wheel_steps(wheel: Path, root: Path, python: str) -> list[dict[str, Any]]:
    venv = root / "installed-wheel"
    scripts = venv / ("Scripts" if os.name == "nt" else "bin")
    installed_python = scripts / ("python.exe" if os.name == "nt" else "python")
    executable_suffix = ".exe" if os.name == "nt" else ""
    env = dict(os.environ)
    env.update(
        {
            "HOME": str(root),
            "USERPROFILE": str(root),
            "INTENT_TRANSLATOR_PROFILE": str(root / "data" / "profile.json"),
            "INTENT_TRANSLATOR_MEMORY_DB": str(root / "data" / "memory.db"),
            "PIP_CACHE_DIR": str(root / "pip-cache"),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PYTHONUTF8": "1",
        }
    )
    steps = [run_step("wheel-venv", [python, "-m", "venv", str(venv)])]
    if not steps[-1]["passed"]:
        return steps
    steps.append(
        run_step(
            "wheel-install",
            [str(installed_python), "-m", "pip", "install", str(wheel)],
            env=env,
        )
    )
    if not steps[-1]["passed"]:
        return steps
    steps.extend(
        [
            run_step(
                "wheel-doctor",
                [str(scripts / f"intent-translator-doctor{executable_suffix}"), "--json"],
                env=env,
            ),
            run_step(
                "wheel-onboarding",
                [
                    str(scripts / f"intent-translator-onboard{executable_suffix}"),
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
                [str(installed_python), "-c", "from intent_translator_mcp.server import mcp; assert mcp"],
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
            run_step("stranger-smoke", [python, "scripts/stranger_smoke.py"]),
            run_step("release-audit", [python, "scripts/release_audit.py", "--repo", str(REPO_ROOT)]),
        ]
    )

    package_report: dict[str, Any] | None = None
    if mode == "full" and all(step["passed"] for step in steps):
        with tempfile.TemporaryDirectory() as temp:
            dist = Path(temp) / "dist"
            build = run_step("package-build", [python, "-m", "build", "--outdir", str(dist)])
            steps.append(build)
            if build["passed"]:
                package_audit = run_step(
                    "package-audit",
                    [python, "scripts/release_audit.py", "--repo", str(REPO_ROOT), "--dist", str(dist)],
                )
                steps.append(package_audit)
                package_report = {"artifacts": sorted(path.name for path in dist.iterdir())}
                if package_audit["passed"]:
                    wheel = next(dist.glob("*.whl"))
                    steps.extend(installed_wheel_steps(wheel, Path(temp), python))

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
