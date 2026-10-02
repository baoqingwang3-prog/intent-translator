"""Development regression against the frozen v3 fixture.

This is not an acceptance run. It does not replace the formal result,
does not rewrite the fixture, the scorer, or the thresholds, and it
does not write the one-run receipt.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
FIXTURE_SHA256 = "8F91B7A9FD6F403D065792C3531202170FE90A39E8048BC1F72F8C0477A53164"


def load_gate(gate_path: Path):
    spec = importlib.util.spec_from_file_location("independent_gate_v3", gate_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit-dir", type=Path, default=os.environ.get("ILANG_DEV_AUDIT_DIR"),
        required=not bool(os.environ.get("ILANG_DEV_AUDIT_DIR")),
        help="Directory containing the unchanged frozen v3 fixture, scorer, and manifest.",
    )
    parser.add_argument("--semantic-python", type=Path, help="Override the manifest interpreter.")
    parser.add_argument("--output", type=Path, required=True, help="New result path; existing files are preserved.")
    args = parser.parse_args(argv)
    fixture = args.audit_dir / "independent_cases_v3.jsonl"
    gate_path = args.audit_dir / "independent_gate_v3.py"
    manifest_path = args.audit_dir / "independent_freeze_manifest_v3.json"
    output = args.output
    if output.exists():
        parser.error("output already exists; choose a new path to preserve previous results")
    for resource in (fixture, gate_path, manifest_path):
        if not resource.is_file():
            parser.error(f"frozen audit resource is missing: {resource}")
    gate = load_gate(gate_path)
    if gate.sha256(fixture) != FIXTURE_SHA256:
        raise SystemExit("frozen fixture hash changed; refusing to score")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    semantic_python = args.semantic_python or Path(manifest["semantic_python"])
    cases = gate.load_jsonl(fixture)
    sys.path.insert(0, str(REPO / "scripts"))
    sys.path.insert(0, str(REPO / "src"))
    import ilang_distill_router
    import ilang_semantic_main
    from intent_translator_mcp.core import IntentCompiler
    from intent_translator_mcp.models import CompileRequest
    from intent_translator_mcp.semantic import SemanticProposal, adapter_from_env

    adapter = adapter_from_env({
        "INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON": json.dumps([
            str(semantic_python), "-B", str(REPO / "scripts" / "ilang_semantic_main.py"),
        ]),
        "INTENT_TRANSLATOR_SEMANTIC_TIMEOUT": "120",
    })
    if adapter is None:
        raise SystemExit("local semantic adapter unavailable")

    records = []
    with tempfile.TemporaryDirectory(prefix="intent-dev-regression-") as directory:
        temporary = Path(directory)
        profile = temporary / "profile.json"
        profile.write_text(json.dumps({
            "schema_version": 1,
            "profile_id": "dev-regression",
            "language": "zh-CN",
            "phrase_mappings": {},
            "memory": {"adapter": "none", "location": ""},
            "study": {"enabled": False},
        }), encoding="utf-8")
        environment = {
            "INTENT_TRANSLATOR_PROFILE": str(profile),
            "INTENT_TRANSLATOR_MEMORY_DB": str(temporary / "memory.db"),
            "INTENT_TRANSLATOR_STATE_DB": str(temporary / "memory.db"),
            "ILANG_DISTILL_OFFLINE": "1",
        }
        with patch.dict(os.environ, environment, clear=False):
            encoder = ilang_distill_router._load_encoder()
            if encoder.model_name != manifest["model_name"]:
                raise SystemExit("semantic model name differs from the frozen run")
            compiler = IntentCompiler(registry={"skills": [], "errors": []}, semantic_adapter=adapter)
            for index, case in enumerate(cases, 1):
                proposal = gate.semantic_proposal(ilang_semantic_main, case)
                try:
                    SemanticProposal.model_validate(proposal, strict=True)
                    proposal_schema_ok = True
                except Exception:
                    proposal_schema_ok = False
                control = case["expected_control"]
                label = case["expected_mode"] if control == "normal" else control
                semantic_ok = (
                    proposal.get("mode") == case["expected_mode"]
                    and proposal.get("control_status") == control
                )
                if control == "clarify":
                    semantic_ok = semantic_ok and proposal.get("clarification_recommended") is True
                if control == "revoke":
                    semantic_ok = semantic_ok and proposal.get("clarification_recommended") is False
                result = compiler.compile(CompileRequest(
                    utterance=case["utterance"],
                    context=case.get("context", ""),
                    pending_action=case.get("pending_action", ""),
                    semantic_mode="required",
                    include_prompt=False,
                ))
                contract = result["intent_contract"]
                active = [item["predicate"] for item in contract["actions"] if item.get("active_now")]
                forbidden = set(case["forbidden_active_predicates"])
                prohibitions = {item["action"] for item in contract["prohibitions"]}
                host_control_ok = (
                    not active and contract["effect"] == "none"
                    and not result["completion_contract"]["execute"]
                    and (control != "clarify" or result["clarification_required"])
                    and (control != "revoke" or (not result["clarification_required"] and bool(prohibitions)))
                ) if control in gate.CONTROL_LABELS else True
                schema_ok = bool(
                    proposal_schema_ok
                    and isinstance(result.get("intent_contract"), dict)
                    and isinstance(contract.get("actions"), list)
                    and isinstance(contract.get("prohibitions"), list)
                    and contract.get("effect") in gate.EFFECTS
                    and isinstance(result.get("completion_contract", {}).get("execute"), bool)
                    and isinstance(result.get("clarification_required"), bool)
                    and isinstance(result.get("semantic", {}).get("status"), str)
                )
                records.append({
                    "case_id": case["case_id"],
                    "expected_mode": case["expected_mode"],
                    "expected_control": control,
                    "expected_label": label,
                    "semantic_mode": proposal.get("mode"),
                    "semantic_control": proposal.get("control_status"),
                    "semantic_label_ok": bool(semantic_ok),
                    "host_mode": result["mode"],
                    "host_mode_ok": control == "normal" and result["mode"] == label,
                    "effect": contract["effect"],
                    "effect_ok": contract["effect"] in case["allowed_effects"],
                    "execute": result["completion_contract"]["execute"],
                    "must_execute": case["must_execute"],
                    "execution_ok": not (case["must_not_execute"] and result["completion_contract"]["execute"]),
                    "required_execution_ok": not case["must_execute"] or result["completion_contract"]["execute"],
                    "active_predicates": active,
                    "required_active_predicates": case["required_active_predicates"],
                    "required_actions_ok": set(case["required_active_predicates"]).issubset(active),
                    "forbidden_actions_ok": not bool(forbidden.intersection(active)),
                    "prohibitions_ok": set(case["required_prohibitions"]).issubset(prohibitions),
                    "host_control_ok": host_control_ok,
                    "host_semantic_applied": result["semantic"]["status"] == "applied",
                    "schema_ok": schema_ok,
                    "latency_ms": 0,
                })
                if index % 20 == 0:
                    print(f"compiled {index}/{len(cases)}", flush=True)

    summary = gate.summarize(records)
    summary["role"] = "development-regression"
    summary["acceptance"] = False
    summary["fixture_sha256"] = FIXTURE_SHA256
    summary["model_name"] = encoder.model_name
    summary["records"] = records
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    public = {key: value for key, value in summary.items() if key != "records"}
    print(json.dumps(public, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
