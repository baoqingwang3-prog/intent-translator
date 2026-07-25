#!/usr/bin/env python3
"""Run an operator-driven Codex preflight -> tool -> result trace with redacted evidence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from intent_translator_mcp.models import CompileRequest, ExecutionVerificationRequest  # noqa: E402
from intent_translator_mcp.server import intent_compile, intent_verify_execution  # noqa: E402


def run_smoke(python: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        os.environ.update(
            {
                "HOME": str(root),
                "USERPROFILE": str(root),
                "INTENT_TRANSLATOR_HOST": "codex",
                "INTENT_TRANSLATOR_PROFILE": str(root / "profile.json"),
                "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
                "INTENT_TRANSLATOR_STATE_DB": str(root / "state.db"),
                "INTENT_TRANSLATOR_SKILL_DIR": str(REPO_ROOT / "skills" / "intent-translator"),
            }
        )
        compiled = intent_compile(
            CompileRequest(
                utterance="Run the local IntentBench v2 conformance test",
                semantic_mode="off",
                include_prompt=False,
            )
        )
        contract = compiled["intent_contract"]
        completed = subprocess.run(
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
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        verification = intent_verify_execution(
            ExecutionVerificationRequest(
                scope="codex-host-smoke",
                utterance="Run the local IntentBench v2 conformance test",
                expected_goal=compiled["normalized_goal"],
                expected_operation=contract["operation"],
                expected_skill=compiled["routing"]["primary_skill"] or "agent-host",
                actual_goal=compiled["normalized_goal"],
                actual_operation="test",
                actual_skill="agent-host",
                success=completed.returncode == 0,
                invocation_receipt_id=compiled["invocation_receipt"]["receipt_id"],
            )
        )
        return {
            "schema_version": 1,
            "evidence_class": "operator-driven-codex-host-smoke",
            "host": "codex",
            "automatic_host_interception_verified": False,
            "chain": [
                "user-request",
                "intent_compile-invocation-receipt",
                "actual-local-tool-call",
                "execution-result-verification",
            ],
            "invocation_receipt": compiled["invocation_receipt"],
            "planned": {
                "operation": contract["operation"],
                "skill": compiled["routing"]["primary_skill"] or "agent-host",
                "decision": compiled["tool_gateway"]["decision"],
            },
            "actual": {
                "tool": "intent-translator-bench",
                "operation": "test",
                "skill": "agent-host",
                "returncode": completed.returncode,
            },
            "verification": verification["execution_trace"],
            "passed": bool(
                completed.returncode == 0
                and verification["matched"]
                and compiled["invocation_receipt"]["preflight_observed"]
            ),
            "claim_limits": [
                "This proves an operator-driven Codex machine trace, not automatic interception of every Codex turn.",
                "Claude, Cursor, and other host enforcement remain unverified until host-specific traces exist.",
            ],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_smoke(args.python)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
