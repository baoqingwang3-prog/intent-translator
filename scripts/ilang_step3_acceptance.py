r"""Step 3 acceptance: held-out set + context continuation + tightening.

Checks the complete SemanticProposal schema and exact mode labels for every
case. Quoted I-Lang must not enter the parser; invalid input must abstain;
external continuations must request review. Execution authorization and
preservation of action prohibitions require a separate host-level test.

Usage: python ilang_step3_acceptance.py [--fast]
Exit code 0 iff all checks pass.
"""

from __future__ import annotations

import json
import argparse
import contextlib
import io
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable
MAIN = HERE / "ilang_semantic_main.py"
REPO = HERE.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))
import ilang_semantic_main  # noqa: E402 - also locates the existing local dependencies
from intent_translator_mcp.semantic import SemanticProposal  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def run(payload: dict) -> dict:
    proc = subprocess.run(
        [PY, str(MAIN)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-300:])
    return json.loads(proc.stdout)


def run_in_process(payload: dict) -> dict:
    """Reuse one warmed model when inspecting the complete case set."""
    original_stdin = sys.stdin
    stdout = io.StringIO()
    try:
        sys.stdin = io.StringIO(json.dumps(payload, ensure_ascii=False))
        with contextlib.redirect_stdout(stdout):
            code = ilang_semantic_main.main()
    finally:
        sys.stdin = original_stdin
    if code:
        raise RuntimeError(f"semantic entry point exited with code {code}")
    return json.loads(stdout.getvalue())


def check_case(case: dict, out: dict) -> list[str]:
    """Check the proposal contract, not whether an action was authorized."""
    errors = []
    try:
        SemanticProposal.model_validate(out, strict=True)
    except Exception as exc:
        errors.append(f"invalid SemanticProposal: {exc}")

    want = case.get("expected_mode")
    got = out.get("mode")
    constraint = case.get("constraint", "")
    if got != want:
        errors.append(f"mode {got!r} != {want!r}")
    if want is None and out.get("clarification_recommended") is not True:
        errors.append("abstention must recommend clarification")
    if constraint.startswith(("quoted-ilang", "plain-bracket")):
        if str(out.get("interpretation", "")).startswith("[ilang]"):
            errors.append("quoted or ordinary brackets entered the I-Lang path")
    if constraint == "continuation-high-risk":
        if out.get("clarification_recommended") is not True:
            errors.append("external continuation needs review")
        if "external" not in (out.get("risk_hints") or []):
            errors.append("external continuation needs an external risk hint")
    if constraint in {"revoked-deletion", "continuation-refusal"}:
        if out.get("clarification_recommended") is not True:
            errors.append("revocation must recommend clarification")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", action="store_true", help="reuse one warmed model instead of one subprocess per case")
    args = parser.parse_args(argv)
    runner = run_in_process if args.fast else run
    cases = [json.loads(line) for line in open(HERE / "ilang_heldout_set.jsonl", encoding="utf-8") if line.strip()]
    failures: list[str] = []
    passed = 0

    for index, case in enumerate(cases, 1):
        utt = case["utterance"]
        payload = {
            "utterance": utt,
            "context": case.get("context", ""),
            "pending_action": case.get("pending_action", ""),
            "deterministic_draft": {},
        }
        out = runner(payload)
        errors = check_case(case, out)
        if errors:
            failures.append(f"H{index:03} [{case.get('constraint', '') or 'plain'}] {utt}: {'; '.join(errors)}")
        else:
            passed += 1

    total = len(cases)
    print(f"\nheld-out acceptance: {passed}/{total} passed, {len(failures)} failures")
    print("Scope: semantic proposal mode/schema/syntax only; execution authorization requires a separate host test.")
    for f in failures:
        print("  FAIL", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
