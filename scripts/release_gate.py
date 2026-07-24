#!/usr/bin/env python3
"""Run the reproducible GitHub Alpha release quality gate."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_step(name: str, command: list[str], *, cwd: Path = REPO_ROOT) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    result: dict[str, Any] = {"name": name, "passed": completed.returncode == 0}
    if completed.returncode != 0:
        result["returncode"] = completed.returncode
        result["output_tail"] = (completed.stdout + completed.stderr)[-3000:]
    return result


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
