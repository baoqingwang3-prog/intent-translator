"""Exercise the local semantic command through the real intent compiler.

The semantic interpreter and compiler may use different Python environments.
Run this script with the compiler's project environment and pass the cached
interpreter's Python executable with --semantic-python. This does not touch a
resident host process or its configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from intent_translator_mcp.core import IntentCompiler  # noqa: E402
from intent_translator_mcp.models import CompileRequest  # noqa: E402
from intent_translator_mcp.semantic import adapter_from_env  # noqa: E402


CASES = {
    141: ("change", "none", "none", "delete", False),
    142: ("search", "read_public", "public_query", "transfer", False),
    143: ("change", None, None, "change", None),
    144: ("compress", "none", "none", "transfer", False),
    145: ("diagnose", None, None, "deploy", None),
    146: ("build", None, None, "publish", None),
    147: ("diagnose", "none", "none", "change", False),
    148: ("search", "read_public", "public_query", "payment", True),
    149: ("change", "write_local", "none", "transfer", False),
    150: ("answer", None, None, "change", None),
    151: ("change", "read_local", "none", "network_request", True),
    152: ("change", None, None, "change", None),
    153: ("answer", "none", "none", None, False),
    172: ("build", "write_external", "user_text", None, False),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--semantic-python", required=True, type=Path)
    parser.add_argument("--cases", nargs="+", type=int, help="run only these held-out case numbers")
    args = parser.parse_args()
    if not args.semantic_python.is_file():
        parser.error("--semantic-python must point to an existing executable")
    selected = set(args.cases or CASES)
    unknown = selected - CASES.keys()
    if unknown:
        parser.error(f"unsupported case numbers: {sorted(unknown)}")

    argv = [str(args.semantic_python), "-B", str(REPO / "scripts" / "ilang_semantic_main.py")]
    adapter = adapter_from_env({
        "INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON": json.dumps(argv),
        "INTENT_TRANSLATOR_SEMANTIC_TIMEOUT": "120",
    })
    assert adapter is not None
    heldout = [json.loads(line) for line in (REPO / "scripts" / "ilang_heldout_set.jsonl").read_text(
        encoding="utf-8"
    ).splitlines() if line.strip()]
    failures = []
    failed_cases = set()

    with tempfile.TemporaryDirectory(prefix="ilang-host-acceptance-") as temporary:
        root = Path(temporary)
        profile = root / "profile.json"
        profile.write_text(json.dumps({
            "schema_version": 1,
            "profile_id": "host-acceptance",
            "language": "zh-CN",
            "phrase_mappings": {},
            "memory": {"adapter": "none", "location": ""},
        }, ensure_ascii=False), encoding="utf-8")
        host_env = {
            "INTENT_TRANSLATOR_PROFILE": str(profile),
            "INTENT_TRANSLATOR_MEMORY_DB": str(root / "memory.db"),
            "INTENT_TRANSLATOR_STATE_DB": str(root / "memory.db"),
        }
        with patch.dict(os.environ, host_env, clear=False):
            compiler = IntentCompiler(registry={"skills": [], "errors": []}, semantic_adapter=adapter)
            for number, (mode, effect, egress, forbidden, execute) in CASES.items():
                if number not in selected:
                    continue
                case = heldout[number - 1]
                result = compiler.compile(CompileRequest(
                    utterance=case["utterance"],
                    context=case.get("context", ""),
                    pending_action=case.get("pending_action", ""),
                    semantic_mode="required",
                    include_prompt=False,
                ))
                contract = result["intent_contract"]
                actual = (
                    result["semantic"]["status"], result["mode"],
                    contract["effect"], contract["data_egress"],
                    result["completion_contract"]["execute"],
                )
                expected = ("applied", mode, effect, egress, execute)
                prohibited = {item["action"] for item in contract["prohibitions"]}
                forbidden_aliases = {forbidden}
                if forbidden == "transfer":
                    forbidden_aliases.add("upload")
                has_prohibition = forbidden is None or bool(forbidden_aliases & prohibited)
                if (any(want is not None and got != want for got, want in zip(actual, expected))
                        or not has_prohibition):
                    failures.append(f"H{number:03} contract mismatch")
                    failed_cases.add(number)
                if forbidden is not None:
                    prohibited_actions = [
                        item for item in contract["actions"]
                        if item.get("polarity") == "prohibited"
                        and item.get("predicate") in forbidden_aliases
                    ]
                    active = [item for item in contract["actions"] if item.get("active_now")]
                    if not prohibited_actions or any(
                        item.get("predicate") in forbidden_aliases
                        and item.get("object") == prohibited.get("object")
                        for item in active for prohibited in prohibited_actions
                    ):
                        failures.append(f"H{number:03} prohibited action active or missing")
                        failed_cases.add(number)
                print(f"H{number:03} semantic={actual[0]} mode={actual[1]} "
                      f"effect={actual[2]} egress={actual[3]} "
                      f"prohibition={'yes' if has_prohibition and forbidden else 'n/a'} "
                      f"execute={actual[4]}")

    total = len(selected)
    print(f"host acceptance: {total - len(failed_cases)}/{total} passed")
    for failure in failures:
        print("FAIL", failure)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
